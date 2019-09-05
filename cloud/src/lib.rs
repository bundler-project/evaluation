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
        .cmd("cd ~/tools/udping && screen -d -m ./target/debug/server -p 5999")
        .map(|_| ())?;

    // udping sender -> receiver
    let udping_sender_receiver = format!("cd ~/tools/udping && screen -d -m bash -c \"./target/debug/client -c {} -p 5999 > {}/udping_receiver.out 2> {}/udping_receiver.out\"", receiver.ip, sender_home, sender_home);
    slog::debug!(log, "starting udping"; "from" => sender.name, "to" => receiver.name);
    sender.ssh.cmd(&udping_sender_receiver).map(|_| ())?;
    // bmon receiver
    slog::debug!(log, "starting bmon"; "from" => sender.name, "to" => receiver.name);
    receiver
        .ssh
        .cmd(&format!(
            "screen -d -m bash -c \"bmon -p {} -b -o format:fmt='$(element:name) $(attr:rxrate:bytes)\n' > {}/bmon.out\"",
            receiver.iface, receiver_home
        ))
        .map(|_| ())?;

    // wait to start
    std::thread::sleep(std::time::Duration::from_secs(5));

    // 2x iperf sender
    let iperf_cmd = format!(
        "screen -d -m bash -c \"iperf -c {} -p 5001 -t 60 -i 1 -P 10 > {}/iperf_client_1.out 2> {}/iperf_client_1.out\"",
        receiver.ip,
        sender_home,
        sender_home,
    );

    slog::debug!(log, "starting iperf sender 1"; "from" => sender.name, "to" => receiver.name, "cmd" => &iperf_cmd);
    sender.ssh.cmd(&iperf_cmd).map(|_| ())?;

    let iperf_cmd = format!("iperf -c {} -p 5001 -t 60 -i 1 -P 10", receiver.ip);
    slog::debug!(log, "starting iperf sender 2"; "from" => sender.name, "to" => receiver.name, "cmd" => &iperf_cmd);
    sender.ssh.cmd(&iperf_cmd).and_then(|(out, err)| {
        if err.contains("connect failed") {
            slog::warn!(log, "iperf connect failed"; "from" => sender.name, "to" => receiver.name, "cmd" => &iperf_cmd);
            Err(failure::format_err!("iperf failed: {}", err)
                .context(iperf_cmd)
                .into())
        } else {
            let mut iperf_out = std::fs::File::create(&out_dir.join("./iperf_client.log"))?;
            iperf_out.write_all(out.as_bytes())?;
            Ok(())
        }
    })?;

    slog::debug!(log, "iperf done"; "from" => sender.name, "to" => receiver.name);
    // wait for logs
    std::thread::sleep(std::time::Duration::from_secs(5));

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
        .cmd("cd ~/tools/udping && screen -d -m ./target/debug/server -p 5999")
        .map(|_| ())?;

    // udping sender -> receiver
    let udping_sender_receiver = format!("cd ~/tools/udping && screen -d -m bash -c \"./target/debug/client -c {} -p 5999 > {}/udping_receiver.out 2> {}/udping_receiver.out\"", receiver.ip, sender_home, sender_home);
    sender.ssh.cmd(&udping_sender_receiver).map(|_| ())?;
    // bmon receiver
    receiver
        .ssh
        .cmd(&format!(
            "screen -d -m bash -c \"bmon -p {} -b -o format:fmt='$(element:name) $(attr:rxrate:bytes)\n' > {}/bmon.out\"",
            receiver.iface, receiver_home
        ))
        .map(|_| ())?;

    slog::debug!(log, "control, waiting"; "from" => sender.name, "to" => receiver.name);

    // wait for 60s
    std::thread::sleep(std::time::Duration::from_secs(60));

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
            ssh.cmd("sudo apt update && sudo DEBIAN_FRONTEND=noninteractive apt install -y build-essential bmon iperf git automake autoconf libtool mahimahi")
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

#[cfg(test)]
mod tests {
    #[test]
    fn iface() {
        let out = r"1: lo    inet 127.0.0.1/8 scope host lo\       valid_lft forever preferred_lft forever
2: em1    inet 18.26.5.2/23 brd 18.26.5.255 scope global em1\       valid_lft forever preferred_lft forever".to_string();
        assert_eq!(super::iface_name((out, String::new())).unwrap(), "em1");
    }
}
