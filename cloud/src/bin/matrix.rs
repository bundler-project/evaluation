#![recursion_limit = "256"]

use color_eyre::eyre;
use eyre::{eyre, Error, WrapErr};
use itertools::Itertools;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::Path;
use std::sync::Arc;
use structopt::StructOpt;
use tokio::sync::Mutex;
use tracing::{debug, info, warn};
use tracing_futures::Instrument;
use tsunami::providers::{aws, azure, baremetal};
use tsunami::{Machine, Tsunami};

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
    Azure {
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
            Node::Azure { region: r } => format!("az_{}", r.replace("-", "")),
            Node::Baremetal { name: n, .. } => n.clone(),
        }
    }
}

#[derive(Deserialize, Serialize, Clone)]
struct Exp {
    from: Node,
    to: Node,
}

fn check_path(from: &str, to: &str) -> bool {
    let control_path_string = format!("./{}-{}/control", from, to);
    let iperf_path_string = format!("./{}-{}/iperf", from, to);
    let bundler_path_string = format!("./{}-{}/bundler", from, to);
    let control_path = Path::new(control_path_string.as_str());
    let iperf_path = Path::new(iperf_path_string.as_str());
    let bundler_path = Path::new(bundler_path_string.as_str());

    if let Err(_) = std::fs::create_dir_all(control_path) {
        return true;
    }

    if let Err(_) = std::fs::create_dir_all(iperf_path) {
        return true;
    }

    if let Err(_) = std::fs::create_dir_all(bundler_path) {
        return true;
    }

    if Path::new(&control_path_string).join("bmon.log").exists()
        && Path::new(&control_path_string).join("udping.log").exists()
        && Path::new(&iperf_path_string).join("bmon.log").exists()
        && Path::new(&iperf_path_string).join("udping.log").exists()
        && Path::new(&bundler_path_string).join("bmon.log").exists()
        && Path::new(&bundler_path_string).join("udping.log").exists()
    {
        return false;
    } else {
        return true;
    }
}

async fn register_node(
    aws: &mut HashMap<String, aws::Setup>,
    az: &mut HashMap<String, azure::Setup>,
    bare: &mut HashMap<String, baremetal::Setup>,
    machine_info: &mut HashMap<String, (String, String)>,
    r: Node,
) -> Result<String, Error> {
    match r {
        Node::Aws { region: r } => {
            let name = format!("aws_{}", r.replace("-", ""));
            if !aws.contains_key(&name) {
                let m = aws::Setup::default()
                    .region_with_ubuntu_ami(r.clone().parse()?)
                    .await?
                    .instance_type("t3.medium")
                    .setup(|vm| {
                        Box::pin(async move {
                            cloud::install_basic_packages(&vm.ssh).await?;
                            debug!("finished apt install");
                            cloud::get_tools(&vm.ssh).await?;
                            Ok(())
                        })
                    });

                aws.insert(name.clone(), m);
                machine_info.insert(name.clone(), ("ubuntu".to_owned(), "ens5".to_owned()));
            }

            Ok(name)
        }
        Node::Azure { region: r } => {
            let name = format!("aws_{}", r.replace("-", ""));
            if !az.contains_key(&name) {
                let m = azure::Setup::default()
                    .region(r.clone().parse()?)
                    .setup(|vm| {
                        Box::pin(async move {
                            cloud::install_basic_packages(&vm.ssh).await?;
                            debug!("finished apt install");
                            cloud::get_tools(&vm.ssh).await?;
                            Ok(())
                        })
                    });

                az.insert(name.clone(), m);
                machine_info.insert(name.clone(), ("ubuntu".to_owned(), "ens5".to_owned()));
            }

            Ok(name)
        }
        Node::Baremetal {
            name: n,
            ip: i,
            user: u,
            iface: f,
        } => {
            if !bare.contains_key(&n) {
                let m =
                    tsunami::providers::baremetal::Setup::new((i.as_str(), 22), Some(u.clone()))?
                        .setup(|vm| {
                            Box::pin(async move {
                                cloud::install_basic_packages(&vm.ssh).await?;
                                debug!("finished apt install");
                                cloud::get_tools(&vm.ssh).await?;
                                // TODO check that opt.recv_iface exists
                                Ok(())
                            })
                        });
                bare.insert(n.clone(), m);
                machine_info.insert(n.clone(), (u, f));
            }

            Ok(n)
        }
    }
}

#[tokio::main]
async fn main() -> Result<(), Error> {
    tracing_subscriber::fmt::init();
    color_eyre::install()?;
    let opt = Opt::from_args();

    let mut pairs = vec![];
    let mut aws = HashMap::new();
    let mut azure = HashMap::new();
    let mut bare = HashMap::new();
    let mut machine_info = HashMap::new();
    let f = std::fs::File::open(opt.cfg)?;
    let r = std::io::BufReader::new(f);
    let u: Vec<Exp> = serde_json::from_reader(r)?;
    for r in u {
        if check_path(&r.from.get_name(), &r.to.get_name()) {
            let from_name =
                register_node(&mut aws, &mut azure, &mut bare, &mut machine_info, r.from).await?;
            let to_name =
                register_node(&mut aws, &mut azure, &mut bare, &mut machine_info, r.to).await?;
            pairs.push((from_name, to_name));
        } else {
            info!(sender = ?&r.from.get_name(), recevier = ?&r.to.get_name(), "skipping experiment");
        }
    }

    info!("starting machines");
    let mut aws_launcher = aws::Launcher::default();
    let mut az_launcher = azure::Launcher::default();
    let (aws_res, az_res, bare_launchers) = futures_util::join!(
        aws_launcher
            .spawn(aws, Some(std::time::Duration::from_secs(180)))
            .instrument(tracing::info_span!("aws spawn")),
        az_launcher
            .spawn(azure, Some(std::time::Duration::from_secs(180)))
            .instrument(tracing::info_span!("azure spawn")),
        futures_util::future::join_all(bare.into_iter().map(|bare_desc| async move {
            let mut launcher = baremetal::Machine::default();
            launcher
                .spawn(vec![bare_desc], Some(std::time::Duration::from_secs(180)))
                .await?;
            Ok::<_, Error>(launcher)
        }))
        .instrument(tracing::info_span!("baremetal spawn")),
    );

    aws_res?;
    az_res?;
    let bare_launchers: Result<Vec<_>, _> = bare_launchers.into_iter().collect();
    let bare_launchers = bare_launchers?;
    info!("started machines");

    info!("connecting to machines");
    let (aws_vms, az_vms, bare_vms) = futures_util::join!(
        aws_launcher.connect_all(),
        az_launcher.connect_all(),
        futures_util::future::try_join_all(bare_launchers.iter().map(|l| l.connect_all())),
    );

    let vms: HashMap<String, Arc<Mutex<Machine>>> = bare_vms?
        .into_iter()
        .flatten()
        .chain(aws_vms?)
        .chain(az_vms?)
        .map(|(k, v)| (k, Arc::new(Mutex::new(v))))
        .collect();
    info!("connected to machines");

    wait_for_continue();

    let vms = Arc::new(Mutex::new(vms));
    let machine_info = Arc::new(Mutex::new(machine_info));
    futures_util::future::join_all(pairs.into_iter().map(|(from, to): (String, String)| {
        let f = from.clone();
        let t = to.clone();
        let vms = vms.clone();
        let machine_info = machine_info.clone();
        async move {
            let (sender_lock, receiver_lock) = {
                let vm_guard = vms.lock().await;
                let sender_lock = vm_guard.get(&from).expect("vms get from").clone();
                let receiver_lock = vm_guard.get(&to).expect("vms get to").clone();
                (sender_lock, receiver_lock)
            };

            let (sender, receiver) = if from < to {
                info!("waiting for lock");
                let sender = sender_lock.lock().await;
                let receiver = receiver_lock.lock().await;
                (sender, receiver)
            } else if from > to {
                info!("waiting for lock");
                let receiver = receiver_lock.lock().await;
                let sender = sender_lock.lock().await;
                (sender, receiver)
            } else {
                warn!(from = ?&from, to = ?&to, "from == to?");
                return Ok::<_, Error>(());
            };

            info!("locked pair");

            let (sender_user, sender_iface, receiver_user, receiver_iface) = {
                let machine_info_guard = machine_info.lock().await;
                let (sender_user, sender_iface) = machine_info_guard
                    .get(&from)
                    .map(|(user, iface)| (user.clone(), iface.clone()))
                    .unwrap();

                let (receiver_user, receiver_iface) = machine_info_guard
                    .get(&to)
                    .map(|(user, iface)| (user.clone(), iface.clone()))
                    .unwrap();

                (sender_user, sender_iface, receiver_user, receiver_iface)
            };

            info!("got machine info");

            let sender_node = cloud::Node {
                ssh: &sender.ssh,
                name: &from,
                ip: &sender.public_ip,
                iface: &sender_iface,
                user: &sender_user,
            };

            let receiver_node = cloud::Node {
                ssh: &receiver.ssh,
                name: &to,
                ip: &receiver.public_ip,
                iface: &receiver_iface,
                user: &receiver_user,
            };

            cloud::reset(&sender_node, &receiver_node).await;
            let control_path_string = format!("./{}-{}/control", from, to);
            let control_path = Path::new(control_path_string.as_str());
            std::fs::create_dir_all(control_path)?;

            if Path::new(&control_path_string).join("bmon.log").exists()
                && Path::new(&control_path_string).join("udping.log").exists()
            {
                info!("skipping control experiment");
            } else {
                info!("running control experiment");
                cloud::nobundler_exp_control(&control_path, &sender_node, &receiver_node)
                    .await
                    .wrap_err(eyre!("control experiment {} -> {}", &from, &to))?;
                info!("control experiment done");
                cloud::reset(&sender_node, &receiver_node).await;
            }

            let iperf_path_string = format!("./{}-{}/iperf", from, to);
            let iperf_path = Path::new(iperf_path_string.as_str());
            std::fs::create_dir_all(iperf_path)?;
            if Path::new(&iperf_path_string).join("bmon.log").exists()
                && Path::new(&iperf_path_string).join("udping.log").exists()
            {
                info!("skipping iperf experiment");
            } else {
                info!("running iperf experiment");
                cloud::nobundler_exp_iperf(&iperf_path, &sender_node, &receiver_node)
                    .await
                    .wrap_err(eyre!("iperf experiment {} -> {}", &from, &to))?;
                info!("iperf experiment done");
                cloud::reset(&sender_node, &receiver_node).await;
            }

            let bundler_path_string = format!("./{}-{}/bundler", from, to);
            let bundler_path = Path::new(bundler_path_string.as_str());
            std::fs::create_dir_all(bundler_path)?;
            if Path::new(&bundler_path_string).join("bmon.log").exists()
                && Path::new(&bundler_path_string).join("udping.log").exists()
            {
                info!("skipping bundler experiment");
            } else {
                info!("skipping bundler experiment");
                //info!("running bundler experiment");
                //cloud::bundler_exp_iperf(
                //    &bundler_path,
                //    &log,
                //    &sender_node,
                //    &receiver_node,
                //    "sfq",
                //    "1000mbit",
                //).await
                //.wrap_err(eyre!("bundler experiment {} -> {}", &from, &to))?;
                //info!("bundler experiment done");
                cloud::reset(&sender_node, &receiver_node).await;
            }

            info!("done");
            Ok(())
        }
        .instrument(tracing::info_span!("pair", from = ?&f, to = ?&t))
    }))
    .await;

    info!("collecting logs");

    std::process::Command::new("python3")
        .arg("parse_udping.py")
        .arg(".")
        .spawn()?
        .wait()?;

    std::process::Command::new("Rscript")
        .arg("plot_paths.r")
        .spawn()?
        .wait()?;

    std::process::Command::new("python3")
        .arg("plot_ccp.py")
        .spawn()?
        .wait()?;

    Ok(())
}

fn matrix(vms: &HashMap<String, Machine>) -> impl Iterator<Item = (String, String)> {
    let names: Vec<String> = vms.keys().cloned().collect();
    let names2 = names.clone();

    names.into_iter().cartesian_product(names2)
}

fn wait_for_continue() {
    warn!("pausing for manual instance inspection, press enter to continue");

    use std::io::prelude::*;
    let stdin = std::io::stdin();
    let mut iterator = stdin.lock().lines();
    iterator.next().unwrap().unwrap();
}
