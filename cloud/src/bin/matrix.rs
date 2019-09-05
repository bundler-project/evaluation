use failure::{Error, ResultExt};
use itertools::Itertools;
use rayon::prelude::*;
use serde::{Deserialize, Serialize};
use slog::Drain;
use std::collections::HashMap;
use std::path::Path;
use std::sync::Mutex;
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

fn main() -> Result<(), Error> {
    let opt = Opt::from_args();

    let decorator = slog_term::TermDecorator::new().build();
    let drain = Mutex::new(slog_term::FullFormat::new(decorator).build()).fuse();
    let log = slog::Logger::root(drain, slog::o!());

    let f = std::fs::File::open(opt.cfg)?;
    let r = std::io::BufReader::new(f);
    let u: Vec<Node> = serde_json::from_reader(r)?;

    let mut b = TsunamiBuilder::default();
    b.set_logger(log);

    // spawn the ec2 nodes
    let mut baremetal_meta = HashMap::new();
    for r in u {
        match r {
            Node::Aws { region: r } => {
                let m = MachineSetup::default()
                    .region(r.clone().parse()?)
                    .instance_type("t3.medium")
                    .setup(|ssh, log| {
                        cloud::install_basic_packages(ssh)
                            .map_err(|e| e.context("apt install failed"))?;
                        slog::debug!(log, "finished apt install"; "node" => "m0");
                        cloud::get_tools(ssh)
                    });

                b.add(r, Setup::AWS(m));
            }
            Node::Baremetal {
                name: n,
                ip: i,
                user: u,
                iface: f,
            } => {
                let m =
                    tsunami::providers::baremetal::Setup::new((i.as_str(), 22), Some(u.clone()))?
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

                            ssh.cmd("make -C tools ~/.cargo/bin/cargo")
                                .map(|(_, _)| ())?;
                            ssh.cmd("cd ~/tools/udping && ~/.cargo/bin/cargo b")
                                .map(|(_, _)| ())?;

                            // TODO check that opt.recv_iface exists
                            slog::info!(log, "machine ready");

                            Ok(())
                        });
                baremetal_meta.insert(n.clone(), (i, u, f));
                b.add(n, Setup::Bare(m));
            }
        }
    }

    b.set_max_duration(1);
    b.run(
        opt.pause,
        |vms: HashMap<String, Machine>, log: &slog::Logger| {
            let names: Vec<String> = vms.keys().cloned().collect();
            let names2 = names.clone();

            let vms: HashMap<String, Mutex<Machine>> =
                vms.into_iter().map(|(k, v)| (k, Mutex::new(v))).collect();

            let pairs: Vec<(String, String)> =
                names.into_iter().cartesian_product(names2).collect();

            pairs
                .into_par_iter()
                .map(|(from, to)| {
                    slog::info!(log, "waiting"; "sender" => &from, "receiver" => &to);
                    let (sender, receiver) = if from < to {
                        let sender = vms.get(&from).expect("vms get from").lock().unwrap();
                        let receiver = vms.get(&to).expect("vms get to").lock().unwrap();
                        (sender, receiver)
                    } else if from > to {
                        let receiver = vms.get(&to).expect("vms get to").lock().unwrap();
                        let sender = vms.get(&from).expect("vms get from").lock().unwrap();
                        (sender, receiver)
                    } else {
                        slog::info!(log, "skipping pair"; "sender" => &from, "receiver" => &to);
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

                    slog::info!(log, "pair"; "sender" => &from, "receiver" => &to);

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

                    sender_ssh.cmd("sudo pkill -9 client").unwrap_or_default();
                    sender_ssh.cmd("sudo pkill -9 iperf").unwrap_or_default();
                    sender_ssh.cmd("sudo pkill -9 bmon").unwrap_or_default();
                    receiver_ssh.cmd("sudo pkill -9 server").unwrap_or_default();
                    receiver_ssh.cmd("sudo pkill -9 iperf").unwrap_or_default();
                    receiver_ssh.cmd("sudo pkill -9 bmon").unwrap_or_default();

                    let control_path_string = format!("./{}-{}/control", from, to);
                    let control_path = Path::new(control_path_string.as_str());
                    std::fs::create_dir_all(control_path)?;

                    if Path::new(&control_path_string).join("bmon.log").exists()
                        && Path::new(&control_path_string).join("udping.log").exists()
                    {
                        slog::info!(log, "skipping control experiment"; "from" => &from, "to" => &to);
                    } else {
                        slog::info!(log, "running control experiment"; "from" => &from, "to" => &to);
                        cloud::nobundler_exp_control(
                            &control_path,
                            &log,
                            &sender_node,
                            &receiver_node,
                        )
                        .context("control experiment")?;
                    }

                    let iperf_path_string = format!("./{}-{}/iperf", from, to);
                    let iperf_path = Path::new(iperf_path_string.as_str());
                    std::fs::create_dir_all(iperf_path)?;
                    if Path::new(&iperf_path_string).join("bmon.log").exists()
                        && Path::new(&iperf_path_string).join("udping.log").exists() {
                        slog::info!(log, "skipping iperf experiment"; "from" => &from, "to" => &to);
                    } else {
                        slog::info!(log, "running iperf experiment"; "from" => &from, "to" => &to);
                        cloud::nobundler_exp_iperf(&iperf_path, &log, &sender_node, &receiver_node)
                            .context("iperf experiment")?;
                    }

                    Ok(())
                })
                .collect()
        },
    )?;

    Ok(())
}
