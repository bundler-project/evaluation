use cloud::{get_file, get_iface_name, get_tools, install_basic_packages};
use failure::{Error, ResultExt};
use rusoto_core::Region;
use slog::{debug, info};
use std::collections::HashMap;
use std::io::prelude::*;
use std::net::ToSocketAddrs;
use std::path::Path;
use structopt::StructOpt;
use tsunami::providers::{aws::MachineSetup, Setup};
use tsunami::{Machine, Session, TsunamiBuilder};

#[derive(StructOpt)]
struct Opt {
    #[structopt(long = "sender", short = "s", default_value = "18.26.5.4")]
    sender: String,
    #[structopt(long = "inbox", short = "i", default_value = "18.26.5.2")]
    inbox: String,

    #[structopt(long = "inbox_queue_type")]
    inbox_qtype: String,
    #[structopt(long = "inbox_buffer_size")]
    inbox_qlen: String,

    #[structopt(short = "r")]
    recv_region: Region,

    #[structopt(long = "pause")]
    pause: bool,
}

fn connect_sender(log: &slog::Logger, opt: &Opt, receiver_ip: &str) -> Result<Session, Error> {
    // sender is pd4
    // sender only needs iperf, ping, and route setup
    let sess = Session::connect(
        log,
        "akshayn",
        (opt.sender.as_str(), 22)
            .to_socket_addrs()?
            .next()
            .expect("Hardcoded socket address failed to parse"),
        None,
        None,
    )?;

    sess.cmd(&format!(
        "sudo ip route add {} via {}",
        receiver_ip, &opt.inbox
    ))?;
    sess.cmd("sudo sysctl -w net.ipv4.ip_forward=1")
        .map(|(_, _)| ())?;

    sess.cmd("sudo sysctl -w net.ipv4.tcp_wmem=\"4096000 50331648 50331648\"")
        .map(|(_, _)| ())?;
    sess.cmd("sudo sysctl -w net.ipv4.tcp_rmem=\"4096000 50331648 50331648\"")
        .map(|(_, _)| ())?;

    sess.cmd("rm -f ~/ping.out").map(|(_, _)| ())?;

    info!(log, "sender ready");

    Ok(sess)
}

fn connect_inbox(log: &slog::Logger, opt: &Opt) -> Result<Session, Error> {
    let sess = Session::connect(
        log,
        "akshayn",
        (opt.inbox.as_str(), 22)
            .to_socket_addrs()?
            .next()
            .expect("Hardcoded socket address failed to parse"),
        None,
        None,
    )?;

    sess.cmd("sudo sysctl -w net.ipv4.ip_forward=1")
        .map(|(_, _)| ())?;
    sess.cmd("sudo iptables -A FORWARD -i 10gp1 -o em1 -j ACCEPT")
        .map(|(_, _)| ())?;
    sess.cmd("sudo iptables -t nat -A POSTROUTING -o em1 -j MASQUERADE")
        .map(|(_, _)| ())?;
    sess.cmd("sudo tc qdisc del dev em1 root")
        .unwrap_or_default();
    sess.cmd("sudo tc qdisc add dev em1 root pfifo_fast")
        .map(|(_, _)| ())?;

    sess.cmd("sudo sysctl -w net.ipv4.tcp_wmem=\"4096000 50331648 50331648\"")
        .map(|(_, _)| ())?;
    sess.cmd("sudo sysctl -w net.ipv4.tcp_rmem=\"4096000 50331648 50331648\"")
        .map(|(_, _)| ())?;
    sess.cmd("cd ~/tools/bundler && git fetch && git checkout origin/no_dst_ip")
        .map(|(_, _)| ())?;

    // compile bundler and nimbus
    sess.cmd("make -C tools bundler/target/debug/inbox nimbus/target/debug/nimbus")
        .map(|(_, _)| ())?;

    sess.cmd("rm -f ~/iperf_client_1.out").map(|(_, _)| ())?;

    info!(log, "inbox ready");

    Ok(sess)
}

fn nobundler_exp(
    log: &slog::Logger,
    out_dir: &std::path::Path,
    sender: &Session,
    inbox: &Session,
    receiver: &Session,
    receiver_ip: &str,
) -> Result<(), Error> {
    // start iperf receiver
    receiver
        .cmd("screen -d -m bash -c \"iperf -s -p 5001 > ~/iperf_server.out 2> ~/iperf_server.out\"")
        .map(|_| ())?;

    info!(log, "started iperf server");

    // ping
    sender
        .cmd(&format!(
            "sudo screen -d -m bash -c \"ping {} > ~/ping.out 2> ~/ping.out\"",
            receiver_ip
        ))
        .map(|(_, _)| ())?;

    info!(log, "started ping");

    // sender iperf
    let iperf_cmd = format!("screen -d -m bash -c \"mm-delay 0 iperf -c {} -p 5001 -t 90 -i 1 -P 30 > ~/iperf_client_1.out 2> ~/iperf_client_1.out\"", receiver_ip);
    inbox.cmd(&iperf_cmd).map(|(_, _)| ())?;

    info!(log, "started iperf client 1");

    let iperf_cmd = format!("iperf -c {} -p 5001 -t 60 -i 1 -P 30", receiver_ip);
    sender.cmd(&iperf_cmd).and_then(|(out, err)| {
        if err.contains("connect failed") {
            println!("iperf cmd: {:?}", iperf_cmd);
            Err(failure::format_err!("iperf failed: {}", err)
                .context(iperf_cmd)
                .into())
        } else {
            let mut iperf_out = std::fs::File::create(&out_dir.join("iperf_client_2.log"))
                .context("failed to create iperf_client_2.log")?;
            iperf_out
                .write_all(out.as_bytes())
                .context("failed to write iperf output to log")?;
            Ok(())
        }
    })?;

    info!(log, "copy_files");

    get_file(
        receiver,
        Path::new("/home/ubuntu/iperf_server.out"),
        &out_dir.join("./iperf_server.log"),
    )?;
    get_file(
        inbox,
        Path::new("/home/akshayn/iperf_client_1.out"),
        &out_dir.join("./iperf_client_1.log"),
    )?;
    get_file(
        sender,
        Path::new("/home/akshayn/ping.out"),
        &out_dir.join("./ping.log"),
    )?;

    info!(log, "done");

    Ok(())
}

fn bundler_exp(
    log: &slog::Logger,
    out_dir: &std::path::Path,
    sender: &Session,
    inbox: &Session,
    receiver: &Session,
    receiver_ip: &str,
    receiver_iface: &str,
    inbox_qtype: &str,
    inbox_qlen: &str,
) -> Result<(), Error> {
    // start iperf receiver
    receiver
        .cmd("screen -d -m bash -c \"iperf -s -p 5001 > ~/iperf_server.out 2> ~/iperf_server.out\"")
        .map(|_| ())?;

    // start outbox
    receiver.cmd(&format!("cd ~/tools/bundler && sudo screen -d -m bash -c \"./target/debug/outbox --filter=\\\"dst portrange 5000-6000\\\" --iface={} --inbox {}:28316 --sample_rate=64 > ~/outbox.out 2> ~/outbox.out\"",
        receiver_iface,
        "18.26.5.2",
    ))
    .map(|(_, _)| ())?;

    info!(log, "started iperf server + outbox");

    // ping
    sender
        .cmd(&format!(
            "sudo screen -d -m bash -c \"ping {} > ~/ping.out 2> ~/ping.out\"",
            receiver_ip
        ))
        .map(|(_, _)| ())?;

    info!(log, "started ping");

    // inbox
    inbox
        .cmd(&format!("cd ~/tools/bundler && sudo screen -d -m bash -c \"./target/debug/inbox --iface={} --port 28316 --sample_rate=128 --qtype={} --buffer={} > ~/inbox.out 2> ~/inbox.out\"",
            "em1",
            inbox_qtype,
            inbox_qlen,
        ))
        .map(|(_,_)| ())?;

    // wait for inbox to get ready
    std::thread::sleep(std::time::Duration::from_secs(5));

    // start nimbus
    inbox.cmd(&format!("cd ~/tools/nimbus && sudo screen -d -m bash -c \"./target/debug/nimbus --ipc=unix --use_switching=true --loss_mode=Bundle --delay_mode=Nimbus --flow_mode=XTCP --bw_est_mode=true --bundler_qlen_alpha=100 --bundler_qlen_beta=10000 --bundler_qlen=100 > ~/ccp.out 2> ~/ccp.out\"")).map(|(_, _)| ())?;

    // wait for inbox to get ready
    std::thread::sleep(std::time::Duration::from_secs(5));

    // sender iperf
    let iperf_cmd = format!("screen -d -m bash -c \"mm-delay 0 iperf -c {} -p 5001 -t 90 -i 1 -P 30 > ~/iperf_client_1.out 2> ~/iperf_client_1.out\"", receiver_ip);
    inbox.cmd(&iperf_cmd).map(|(_, _)| ())?;

    info!(log, "started iperf client 1");

    let iperf_cmd = format!("iperf -c {} -p 5001 -t 60 -i 1 -P 30", receiver_ip);
    sender.cmd(&iperf_cmd).and_then(|(out, err)| {
        if err.contains("connect failed") {
            println!("iperf cmd: {:?}", iperf_cmd);
            Err(failure::format_err!("iperf failed: {}", err)
                .context(iperf_cmd)
                .into())
        } else {
            let mut iperf_out = std::fs::File::create(&out_dir.join("iperf_client_2.log"))
                .context("failed to create iperf_client_2.log")?;
            iperf_out
                .write_all(out.as_bytes())
                .context("failed to write iperf output to log")?;
            Ok(())
        }
    })?;

    info!(log, "copy_files");

    get_file(
        receiver,
        Path::new("/home/ubuntu/iperf_server.out"),
        &out_dir.join("./iperf_server.log"),
    )?;
    get_file(
        receiver,
        Path::new("/home/ubuntu/outbox.out"),
        &out_dir.join("./outbox.log"),
    )?;

    get_file(
        inbox,
        Path::new("/home/akshayn/iperf_client_1.out"),
        &out_dir.join("./iperf_client_1.log"),
    )?;
    get_file(
        inbox,
        Path::new("/home/akshayn/inbox.out"),
        &out_dir.join("./inbox.log"),
    )?;
    get_file(
        inbox,
        Path::new("/home/akshayn/ccp.out"),
        &out_dir.join("./ccp.log"),
    )?;

    get_file(
        sender,
        Path::new("/home/akshayn/ping.out"),
        &out_dir.join("./ping.log"),
    )?;

    info!(log, "done");

    Ok(())
}

fn main() -> Result<(), Error> {
    let opt = Opt::from_args();

    let mut b = TsunamiBuilder::default();
    b.use_term_logger();

    let m0 = MachineSetup::default()
        .region(opt.recv_region.clone())
        .instance_type("t3.medium")
        .setup(|ssh, _log| {
            install_basic_packages(ssh)?;
            ssh.cmd("sudo sysctl -w net.ipv4.ip_forward=1")
                .map(|(_, _)| ())?;
            ssh.cmd("sudo sysctl -w net.ipv4.tcp_wmem=\"4096000 50331648 50331648\"")
                .map(|(_, _)| ())?;
            ssh.cmd("sudo sysctl -w net.ipv4.tcp_rmem=\"4096000 50331648 50331648\"")
                .map(|(_, _)| ())?;
            ssh.cmd("git clone --recursive https://github.com/bundler-project/tools")
                .map(|(_, _)| ())?;
            ssh.cmd("cd ~/tools/bundler && git checkout no_dst_ip")
                .map(|(_, _)| ())?;
            ssh.cmd("make -C tools bundler/target/debug/outbox")
                .map(|(_, _)| ())?;

            Ok(())
        });

    b.add(String::from("receiver"), Setup::AWS(m0));
    b.set_max_duration(1);
    b.run(opt.pause, |vms: HashMap<String, Machine>, log| {
        let recevr = vms
            .get("receiver")
            .expect("get receiver")
            .ssh
            .as_ref()
            .expect("receiver ssh connection");
        let receiver_ip = vms.get("receiver").expect("get receiver").public_ip.clone();
        let receiver_iface = get_iface_name(recevr)?;

        let sender = connect_sender(log, &opt, &receiver_ip)?;
        let inbox = connect_inbox(log, &opt)?;

        info!(log, "nobundler experiment");
        let nobundler_out_dir = std::path::Path::new("./nobundler-exp");
        std::fs::create_dir_all(nobundler_out_dir)?;
        nobundler_exp(
            log,
            nobundler_out_dir,
            &sender,
            &inbox,
            recevr,
            &receiver_ip,
        )
        .context("nobundler_exp failed")?;

        info!(log, "bundler experiment");

        let bundler_out_dir = std::path::Path::new("./bundler-exp");
        std::fs::create_dir_all(bundler_out_dir)?;
        bundler_exp(
            log,
            bundler_out_dir,
            &sender,
            &inbox,
            recevr,
            &receiver_ip,
            &receiver_iface,
            &opt.inbox_qtype,
            &opt.inbox_qlen,
        )
        .context("bundler_exp failed")?;

        Ok(())
    })?;

    Ok(())
}
