use failure::{format_err, Error};
use regex::Regex;
use std::io::prelude::*;
use std::path::Path;
use tsunami::Session;

lazy_static::lazy_static! {
    static ref IFACE_REGEX: Regex = Regex::new(r"[0-9]+:\s+([a-z]+[0-9]+)\s+inet").unwrap();
}

pub struct Node<'a, 'b> {
    pub ssh: &'a Session,
    pub name: &'b str,
    pub ip: &'b str,
    pub iface: &'b str,
    pub user: &'b str,
}

// ip netns: http://man7.org/linux/man-pages/man8/ip-netns.8.html
// netns: https://unix.stackexchange.com/questions/156847/linux-namespace-how-to-connect-internet-in-network-namespace
// iptables: https://unix.stackexchange.com/questions/222054/how-can-i-use-linux-as-a-gateway
pub fn setup_netns(log: &slog::Logger, sender: &Node) -> Result<(), Error> {
    sender.ssh.cmd("sudo ip netns add BUNDLER_NS")?;
    sender
        .ssh
        .cmd("sudo ip link add veth0 type veth peer name veth1")?;
    sender.ssh.cmd("sudo ip link set veth1 netns BUNDLER_NS")?;

    let out = sender.ssh.cmd("sudo ip netns").map(|(x, _)| x)?;
    slog::trace!(log, "setup netns"; "out" => out);

    sender.ssh.cmd("sudo ip link add name br0 type bridge")?;
    sender.ssh.cmd("sudo ip link set veth0 master br0")?;
    sender.ssh.cmd("sudo ip addr add 100.64.0.1/24 dev br0")?;
    sender.ssh.cmd("sudo ip link set br0 up")?;
    sender.ssh.cmd("sudo ip link set veth0 up")?;

    sender
        .ssh
        .cmd("sudo ip netns exec BUNDLER_NS ip link set veth1 up")?;
    sender
        .ssh
        .cmd("sudo ip netns exec BUNDLER_NS ip addr add dev veth1 100.64.0.2/24")?;
    sender
        .ssh
        .cmd("sudo ip netns exec BUNDLER_NS ip route add default via 100.64.0.1")?;

    sender.ssh.cmd(&format!(
        "sudo iptables -t nat -A POSTROUTING -o {} -j MASQUERADE",
        sender.iface
    ))?;
    sender.ssh.cmd(&format!(
        "sudo iptables -A FORWARD -i veth0 -o {} -j ACCEPT",
        sender.iface
    ))?;

    Ok(())
}

pub fn cleanup_netns(log: &slog::Logger, sender: &Node) -> Result<(), Error> {
    sender
        .ssh
        .cmd("sudo ip netns del BUNDLER_NS")
        .unwrap_or_default();
    sender
        .ssh
        .cmd("sudo ip link del dev br0")
        .unwrap_or_default();
    sender
        .ssh
        .cmd("sudo ip link del dev veth0")
        .unwrap_or_default();
    sender
        .ssh
        .cmd("sudo bash -c \"iptables -F && iptables -t nat -F && iptables -X\"")?;

    let out = sender.ssh.cmd("sudo ip netns").map(|(x, _)| x)?;
    slog::trace!(log, "cleanup netns"; "out" => out);

    Ok(())
}

pub fn bundler_exp_iperf(
    out_dir: &Path,
    log: &slog::Logger,
    sender: &Node,
    receiver: &Node,
    inbox_qtype: &str,
    inbox_qlen: &str,
) -> Result<(), Error> {
    let sender_home = get_home(sender.ssh, sender.user)?;
    let receiver_home = get_home(receiver.ssh, receiver.user)?;

    cleanup_netns(log, sender).unwrap_or_default();
    setup_netns(log, sender)?;

    // start outbox
    receiver.ssh.cmd(&format!("cd ~/tools/bundler && sudo screen -d -m bash -c \"./target/debug/outbox --filter=\\\"dst portrange 5000-6000\\\" --iface={} --inbox {}:28316 --sample_rate=64 > {}/outbox.out 2> {}/outbox.out\"",
                receiver.iface,
                sender.ip,
                receiver_home,
                receiver_home,
            ))
            .map(|(_, _)| ())?;

    // start inbox
    sender.ssh
            .cmd(&format!("cd ~/tools/bundler && sudo screen -d -m bash -c \"./target/debug/inbox --iface={} --port 28316 --sample_rate=128 --qtype={} --buffer={} > {}/inbox.out 2> {}/inbox.out\"",
                sender.iface,
                inbox_qtype,
                inbox_qlen,
                sender_home,
                sender_home,
            ))
            .map(|(_,_)| ())?;

    // start nimbus
    // wait for inbox to get ready
    std::thread::sleep(std::time::Duration::from_secs(5));

    // start nimbus
    sender.ssh.cmd(&format!("cd ~/tools/nimbus && sudo screen -d -m bash -c \"./target/debug/nimbus --ipc=unix --loss_mode=Bundle --delay_mode=Nimbus --flow_mode=Delay --uest=875000000 --bundler_qlen_alpha=100 --bundler_qlen_beta=10000 --bundler_qlen=1000 > {}/ccp.out 2> {}/ccp.out\"",
        sender_home,
        sender_home,
    )).map(|(_, _)| ())?;

    //sender.ssh.cmd(&format!("cd ~/tools/ccp_copa && sudo screen -d -m bash -c \"./target/debug/copa --ipc=unix --default_delta=0.125 --delta_mode=NoTCP > {}/ccp.out 2> {}/ccp.out\"",
    //    sender_home,
    //    sender_home,
    //))?;

    // let everything settle
    std::thread::sleep(std::time::Duration::from_secs(5));

    // iperf receiver
    receiver
        .ssh
        .cmd("screen -d -m bash -c \"iperf -s -p 5001 > ~/iperf_server.out 2> ~/iperf_server.out\"")
        .map(|_| ())?;
    // udping receiver
    receiver
        .ssh
        .cmd("cd ~/tools/udping && screen -d -m ./target/debug/udping_server -p 5999")
        .map(|_| ())?;

    // udping sender -> receiver
    let udping_sender_receiver = format!("cd ~/tools/udping && screen -d -m bash -c \"./target/debug/udping_client -c {} -p 5999 > {}/udping_receiver.out 2> {}/udping_receiver.out\"", receiver.ip, sender_home, sender_home);
    slog::debug!(log, "starting udping");
    sender.ssh.cmd(&udping_sender_receiver).map(|_| ())?;

    // 2x iperf sender
    let iperf_cmd = format!(
        "screen -d -m bash -c \"sudo ip netns exec BUNDLER_NS iperf -c {} -p 5001 -t 150 -i 1 -P 10 > {}/iperf_client_1.out 2> {}/iperf_client_1.out\"",
        receiver.ip,
        sender_home,
        sender_home,
    );

    slog::debug!(log, "starting iperf sender 1"; "cmd" => &iperf_cmd);
    sender.ssh.cmd(&iperf_cmd).map(|_| ())?;

    let iperf_cmd = format!("screen -d -m bash -c \"sudo ip netns exec BUNDLER_NS iperf -c {} -p 5001 -t 150 -i 1 -P 10 > {}/iperf_client.out 2> {}/iperf_client.out\"", receiver.ip, sender_home, sender_home);
    slog::debug!(log, "starting iperf sender 2"; "cmd" => &iperf_cmd);
    sender.ssh.cmd(&iperf_cmd).map(|_| ())?;

    std::thread::sleep(std::time::Duration::from_secs(15));

    // bmon receiver
    slog::debug!(log, "starting bmon");
    receiver
        .ssh
        .cmd(&format!(
            "screen -d -m bash -c \"stdbuf -o0 bmon -p {} -b -o format:fmt='\\$(element:name) \\$(attr:rxrate:bytes)\n' > {}/bmon.out\"",
            receiver.iface, receiver_home
        ))
        .map(|_| ())?;

    std::thread::sleep(std::time::Duration::from_secs(165));

    cleanup_netns(log, sender)?;

    get_file(
        sender.ssh,
        Path::new(&format!("{}/iperf_client.out", sender_home)),
        &out_dir.join("./iperf_client.log"),
    )?;
    get_file(
        sender.ssh,
        Path::new(&format!("{}/iperf_client_1.out", sender_home)),
        &out_dir.join("./iperf_client_1.log"),
    )?;
    get_file(
        sender.ssh,
        Path::new(&format!("{}/udping_receiver.out", sender_home)),
        &out_dir.join("./udping.log"),
    )?;
    get_file(
        sender.ssh,
        Path::new(&format!("{}/inbox.out", sender_home)),
        &out_dir.join("./inbox.log"),
    )?;
    get_file(
        sender.ssh,
        Path::new(&format!("{}/ccp.out", sender_home)),
        &out_dir.join("./nimbus.log"),
    )?;
    get_file(
        receiver.ssh,
        Path::new(&format!("{}/iperf_server.out", receiver_home)),
        &out_dir.join("./iperf_server.log"),
    )?;
    get_file(
        receiver.ssh,
        Path::new(&format!("{}/bmon.out", receiver_home)),
        &out_dir.join("./bmon.log"),
    )?;
    get_file(
        receiver.ssh,
        Path::new(&format!("{}/outbox.out", receiver_home)),
        &out_dir.join("./outbox.log"),
    )?;

    Ok(())
}

pub fn nobundler_exp_iperf(
    out_dir: &Path,
    log: &slog::Logger,
    sender: &Node,
    receiver: &Node,
) -> Result<(), Error> {
    let sender_home = get_home(sender.ssh, sender.user)?;
    let receiver_home = get_home(receiver.ssh, receiver.user)?;

    // iperf receiver
    receiver
        .ssh
        .cmd("screen -d -m bash -c \"iperf -s -p 5001 > ~/iperf_server.out 2> ~/iperf_server.out\"")
        .map(|_| ())?;
    // udping receiver
    receiver
        .ssh
        .cmd("cd ~/tools/udping && screen -d -m ./target/debug/udping_server -p 5999")
        .map(|_| ())?;

    // udping sender -> receiver
    let udping_sender_receiver = format!("cd ~/tools/udping && screen -d -m bash -c \"./target/debug/udping_client -c {} -p 5999 > {}/udping_receiver.out 2> {}/udping_receiver.out\"", receiver.ip, sender_home, sender_home);
    slog::debug!(log, "starting udping"; "from" => sender.name, "to" => receiver.name);
    sender.ssh.cmd(&udping_sender_receiver).map(|_| ())?;

    // wait to start
    std::thread::sleep(std::time::Duration::from_secs(5));

    // 2x iperf sender
    let iperf_cmd = format!(
        "screen -d -m bash -c \"iperf -c {} -p 5001 -t 150 -i 1 -P 10 > {}/iperf_client_1.out 2> {}/iperf_client_1.out\"",
        receiver.ip,
        sender_home,
        sender_home,
    );

    slog::debug!(log, "starting iperf sender 1"; "from" => sender.name, "to" => receiver.name, "cmd" => &iperf_cmd);
    sender.ssh.cmd(&iperf_cmd).map(|_| ())?;

    let iperf_cmd = format!("screen -d -m bash -c \"iperf -c {} -p 5001 -t 150 -i 1 -P 10 > {}/iperf_client.out 2> {}/iperf_client.out\"", receiver.ip, sender_home, sender_home);
    slog::debug!(log, "starting iperf sender 2"; "from" => sender.name, "to" => receiver.name, "cmd" => &iperf_cmd);
    sender.ssh.cmd(&iperf_cmd).map(|_| ())?;

    std::thread::sleep(std::time::Duration::from_secs(15));

    // bmon receiver
    slog::debug!(log, "starting bmon");
    receiver
        .ssh
        .cmd(&format!(
            "screen -d -m bash -c \"stdbuf -o0 bmon -p {} -b -o format:fmt='\\$(element:name) \\$(attr:rxrate:bytes)\n' > {}/bmon.out\"",
            receiver.iface, receiver_home
        ))
        .map(|_| ())?;

    std::thread::sleep(std::time::Duration::from_secs(165));

    get_file(
        sender.ssh,
        Path::new(&format!("{}/iperf_client.out", sender_home)),
        &out_dir.join("./iperf_client.log"),
    )?;
    get_file(
        sender.ssh,
        Path::new(&format!("{}/iperf_client_1.out", sender_home)),
        &out_dir.join("./iperf_client_1.log"),
    )?;
    get_file(
        sender.ssh,
        Path::new(&format!("{}/udping_receiver.out", sender_home)),
        &out_dir.join("./udping.log"),
    )?;
    get_file(
        receiver.ssh,
        Path::new(&format!("{}/iperf_server.out", receiver_home)),
        &out_dir.join("./iperf_server.log"),
    )?;
    get_file(
        receiver.ssh,
        Path::new(&format!("{}/bmon.out", receiver_home)),
        &out_dir.join("./bmon.log"),
    )?;

    Ok(())
}

pub fn nobundler_exp_control(
    out_dir: &Path,
    log: &slog::Logger,
    sender: &Node,
    receiver: &Node,
) -> Result<(), Error> {
    let sender_home = get_home(sender.ssh, sender.user)?;
    let receiver_home = get_home(receiver.ssh, receiver.user)?;

    // udping receiver
    receiver
        .ssh
        .cmd("cd ~/tools/udping && screen -d -m ./target/debug/udping_server -p 5999")
        .map(|_| ())?;

    // udping sender -> receiver
    let udping_sender_receiver = format!("cd ~/tools/udping && screen -d -m bash -c \"./target/debug/udping_client -c {} -p 5999 > {}/udping_receiver.out 2> {}/udping_receiver.out\"", receiver.ip, sender_home, sender_home);
    sender.ssh.cmd(&udping_sender_receiver).map(|_| ())?;
    // bmon receiver
    receiver
        .ssh
        .cmd(&format!(
            "screen -d -m bash -c \"stdbuf -o0 bmon -p {} -b -o format:fmt='\\$(element:name) \\$(attr:rxrate:bytes)\n' > {}/bmon.out 2> {}/bmon.out\"",
            receiver.iface, receiver_home, receiver_home
        ))
        .map(|_| ())?;

    slog::debug!(log, "control, waiting"; "from" => sender.name, "to" => receiver.name);

    // wait for 60s
    std::thread::sleep(std::time::Duration::from_secs(180));

    slog::debug!(log, "control, getting files"; "from" => sender.name, "to" => receiver.name);

    get_file(
        sender.ssh,
        Path::new(&format!("{}/udping_receiver.out", sender_home)),
        &out_dir.join("./udping.log"),
    )?;
    get_file(
        receiver.ssh,
        Path::new(&format!("{}/bmon.out", receiver_home)),
        &out_dir.join("./bmon.log"),
    )?;

    Ok(())
}

pub fn get_home(ssh: &Session, user: &str) -> Result<String, Error> {
    ssh.cmd(&format!("echo ~{}", user))
        .map(|(out, _)| out.trim().to_string())
}

pub fn iface_name(ip_addr_out: (String, String)) -> Result<String, Error> {
    ip_addr_out
        .0
        .lines()
        .filter_map(|l| Some(IFACE_REGEX.captures(l)?.get(1)?.as_str().to_string()))
        .filter(|l| match l.as_str() {
            "lo" => false,
            _ => true,
        })
        .next()
        .ok_or_else(|| format_err!("No matching interfaces"))
}

pub fn get_iface_name(node: &Session) -> Result<String, Error> {
    node.cmd("bash -c \"ip -o addr | awk '{print $2}'\"")
        .and_then(iface_name)
}

pub fn install_basic_packages(ssh: &Session) -> Result<(), Error> {
    let mut count = 0;
    loop {
        count += 1;
        let res = (|| -> Result<(), Error> {
            ssh.cmd("sudo apt update")
                .map(|(_, _)| ())
                .map_err(|e| e.context("apt update failed"))?;
            ssh.cmd("sudo apt update && sudo DEBIAN_FRONTEND=noninteractive apt install -y build-essential bmon iperf coreutils git automake autoconf libtool")
                .map(|(_, _)| ())
                .map_err(|e| e.context("apt install failed"))?;
            Ok(())
        })();

        if let Ok(_) = res {
            return res;
        } else {
            println!("apt failed: {:?}", res);
        }

        if count > 15 {
            return res;
        }

        std::thread::sleep(std::time::Duration::from_millis(100));
    }
}

pub fn get_tools(ssh: &Session) -> Result<(), Error> {
    ssh.cmd("sudo sysctl -w net.ipv4.ip_forward=1")
        .map(|(_, _)| ())?;
    ssh.cmd("sudo sysctl -w net.ipv4.tcp_wmem=\"4096000 50331648 50331648\"")
        .map(|(_, _)| ())?;
    ssh.cmd("sudo sysctl -w net.ipv4.tcp_rmem=\"4096000 50331648 50331648\"")
        .map(|(_, _)| ())?;
    if let Err(_) = ssh
        .cmd("git clone --recursive https://github.com/bundler-project/tools")
        .map(|(_, _)| ())
    {
        ssh.cmd("ls ~/tools").map(|(_, _)| ())?;
    }
    ssh.cmd("cd ~/tools/bundler && git checkout no_dst_ip")
        .map(|(_, _)| ())?;

    ssh.cmd("make -C tools").map(|(_, _)| ())
}

pub fn get_file(ssh: &Session, remote_path: &Path, local_path: &Path) -> Result<(), Error> {
    ssh.scp_recv(std::path::Path::new(remote_path))
        .map_err(Error::from)
        .and_then(|(mut channel, _)| {
            let mut out = std::fs::File::create(local_path)?;
            std::io::copy(&mut channel, &mut out)?;
            Ok(())
        })
        .map_err(|e| e.context(format!("scp {:?}", remote_path)))?;
    Ok(())
}

pub fn reset(sender: &Node, receiver: &Node, log: &slog::Logger) {
    let sender_ssh = sender.ssh;
    pkill(sender_ssh, "udping_client", &log);
    pkill(sender_ssh, "iperf", &log);
    pkill(sender_ssh, "bmon", &log);
    sender_ssh.cmd("sudo pkill -9 inbox").unwrap_or_default();
    sender_ssh.cmd("sudo pkill -9 nimbus").unwrap_or_default();
    sender_ssh
        .cmd(&format!("sudo tc qdisc del dev {} root", sender.iface))
        .unwrap_or_default();
    let receiver_ssh = receiver.ssh;
    pkill(receiver_ssh, "udping_server", &log);
    pkill(receiver_ssh, "iperf", &log);
    pkill(receiver_ssh, "bmon", &log);
    receiver_ssh.cmd("sudo pkill -9 outbox").unwrap_or_default();
}

pub fn pkill(ssh: &Session, procname: &str, _log: &slog::Logger) {
    let cmd = format!("pkill -9 {}", procname);
    ssh.cmd(&cmd).unwrap_or_default();
    //if let Err(e) = ssh.cmd(&cmd) {
    //    slog::warn!(log, "pkill failed";
    //        "cmd" => procname,
    //        "error" => ?e,
    //    );
    //}
}

#[cfg(test)]
mod tests {
    #[test]
    fn iface() {
        let out = r"1: lo    inet 127.0.0.1/8 scope host lo\       valid_lft forever preferred_lft forever
2: em1    inet 18.26.5.2/23 brd 18.26.5.255 scope global em1\       valid_lft forever preferred_lft forever".to_string();
        assert_eq!(super::iface_name((out, String::new())).unwrap(), "em1");
    }
}
