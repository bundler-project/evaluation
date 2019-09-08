use failure::{Error, ResultExt};
use itertools::Itertools;
use rayon::prelude::*;
use serde::{Deserialize, Serialize};
use slog::Drain;
use std::collections::HashMap;
use std::path::Path;
use std::sync::{Arc, Mutex};
use structopt::StructOpt;
use tsunami::providers::{aws::MachineSetup, Setup};
use tsunami::{Machine, TsunamiBuilder};

#[derive(StructOpt)]
struct Opt {
    #[structopt(long = "cfg", short = "f")]
    cfg: String,

    #[structopt(long = "pause")]
    pause: bool,
}

#[derive(Deserialize, Serialize, Clone)]
enum Node {
    Aws {
        region: String,
    },
    Baremetal {
        name: String,
        ip: String,
        user: String,
        iface: String,
    },
}

impl Node {
    fn get_name(&self) -> String {
        match self {
            Node::Aws { region: r } => format!("aws_{}", r.replace("-", "")),
            Node::Baremetal { name: n, .. } => n.clone(),
        }
    }
}

#[derive(Deserialize, Serialize, Clone)]
struct Exp {
    from: Node,
    to: Node,
}

fn register_node(
    b: &mut TsunamiBuilder,
    baremetal_meta: &mut HashMap<String, (String, String, String)>,
    r: Node,
) -> Result<String, Error> {
    match r {
        Node::Aws { region: r } => {
            let m = MachineSetup::default()
                .region(r.clone().parse()?)
                .instance_type("t3.medium")
                .setup(|ssh, log| {
                    cloud::install_basic_packages(ssh)
                        .map_err(|e| e.context("apt install failed"))?;
                    slog::debug!(log, "finished apt install"; "node" => "m0");
                    ssh.cmd("sudo sysctl -w net.ipv4.ip_forward=1")
                        .map(|(_, _)| ())?;
                    ssh.cmd("sudo sysctl -w net.ipv4.tcp_wmem=\"4096000 50331648 50331648\"")
                        .map(|(_, _)| ())?;
                    ssh.cmd("sudo sysctl -w net.ipv4.tcp_rmem=\"4096000 50331648 50331648\"")
                        .map(|(_, _)| ())?;
                    ssh.cmd("git clone --recursive https://github.com/bundler-project/tools")
                        .map(|(_, _)| ())?;

                    ssh.cmd("make -C tools").map(|(_, _)| ())?;
                    Ok(())
                });

            let name = format!("aws_{}", r.replace("-", ""));
            b.add(name.clone(), Setup::AWS(m));
            Ok(name)
        }
        Node::Baremetal {
            name: n,
            ip: i,
            user: u,
            iface: f,
        } => {
            let m = tsunami::providers::baremetal::Setup::new((i.as_str(), 22), Some(u.clone()))?
                .setup(|ssh, log| {
                    cloud::install_basic_packages(ssh)
                        .map_err(|e| e.context("apt install failed"))?;
                    slog::debug!(log, "finished apt install"; "node" => "m0");
                    ssh.cmd("sudo sysctl -w net.ipv4.ip_forward=1")
                        .map(|(_, _)| ())?;
                    ssh.cmd(
                        "sudo sysctl -w net.ipv4.tcp_wmem=\"4096000 50331648 50331648\"",
                    )
                    .map(|(_, _)| ())?;
                    ssh.cmd(
                        "sudo sysctl -w net.ipv4.tcp_rmem=\"4096000 50331648 50331648\"",
                    )
                    .map(|(_, _)| ())?;
                    if let Err(_) = ssh
                        .cmd("git clone --recursive https://github.com/bundler-project/tools")
                        .map(|(_, _)| ())
                    {
                        ssh.cmd("cd tools && git pull origin master && git submodule update --init --recursive").map(|(_, _)| ())?;
                    }

                    ssh.cmd("make -C tools")
                        .map(|(_, _)| ())?;

                    // TODO check that opt.recv_iface exists
                    Ok(())
                });
            baremetal_meta.insert(n.clone(), (i, u, f));
            b.add(n.clone(), Setup::Bare(m));
            Ok(n)
        }
    }
}

fn check_path(from: &str, to: &str) -> bool {
    let control_path_string = format!("./{}-{}/control", from, to);
    let iperf_path_string = format!("./{}-{}/iperf", from, to);
    let control_path = Path::new(control_path_string.as_str());
    let iperf_path = Path::new(control_path_string.as_str());

    if let Err(_) = std::fs::create_dir_all(control_path) {
        return true;
    }

    if let Err(_) = std::fs::create_dir_all(iperf_path) {
        return true;
    }

    if Path::new(&control_path_string).join("bmon.log").exists()
        && Path::new(&control_path_string).join("udping.log").exists()
        && Path::new(&iperf_path_string).join("bmon.log").exists()
        && Path::new(&iperf_path_string).join("udping.log").exists()
    {
        return false;
    } else {
        return true;
    }
}

fn main() -> Result<(), Error> {
    let opt = Opt::from_args();

    let decorator = slog_term::TermDecorator::new().build();
    let drain = Mutex::new(slog_term::FullFormat::new(decorator).build()).fuse();
    let log = slog::Logger::root(drain, slog::o!());

    let f = std::fs::File::open(opt.cfg)?;
    let r = std::io::BufReader::new(f);
    let u: Vec<Exp> = serde_json::from_reader(r)?;

    let mut b = TsunamiBuilder::default();
    b.set_logger(log.clone());

    let mut pairs = vec![];

    // spawn the ec2 nodes
    let mut baremetal_meta = HashMap::new();
    for r in u {
        if check_path(&r.from.get_name(), &r.to.get_name()) {
            let from_name = register_node(&mut b, &mut baremetal_meta, r.from)?;
            let to_name = register_node(&mut b, &mut baremetal_meta, r.to)?;
            pairs.push((from_name, to_name));
        } else {
            slog::info!(log, "skipping experiment"; "sender" => r.from.get_name(), "recevier" => r.to.get_name());
        }
    }

    b.set_max_duration(6);
    b.run(
        opt.pause,
        |vms: HashMap<String, Machine>, log: &slog::Logger| {
            let vms: HashMap<String, Arc<Mutex<Machine>>> = vms
                .into_iter()
                .map(|(k, v)| (k, Arc::new(Mutex::new(v))))
                .collect();

            pairs
                .into_par_iter()
                .map(|(from, to)| {
                    let log = log.new(slog::o!("sender" => from.clone(), "receiver" => to.clone()));
                    let sender_lock = vms.get(&from).expect("vms get from").clone();
                    let receiver_lock = vms.get(&to).expect("vms get to").clone();
                    let (sender, receiver) = if from < to {
                        slog::info!(log, "waiting for lock");
                        let sender = sender_lock.lock().unwrap();
                        let receiver = receiver_lock.lock().unwrap();
                        (sender, receiver)
                    } else if from > to {
                        slog::info!(log, "waiting for lock");
                        let receiver = receiver_lock.lock().unwrap();
                        let sender = sender_lock.lock().unwrap();
                        (sender, receiver)
                    } else {
                        return Ok(());
                    };

                    let (sender_user, sender_iface) = baremetal_meta
                        .get(&from)
                        .map(|(_, user, iface)| (user.clone(), iface.clone()))
                        .unwrap_or_else(|| ("ubuntu".to_string(), "ens5".to_string()));

                    let (receiver_user, receiver_iface) = baremetal_meta
                        .get(&to)
                        .map(|(_, user, iface)| (user.clone(), iface.clone()))
                        .unwrap_or_else(|| ("ubuntu".to_string(), "ens5".to_string()));

                    slog::info!(log, "locked pair");

                    let sender_ssh = sender.ssh.as_ref().expect("sender ssh connection");
                    let receiver_ssh = receiver.ssh.as_ref().expect("receiver ssh connection");

                    let sender_node = cloud::Node {
                        ssh: sender_ssh,
                        name: &from,
                        ip: &sender.public_ip,
                        iface: &sender_iface,
                        user: &sender_user,
                    };

                    let receiver_node = cloud::Node {
                        ssh: receiver_ssh,
                        name: &to,
                        ip: &receiver.public_ip,
                        iface: &receiver_iface,
                        user: &receiver_user,
                    };

                    slog::trace!(log, "starting pair";
                        "sender_user" => sender_node.user,
                        "receiver_user" => receiver_node.user,
                    );

                    cloud::pkill(sender_ssh, "udping_client", &log);
                    cloud::pkill(sender_ssh, "iperf", &log);
                    cloud::pkill(sender_ssh, "bmon", &log);
                    cloud::pkill(receiver_ssh, "udping_server", &log);
                    cloud::pkill(receiver_ssh, "iperf", &log);
                    cloud::pkill(receiver_ssh, "bmon", &log);

                    //let control_path_string = format!("./{}-{}/control", from, to);
                    //let control_path = Path::new(control_path_string.as_str());
                    //std::fs::create_dir_all(control_path)?;

                    //if Path::new(&control_path_string).join("bmon.log").exists()
                    //    && Path::new(&control_path_string).join("udping.log").exists()
                    //{
                    //    slog::info!(log, "skipping control experiment");
                    //} else {
                    //    slog::info!(log, "running control experiment");
                    //    cloud::nobundler_exp_control(
                    //        &control_path,
                    //        &log,
                    //        &sender_node,
                    //        &receiver_node,
                    //    )
                    //    .context(format!("control experiment {} -> {}", &from, &to))?;
                    //}

                    //cloud::pkill(sender_ssh, "udping_client", &log);
                    //cloud::pkill(sender_ssh, "iperf", &log);
                    //cloud::pkill(sender_ssh, "bmon", &log);
                    //cloud::pkill(receiver_ssh, "udping_server", &log);
                    //cloud::pkill(receiver_ssh, "iperf", &log);
                    //cloud::pkill(receiver_ssh, "bmon", &log);

                    //let iperf_path_string = format!("./{}-{}/iperf", from, to);
                    //let iperf_path = Path::new(iperf_path_string.as_str());
                    //std::fs::create_dir_all(iperf_path)?;
                    //if Path::new(&iperf_path_string).join("bmon.log").exists()
                    //    && Path::new(&iperf_path_string).join("udping.log").exists()
                    //{
                    //    slog::info!(log, "skipping iperf experiment");
                    //} else {
                    //    slog::info!(log, "running iperf experiment");
                    //    cloud::nobundler_exp_iperf(&iperf_path, &log, &sender_node, &receiver_node)
                    //        .context(format!("iperf experiment {} -> {}", &from, &to))?;
                    //}

                    let bundler_path_string = format!("./{}-{}/bundler", from, to);
                    let bundler_path = Path::new(iperf_path_string.as_str());
                    std::fs::create_dir_all(bundler_path)?;
                    if Path::new(&bundler_path_string).join("bmon.log").exists()
                        && Path::new(&bundler_path_string).join("udping.log").exists()
                    {
                        slog::info!(log, "skipping bundler experiment");
                    } else {
                        slog::info!(log, "running bundler experiment");
                        cloud::bundler_exp_iperf(&bundler_path, &log, &sender_node, &receiver_node)
                            .context(format!("bundler experiment {} -> {}", &from, &to))?;
                    }

                    cloud::pkill(sender_ssh, "udping_client", &log);
                    cloud::pkill(sender_ssh, "iperf", &log);
                    cloud::pkill(sender_ssh, "bmon", &log);
                    cloud::pkill(receiver_ssh, "udping_server", &log);
                    cloud::pkill(receiver_ssh, "iperf", &log);
                    cloud::pkill(receiver_ssh, "bmon", &log);

                    slog::info!(log, "pair done");
                    Ok(())
                })
                .collect()
        },
    )?;

    Ok(())
}

fn matrix(vms: &HashMap<String, Machine>) -> impl Iterator<Item = (String, String)> {
    let names: Vec<String> = vms.keys().cloned().collect();
    let names2 = names.clone();

    names.into_iter().cartesian_product(names2)
}
