use failure::{format_err, Error};
use rusoto_core::Region;
use std::collections::HashMap;
use structopt::StructOpt;
use tsunami::{Machine, MachineSetup, Session, TsunamiBuilder};

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
}

fn get_iface_name(node: &Session) -> Result<String, Error> {
    node.cmd("bash -c \"ip -o addr | awk '{print $2}'\"")
        .and_then(|(out, _)| {
            out.lines()
                .filter(|l| match l {
                    &"lo" => false,
                    _ => true,
                })
                .map(|s| s.to_string())
                .next()
                .ok_or_else(|| format_err!(""))
        })
}

fn get_tools(ssh: &Session) -> Result<(), Error> {
    ssh.cmd("git clone --recursive https://github.com/bundler-project/tools")
        .map(|(out, err)| {
            println!("clone_stdout: {}", out);
            println!("clone_stderr: {}", err);
        })?;

    println!("press enter to continue");
    let mut buf = String::new();
    std::io::stdin().read_line(&mut buf)?;

    ssh.cmd("make -C tools").map(|(out, err)| {
        println!("make_stdout: {}", out);
        println!("make_stderr: {}", err);
    })
}

fn main() -> Result<(), Error> {
    let opt = Opt::from_args();

    let mut b = TsunamiBuilder::default();
    b.use_term_logger();

    let m0 = MachineSetup::default()
        .region(opt.send_region.clone())
        .instance_type("t3.small")
        .setup(|ssh| {
            // also need mahimahi to do mm-delay 0 in front of sending iperf
            ssh.cmd("sudo apt update && sudo DEBIAN_FRONTEND=noninteractive apt install -y build-essential git automake autoconf libtool mahimahi")
                .map(|(_, _)| ())?;
            println!("m0 finished apt install");

            get_tools(ssh)
        });

    let m1 = MachineSetup::default()
        .region(opt.recv_region.clone())
        .instance_type("t3.small")
        .setup(|ssh| {
            ssh.cmd("sudo apt update && sudo DEBIAN_FRONTEND=noninteractive apt install -y build-essential git automake autoconf libtool")
                .map(|(_, _)| ())?;
            println!("m1 finished apt install");

            get_tools(ssh)
        });

    b.add("sender".into(), m0);
    b.add("receiver".into(), m1);
    b.set_max_duration(1);
    b.run(|vms: HashMap<String, Machine>| {
        let sender_ip = &vms.get("sender").expect("get sender").public_ip;
        let receiver_ip = &vms.get("sender").expect("get sender").public_ip;

        let sender = vms.get("sender")
            .expect("get sender")
            .ssh
            .as_ref()
            .expect("sender ssh connection");
        let recevr = vms.get("receiver")
            .expect("get receiver")
            .ssh
            .as_ref()
            .expect("receiver ssh connection");
        let sender_iface = get_iface_name(sender)?;
        let receiver_iface = get_iface_name(recevr)?;

        // start outbox
        recevr.cmd(&format!("cd ~/tools/bundler && sudo screen -d -m bash -c \"./target/debug/outbox --filter=\\\"src portrange 5000-6000\\\" --iface={} --inbox {}:28316 --sample-rate=64", 
                receiver_iface,
                sender_ip,
            ))
            .map(|(out, err)| {
                println!("outbox_out: {}", out);
                println!("errbox_err: {}", err);
            })?;

        // start iperf receiver
        recevr.cmd("cd ~/tools/iperf && screen -d -m bash -c \"./src/iperf -s -p 5001\"").map(|_| ())?;

        // start inbox
        sender
            .cmd(&format!("cd ~/tools/bundler && sudo screen -d -m bash -c \"./target/debug/inbox --iface={} --port 28316 --sample_rate=128 --qtype={} --buffer={}\"", 
                          sender_iface,
                          opt.inbox_qtype,
                          opt.inbox_qlen,
                          ))
            .map(|(out, err)| {
                println!("inbox_out: {}", out);
                println!("inbox_err: {}", err);
            })?;

        // start nimbus
        sender.cmd(&format!("cd ~/tools/nimbus && sudo ./target/debug/nimbus --ipc=unix --use_switching=true --loss_mode=Bundle --delay_mode=Nimbus --flow_mode=XTCP --bundler_qlen_alpha=100 --bundler-qlen-beta=10000 --bundler_qlen_target=100")).map(|(out, err)| {
            println!("nimbus_out: {}", out);
            println!("nimbus_err: {}", err);
        })?;

        // start iperf sender inside mm-delay 0
        sender.cmd(&format!("cd ~/tools/iperf && ./src/iperf -c {} -p 5001 -t 30 -i 1", receiver_ip)).map(|(out, err)| {
            println!("iperf sender_out: {}", out);  
            println!("iperf sender_err: {}", err);  
        })?;

        Ok(())
    })?;

    Ok(())
}
