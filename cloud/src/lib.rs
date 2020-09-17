use color_eyre::eyre;
use eyre::{eyre, Error, WrapErr};
use openssh::Session;
use regex::Regex;
use std::path::Path;
use tracing::{debug, trace};

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
pub async fn setup_netns(sender: &Node<'_, '_>) -> Result<(), Error> {
    sender
        .ssh
        .shell("sudo ip netns add BUNDLER_NS")
        .status()
        .await?;
    sender
        .ssh
        .shell("sudo ip link add veth0 type veth peer name veth1")
        .status()
        .await?;
    sender
        .ssh
        .shell("sudo ip link set veth1 netns BUNDLER_NS")
        .status()
        .await?;

    let out = sender.ssh.shell("sudo ip netns").output().await?;
    let out = String::from_utf8(out.stdout)?;
    trace!(out = ?&out, "setup netns");

    sender
        .ssh
        .shell("sudo ip link add name br0 type bridge")
        .status()
        .await?;
    sender
        .ssh
        .shell("sudo ip link set veth0 master br0")
        .status()
        .await?;
    sender
        .ssh
        .shell("sudo ip addr add 100.64.0.1/24 dev br0")
        .status()
        .await?;
    sender.ssh.shell("sudo ip link set br0 up").status().await?;
    sender
        .ssh
        .shell("sudo ip link set veth0 up")
        .status()
        .await?;

    sender
        .ssh
        .shell("sudo ip netns exec BUNDLER_NS ip link set veth1 up")
        .status()
        .await?;
    sender
        .ssh
        .shell("sudo ip netns exec BUNDLER_NS ip addr add dev veth1 100.64.0.2/24")
        .status()
        .await?;
    sender
        .ssh
        .shell("sudo ip netns exec BUNDLER_NS ip route add default via 100.64.0.1")
        .status()
        .await?;

    sender
        .ssh
        .shell(&format!(
            "sudo iptables -t nat -A POSTROUTING -o {} -j MASQUERADE",
            sender.iface
        ))
        .status()
        .await?;
    sender
        .ssh
        .shell(&format!(
            "sudo iptables -A FORWARD -i veth0 -o {} -j ACCEPT",
            sender.iface
        ))
        .status()
        .await?;

    Ok(())
}

pub async fn cleanup_netns(sender: &Node<'_, '_>) -> Result<(), Error> {
    sender
        .ssh
        .shell("sudo ip netns del BUNDLER_NS")
        .status()
        .await?;
    sender
        .ssh
        .shell("sudo ip link del dev br0")
        .status()
        .await?;
    sender
        .ssh
        .shell("sudo ip link del dev veth0")
        .status()
        .await?;
    sender
        .ssh
        .shell("sudo bash -c \"iptables -F && iptables -t nat -F && iptables -X\"")
        .status()
        .await?;

    let out = sender.ssh.shell("sudo ip netns").output().await?;
    let out = String::from_utf8(out.stdout)?;
    trace!(out = ?&out, "cleanup netns");

    Ok(())
}

pub async fn bundler_exp_iperf(
    out_dir: &Path,
    sender: &Node<'_, '_>,
    receiver: &Node<'_, '_>,
    inbox_qtype: &str,
    inbox_qlen: &str,
) -> Result<(), Error> {
    let sender_home = get_home(sender.ssh, sender.user).await?;
    let receiver_home = get_home(receiver.ssh, receiver.user).await?;

    cleanup_netns(sender).await?;
    setup_netns(sender).await?;

    // start outbox
    receiver.ssh.shell(&format!("cd ~/tools/bundler && sudo screen -d -m bash -c \"./target/debug/outbox --filter=\\\"dst portrange 5000-6000\\\" --iface={} --inbox {}:28316 --sample_rate=64 > {}/outbox.out 2> {}/outbox.out\"",
                receiver.iface,
                sender.ip,
                receiver_home,
                receiver_home,
            ))
        .status().await?;
    // start inbox
    sender.ssh
            .shell(&format!("cd ~/tools/bundler && sudo screen -d -m bash -c \"./target/debug/inbox --iface={} --port 28316 --sample_rate=128 --qtype={} --buffer={} > {}/inbox.out 2> {}/inbox.out\"",
                sender.iface,
                inbox_qtype,
                inbox_qlen,
                sender_home,
                sender_home,
            ))
        .status().await?;

    // start nimbus
    // wait for inbox to get ready
    tokio::time::delay_for(tokio::time::Duration::from_secs(5)).await;

    // start nimbus
    sender.ssh.shell(&format!("cd ~/tools/nimbus && sudo screen -d -m bash -c \"./target/debug/nimbus --ipc=unix --loss_mode=Bundle --delay_mode=Nimbus --flow_mode=Delay --uest=875000000 --bundler_qlen_alpha=100 --bundler_qlen_beta=10000 --bundler_qlen=1000 > {}/ccp.out 2> {}/ccp.out\"",
        sender_home,
        sender_home,
    )).status().await?;

    //sender.ssh.cmd(&format!("cd ~/tools/ccp_copa && sudo screen -d -m bash -c \"./target/debug/copa --ipc=unix --default_delta=0.125 --delta_mode=NoTCP > {}/ccp.out 2> {}/ccp.out\"",
    //    sender_home,
    //    sender_home,
    //))?;

    // let everything settle
    tokio::time::delay_for(tokio::time::Duration::from_secs(5)).await;

    // iperf receiver
    receiver
        .ssh
        .shell(
            "screen -d -m bash -c \"iperf -s -p 5001 > ~/iperf_server.out 2> ~/iperf_server.out\"",
        )
        .status()
        .await?;
    // udping receiver
    receiver
        .ssh
        .shell("cd ~/tools/udping && screen -d -m ./target/debug/udping_server -p 5999")
        .status()
        .await?;

    // udping sender -> receiver
    let udping_sender_receiver = format!("cd ~/tools/udping && screen -d -m bash -c \"./target/debug/udping_client -c {} -p 5999 > {}/udping_receiver.out 2> {}/udping_receiver.out\"", receiver.ip, sender_home, sender_home);
    debug!("starting udping");
    sender.ssh.shell(&udping_sender_receiver).status().await?;

    // 2x iperf sender
    let iperf_cmd = format!(
        "screen -d -m bash -c \"sudo ip netns exec BUNDLER_NS iperf -c {} -p 5001 -t 150 -i 1 -P 10 > {}/iperf_client_1.out 2> {}/iperf_client_1.out\"",
        receiver.ip,
        sender_home,
        sender_home,
    );

    debug!(cmd = ?&iperf_cmd, "starting iperf sender 1");
    sender.ssh.shell(&iperf_cmd).status().await?;

    let iperf_cmd = format!("screen -d -m bash -c \"sudo ip netns exec BUNDLER_NS iperf -c {} -p 5001 -t 150 -i 1 -P 10 > {}/iperf_client.out 2> {}/iperf_client.out\"", receiver.ip, sender_home, sender_home);
    debug!(cmd = ?&iperf_cmd, "starting iperf sender 2");
    sender.ssh.shell(&iperf_cmd).status().await?;

    tokio::time::delay_for(tokio::time::Duration::from_secs(15)).await;

    // bmon receiver
    debug!("starting bmon");
    receiver
        .ssh
        .shell(&format!(
            "screen -d -m bash -c \"stdbuf -o0 bmon -p {} -b -o format:fmt='\\$(element:name) \\$(attr:rxrate:bytes)\n' > {}/bmon.out\"",
            receiver.iface, receiver_home
        ))
        .status().await?;

    tokio::time::delay_for(tokio::time::Duration::from_secs(165)).await;

    cleanup_netns(sender).await?;

    get_file(
        sender.ssh,
        Path::new(&format!("{}/iperf_client.out", sender_home)),
        &out_dir.join("./iperf_client.log"),
    )
    .await?;
    get_file(
        sender.ssh,
        Path::new(&format!("{}/iperf_client_1.out", sender_home)),
        &out_dir.join("./iperf_client_1.log"),
    )
    .await?;
    get_file(
        sender.ssh,
        Path::new(&format!("{}/udping_receiver.out", sender_home)),
        &out_dir.join("./udping.log"),
    )
    .await?;
    get_file(
        sender.ssh,
        Path::new(&format!("{}/inbox.out", sender_home)),
        &out_dir.join("./inbox.log"),
    )
    .await?;
    get_file(
        sender.ssh,
        Path::new(&format!("{}/ccp.out", sender_home)),
        &out_dir.join("./nimbus.log"),
    )
    .await?;
    get_file(
        receiver.ssh,
        Path::new(&format!("{}/iperf_server.out", receiver_home)),
        &out_dir.join("./iperf_server.log"),
    )
    .await?;
    get_file(
        receiver.ssh,
        Path::new(&format!("{}/bmon.out", receiver_home)),
        &out_dir.join("./bmon.log"),
    )
    .await?;
    get_file(
        receiver.ssh,
        Path::new(&format!("{}/outbox.out", receiver_home)),
        &out_dir.join("./outbox.log"),
    )
    .await?;

    Ok(())
}

pub async fn nobundler_exp_iperf(
    out_dir: &Path,
    sender: &Node<'_, '_>,
    receiver: &Node<'_, '_>,
) -> Result<(), Error> {
    let sender_home = get_home(sender.ssh, sender.user).await?;
    let receiver_home = get_home(receiver.ssh, receiver.user).await?;

    // iperf receiver
    receiver
        .ssh
        .shell(
            "screen -d -m bash -c \"iperf -s -p 5001 > ~/iperf_server.out 2> ~/iperf_server.out\"",
        )
        .status()
        .await?;
    // udping receiver
    receiver
        .ssh
        .shell("cd ~/tools/udping && screen -d -m ./target/debug/udping_server -p 5999")
        .status()
        .await?;

    // udping sender -> receiver
    let udping_sender_receiver = format!("cd ~/tools/udping && screen -d -m bash -c \"./target/debug/udping_client -c {} -p 5999 > {}/udping_receiver.out 2> {}/udping_receiver.out\"", receiver.ip, sender_home, sender_home);
    debug!("starting udping");
    sender.ssh.shell(&udping_sender_receiver).status().await?;

    // wait to start
    tokio::time::delay_for(tokio::time::Duration::from_secs(5)).await;

    // 2x iperf sender
    let iperf_cmd = format!(
        "screen -d -m bash -c \"iperf -c {} -p 5001 -t 150 -i 1 -P 10 > {}/iperf_client_1.out 2> {}/iperf_client_1.out\"",
        receiver.ip,
        sender_home,
        sender_home,
    );

    debug!(cmd = ?&iperf_cmd, "starting iperf sender 1");
    sender.ssh.shell(&iperf_cmd).status().await?;

    let iperf_cmd = format!("screen -d -m bash -c \"iperf -c {} -p 5001 -t 150 -i 1 -P 10 > {}/iperf_client.out 2> {}/iperf_client.out\"", receiver.ip, sender_home, sender_home);
    debug!(cmd = ?&iperf_cmd, "starting iperf sender 2");
    sender.ssh.shell(&iperf_cmd).status().await?;

    tokio::time::delay_for(tokio::time::Duration::from_secs(15)).await;

    // bmon receiver
    debug!("starting bmon");
    receiver
        .ssh
        .shell(&format!(
            "screen -d -m bash -c \"stdbuf -o0 bmon -p {} -b -o format:fmt='\\$(element:name) \\$(attr:rxrate:bytes)\n' > {}/bmon.out\"",
            receiver.iface, receiver_home
        ))
        .status().await?;

    tokio::time::delay_for(tokio::time::Duration::from_secs(165)).await;

    get_file(
        sender.ssh,
        Path::new(&format!("{}/iperf_client.out", sender_home)),
        &out_dir.join("./iperf_client.log"),
    )
    .await?;
    get_file(
        sender.ssh,
        Path::new(&format!("{}/iperf_client_1.out", sender_home)),
        &out_dir.join("./iperf_client_1.log"),
    )
    .await?;
    get_file(
        sender.ssh,
        Path::new(&format!("{}/udping_receiver.out", sender_home)),
        &out_dir.join("./udping.log"),
    )
    .await?;
    get_file(
        receiver.ssh,
        Path::new(&format!("{}/iperf_server.out", receiver_home)),
        &out_dir.join("./iperf_server.log"),
    )
    .await?;
    get_file(
        receiver.ssh,
        Path::new(&format!("{}/bmon.out", receiver_home)),
        &out_dir.join("./bmon.log"),
    )
    .await?;

    Ok(())
}

pub async fn nobundler_exp_control(
    out_dir: &Path,
    sender: &Node<'_, '_>,
    receiver: &Node<'_, '_>,
) -> Result<(), Error> {
    let sender_home = get_home(sender.ssh, sender.user).await?;
    let receiver_home = get_home(receiver.ssh, receiver.user).await?;

    // udping receiver
    receiver
        .ssh
        .shell("cd ~/tools/udping && screen -d -m ./target/debug/udping_server -p 5999")
        .status()
        .await?;

    // udping sender -> receiver
    let udping_sender_receiver = format!("cd ~/tools/udping && screen -d -m bash -c \"./target/debug/udping_client -c {} -p 5999 > {}/udping_receiver.out 2> {}/udping_receiver.out\"", receiver.ip, sender_home, sender_home);
    sender.ssh.shell(&udping_sender_receiver).status().await?;
    // bmon receiver
    receiver
        .ssh
        .shell(&format!(
            "screen -d -m bash -c \"stdbuf -o0 bmon -p {} -b -o format:fmt='\\$(element:name) \\$(attr:rxrate:bytes)\n' > {}/bmon.out 2> {}/bmon.out\"",
            receiver.iface, receiver_home, receiver_home
        ))
        .status().await?;

    debug!("control, waiting");

    tokio::time::delay_for(tokio::time::Duration::from_secs(180)).await;

    debug!("control, getting files");

    get_file(
        sender.ssh,
        Path::new(&format!("{}/udping_receiver.out", sender_home)),
        &out_dir.join("./udping.log"),
    )
    .await?;
    get_file(
        receiver.ssh,
        Path::new(&format!("{}/bmon.out", receiver_home)),
        &out_dir.join("./bmon.log"),
    )
    .await?;

    Ok(())
}

pub async fn get_home(ssh: &Session, user: &str) -> Result<String, Error> {
    let out = ssh.shell(&format!("echo ~{}", user)).output().await?;
    let out = String::from_utf8(out.stdout)?;
    Ok(out.trim().to_string())
}

pub fn iface_name(ip_addr_out: String) -> Result<String, Error> {
    ip_addr_out
        .lines()
        .filter_map(|l| Some(IFACE_REGEX.captures(l)?.get(1)?.as_str().to_string()))
        .filter(|l| match l.as_str() {
            "lo" => false,
            _ => true,
        })
        .next()
        .ok_or_else(|| eyre!("No matching interfaces"))
}

pub async fn get_iface_name(node: &Session) -> Result<String, Error> {
    let out = node
        .shell("bash -c \"ip -o addr | awk '{print $2}'\"")
        .output()
        .await?;
    iface_name(String::from_utf8(out.stdout)?)
}

pub async fn install_basic_packages(ssh: &Session) -> Result<(), Error> {
    let mut count = 0;
    loop {
        count += 1;
        async fn do_apt(ssh: &Session) -> Result<(), Error> {
            ssh.shell("sudo apt update")
                .status()
                .await
                .wrap_err("apt update failed")?;
            ssh.shell("sudo apt update && sudo DEBIAN_FRONTEND=noninteractive apt install -y build-essential bmon iperf coreutils git automake autoconf libtool")
                .status()
                .await
                .wrap_err("apt install failed")?;
            Ok(())
        }

        match do_apt(ssh).await {
            x @ Ok(_) => return x,
            x @ Err(_) if count > 15 => return x,
            Err(e) => debug!(err = ?e, "apt failed"),
        }

        tokio::time::delay_for(tokio::time::Duration::from_secs(100)).await;
    }
}

pub async fn get_tools(ssh: &Session) -> Result<(), Error> {
    ssh.shell("sudo sysctl -w net.ipv4.ip_forward=1")
        .status()
        .await?;
    ssh.shell("sudo sysctl -w net.ipv4.tcp_wmem=\"4096000 50331648 50331648\"")
        .status()
        .await?;
    ssh.shell("sudo sysctl -w net.ipv4.tcp_rmem=\"4096000 50331648 50331648\"")
        .status()
        .await?;
    if let Err(_) = ssh
        .shell("git clone --recursive https://github.com/bundler-project/tools")
        .status()
        .await
    {
        ssh.shell("ls ~/tools")
            .status()
            .await
            .wrap_err("could not find tools directory")?;
    }
    ssh.shell("cd ~/tools/bundler && git checkout master")
        .status()
        .await?;

    ssh.shell("make -C tools").status().await?;
    Ok(())
}

pub async fn get_file(ssh: &Session, remote_path: &Path, local_path: &Path) -> Result<(), Error> {
    let mut sftp = ssh.sftp();
    let mut remote_file = sftp
        .read_from(std::path::Path::new(remote_path))
        .await
        .map_err(Error::from)?;
    let mut out = tokio::fs::File::create(local_path).await?;
    tokio::io::copy(&mut remote_file, &mut out).await?;
    Ok(())
}

pub async fn reset(sender: &Node<'_, '_>, receiver: &Node<'_, '_>) {
    let sender_ssh = sender.ssh;
    pkill(sender_ssh, "udping_client").await;
    pkill(sender_ssh, "iperf").await;
    pkill(sender_ssh, "bmon").await;
    sender_ssh
        .shell("sudo pkill -9 inbox")
        .status()
        .await
        .unwrap();
    sender_ssh
        .shell("sudo pkill -9 nimbus")
        .status()
        .await
        .unwrap();
    sender_ssh
        .shell(&format!("sudo tc qdisc del dev {} root", sender.iface))
        .status()
        .await
        .unwrap();
    let receiver_ssh = receiver.ssh;
    pkill(receiver_ssh, "udping_server").await;
    pkill(receiver_ssh, "iperf").await;
    pkill(receiver_ssh, "bmon").await;
    receiver_ssh
        .shell("sudo pkill -9 outbox")
        .status()
        .await
        .unwrap();
}

pub async fn pkill(ssh: &Session, procname: &str) {
    let cmd = format!("pkill -9 {}", procname);
    ssh.shell(&cmd).status().await.unwrap();
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
