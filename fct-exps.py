#!/usr/bin/python3

import argparse
import subprocess as sh
import os
import random

parser = argparse.ArgumentParser()
parser.add_argument('--iters', type=int, dest='iters')
parser.add_argument('--reqs', type=int, dest='reqs')
parser.add_argument('--load', type=str, action='append', dest='loads')
parser.add_argument('--alg', type=str, action='append', dest='algs')
parser.add_argument('--dir', type=str, dest='dir')

args = parser.parse_args()

seeds = [random.randint(0, 100) for _ in range(args.iters)]

def get_name(args, load, name, seed):
    return "./{0}/{1}load-{2}req-{3}-{4}".format(args.dir, load, name, seed)

def run_no_bundler(args, scheme):
    for seed, i in zip(seeds, range(args.iters)):
        for l in args.loads:
            exp_name = get_name(args, l, )
            if not os.path.exists(exp_name):
                sh.run(
                    "python3 ./bundler-exp.py \
                        --fct_experiment \
                        --three_machines \
                        --backlogged_bundle \
                        --conns=100 \
                        --outdir {0} \
                        --no_bundler \
                        --load {1} \
                        --reqs={2} \
                        --seed={3} \
                        --alg nimbus \
                        --time 30 \
                        --samplerate=512".format(
                        exp_name,
                        l,
                        args.reqs,
                        seed
                    ),
                    shell=True,
                )

# with tcp proxy
sh.run("ssh 10.1.1.2 \"cd ~/bundler/qdisc && ./setup-tcpproxy-qdisc.sh sfq 15mbit\"", shell=True)
# set init cwnd to be high
sh.run("ssh 192.168.1.5 \"sudo ip route change 10.1.1.6 via 192.168.1.2 dev em2 proto kernel initcwnd 1000\"", shell=True)
run_no_bundler("nobundler_proxy_sfq")
# reset init cwnd to default
sh.run("ssh 192.168.1.5 \"sudo ip route change 10.1.1.6 via 192.168.1.2 dev em2 proto kernel initcwnd 10\"", shell=True)

# no bundler
sh.run("ssh 10.1.1.2 ~/bundler/qdisc/setup-no-bundler-qdisc.sh 15mbit", shell=True)
run_no_bundler("fifo")

def run_bundler(qdisc_type, qdisc):
    for seed, i in zip(seeds, range(args.iters)):
        for l in args.loads:
            for alg in args.algs:
                outdir_name = get_name(args, l, "{}_{}".format(alg, qdisc_type), seed)
                if not os.path.exists(outdir_name):
                    sh.run(
                        "python3 ./bundler-exp.py \
                            --fct_experiment \
                            --three_machines \
                            --backlogged_bundle \
                            --conns=100 \
                            --outdir {0} \
                            --load {1} \
                            --reqs {2} \
                            --qdisc {3} \
                            --seed {4} \
                            --alg {5} \
                            --time 30 \
                            --samplerate=512".format(
                            bbr_outdir_name,
                            l,
                            args.reqs,
                            qdisc,
                            seed,
                            alg,
                        ),
                        shell=True,
                    )

# with bundler-fifo
qdisc = sh.check_output("ssh 10.1.1.2 \"cd ~/bundler/qdisc && ./setup-bundler-qdisc.sh fifo 15mbit\" | grep bundle_inbox | awk '{print $3}'", shell=True)
qdisc = "0x{}".format(qdisc.decode('utf-8').strip().split("\n")[-1][:-1])
run_bundler("fifo", qdisc)

# with bundler-fqcodel
qdisc = sh.check_output("ssh 10.1.1.2 \"cd ~/bundler/qdisc && ./setup-bundler-qdisc.sh fq_codel 15mbit\" | grep bundle_inbox | awk '{print $3}'", shell=True)
qdisc = "0x{}".format(qdisc.decode('utf-8').strip().split("\n")[-1][:-1])
run_bundler("fqcodel", qdisc)

# with bundler-sfq
qdisc = sh.check_output("ssh 10.1.1.2 \"cd ~/bundler/qdisc && ./setup-bundler-qdisc.sh sfq 15mbit\" | grep bundle_inbox | awk '{print $3}'", shell=True)
qdisc = "0x{}".format(qdisc.decode('utf-8').strip().split("\n")[-1][:-1])
run_bundler("sfq", qdisc)

# with tcp proxy
sh.run("ssh 10.1.1.2 \"cd ~/bundler/qdisc && ./setup-tcpproxy-qdisc.sh sfq 15mbit\"", shell=True)
# set init cwnd to be high
sh.run("ssh 192.168.1.5 \"sudo ip route change 10.1.1.6 via 192.168.1.2 dev em2 proto kernel initcwnd 1000\"", shell=True)
run_bundler("proxy_sfq", qdisc)
# reset init cwnd to default
sh.run("ssh 192.168.1.5 \"sudo ip route change 10.1.1.6 via 192.168.1.2 dev em2 proto kernel initcwnd 10\"", shell=True)
