import sys
import toml
from fabric import Connection, Result
import argparse
import agenda
import os.path
from collections import namedtuple
import time
from termcolor import colored
import logging
import socket
import itertools
import random

###################################################################################################
# Parse arguments
###################################################################################################
parser = argparse.ArgumentParser()
parser.add_argument('config')
parser.add_argument('--dry-run', action='store_true', dest='dry_run',
        help="if supplied, print commands but don't execute them, implies verbose")
parser.add_argument('--verbose', '-v', action='count', dest='verbose',
        help="if supplied, print all commands and their outputs")
parser.add_argument('--skip-setup', action='store_true', dest='skip_setup',
        help="if supplied, skip setting up the network (routing tables, nic settings, etc.)")
parser.add_argument('--skip-git', action='store_true', dest='skip_git',
        help="if supplied, skip synchronizing bundler and ccp get repos according to the config")
parser.add_argument('--interact', action='store_true', dest='interact',
        help="if supplied, wait for user to press a key before executing each command (should use with verbose)")
parser.add_argument('--overwrite-existing', action='store_true', dest='overwrite_existing',
        help="if supplied, if results already exist for a given experiment, the experiment will be re-run and results overwritten, be careful when supplying this!")
parser.add_argument('--skip-existing', action='store_true', dest='skip_existing',
        help="if supplied, if results already exist for a given experiment, that experiment will be skipped and results preserved, good for finishing an incomplete experiment")
parser.add_argument('--tcpprobe', action='store_true', dest='tcpprobe',
        help="if supplied, run tcpprobe at the sender")
###################################################################################################

###################################################################################################
# Helpers
###################################################################################################
import io
class FakeResult(object):
    def __init__(self):
        self.exited = 0
        self.stdout = '(dryrun)'

class ConnectionWrapper(Connection):
    def __init__(self, addr, nickname, verbose=False, dry=False, interact=False):
        super().__init__(addr)
        self.addr = addr
        self.nickname = nickname
        self.verbose = verbose
        self.dry = dry
        self.interact = interact

        # Start the ssh connection
        super().open()

    """
    Run a command on the remote machine

    verbose    : if true, print the command before running it, and any output it produces
                 (if not redirected)
                 if false, capture anything produced in stdout and save in result (res.stdout)
    background : if true, start the process in the background via nohup.
                 if output is not directed to a file or pty=True, this won't work
    stdin      : string of filename for stdin (default /dev/stdin as expected)
    stdout     : ""
    stderr     : ""
    ignore_out : shortcut to set stdout and stderr to /dev/null
    wd         : cd into this directory before running the given command
    sudo       : if true, execute this command with sudo (done AFTER changing to wd)

    returns result struct
        .exited = return code
        .stdout = stdout string (if not redirected to a file)
        .stderr = stderr string (if not redirected to a file)
    """
    def run(self, cmd, *args, stdin="/dev/stdin", stdout="/dev/stdout", stderr="/dev/stderr", ignore_out=False, wd=None, sudo=False, background=False, pty=True, **kwargs):
        # Prepare command string
        pre = ""
        if wd:
            pre += "cd {} && ".format(wd)
        if sudo:
            pre += "sudo "
            if ';' in cmd:
                pre += "bash -c \""
        if background:
            pre += "nohup "
        if ignore_out:
            stdin="/dev/null"
            stdout="/dev/null"
            stderr="/dev/null"
        full_cmd = "{pre}{cmd} > {stdout} 2> {stderr} < {stdin} {bg}".format(
            pre=pre,
            cmd=cmd,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            bg=("&" if background else "")
        )
        if sudo and ';' in cmd:
            full_cmd += "\""

        # Prepare arguments for invoke/fabric
        if background:
            pty=False

        # Print command if necessary
        if self.dry or self.verbose:
            print("[{}]{} {}".format(self.nickname.ljust(10), " (bg) " if background else "      ", full_cmd))

        # Finally actually run it
        if self.interact:
            input("")

        if not self.dry:
            return super().run(full_cmd, *args, hide=(not self.verbose), warn=True, pty=pty, **kwargs)
        else:
            return FakeResult()

    def file_exists(self, fname):
        res = self.run("ls {}".format(fname))
        return res.exited == 0

    def prog_exists(self, prog):
        res = self.run("which {}".format(prog))
        return res.exited == 0

    def check_proc(self, proc_name, proc_out):
        res = self.run("pgrep {}".format(proc_name))
        if res.exited != 0:
            fatal_warn('failed to find running process with name \"{}\" on {}'.format(proc_name, self.addr), exit=False)
            res = self.run('tail {}'.format(proc_out))
            if not self.verbose and res.exited == 0:
                print(res.command)
                print(res.stdout)
            sys.exit(1)


    def check_file(self, grep, where):
        res = self.run("grep \"{}\" {}".format(grep, where))
        if res.exited != 0:
            fatal_warn("Unable to find search string (\"{}\") in process output file {}".format(
                grep,
                where
            ), exit=False)
            res = self.run('tail {}'.format(where))
            if not self.verbose and res.exited == 0:
                print(res.command)
                print(res.stdout)
            sys.exit(1)

    def put(self, local_file, remote=None, preserve_mode=True):
        if remote and remote[0] == "~":
            remote = remote[2:]
        if self.dry or self.verbose:
            print("[{}] scp localhost:{} -> {}:{}".format(
                self.addr,
                local_file,
                self.addr,
                remote
            ))

        if self.interact:
            input("")

        if not self.dry:
            return super().put(local_file, remote, preserve_mode)
        else:
            return FakeResult()

    def get(self, remote_file, local=None, preserve_mode=True):
        if self.dry or self.verbose:
            print("[{}] scp {}:{} -> localhost:{}".format(
                self.addr,
                self.addr,
                remote_file,
                local
            ))

        if self.interact:
            input("")

        if not self.dry:
            return super().get(remote_file, local, preserve_mode)
        else:
            return FakeResult()

def expect(res, msg):
    if res and res.exited:
        agenda.subfailure(msg)
        print("exit code: {}\ncommand: {}\nstdout: {}\nstderr: {}".format(
            res.exited,
            res.command,
            res.stdout,
            res.stderr
        ))
    return res

def warn(msg, exit=True):
    print()
    for m in msg.split("\n"):
        print(colored("  -> {}".format(m), 'yellow', attrs=['bold']))
    print()
    if exit:
        sys.exit(1)

def fatal_warn(msg, exit=True):
    print()
    for m in msg.split("\n"):
        agenda.subfailure(m)
    print()
    if exit:
        sys.exit(1)

def fatal_error(msg, exit=True):
    print()
    agenda.failure(msg)
    print()
    if exit:
        sys.exit(1)

def read_config():
    agenda.task("Reading config file: {}".format(args.config))
    with open(args.config) as f:
        try:
            config = toml.loads(f.read())
            config['experiment_name'] = args.config.split(".toml")[0]
        except Exception as e:
            fatal_error("Failed to parse config")
            raise e
        check_config(config)
    return config

def check_config(config):
    agenda.task("Checking config file")
    topology = config['topology']
    nodes = ['sender', 'inbox', 'outbox', 'receiver']
    for node in nodes:
        assert node in topology, "Missing key topology.{}".format(node)
        assert 'name' in topology[node], "topology.{} is missing 'name' key".format(node)
        assert 'ifaces' in topology[node], "topology.{} is missing 'ifaces' key".format(node)
        assert len(topology[node]['ifaces']) > 0, "topology.{} must have at least 1 interface".format(node)
        for i,iface in enumerate(topology[node]['ifaces']):
            assert 'dev' in iface, "topology.{} iface {} is missing 'dev' key".format(node, i)
            assert 'addr' in iface, "topology.{} iface {} is missing 'addr' key".format(node, i)
    assert len(topology['inbox']['ifaces']) > 1, "topology.inbox must have at least 2 interaces"

    assert 'initial_sample_rate' in config['parameters'], "parameters must include initial_sample_rate"
    assert 'bg_port_start' in config['parameters'], "parameters must include bg_port_start"

    assert 'bundle_traffic' in config['experiment'], "must specify at least one type of bundle traffic"
    assert 'cross_traffic' in config['experiment'], "must specify at least one type of cross traffic"
    sources = ['iperf', 'poisson']
    for traffic_type in ['bundle_traffic', 'cross_traffic']:
        for traffic in config['experiment'][traffic_type]:
            for t in traffic:
                assert t['source'] in sources, "{} traffic source must be one of ({})".format(traffic_type, "|".join(sources))
                if 'start_delay' not in t:
                    t['start_delay'] = 0
                if t['source'] == 'iperf':
                    assert t['alg'], "{} missing 'alg' (str)".format(traffic_type)
                    assert t['flows'], "{} missing 'flows' (int)".format(traffic_type)
                    assert t['length'], "{} missing 'length' (int)".format(traffic_type)
                if t['source'] == 'poisson':
                    assert t['conns'], "{} missing 'conns' (int)".format(traffic_type)
                    assert t['reqs'], "{} missing 'reqs' (int)".format(traffic_type)
                    assert t['dist'], "{} missing 'dist' (str)".format(traffic_type)
                    assert t['load'], "{} missing 'load' (str)".format(traffic_type)
                    assert t['alg'], "{} missing 'alg' (str)".format(traffic_type)
                    assert t['backlogged'], "{} missing 'backlogged' (int)".format(traffic_type)

def create_ssh_connections(config):
    agenda.task("Creating SSH connections")
    conns = {}
    machines = {}
    args = config['args']
    for (role, details) in config['topology'].items():
        hostname = details['name']
        if not hostname in conns:
            agenda.subtask(hostname)
            conns[hostname] = ConnectionWrapper(hostname, nickname=role, dry=args.dry_run, verbose=args.verbose, interact=args.interact)
        machines[role] = conns[hostname]

    localhost = ConnectionWrapper('localhost', nickname='self', dry=args.dry_run, verbose=args.verbose, interact=args.interact)
    machines['self'] = localhost
    conns['self'] = localhost

    return (conns, machines)

def setup_networking(machines, config):
    agenda.task("Setting up routing tables")

    agenda.subtask("sender")
    expect(
        machines['sender'].run(
            "ip route del {receiver}; ip route add {receiver} via {inbox}".format(
                receiver = config['topology']['receiver']['ifaces'][0]['addr'],
                inbox    = config['topology']['inbox']['ifaces'][0]['addr']
            ),
            sudo=True
        ),
        "Failed to set routing tables at sender"
    )

    agenda.subtask("inbox")
    expect(
        machines['inbox'].run(
            "sysctl net.ipv4.ip_forward=1",
            sudo=True
        ),
        "Failed to set IP forwarding at inbox"
    )
    expect(
        machines['inbox'].run(
            "ip route del {receiver}; ip route add {receiver} dev {inbox_send_iface}".format(
                receiver = config['topology']['receiver']['ifaces'][0]['addr'],
                inbox_send_iface = config['topology']['inbox']['ifaces'][1]['dev']
            ),
            sudo=True
        ),
        "Failed to set forward route at inbox"
    )
    expect(
        machines['inbox'].run(
            "ip route del {sender}; ip route add {sender} dev {inbox_recv_iface}".format(
                sender = config['topology']['sender']['ifaces'][0]['addr'],
                inbox_recv_iface = config['topology']['inbox']['ifaces'][0]['dev']
            ),
            sudo=True
        ),
        "Failed to set reverse route at inbox"
    )

    agenda.subtask("outbox")
    expect(
        machines['outbox'].run(
            "ip route del {sender_addr}; ip route add {sender_addr} via {inbox_addr}".format(
                sender_addr = config['topology']['sender']['ifaces'][0]['addr'],
                inbox_addr = config['topology']['inbox']['ifaces'][1]['addr']
            ), sudo=True
        ),
        "Failed to set routing tables at outbox"
    )

    agenda.task("Turn off TSO, GSO, and GRO")
    for node in ['sender', 'inbox', 'outbox', 'receiver']:
        agenda.subtask(node)
        for i,iface in enumerate(config['topology'][node]['ifaces']):
            expect(
                machines[node].run(
                    "ethtool -K {} tso off gso off gro off".format(
                        config['topology'][node]['ifaces'][i]['dev']
                    ),
                    sudo=True
                ),
                "Failed to turn off optimizations"
            )

def create_etg_config(global_config, f, traffic):
    port_start = int(global_config['parameters']['bg_port_start'])
    num_conns = int(traffic.num_conns)
    num_backlogged = int(traffic.num_backlogged)
    for p in range(port_start, port_start + num_conns):
        f.write("server {} {}\n".format(global_config['topology']['sender']['ifaces'][0]['addr'], p))
    f.write("req_size_dist {}\n".format(os.path.expanduser(os.path.join(global_config['distribution_dir'], traffic.distribution))))
    f.write("fanout {}\n".format(traffic.fanout))
    if num_backlogged:
        f.write("persistent_servers {}\n".format(num_backlogged))
    f.write("load {}Mbps\n".format(traffic.load))
    f.write("num_reqs {}\n".format(traffic.num_reqs))

def kill_leftover_procs(config, conns):
    agenda.subtask("Kill leftover experiment processes")
    for (addr, conn) in conns.items():
        if args.verbose:
            agenda.subtask(addr)
        proc_regex = "|".join(["inbox", "outbox", *config['ccp'].keys(), "iperf", "etgClient", "etgServer"])
        conn.run(
            "pkill -9 \"({search})\"".format(
                search=proc_regex
            ),
            sudo=True
        )
        res = conn.run(
            "pgrep -c \"({search})\"".format(
                search=proc_regex
            ),
            sudo=True
        )
        if not res.exited and not config['args'].dry_run:
            fatal_warn("Failed to kill all procs on {}.".format(conn.addr))

    # True = some processes remain, therefore there *are* zombies, so we return false
    return (not res.exited)

def get_ccp_alg_dir(config, alg):
    alg_config = config['ccp'][alg]
    dir_name = alg_config['repo'].split("/")[-1].split(".git")[0]
    alg_dir = os.path.join(config['ccp_dir'], dir_name)
    return alg_dir

def get_ccp_binary_path(config, alg):
    alg_config = config['ccp'][alg]
    alg_dir = get_ccp_alg_dir(config, alg)

    if alg_config['language'] == 'rust':
        return os.path.join(alg_dir, alg_config['target'])
    elif alg_config['language'] == 'python':
        return "python {}".format(os.path.join(alg_dir, alg_config['target']))
    else:
        fatal_warn("Unknown language for {}: {}".format(alg, alg_config['language']))

def get_inbox_binary(config):
   return os.path.join(config['structure']['bundler_dir'], config['structure']['inbox_target'])

def get_outbox_binary(config):
   return os.path.join(config['structure']['bundler_dir'], config['structure']['outbox_target'])

def check_etg(config, node):
    if not node.file_exists(config['structure']['etg_dir']):
        fatal_warn("Unable to find empirical traffic generator on {}. Make sure it has been cloned".format(node.addr))

    if not node.file_exists(config['etg_client_path']):
        node.run("make -C {}".format(config['structure']['etg_dir']))


    expect(
        node.run("mkdir -p {}".format(config['distribution_dir'])),
        "Failed to create distributions directory {}".format(config['distribution_dir'])
    )

    for (dist_name, path) in config['distributions'].items():
        remote_path = os.path.join(config['distribution_dir'], dist_name)
        if not node.file_exists(remote_path):
            node.put(os.path.expanduser(path), remote=config['distribution_dir'])

    node.run("chmod +x {}".format(os.path.join(config['structure']['etg_dir'], config['structure']['etg_server'])))

def check_sender(config, sender):

    agenda.subtask("iperf (sender)")

    if not sender.file_exists(config['structure']['iperf_path']):
        fatal_warn("Unable to find reverse iperf at {} on the sender machine. Make sure it exists and is compiled.".format(config['structure']['iperf_path']))

    agenda.subtask("empirical traffic generator (sender)")
    check_etg(config, sender)


def check_inbox(config, inbox):

    agenda.subtask("inbox")

    inbox_binary = get_inbox_binary(config)
    if not inbox.file_exists(inbox_binary):
        expect(
            inbox.run("make -C {} {}".format(
                config['structure']['bundler_dir'],
                'release' if 'release' in inbox_binary else ''
            )),
            "Inbox failed to build bundler repository"
        )


    for (alg, details) in config['ccp'].items():
        agenda.subtask(alg)
        alg_dir = get_ccp_alg_dir(config, alg)
        if not inbox.file_exists(alg_dir):
            expect(
                inbox.run("git clone {} {}".format(details['repo'], alg_dir)),
                "Inbox failed to clone {}".format(alg)
            )
        branch = inbox.run("git -C {} rev-parse --abbrev-ref HEAD".format(alg_dir)).stdout.strip()
        if branch != details['branch']:
            expect(
                inbox.run("git -C {} checkout {}".format(alg_dir, details['branch'])),
                "Inbox failed to checkout branch {} of {}".format(details['branch'], alg)
            )

        commit = inbox.run("git -C {} rev-parse HEAD".format(alg_dir)).stdout.strip()
        should_recompile = False
        if not details['commit'] in commit:
            pull = expect(
                inbox.run("git -C {} pull".format(alg_dir)),
                "Inbox failed to pull latest code for {}".format(alg)
            ).stdout.strip()
            if details['commit'] == 'latest':
                if not 'Already up-to-date.' in pull:
                    should_recompile = True
            else:
                expect(
                    inbox.run("git -C {} checkout {}".format(alg_dir, details['commit'])),
                    "Inbox failed to checkout commit {} of {}".format(details['commit'], alg)
                )
                should_recompile = True

        if details['language'] == 'rust':
            ccp_binary = get_ccp_binary_path(config, alg)
            if not inbox.file_exists(ccp_binary):
                print("could not find ccp binary")
                should_recompile = True

            if should_recompile:
                new_commit = inbox.run("git -C {} rev-parse HEAD".format(alg_dir)).stdout.strip()
                if commit.strip() != new_commit.strip():
                    print("updated {} -> {}".format(alg, commit[:6], new_commit[:6]))

                print("compiling...")
                expect(
                    machines['inbox'].run("~/.cargo/bin/cargo build {}".format('--release' if 'release' in ccp_binary else ''), wd=alg_dir),
                    "Inbox failed to build {}".format(alg)
                )

def check_outbox(config, outbox):

    agenda.subtask("outbox")

    outbox_binary = get_outbox_binary(config)
    if not outbox.file_exists(outbox_binary):
        expect(
            outbox.run("make -C {} {}".format(
                config['box_root'],
                'release' if 'release' in outbox_binary else ''
            )),
            "Outbox failed to build bundler repository"
        )

def check_receiver(config, receiver):

    agenda.subtask("mahimahi (receiver)")
    if not receiver.prog_exists("mm-delay"):
        fatal_warn("Receiver does not have mahimahi installed.")

    agenda.subtask("iperf (receiver)")
    if not receiver.file_exists(config['structure']['iperf_path']):
        fatal_warn("Unable to find reverse iperf at {} on the receiver machine. Make sure it exists and is compiled.".format(config['structure']['iperf_path']))

    agenda.subtask("empirical traffic generator (receiver)")

    check_etg(config, receiver)

def start_outbox(config, outbox, emulation_env=None, bundle_client=None, cross_client=None):
    outbox_cmd = "sudo {path} --filter \"{pcap_filter}\" --iface {iface} --inbox {inbox_addr} --sample_rate {sample_rate} {extra}".format(
        path=get_outbox_binary(config),
        pcap_filter="src portrange {}-{}".format(config['parameters']['bg_port_start'], config['parameters']['bg_port_end']),
        iface="ingress" if emulation_env else config['topology']['outbox']['ifaces'][0]['dev'],
        inbox_addr='{}:{}'.format(config['topology']['inbox']['ifaces'][1]['addr'], config['topology']['inbox']['listen_port']),
        sample_rate=config['parameters']['initial_sample_rate'],
        extra="--no_ethernet" if emulation_env else '',
    )

    mm_inner = io.StringIO()
    mm_inner.write("""#!/bin/bash
set -x

{outbox_cmd} > {outbox_output} 2> {outbox_output} &

sleep 1

pids=()
{cross_clients}
{bundle_clients}

for pid in ${{pids[*]}}; do
    wait $pid
done
""".format(
        outbox_cmd=outbox_cmd,
        outbox_output=os.path.join(config['iteration_dir'], 'outbox.out'),
        cross_clients='\n'.join(["({}) &\npids+=($!)".format(c) for c in cross_client]),
        bundle_clients='\n'.join(["({}) &\npids+=($!)".format(c) for c in bundle_client]),
    ))

    mm_inner_path = os.path.join(config['iteration_dir'], 'mm_inner.sh')
    outbox.put(mm_inner, remote=mm_inner_path)
    outbox.run("chmod +x {}".format(mm_inner_path))

    if emulation_env:
        agenda.subtask("Starting traffic in emulation env ({})".format(emulation_env))
        queue_args = ''
        if emulation_env.num_bdp != 'inf':
            bdp = int((emulation_env.rate * 1000000.00 / 8.0) * (emulation_env.rtt / 1000.0) / 1500.0)
            buf_pkts = emulation_env.num_bdp * bdp
            if emulation_env.ecmp:
                queue_args = '--downlink-queue="ecmp" --uplink-queue="droptail" --downlink-queue-args="packets={buf}, queues={queues}, mean_jitter={jitter}, nonworkconserving={nonwc}" --uplink-queue-args="packets={buf}"'.format(
                    buf=buf_pkts,
                    queues=emulation_env.ecmp.queues,
                    jitter=emulation_env.ecmp.mean_jitter,
                    nonwc=(1 if emulation_env.ecmp.nonworkconserving else 0)
            )
            else:
                queue_args = '--downlink-queue="droptail" --uplink-queue="droptail" --downlink-queue-args="packets={buf}" --uplink-queue-args="packets={buf}"'.format(
                        buf=buf_pkts
                )
        if config['args'].dry_run:
            print("cat mm_inner.sh\n{}".format(mm_inner.getvalue()))
        outbox.verbose = True
        expect(
            outbox.run(
                "mm-delay {delay} mm-link --cbr {rate}M {rate}M {queue_args} --downlink-log=downlink.log {inner}".format(
                    delay=int(emulation_env.rtt / 2),
                    rate=emulation_env.rate,
                    queue_args=queue_args,
                    inner=mm_inner_path,
                ),
                wd=config['iteration_dir'],
            ),
            "Failed to start mahimahi shell on receiver"
        )
        config['iteration_outputs'].append((outbox, os.path.join(config['iteration_dir'], 'downlink.log')))
        outbox.verbose = False
    else:
        agenda.subtask("Starting traffic, no emulation")
        outbox.run(mm_inner_path, background=True)


def start_inbox(config, inbox, qtype, q_buffer_size):
    agenda.subtask("Starting inbox")

    inbox_out = os.path.join(config['iteration_dir'], "inbox.out")

    res = inbox.run(
        "{path} --iface={iface} --port={port} --sample_rate={sample} --qtype={qtype} --buffer={buf}".format(
            path=get_inbox_binary(config),
            iface=config['topology']['inbox']['ifaces'][1]['dev'],
            port=config['topology']['inbox']['listen_port'],
            sample=config['parameters']['initial_sample_rate'],
            qtype=qtype,
            buf=q_buffer_size
        ),
        sudo=True,
        background=True,
        stdout=inbox_out,
        stderr=inbox_out,
    )

    if not config['args'].dry_run:
        time.sleep(2)
    inbox.check_proc('inbox', inbox_out)
    inbox.check_file('Wait for CCP to install datapath program', inbox_out)

    config['iteration_outputs'].append((inbox, inbox_out))

    return inbox_out


def start_ccp(config, inbox, alg):
    if config['args'].verbose:
        agenda.subtask("Starting ccp")

    ccp_binary = get_ccp_binary_path(config, alg)
    ccp_binary_name = ccp_binary.split('/')[-1]
    ccp_out = os.path.join(config['iteration_dir'], "ccp.out")

    alg_args = []
    for (arg, val) in config['ccp'][alg]['args'].items():
        alg_args.append("--{}={}".format(arg, val))

    res = machines['inbox'].run(
        "{} --ipc=unix {}".format(
            ccp_binary,
            " ".join(alg_args)
        ),
        sudo=True,
        background=True,
        stdout=ccp_out,
        stderr=ccp_out,
    )

    if not config['args'].dry_run:
        time.sleep(1)
    inbox.check_proc(ccp_binary_name, ccp_out)
    inbox.check_file('starting CCP', ccp_out)

    config['iteration_outputs'].append((inbox, ccp_out))

    return ccp_out

def prepare_directories(config, conns):
    bundler_root = config['structure']['bundler_root']
    config['box_root'] = os.path.join(bundler_root, "bundler")
    config['experiment_root'] = os.path.join(bundler_root, "experiments")

    config['experiment_dir'] = os.path.join(config['experiment_root'], config['experiment_name'])
    config['ccp_dir'] = os.path.join(bundler_root, 'ccp')
    config['distribution_dir'] = os.path.join(bundler_root, 'distributions')
    config['etg_client_path'] = os.path.join(config['structure']['etg_dir'], config['structure']['etg_client'])
    config['etg_server_path'] = os.path.join(config['structure']['etg_dir'], config['structure']['etg_server'])
    config['parameters']['bg_port_end'] = config['parameters']['bg_port_start'] + 1000

    if os.path.exists(os.path.expanduser(config['experiment_dir'])):
        if not (config['args'].skip_existing or config['args'].overwrite_existing):
            fatal_warn("There are existing results for this experiment.\nYou must run this script with either --skip or --overwrite to specify how to proceed.")

    if config['args'].overwrite_existing:
        while True:
            warn("Overwrite existing results set to TRUE. Are you sure you want to continue? (y/n)", exit=False)
            got = input().strip()
            if got == 'y':
                break
            elif got == 'n':
                sys.exit(1)

    for (addr, conn) in conns.items():
        if config['args'].verbose:
            agenda.subtask(addr)

        if config['args'].overwrite_existing:
           expect(
               conn.run("rm -rf {}".format(config['experiment_dir'])),
               "Failed to remove existing experiment directory {}".format(config['experiment_dir'])
           )

        expect(
            conn.run("mkdir -p {}".format(config['experiment_dir'])),
            "Failed to create experiment directory {}".format(config['experiment_dir'])
        )
        expect(
            conn.run("mkdir -p {}".format(config['ccp_dir'])),
            "Failed to create experiment directory {}".format(config['experiment_dir'])
        )

    # Keep a copy of the config in the experiment directory for future reference
    conns['self'].run("cp {} {}".format(config['args'].config, config['experiment_dir']))

iteration_dirs = set()
def prepare_iteration_dir(config, conns):
    if config['iteration_dir'] in iteration_dirs:
        fatal_error("Iteration directory not reset! This must be a bug.")

    iteration_dirs.add(config['iteration_dir'])
    for (addr, conn) in conns.items():
        expect(
            conn.run("mkdir -p {}".format(config['iteration_dir'])),
            "Failed to create iteration directory {}".format(config['iteration_dir'])
        )


IperfTraffic = namedtuple('IperfTraffic', ['port', 'report_interval', 'length', 'num_flows', 'alg', 'start_delay'])
PoissonTraffic = namedtuple('PoissonTraffic', ['num_conns', 'num_backlogged', 'num_reqs', 'distribution', 'fanout', 'load', 'congalg', "seed", 'start_delay'])
MahimahiConfig = namedtuple('MahimahiConfig', ['rtt', 'rate', 'ecmp', 'num_bdp'])


def start_multiple_client(config, node, traffic, execute=True):
    for t in traffic:
        yield start_client(config, node, t, execute)

def start_client(config, node, traffic, execute=True):
    if not traffic:
        return None if execute else ''
    if isinstance(traffic, IperfTraffic):
        agenda.subtask("Start iperf client ({})".format(traffic))
        iperf_out = os.path.join(config['iteration_dir'], "iperf_client_{}.out".format(traffic.port))
        if traffic.port < config['parameters']['bg_port_start'] or traffic.port > config['parameters']['bg_port_end']:
            fatal_warn("Traffic ({}) is outside of bundle capture region! ({}-{})".format(
                traffic.port, config['parameters']['bg_port_start'], config['parameters']['bg_port_end']
            ))
        cmd = "sleep {delay} && {path} -c {ip} -p {port} --reverse -i {report_interval} -t {length} -P {num_flows} -Z {alg}".format(
            path=config['structure']['iperf_path'],
            ip=config['topology']['sender']['ifaces'][0]['addr'],
            port=traffic.port,
            report_interval=traffic.report_interval,
            length=traffic.length,
            num_flows=traffic.num_flows,
            alg=traffic.alg,
            delay=traffic.start_delay
        )

        config['iteration_outputs'].append((node, iperf_out))

        if execute:
            expect(
                node.run(cmd,
                    background=True,
                    stdout=iperf_out,
                    stderr=iperf_out
                ),
                "Failed to start iperf client on {}".format(node.addr)
            )
        else:
            return cmd + " > {}".format(iperf_out)
    elif isinstance(traffic, PoissonTraffic):
        if config['args'].verbose:
            agenda.subtask("Create ETG config file")

        if traffic.num_conns > 1000:
            fatal_warn("Requestedp poisson traffic with more than 1000 connections, which would be outside of outbox portrange ({}-{})".format(
                config['parameters']['bg_port_start'], config['parameters']['bg_port_end']
            ))

        i=1
        etg_config_path = os.path.join(config['iteration_dir'], "etgConfig{}".format(i))
        while node.file_exists(etg_config_path) and not config['args'].dry_run:
            i+=1
            etg_config_path = os.path.join(config['iteration_dir'], "etgConfig{}".format(i))
        with io.StringIO() as etg_config:
            create_etg_config(config, etg_config, traffic)
            node.put(etg_config, remote=os.path.join(config['iteration_dir'], "etgConfig{}".format(i)))

        etg_out = os.path.join(config['iteration_dir'], "{}".format(i))

        # NOTE: using cd + relative paths instead of absolute because etg has a buffer size of 80 for filenames
        cmd = "sleep {delay} && cd {wd} && {path} -c {config} -l {out_prefix} -s {seed}".format(
            wd=config['iteration_dir'],
            path=config['etg_client_path'],
            config=os.path.basename(etg_config_path),
            out_prefix=str(i),
            seed=traffic.seed,
            delay=traffic.start_delay
        )

        config['iteration_outputs'].append((node, etg_out + "_flows.out"))
        config['iteration_outputs'].append((node, etg_out + "_reqs.out"))

        if execute:
            expect(
                node.run(cmd,
                    background=True,
                    stdout=etg_out,
                    stderr=etg_out,
                ),
                "Failed to start poisson client on {}".format(node.addr)
            )
        else:
            return cmd

    else:
        fatal_warn("Unknown traffic type; tailed to start client")

def start_multiple_server(config, node, traffic, execute=True):
    for t in traffic:
        yield start_server(config, node, t, execute)

def start_server(config, node, traffic, execute=True):
    if not traffic:
        return None if execute else ''
    if isinstance(traffic, IperfTraffic):
        agenda.subtask("Start iperf server ({})".format(traffic))
        iperf_out = os.path.join(config['iteration_dir'], "iperf_server_{}.out".format(traffic.port))
        expect(
            node.run(
                "{path} -s -p {port} --reverse -i {report_interval} -t {length} -P {num_flows}".format(
                    path=config['structure']['iperf_path'],
                    port=traffic.port,
                    report_interval=traffic.report_interval,
                    length=traffic.length,
                    num_flows=traffic.num_flows,
                ),
                background=True,
                stdout=iperf_out,
                stderr=iperf_out
            ),
            "Failed to start iperf server on {}".format(node.addr)
        )

        if not config['args'].dry_run:
            time.sleep(1)
        node.check_file('Server listening on TCP port', iperf_out)

        config['iteration_outputs'].append((node, iperf_out))

        return iperf_out

    elif isinstance(traffic, PoissonTraffic):
        agenda.subtask("Start poisson server ({})".format(traffic))

        i=1
        etg_out = os.path.join(config['iteration_dir'], "etg_server{}.out".format(i))
        while node.file_exists(etg_out) and not config['args'].dry_run:
            i+=1
            etg_out = os.path.join(config['iteration_dir'], "etg_server{}.out".format(i))

        expect(
            node.run(
                "{sh} {start} {conns} {alg}".format(
                    sh=os.path.join(config['etg_server_path']),
                    start=config['parameters']['bg_port_start'],
                    conns=traffic.num_conns,
                    alg=traffic.congalg
                ),
                stdout=etg_out,
                stderr=etg_out,
                background=True,
            ),
            "Failed to start poisson servers on {}".format(node.addr)
        )

        if not config['args'].dry_run:
            time.sleep(1)
            num_servers_running = int(node.run("pgrep -c etgServer").stdout.strip())
        else:
            num_servers_running = traffic.num_conns
        if num_servers_running != traffic.num_conns:
            fatal_warn("Traffic pattern requested {} servers, but only {} are running properly.".format(traffic.num_conns, num_servers_running), exit=False)
            with io.BytesIO() as f:
                node.get(os.path.expanduser(etg_out), local=f)
                print(f.getvalue().decode("utf-8"))
            sys.exit(1)

        config['iteration_outputs'].append((node, etg_out))

        return etg_out

    else:
        fatal_warn("Unknown traffic type; tailed to start client")

def start_tcpprobe(config, sender):
    if config['args'].verbose:
        agenda.subtask("Start tcpprobe")
    if not sender.file_exists("/proc/net/tcpprobe"):
        fatal_warn("Could not find tcpprobe on sender. Make sure the kernel module is loaded.")

    expect(
        sender.run("dd if=/dev/null of=/proc/net/tcpprobe bs=256", sudo=True, background=True),
        "Sender failed to clear tcpprobe buffer"
    )

    tcpprobe_out = os.path.join(config['iteration_dir'], 'tcpprobe.out')
    expect(
        sender.run(
            "dd if=/proc/net/tcpprobe of={} bs=256".format(tcpprobe_out),
            sudo=True,
            background=True
        ),
        "Sender failed to start tcpprobe"
    )

    config['iteration_outputs'].append((sender, tcpprobe_out))

    return tcpprobe_out

def create_traffic_config(traffic, seed):
    for t in traffic:
        if t['source'] == 'iperf':
            yield IperfTraffic(
                port=t['port'],
                report_interval=1,
                length=t['length'],
                num_flows=t['flows'],
                alg=t['alg'],
                start_delay=t['start_delay']
            )
        elif t['source'] == 'poisson':
            yield PoissonTraffic(
                num_conns=t['conns'],
                num_backlogged=t['backlogged'],
                num_reqs=t['reqs'],
                distribution=t['dist'],
                congalg=t['alg'],
                seed=exp.seed,
                load=(int(eval(t['load'])) * exp.rate),
                start_delay=t['start_delay'],
                fanout='1 100'
        )

def traffic_str(traffic):
    if isinstance(traffic, IperfTraffic):
        return "iperf.{}.{}".format(traffic.alg, traffic.num_flows)
    if isinstance(traffic, PoissonTraffic):
        return "poisson.{}.{}".format(traffic.distribution.split("_")[0], traffic.load)


###################################################################################################

def start_interacting(machines):
    warn("Starting interactive mode", exit=False)
    for name, m in machines.items():
        m.interact = True
        m.verbose = True
def stop_interacting(machines):
    warn("Stopping interactive mode", exit=False)
    for name, m in machines.items():
        m.interact = False
        m.verbose = False

###################################################################################################
# Setup
###################################################################################################
if __name__ == "__main__":
    args = parser.parse_args()

    if args.interact:
        warn("Running in interactive mode. Each command is printed before it's run.\nPress any key to continue executing the command or control-c to stop.", exit=False)

    agenda.section("Setup")

    config = read_config()
    config['args'] = args
    if config['args'].verbose and config['args'].verbose >= 2:
        logging.basicConfig(level=logging.DEBUG)
    conns, machines = create_ssh_connections(config)
    if not args.skip_setup:
        setup_networking(machines, config)

    agenda.task("Preparing result directories")
    prepare_directories(config, conns)

    if not args.skip_git:
        agenda.task("Synchronizing code versions")
        check_sender(config, machines['sender'])
        check_inbox(config, machines['inbox'])
        check_outbox(config, machines['outbox'])
        check_receiver(config, machines['receiver'])


    agenda.section("Starting experiments")

    exp_args = config['experiment']

    ExperimentConfig = namedtuple('ExperimentConfig', list(exp_args.keys()))
    axes = list(exp_args.values())
    ps = list(itertools.product(*axes))
    exps = [ExperimentConfig(*p) for p in ps]
    random.shuffle(exps)
    total_exps = len(exps)

    for i,exp in enumerate(exps):

        if exp.alg == "nobundler" and exp.sch != "fifo":
            agenda.subtask("skipping...")
            continue

        max_digits = len(str(total_exps))
        progress = "{}/{}".format(str(i+1).zfill(max_digits), total_exps)
        agenda.task("{} | {}".format(progress, exp))

        kill_leftover_procs(config, conns)

        #TODO get exact system time that each program starts

        bundle_traffic = list(create_traffic_config(exp.bundle_traffic, exp))
        cross_traffic = list(create_traffic_config(exp.cross_traffic, exp))
        env = MahimahiConfig(rate=exp.rate, rtt=exp.rtt, num_bdp=exp.bdp, ecmp=None)

        iteration_name = "{sch}_{alg}_{rate}_{rtt}/b={bundle}_c={cross}/{seed}".format(sch=exp.sch, alg=exp.alg, rate=exp.rate, rtt=exp.rtt, seed=exp.seed, bundle=traffic_str(bundle_traffic), cross=traffic_str(cross_traffic))
        config['iteration_dir'] = os.path.join(config['experiment_dir'], iteration_name)

        if os.path.exists(os.path.expanduser(config['iteration_dir'])):
            if config['args'].skip_existing:
                agenda.subtask("skipping")
                continue
            elif config['args'].overwrite_existing:
                agenda.subtask("overwriting")
            else:
                fatal_warn("Found existing results for this experiment, but unsure how to handle it. Please provide --skip-existing or --overwite-existing")
        else:
            agenda.subtask("fresh")

        config['iteration_outputs'] = []

        prepare_iteration_dir(config, conns)

        ##### RUN EXPERIMENT

        inbox_out = start_inbox(config, machines['inbox'], exp.sch, config['parameters']['qdisc_buf_size'])
        ccp_out = start_ccp(config, machines['inbox'], exp.alg)
        machines['inbox'].check_file('Inbox ready', inbox_out)

        if config['args'].tcpprobe:
            #TODO figure out how to check for and kill dd, it's a substring in other process names
            tcpprobe_out = start_tcpprobe(config, machines['sender'])

        bundle_out = list(start_multiple_server(config, machines['sender'], bundle_traffic))
        if cross_traffic:
            cross_out = list(start_multiple_server(config, machines['sender'], cross_traffic))

        bundle_client = list(start_multiple_client(config, machines['receiver'], bundle_traffic, execute=False))
        cross_client = list(start_multiple_client(config, machines['receiver'], cross_traffic, execute=False))
        start_outbox(config, machines['outbox'], emulation_env=env, bundle_client=bundle_client, cross_client=cross_client)

        agenda.subtask("collecting results")
        for (m, fname) in config['iteration_outputs']:
            if m != machines['self']:
                try:
                    m.get(os.path.expanduser(fname), local=os.path.expanduser(os.path.join(config['iteration_dir'], os.path.basename(fname))))
                except:
                    warn("could not get file {}".format(fname))


    ### if simulation, otherwise dont need to put outbox thing in a separate script

    ###################################################################################################

