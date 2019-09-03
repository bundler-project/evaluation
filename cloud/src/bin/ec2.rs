#[macro_use]
extern crate slog;

use failure::Error;
use rusoto_core::Region;
use std::collections::HashMap;
use std::io::prelude::*;
use std::path::Path;
use structopt::StructOpt;
use tsunami::providers::{aws::MachineSetup, Setup};
use tsunami::{Machine, Session, TsunamiBuilder};

use cloud::{get_file, get_iface_name, get_tools, install_basic_packages};

#[derive(StructOpt)]
struct Opt {
    #[structopt(short = "s")]
    send_region: Region,

    #[structopt(long = "inbox_queue_type")]
    inbox_qtype: String,
    #[structopt(long = "inbox_buffer_size")]
    inbox_qlen: String,

    #[structopt(short = "r")]
    recv_region: Region,

    #[structopt(long = "pause")]
    pause: bool,
}

fn nobundler_exp(
    sender: &Session,
    _sender_ip: &str,
    _sender_iface: &str,
    recevr: &Session,
    receiver_ip: &str,
    _receiver_iface: &str,
    _inbox_qtype: &str,
    _inbox_qlen: &str,
    out_dir: &Path,
) -> Result<(), Error> {
    // start iperf receiver
    recevr.cmd("cd ~/tools/iperf && screen -d -m bash -c \"./src/iperf -s -p 5001 > ~/iperf_server.out 2> ~/iperf_server.out\"").map(|_| ())?;

    // ping
    sender
        .cmd(&format!(
            "sudo screen -d -m bash -c \"ping {} > ~/ping.out 2> ~/ping.out\"",
            receiver_ip
        ))
        .map(|(_, _)| ())?;

    // start iperf sender inside mm-delay 0
    let iperf_cmd = format!(
        "cd ~/tools/iperf && mm-delay 0 ./src/iperf -c {} -p 5001 -t 60 -i 1 -P 10",
        receiver_ip
    );
    sender.cmd(&iperf_cmd).and_then(|(out, err)| {
        println!("iperf sender_out: {}", out);
        println!("iperf sender_err: {}", err);
        if err.contains("connect failed") {
            println!("iperf cmd: {:?}", iperf_cmd);
            Err(failure::format_err!("iperf failed: {}", err)
                .context(iperf_cmd)
                .into())
        } else {
            let mut iperf_out = std::fs::File::create(&out_dir.join("./iperf_client.log"))?;
            iperf_out.write_all(out.as_bytes())?;
            Ok(())
        }
    })?;

    // wait for logs to flush
    std::thread::sleep(std::time::Duration::from_secs(5));

    // copy log files back
    get_file(
        sender,
        Path::new("/home/ubuntu/ping.out"),
        &out_dir.join("./ping.log"),
    )?;
    get_file(
        recevr,
        Path::new("/home/ubuntu/iperf_server.out"),
        &out_dir.join("./iperf_server.log"),
    )?;

    Ok(())
}

fn bundler_exp(
    sender: &Session,
    sender_ip: &str,
    sender_iface: &str,
    recevr: &Session,
    receiver_ip: &str,
    receiver_iface: &str,
    inbox_qtype: &str,
    inbox_qlen: &str,
    out_dir: &Path,
) -> Result<(), Error> {
    // start outbox
    recevr.cmd(&format!("cd ~/tools/bundler && sudo screen -d -m bash -c \"./target/debug/outbox --filter=\\\"dst portrange 5000-6000\\\" --iface={} --inbox {}:28316 --sample_rate=64 > ~/outbox.out 2> ~/outbox.out\"",
                receiver_iface,
                sender_ip,
            ))
            .map(|(_, _)| ())?;

    // start iperf receiver
    recevr.cmd("cd ~/tools/iperf && screen -d -m bash -c \"./src/iperf -s -p 5001 > ~/iperf_server.out 2> ~/iperf_server.out\"").map(|_| ())?;

    // ping
    sender
        .cmd(&format!(
            "sudo screen -d -m bash -c \"ping {} > ~/ping.out 2> ~/ping.out\"",
            receiver_ip
        ))
        .map(|(_, _)| ())?;

    // start inbox
    sender
            .cmd(&format!("cd ~/tools/bundler && sudo screen -d -m bash -c \"./target/debug/inbox --iface={} --port 28316 --sample_rate=128 --qtype={} --buffer={} > ~/inbox.out 2> ~/inbox.out\"",
                sender_iface,
                inbox_qtype,
                inbox_qlen,
            ))
            .map(|(_,_)| ())?;

    // wait for inbox to get ready
    std::thread::sleep(std::time::Duration::from_secs(5));

    // start nimbus
    sender.cmd(&format!("cd ~/tools/nimbus && sudo screen -d -m bash -c \"./target/debug/nimbus --ipc=unix --use_switching=true --loss_mode=Bundle --delay_mode=Nimbus --flow_mode=XTCP --bw_est_mode=true --bundler_qlen_alpha=100 --bundler_qlen_beta=10000 --bundler_qlen=100 > ~/ccp.out 2> ~/ccp.out\"")).map(|(_, _)| ())?;

    // start iperf sender inside mm-delay 0
    let iperf_cmd = format!(
        "cd ~/tools/iperf && mm-delay 0 ./src/iperf -c {} -p 5001 -t 60 -i 1 -P 10",
        receiver_ip
    );
    sender.cmd(&iperf_cmd).and_then(|(out, err)| {
        println!("iperf sender_out: {}", out);
        println!("iperf sender_err: {}", err);
        if err.contains("connect failed") {
            println!("iperf cmd: {:?}", iperf_cmd);
            Err(failure::format_err!("iperf failed: {}", err)
                .context(iperf_cmd)
                .into())
        } else {
            let mut iperf_out = std::fs::File::create(&out_dir.join("./iperf_client.log"))?;
            iperf_out.write_all(out.as_bytes())?;
            Ok(())
        }
    })?;

    // wait for logs to flush
    std::thread::sleep(std::time::Duration::from_secs(5));

    // copy log files back
    get_file(
        sender,
        Path::new("/home/ubuntu/ping.out"),
        &out_dir.join("./ping.log"),
    )?;
    get_file(
        sender,
        Path::new("/home/ubuntu/ccp.out"),
        &out_dir.join("./ccp.log"),
    )?;
    get_file(
        sender,
        Path::new("/home/ubuntu/inbox.out"),
        &out_dir.join("./inbox.log"),
    )?;
    get_file(
        recevr,
        Path::new("/home/ubuntu/outbox.out"),
        &out_dir.join("./outbox.log"),
    )?;
    get_file(
        recevr,
        Path::new("/home/ubuntu/iperf_server.out"),
        &out_dir.join("./iperf_server.log"),
    )?;

    Ok(())
}

fn main() -> Result<(), Error> {
    let opt = Opt::from_args();

    let mut b = TsunamiBuilder::default();
    b.use_term_logger();

    let m0 = MachineSetup::default()
        .region(opt.send_region.clone())
        .instance_type("t3.medium")
        .setup(|ssh, log| {
            install_basic_packages(ssh).map_err(|e| e.context("m0 apt install failed"))?;
            debug!(log, "finished apt install"; "node" => "m0");
            get_tools(ssh)
        });

    let m1 = MachineSetup::default()
        .region(opt.recv_region.clone())
        .instance_type("t3.medium")
        .setup(|ssh, log| {
            install_basic_packages(ssh).map_err(|e| e.context("m1 apt install failed"))?;
            debug!(log, "finished apt install"; "node" => "m1");
            get_tools(ssh)
        });

    b.add("sender".into(), Setup::AWS(m0));
    b.add("receiver".into(), Setup::AWS(m1));
    b.set_max_duration(1);
    b.run(
        opt.pause,
        |vms: HashMap<String, Machine>, log: &slog::Logger| {
            let sender = vms
                .get("sender")
                .expect("get sender")
                .ssh
                .as_ref()
                .expect("sender ssh connection");
            let recevr = vms
                .get("receiver")
                .expect("get receiver")
                .ssh
                .as_ref()
                .expect("receiver ssh connection");
            let sender_ip = vms.get("sender").expect("get sender").public_ip.clone();
            let receiver_ip = vms.get("receiver").expect("get receiver").public_ip.clone();

            let sender_iface = get_iface_name(sender)?;
            let receiver_iface = get_iface_name(recevr)?;

            debug!(log, "interfaces";
               "sender_ip" => &sender_ip,
               "sender_iface" => &sender_iface,
               "receiver_ip" => &receiver_ip,
               "receiver_iface" => &receiver_iface,
            );

            if opt.pause {
                debug!(
                    log,
                    "pausing for manual instance inspection, press enter to continue"
                );
                use std::io::prelude::*;
                let stdin = std::io::stdin();
                let mut iterator = stdin.lock().lines();
                iterator.next().unwrap().unwrap();
                debug!(log, "continuing");
            }

            std::fs::create_dir_all(Path::new("./nobundler-exp"))?;
            info!(log, "starting nobundler experiment");

            nobundler_exp(
                sender,
                &sender_ip,
                &sender_iface,
                recevr,
                &receiver_ip,
                &receiver_iface,
                &opt.inbox_qtype,
                &opt.inbox_qlen,
                Path::new("./nobundler-exp"),
            )?;

            // stop old processes
            sender.cmd("sudo pkill iperf").unwrap_or_default();
            sender.cmd("sudo pkill ping").unwrap_or_default();
            recevr.cmd("sudo pkill iperf").unwrap_or_default();

            std::fs::create_dir_all(Path::new("./bundler-exp"))?;
            info!(log, "starting bundler experiment");

            bundler_exp(
                sender,
                &sender_ip,
                &sender_iface,
                recevr,
                &receiver_ip,
                &receiver_iface,
                &opt.inbox_qtype,
                &opt.inbox_qlen,
                Path::new("./bundler-exp"),
            )
        },
    )?;

    Ok(())
}
