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

import pdb

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
parser.add_argument('--tcpdump', action='store_true', dest='tcpdump',
        help="if supplied, run tcpdump at the inbox and outbox")
parser.add_argument('--rows', type=str, help="rows to split graph upon", default='')
parser.add_argument('--cols', type=str, help="cols to split graph upon", default='')
parser.add_argument('--downsample', type=int, default=1, help="how much to downsample measurements")
parser.add_argument('--name', type=str, help="name of experiment directory", required=True)
parser.add_argument('--details', type=str, help="extra information to include in experiment report", default="")
###################################################################################################

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

def prepare_directories(config, conns):
    agenda.task("Preparing result directories")

    local_experiment_dir = config['local_experiment_dir']
    if os.path.exists(local_experiment_dir):
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

    os.makedirs(local_experiment_dir, exist_ok=True)

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
    subprocess.check_output(f"cp {config['args'].config} {local_experiment_dir}", shell=True)

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

    subprocess.call(f"mkdir -p {config['local_iteration_dir']}", shell=True)

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

    topo.setup_routing(config)
    machines = topo.machines
    conns = topo.conns

    disable_tcp_offloads(config, machines)
    update_sysctl(machines, config)

    agenda.section("Setup")
    prepare_directories(config, conns)
    details_md = os.path.join(config['local_experiment_dir'], 'details.md')
    results_md = os.path.join(config['local_experiment_dir'], 'results.md')
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

        kill_leftover_procs(config, machines)

        #TODO get exact system time that each program starts

        bundle_traffic = list(create_traffic_config(exp.bundle_traffic, exp))
        cross_traffic = list(create_traffic_config(exp.cross_traffic, exp))

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
        config['local_iteration_dir'] = os.path.join(config['local_experiment_dir'], iteration_name)
        if os.path.exists(config['local_iteration_dir']):
            if config['args'].skip_existing:
                agenda.subtask("skipping experiment")
                continue
            elif config['args'].overwrite_existing:
                agenda.subtask("overwriting experiment")
            else:
                fatal_warn("Found existing results for this experiment, but unsure how to handle it. Please provide --skip-existing or --overwite-existing")

        config['iteration_outputs'] = []

        prepare_iteration_dir(config, conns)

        ##### RUN EXPERIMENT

        start = time.time()

        # starting inbox is topology-independent
        if exp.alg['name'] != "nobundler":
            inbox_out = topo.start_inbox(exp.sch, config['parameters']['qdisc_buf_size'])
            ccp_out = start_ccp(config, machines['inbox'], exp.alg)
            machines['inbox'].check_file('Inbox ready', inbox_out)
            agenda.subtask("Inbox ready")
        else:
            machines['inbox'].run(
                    "tc qdisc del dev {iface} root".format(
                        iface=config['topology']['inbox']['ifaces'][1]['dev']
                    ), sudo=True
            )
            machines['inbox'].run(
                    "tc qdisc add dev {iface} root bfifo limit 15mbit".format(
                        iface=config['topology']['inbox']['ifaces'][1]['dev']
                    ), sudo=True
            )

        if config['args'].tcpprobe:
            #TODO figure out how to check for and kill dd, it's a substring in other process names
            tcpprobe_out = start_tcpprobe(config, machines['sender'])

        if config['args'].tcpdump:
            config = start_tcpdump(config, machines)

        c = topo.run_traffic(config, exp, bundle_traffic, cross_traffic)
        if c is None:
            continue
        else:
            config = c

        elapsed = time.time() - start
        total_elapsed += elapsed
        agenda.subtask("Ran for {} seconds".format(elapsed))
        kill_leftover_procs(config, machines)
        agenda.subtask("Remove qdisc")
        machines['inbox'].run(
                "tc qdisc del dev {iface} root".format(
                    iface=config['topology']['inbox']['ifaces'][1]['dev']
                ), sudo=True
        )

        agenda.subtask("collecting results")
        for (m, fname) in config['iteration_outputs']:
            if 'self' not in config or m != config['self']:
                try:
                    if fname.startswith("~/"):
                        fname = fname[2:]
                    m.get(fname, local=os.path.join(config['local_iteration_dir'], os.path.basename(fname)))
                except Exception as e:
                    warn("could not get file {}: {}".format(fname, e), exit=False)

    agenda.section("parsing results")
    if not args.dry_run:
        parse_args = {'downsample' : config['args'].downsample}
        if config['args'].rows:
            parse_args['rows'] = config['args'].rows
        if config['args'].cols:
            parser_args['cols'] = config['args'].cols
        parse_outputs(config['local_experiment_dir'], parse_args)

    zulip_notify("{total_exps} experiment(s) finished in **{elapsed}** seconds.\nView results here: {url}".format(
        total_exps=total_exps,
        elapsed=round(total_elapsed,3),
        url="http://128.52.187.169:8080/{}".format(config['experiment_name']),
    ), dry=args.dry_run)
