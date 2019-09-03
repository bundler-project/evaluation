use failure::{format_err, Error};
use regex::Regex;
use std::path::Path;
use tsunami::Session;

lazy_static::lazy_static! {
    static ref IFACE_REGEX: Regex = Regex::new(r"[0-9]+:\s+([a-z]+[0-9]+)\s+inet").unwrap();
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
            ssh.cmd("sudo apt update && sudo DEBIAN_FRONTEND=noninteractive apt install -y build-essential iperf git automake autoconf libtool")
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
    ssh.cmd("git clone --recursive https://github.com/bundler-project/tools")
        .map(|(_, _)| ())?;
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
