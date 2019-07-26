import sys
import argparse
import agenda
import os.path
from collections import namedtuple
import time
import logging
import io
import subprocess
import getpass

from ccp import *
from config import read_config, enumerate_experiments
from parse_outputs import parse_outputs
from traffic import *
from topology import *
from util import *
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

def get_inbox_binary(config):
   p = os.path.join(config['structure']['bundler_root'], "bundler/target/debug/inbox")
   if not os.path.exists(p):
       raise Exception("inbox binary not found")

   return p

def get_outbox_binary(config):
   p = os.path.join(config['structure']['bundler_root'], "bundler/target/debug/outbox")
   if not os.path.exists(p):
       raise Exception("outbox binary not found")

def check_etg(config, node):
    expect(
        node.run("mkdir -p {}".format(config['distribution_dir'])),
        "Failed to create distributions directory {}".format(config['distribution_dir'])
    )

    for (dist_name, path) in config['distributions'].items():
        remote_path = os.path.join(config['distribution_dir'], dist_name)
        if not node.file_exists(remote_path):
            node.put(os.path.expanduser(path), remote=config['distribution_dir'])

def check_inbox(config, inbox):
    agenda.task("inbox")
    check_ccp_alg(config, inbox)

def check_receiver(config, receiver):
    if 'cloudlab' in config['topology']:
        return

    agenda.task("mahimahi (receiver)")
    if not receiver.prog_exists("mm-delay"):
        fatal_warn("Receiver does not have mahimahi installed.")

def outbox_output_location(config):
    return os.path.join(config['iteration_dir'], 'outbox.log')

def start_outbox(config, in_mahimahi=True):
    outbox_output = outbox_output_location(config)
    outbox_cmd = "sudo {path} --filter \"{pcap_filter}\" --iface {iface} --inbox {inbox_addr} --sample_rate {sample_rate} {extra}".format(
        path=get_outbox_binary(config),
        pcap_filter="src portrange {}-{}".format(config['parameters']['bg_port_start'], config['parameters']['bg_port_end']),
        iface="ingress" if in_mahimahi else config['topology']['outbox']['ifaces'][0]['dev'],
        inbox_addr='{}:{}'.format(config['topology']['inbox']['ifaces'][1]['addr'], config['topology']['inbox']['listen_port']),
        sample_rate=config['parameters']['initial_sample_rate'],
        extra="--no_ethernet" if in_mahimahi else '',
    )
    outbox_run = f"{outbox_cmd} > {outbox_output} 2> {outbox_output} &"
    return outbox_run

def start_traffic_mahimahi(config, outbox, with_outbox=True, emulation_env=None, bundle_client=None, cross_client=None):
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
        outbox_run=start_outbox(config, in_mahimahi=emulation_env) if with_outbox else '',
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
                queue_args = f'--downlink-queue="ecmp" --uplink-queue="droptail" \
                    --downlink-queue-args="packets={buf_pkts},\
                    queues={emulation_env.ecmp.queues},\
                    mean_jitter={emulation_env.ecmp.mean_jitter},\
                    nonworkconserving={(1 if emulation_env.ecmp.nonworkconserving else 0)}"\
                    --uplink-queue-args="packets={buf_pkts}"'
            elif emulation_env.sfq:
                queue_args = '--downlink-queue="akshayfq"\
                    --downlink-queue-args="queues={queues},packets={buf}"\
                    --uplink-queue="droptail"\
                    --uplink-queue-args="packets={buf}"'.format(
                    queues=500, # TODO arbitrary for now
                    buf=buf_pkts,
                )
            else:
                queue_args = f'--downlink-queue="droptail"\
                    --uplink-queue="droptail"\
                    --downlink-queue-args="packets={buf}"\
                    --uplink-queue-args="packets={buf_pkts}"'
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
    config['iteration_outputs'].append((outbox, outbox_output_location(config)))


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
    config['etg_client_path'] = os.path.join(config['structure']['bundler_root'], "empirical-traffic-gen/bin/etgClient")
    config['etg_server_path'] = os.path.join(config['structure']['bundler_root'], "empirical-traffic-gen/run-servers.py")
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

    agenda.section("Read config")
    config = read_config(args)
    config['args'] = args
    if config['args'].verbose and config['args'].verbose >= 2:
        logging.basicConfig(level=logging.DEBUG)

    if 'cloudlab' in config['topology']:
        topo = CloudlabTopo(config)
    else:
        topo = MahimahiTopo(config)

    topo.setup_routing()
    machines = topo.machines
    conns = topo.conns

    disable_tcp_offloads(config, machines)
    update_sysctl(machines, config)

    agenda.section("Setup")
    prepare_directories(config, conns)
    details_md = os.path.join(os.path.expanduser(config['experiment_dir']), 'details.md')
    results_md = os.path.join(os.path.expanduser(config['experiment_dir']), 'results.md')
    if not os.path.exists(details_md):
        with open(details_md, 'w') as f:
            f.write(args.details + "\n")
    if not os.path.exists(results_md):
        with open(results_md, 'w') as f:
            f.write("TODO\n")

    agenda.section("Synchronizing code versions")
    if not args.skip_git:
        check_inbox(config, machines['inbox'])
        check_receiver(config, machines['receiver'])

    exps = enumerate_experiments(config)
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

        mahimahiCfg = None
        if 'cloudlab' not in config['topology']:
            mahimahiCfg = MahimahiConfig(
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
            cross_src = machines['receiver']
            if mahimahiCfg is None:
                cross_src = machines['inbox'] # no emulation, cross traffic should traverse the network
            cross_out = list(start_multiple_server(config, machines['receiver'], cross_traffic))

        if mahimahiCfg is None:
            cmd = start_outbox(config, in_mahimahi=False)
            machines['outbox'].run(cmd, stdout=outbox_output_location(config), background=True)

        bundle_client = list(start_multiple_client(
            config,
            machines['receiver'],
            bundle_traffic,
            True,
            execute=(mahimahiCfg is None)))
        cross_client = list(start_multiple_client(
            config,
            machines['receiver'],
            cross_traffic,
            False,
            execute=(mahimahiCfg is None)))

        if mahimahiCfg is not None:
            start_traffic_mahimahi(
                config,
                machines['receiver'],
                emulation_env=mahimahiCfg,
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
                    if fname.startswith("~/"):
                        fname = fname[2:]
                    m.get(fname, local=os.path.expanduser(os.path.join(config['iteration_dir'], os.path.basename(fname))))
                except Exception as e:
                    warn("could not get file {}: {}".format(fname, e), exit=False)

    kill_leftover_procs(config, conns)
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
