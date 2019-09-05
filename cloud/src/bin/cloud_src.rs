#[macro_use]
extern crate slog;

use failure::{Error, ResultExt};
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

    #[structopt(long = "recv_user")]
    recv_username: String,

    #[structopt(long = "recv_ip")]
    recv_machine: String,

    #[structopt(long = "recv_iface")]
    recv_iface: String,

    #[structopt(long = "pause")]
    pause: bool,
}

fn connect_receiver(log: &slog::Logger, opt: &Opt) -> Result<Session, Error> {
    use std::net::ToSocketAddrs;
    let sess = Session::connect(
        log,
        &opt.recv_username,
        (opt.recv_machine.as_str(), 22 as u16)
            .to_socket_addrs()?
            .next()
            .expect("Socket address failed to parse"),
        None,
        None,
    )?;

    sess.cmd("sudo sysctl -w net.ipv4.tcp_wmem=\"4096000 50331648 50331648\"")
        .map(|(_, _)| ())?;
    sess.cmd("sudo sysctl -w net.ipv4.tcp_rmem=\"4096000 50331648 50331648\"")
        .map(|(_, _)| ())?;

    sess.cmd("ls ~/tools/bundler/target/debug/outbox")
        .map(|(_, _)| ())
        .context("Could not find outbox on receiver")?;

    sess.cmd("ls ~/tools/iperf/src/iperf")
        .map(|(_, _)| ())
        .context("Could not find iperf on receiver")?;

    // TODO check that opt.recv_iface exists

    sess.cmd("rm -f ~/ping.out").map(|(_, _)| ())?;

    info!(log, "receiver ready");

    Ok(sess)
}

fn nobundler_exp(
    sender: &Session,
    _sender_ip: &str,
    _sender_iface: &str,
    recevr: &Session,
    receiver_ip: &str,
    _receiver_iface: &str,
    receiver_username: &str,
    _inbox_qtype: &str,
    _inbox_qlen: &str,
    out_dir: &Path,
) -> Result<(), Error> {
    // start iperf receiver
    recevr.cmd("cd ~/tools/iperf && screen -d -m bash -c \"./src/iperf -s -p 5001 > ~/iperf_server.out 2> ~/iperf_server.out\"").map(|_| ())?;

    // ping
    sender
        .cmd(&format!(
            "sudo screen -d -m bash -c \"ping -A {} > ~/ping.out 2> ~/ping.out\"",
            receiver_ip
        ))
        .map(|(_, _)| ())?;

    // start iperf sender inside mm-delay 0
    let iperf_cmd = format!("screen -d -m bash -c \"mm-delay 0 iperf -c {} -p 5001 -t 90 -i 1 -P 10 > ~/iperf_client_1.out 2> ~/iperf_client_1.out\"", receiver_ip);
    sender.cmd(&iperf_cmd).map(|(_, _)| ())?;
    let iperf_cmd = format!(
        "mm-delay 0 iperf -c {} -p 5001 -t 90 -i 1 -P 10",
        receiver_ip
    );
    sender.cmd(&iperf_cmd).and_then(|(out, err)| {
        if err.contains("connect failed") {
            println!("iperf cmd: {:?}", iperf_cmd);
            Err(failure::format_err!("iperf failed: {}", err)
                .context(iperf_cmd)
                .into())
        } else {
            let mut iperf_out = std::fs::File::create(&out_dir.join("./iperf_client_2:.log"))?;
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
        Path::new("/home/ubuntu/iperf_client_1.out"),
        &out_dir.join("./iperf_client_1.log"),
    )?;
    get_file(
        recevr,
        Path::new(&format!("/home/{}/iperf_server.out", receiver_username)),
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
    receiver_username: &str,
    inbox_qtype: &str,
    inbox_qlen: &str,
    out_dir: &Path,
) -> Result<(), Error> {
    // start outbox
    let outbox_cmd = format!("cd ~/tools/bundler && sudo screen -d -m bash -c \"./target/debug/outbox --filter=\\\"dst portrange 5000-6000\\\" --iface={} --inbox {}:28316 --sample_rate=64 > /home/{}/outbox.out 2> /home/{}/outbox.out\"",
                receiver_iface,
                sender_ip,
                receiver_username,
                receiver_username,
            );

    println!("{}", outbox_cmd);
    recevr.cmd(&outbox_cmd).map(|(_, _)| ())?;

    // start iperf receiver
    recevr.cmd("cd ~/tools/iperf && screen -d -m bash -c \"./src/iperf -s -p 5001 > ~/iperf_server.out 2> ~/iperf_server.out\"").map(|_| ())?;

    // ping
    sender
        .cmd(&format!(
            "sudo screen -d -m bash -c \"ping -A {} > ~/ping.out 2> ~/ping.out\"",
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
    let iperf_cmd = format!("screen -d -m bash -c \"mm-delay 0 iperf -c {} -p 5001 -t 90 -i 1 -P 10 > ~/iperf_client_1.out 2> ~/iperf_client_1.out\"", receiver_ip);
    sender.cmd(&iperf_cmd).map(|(_, _)| ())?;
    let iperf_cmd = format!(
        "mm-delay 0 iperf -c {} -p 5001 -t 90 -i 1 -P 10",
        receiver_ip
    );
    sender.cmd(&iperf_cmd).and_then(|(out, err)| {
        if err.contains("connect failed") {
            println!("iperf cmd: {:?}", iperf_cmd);
            Err(failure::format_err!("iperf failed: {}", err)
                .context(iperf_cmd)
                .into())
        } else {
            let mut iperf_out = std::fs::File::create(&out_dir.join("./iperf_client_2:.log"))?;
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
        sender,
        Path::new("/home/ubuntu/iperf_client_1.out"),
        &out_dir.join("./iperf_client_1.log"),
    )?;
    get_file(
        recevr,
        Path::new(&format!("/home/{}/outbox.out", receiver_username)),
        &out_dir.join("./outbox.log"),
    )?;
    get_file(
        recevr,
        Path::new(&format!("/home/{}/iperf_server.out", receiver_username)),
        &out_dir.join("./iperf_server.log"),
    )?;

    Ok(())
}

fn main() -> Result<(), Error> {
    let opt = Opt::from_args();

    let mut b = TsunamiBuilder::default();
    use slog::Drain;
    use std::sync::Mutex;

    let decorator = slog_term::TermDecorator::new().build();
    let drain = Mutex::new(slog_term::FullFormat::new(decorator).build()).fuse();
    let log = slog::Logger::root(drain, o!());

    let receiver = connect_receiver(&log, &opt)?;
    b.set_logger(log);

    let m0 = MachineSetup::default()
        .region(opt.send_region.clone())
        .instance_type("t3.medium")
        .setup(|ssh, log| {
            install_basic_packages(ssh).map_err(|e| e.context("m0 apt install failed"))?;
            debug!(log, "finished apt install"; "node" => "m0");
            get_tools(ssh)
        });

    b.add("sender".to_string(), Setup::AWS(m0));
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
            let sender_ip = vms.get("sender").expect("get sender").public_ip.clone();
            let sender_iface = get_iface_name(sender)?;

            debug!(log, "interfaces";
               "sender_ip" => &sender_ip,
               "sender_iface" => &sender_iface,
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

            sender.cmd("sudo pkill -9 iperf").unwrap_or_default();
            sender.cmd("sudo pkill -9 nimbus").unwrap_or_default();
            sender.cmd("sudo pkill -9 inbox").unwrap_or_default();
            sender.cmd("sudo pkill -9 ping").unwrap_or_default();
            receiver.cmd("sudo pkill -9 iperf").unwrap_or_default();
            receiver.cmd("sudo pkill -9 outbox").unwrap_or_default();

            nobundler_exp(
                sender,
                &sender_ip,
                &sender_iface,
                &receiver,
                &opt.recv_machine,
                &opt.recv_iface,
                &opt.recv_username,
                &opt.inbox_qtype,
                &opt.inbox_qlen,
                Path::new("./nobundler-exp"),
            )?;

            // stop old processes
            sender.cmd("sudo pkill -9 iperf").unwrap_or_default();
            sender.cmd("sudo pkill -9 nimbus").unwrap_or_default();
            sender.cmd("sudo pkill -9 inbox").unwrap_or_default();
            sender.cmd("sudo pkill -9 ping").unwrap_or_default();
            receiver.cmd("sudo pkill -9 iperf").unwrap_or_default();
            receiver.cmd("sudo pkill -9 outbox").unwrap_or_default();

            std::fs::create_dir_all(Path::new("./bundler-exp"))?;
            info!(log, "starting bundler experiment");

            bundler_exp(
                sender,
                &sender_ip,
                &sender_iface,
                &receiver,
                &opt.recv_machine,
                &opt.recv_iface,
                &opt.recv_username,
                &opt.inbox_qtype,
                &opt.inbox_qlen,
                Path::new("./bundler-exp"),
            )
        },
    )?;

    Ok(())
}
