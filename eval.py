import sys
import toml
import argparse
import agenda
import os.path
from collections import namedtuple
import time
import logging
import socket
import itertools
import random
import io
import subprocess
import getpass

from util import *
from traffic import *
from ccp import *
from parse_outputs import parse_outputs
from zulip_notify import zulip_notify

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
parser.add_argument('--rows', type=str, help="rows to split graph upon", default='')
parser.add_argument('--cols', type=str, help="cols to split graph upon", default='')
parser.add_argument('--downsample', type=int, default=1, help="how much to downsample measurements")
parser.add_argument('--name', type=str, help="name of experiment directory", required=True)
parser.add_argument('--details', type=str, help="extra information to include in experiment report", default="")
###################################################################################################

def read_config(args):
    agenda.task("Reading config file: {}".format(args.config))
    with open(args.config) as f:
        try:
            config = toml.loads(f.read())
            config['experiment_name'] = args.name #args.config.split(".toml")[0]
        except Exception as e:
            print(e)
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

    assert 'listen_port' in topology['inbox'], "topology.inbox must define listen_port"

    num_self = 0
    for node in topology:
        if 'self' in topology[node] and topology[node]['self']:
            num_self += 1
    assert num_self > 0, "One node in topology section must be labeled with \"self = true\""
    assert num_self == 1, "Only one node in topology section can be labeled self"

    for k in config['sysctl']:
        v = config['sysctl'][k]
        assert type(v) == str, "key names with dots must be enclosed in quotes (sysctl)"

    assert 'initial_sample_rate' in config['parameters'], "parameters must include initial_sample_rate"
    assert 'bg_port_start' in config['parameters'], "parameters must include bg_port_start"

    structure_fields = [
        ('bundler_root', 'root directory for all experiments and code'),
        ('etg_dir', 'path to empirical traffic generator source'),
        ('etg_client', 'relative path to client binary within etg_dir'),
        ('etg_server', 'relative path to server binary within etg_dir'),
        ('iperf_path', 'path to reverse iperf binary'),
        ('bundler_dir', 'path to bundler (inbox/outbox) source code'),
        ('inbox_target', 'relative path to inbox binary within bundler_dir'),
        ('outbox_target', 'relative path to outbox binary within bundler_dir'),
    ]

    for (field,detail) in structure_fields:
        assert field in config['structure'], "[structure] missing key '{}': {}".format(field, detail)

    assert len(config['experiment']['seed']) > 0, "must specify at least one seed"
    assert len(config['experiment']['sch']) > 0, "must specify at least one scheduler (sch)"
    assert len(config['experiment']['alg']) > 0, "must specify at least one algorithm (alg)"
    assert all('name' in a for a in config['experiment']['alg']), "algs must have key name"
    assert len(config['experiment']['rate']) > 0, "must specify at least one rate"
    assert len(config['experiment']['rtt']) > 0, "must specify at least one rtt"
    assert len(config['experiment']['bdp']) > 0, "must specify at least one bdp"

    assert 'bundle_traffic' in config['experiment'], "must specify at least one type of bundle traffic"
    assert len(config['experiment']['bundle_traffic']) > 0, "must specify at least one type of bundle traffic"
    assert 'cross_traffic' in config['experiment'], "must specify at least one type of cross traffic"
    assert len(config['experiment']['cross_traffic']) > 0, "must specify at least one type of cross traffic"

    sources = ['iperf', 'poisson', 'cbr']
    for traffic_type in ['bundle_traffic', 'cross_traffic']:
        for traffic in config['experiment'][traffic_type]:
            for t in traffic:
                print(t)
                assert t['source'] in sources, "{} traffic source must be one of ({})".format(traffic_type, "|".join(sources))
                assert 'start_delay' in t, "{} missing start_delay (int)".format(traffic_type)
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
                    assert 'backlogged' in t, "{} missing 'backlogged' (int)".format(traffic_type)
                if t['source'] == 'cbr':
                    assert t['length'], "{} missing 'length (int)'".format(traffic_type)
                    assert t['port'], "{} missing 'port (int)'".format(traffic_type)
                    assert t['rate'], "{} missing 'rate (int)'".format(traffic_type)

def create_ssh_connections(config):
    agenda.task("Creating SSH connections")
    conns = {}
    machines = {}
    args = config['args']
    for (role, details) in config['topology'].items():
        hostname = details['name']
        is_self = 'self' in details and details['self']
        if is_self:
            agenda.subtask(hostname)
            conns[hostname] = ConnectionWrapper('localhost', nickname=role, dry=args.dry_run, verbose=args.verbose, interact=args.interact)
            config['self'] = conns[hostname]
        elif not hostname in conns:
            agenda.subtask(hostname)
            user = None
            port = None
            if 'user' in details:
                user = details['user']
            if 'port' in details:
                port = details['port']
            conns[hostname] = ConnectionWrapper(hostname, nickname=role, user=user, port=port, dry=args.dry_run, verbose=args.verbose, interact=args.interact)
        machines[role] = conns[hostname]

    return (conns, machines)

def update_sysctl(conns, config):
    if 'sysctl' in config:
        agenda.task("Updating sysctl")

        for (addr, conn) in conns.items():
            if config['args'].verbose or config['args'].dry_run:
                agenda.subtask(addr)

            for k in config['sysctl']:
                v = config['sysctl'][k]
                expect(
                    conn.run("sysctl -w {k}=\"{v}\"".format(k=k,v=v), sudo=True),
                    "Failed to set {k} on {addr}".format(k=k, addr=addr)
                )

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

def kill_leftover_procs(config, conns):
    agenda.subtask("Kill leftover experiment processes")
    for (addr, conn) in conns.items():
        if args.verbose:
            agenda.subtask(addr)
        proc_regex = "|".join(["inbox", "outbox", *config['ccp'].keys(), "iperf", "etgClient", "etgServer", "ccp_const"])
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

    check_ccp_alg(config, inbox)

def check_commits(config, machines):
    config['commits']['inbox'] = {}
    branch = machines['inbox'].run("git -C {} rev-parse --abbrev-ref HEAD".format(config['structure']['bundler_dir'])).stdout.strip()
    commit = machines['inbox'].run("git -C {} rev-parse HEAD".format(config['structure']['bundler_dir'])).stdout.strip()
    config['commits']['inbox']['bundler'] = "{}:{}".format(branch, commit)

    for (alg, details) in config['ccp'].items():
        alg_dir = get_ccp_alg_dir(config, alg)
        final_branch = machines['inbox'].run("git -C {} rev-parse --abbrev-ref HEAD".format(alg_dir)).stdout.strip()
        final_commit = machines['inbox'].run("git -C {} rev-parse HEAD".format(alg_dir)).stdout.strip()
        config['commits']['inbox'][alg] = "{}:{}".format(final_branch, final_commit)

    config['commits']['receiver'] = {}
    alg_dir = get_ccp_alg_dir(config, 'const')
    final_branch = machines['receiver'].run("git -C {} rev-parse --abbrev-ref HEAD".format(alg_dir)).stdout.strip()
    final_commit = machines['receiver'].run("git -C {} rev-parse HEAD".format(alg_dir)).stdout.strip()
    config['commits']['receiver'][alg] = "{}:{}".format(final_branch, final_commit)


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

    agenda.subtask("CCP (receiver)")
    #check_ccp_alg(config, receiver)

def start_outbox(config, outbox, emulation_env=None, bundle_client=None, cross_client=None, nobundler=False):
    outbox_output = os.path.join(config['iteration_dir'], 'outbox.log')
    if nobundler:
        outbox_run = "echo 'nobundler' > {outbox_output}".format(outbox_output=outbox_output)
    else:
        outbox_cmd = "sudo {path} --filter \"{pcap_filter}\" --iface {iface} --inbox {inbox_addr} --sample_rate {sample_rate} {extra}".format(
            path=get_outbox_binary(config),
            pcap_filter="src portrange {}-{}".format(config['parameters']['bg_port_start'], config['parameters']['bg_port_end']),
            iface="ingress" if emulation_env else config['topology']['outbox']['ifaces'][0]['dev'],
            inbox_addr='{}:{}'.format(config['topology']['inbox']['ifaces'][1]['addr'], config['topology']['inbox']['listen_port']),
            sample_rate=config['parameters']['initial_sample_rate'],
            extra="--no_ethernet" if emulation_env else '',
        )
        outbox_run = "{outbox_cmd} > {outbox_output} 2> {outbox_output} &".format(
            outbox_cmd = outbox_cmd,
            outbox_output = outbox_output,
        )

    mm_inner = io.StringIO()
    mm_inner.write("""#!/bin/bash
set -x

{outbox_run}

sleep 1

pids=()
{cross_clients}
{bundle_clients}

for pid in ${{pids[*]}}; do
    wait $pid
done
""".format(
        outbox_run=outbox_run,
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
            elif emulation_env.sfq:
                queue_args = '--downlink-queue="akshayfq" --downlink-queue-args="queues={queues},packets={buf}" --uplink-queue="droptail" --uplink-queue-args="packets={buf}"'.format(
                    queues=500, # TODO arbitrary for now
                    buf=buf_pkts,
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
    config['iteration_outputs'].append((outbox, outbox_output))


def start_inbox(config, inbox, qtype, q_buffer_size):
    agenda.subtask("Starting inbox")

    inbox_out = os.path.join(config['iteration_dir'], "inbox.log")

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
        time.sleep(10)
    inbox.check_proc('inbox', inbox_out)
    inbox.check_file('Wait for CCP to install datapath program', inbox_out)

    config['iteration_outputs'].append((inbox, inbox_out))

    return inbox_out

def prepare_directories(config, conns):
    agenda.task("Preparing result directories")
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

    os.makedirs(os.path.expanduser(config['experiment_dir']), exist_ok=True)

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

    subprocess.check_output("cp {} {}".format(config['args'].config, config['experiment_dir']), shell=True)

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

MahimahiConfig = namedtuple('MahimahiConfig', ['rtt', 'rate', 'ecmp', 'sfq', 'num_bdp'])

def start_tcpprobe(config, sender):
    if config['args'].verbose:
        agenda.subtask("Start tcpprobe")
    if not sender.file_exists("/proc/net/tcpprobe"):
        fatal_warn("Could not find tcpprobe on sender. Make sure the kernel module is loaded.")

    expect(
        sender.run("dd if=/dev/null of=/proc/net/tcpprobe bs=256", sudo=True, background=True),
        "Sender failed to clear tcpprobe buffer"
    )

    tcpprobe_out = os.path.join(config['iteration_dir'], 'tcpprobe.log')
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

def flatten(exps, dim):
    def f(dct):
        xs = [(k, dct[k]) for k in dct]
        expl = [(a,b) for a,b in xs if type(b) == type([])]
        done = [(a,b) for a,b in xs if type(b) != type([])]
        if len(expl) > 0:
            ks, bs = zip(*expl)
        else:
            ks, bs = ([], [])
        bs = list(itertools.product(*bs))
        expl = [dict(done + list(zip(ks, b))) for b in bs]
        return expl

    for e in exps:
        es = f(e[dim])
        for a in es:
            n = e
            n[dim] = a
            yield n

###################################################################################################
# Setup
###################################################################################################
if __name__ == "__main__":
    args = parser.parse_args()

    if args.interact:
        warn("Running in interactive mode. Each command is printed before it's run.\nPress any key to continue executing the command or control-c to stop.", exit=False)

    agenda.section("Setup")

    config = read_config(args)
    config['args'] = args
    if config['args'].verbose and config['args'].verbose >= 2:
        logging.basicConfig(level=logging.DEBUG)
    conns, machines = create_ssh_connections(config)
    if not args.skip_setup:
        setup_networking(machines, config)
        update_sysctl(machines, config)

    prepare_directories(config, conns)
    details_md = os.path.join(os.path.expanduser(config['experiment_dir']), 'details.md')
    results_md = os.path.join(os.path.expanduser(config['experiment_dir']), 'results.md')
    if not os.path.exists(details_md):
        with open(details_md, 'w') as f:
            f.write(args.details + "\n")
    if not os.path.exists(results_md):
        with open(results_md, 'w') as f:
            f.write("TODO\n")

    if not args.skip_git:
        agenda.task("Synchronizing code versions")
        check_sender(config, machines['sender'])
        check_inbox(config, machines['inbox'])
        check_outbox(config, machines['outbox'])
        check_receiver(config, machines['receiver'])

    config['commits'] = {}
    check_commits(config, machines)
    commits_md = os.path.join(os.path.expanduser(config['experiment_dir']), 'commits.md')
    with open(commits_md, 'w') as f:
        for m, commits in config['commits'].items():
            f.write("[{}]\n".format(m))
            for k, commit in commits.items():
                f.write("{} = {}\n".format(k, commit))
            f.write("\n")

    agenda.section("Starting experiments")

    exp_args = config['experiment']
    axes = list(exp_args.values())
    ps = list(itertools.product(*axes))
    exps = [dict(zip(exp_args.keys(), p)) for p in ps]
    Experiment = namedtuple("Experiment", exp_args.keys())
    exps = [Experiment(**x) for x in flatten(exps, 'alg')]

    random.shuffle(exps)
    total_exps = len(exps)

    try:
        with open('curr_url','r') as f:
            sea_url = "Follow progress here: {}".format(f.read().strip())
    except Exception as e:
        warn("Unable to find current seashells url: {}".format(e), exit=False)
        sea_url = ""

    zulip_notify("""**{me}** started a new experiment: `{name}` ({total_exps} configs)
```quote
{details}
```
{sea_url}
""".format(
        me=getpass.getuser(),
        name=config['experiment_name'],
        details=args.details,
        total_exps=total_exps,
        sea_url=sea_url
    ), dry=args.dry_run)

    total_elapsed = 0

    for i,exp in enumerate(exps):
        if exp.alg['name'] == "nobundler" and not exp.sch in ["fifo", "sfq"]:
            agenda.subtask("skipping...")
            continue

        max_digits = len(str(total_exps))
        progress = "{}/{}".format(str(i+1).zfill(max_digits), total_exps)
        agenda.task("{} | {}".format(progress, exp))

        kill_leftover_procs(config, conns)

        #TODO get exact system time that each program starts

        bundle_traffic = list(create_traffic_config(exp.bundle_traffic, exp))
        cross_traffic = list(create_traffic_config(exp.cross_traffic, exp))
        env = MahimahiConfig(
            rate=exp.rate,
            rtt=exp.rtt,
            num_bdp=exp.bdp,
            sfq=(exp.alg['name'] == "nobundler" and exp.sch == "sfq"),
            ecmp=None
        )

        name = exp.alg['name']
        exp_alg_iteration_name = name + "." + ".".join("{}={}".format(k,v) for k,v in exp.alg.items() if k != 'name')

        iteration_name = "{sch}_{rate}_{rtt}/{alg}/b={bundle}_c={cross}/{seed}".format(
            sch=exp.sch,
            alg=exp_alg_iteration_name,
            rate=exp.rate,
            rtt=exp.rtt,
            seed=exp.seed,
            bundle="+".join(str(b) for b in bundle_traffic),
            cross="+".join(str(c) for c in cross_traffic)
        )

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

        start = time.time()
        if exp.alg['name'] != "nobundler":
            inbox_out = start_inbox(config, machines['inbox'], exp.sch, config['parameters']['qdisc_buf_size'])
            ccp_out = start_ccp(config, machines['inbox'], exp.alg)
            machines['inbox'].check_file('Inbox ready', inbox_out)

        if config['args'].tcpprobe:
            #TODO figure out how to check for and kill dd, it's a substring in other process names
            tcpprobe_out = start_tcpprobe(config, machines['sender'])

        bundle_out = list(start_multiple_server(config, machines['sender'], bundle_traffic))
        if cross_traffic:
            cross_out = list(start_multiple_server(config, machines['receiver'], cross_traffic))

        bundle_client = list(start_multiple_client(config, machines['receiver'], bundle_traffic, True, execute=False))
        cross_client = list(start_multiple_client(config, machines['receiver'], cross_traffic, False, execute=False))
        start_outbox(
            config,
            machines['outbox'],
            emulation_env=env,
            bundle_client=bundle_client,
            cross_client=cross_client,
            nobundler = (exp.alg['name'] == "nobundler"),
        )

        elapsed = time.time() - start
        total_elapsed += elapsed
        agenda.subtask("Ran for {} seconds".format(elapsed))
        kill_leftover_procs(config, conns)

        agenda.subtask("collecting results")
        for (m, fname) in config['iteration_outputs']:
            if m != config['self']:
                try:
                    m.get(os.path.expanduser(fname), local=os.path.expanduser(os.path.join(config['iteration_dir'], os.path.basename(fname))))
                except Exception as e:
                    warn("could not get file {}: {}".format(fname, e), exit=False)

    agenda.task("parsing results")

    if not args.dry_run:
        parse_args = {'downsample' : config['args'].downsample}
        if config['args'].rows:
            parse_args['rows'] = config['args'].rows
        if config['args'].cols:
            parser_args['cols'] = config['args'].cols
        parse_outputs(config['experiment_dir'], parse_args)

    zulip_notify("{total_exps} experiment(s) finished in **{elapsed}** seconds.\nView results here: {url}".format(
        total_exps=total_exps,
        elapsed=round(total_elapsed,3),
        url="http://128.52.187.169:8080/{}".format(config['experiment_name']),
    ), dry=args.dry_run)
