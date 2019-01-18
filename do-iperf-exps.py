#!/usr/bin/python3

import argparse
import itertools
import os
import random
import subprocess as sh
from tqdm import tqdm

parser = argparse.ArgumentParser()
parser.add_argument('--iters', type=int, dest='iters')
parser.add_argument('--alg', type=str, action='append', dest='algs', default=[])
parser.add_argument('--conns', type=str, action='append', dest='conns', default=[])
parser.add_argument('--dir', type=str, dest='dir')

args = parser.parse_args()

print("==> outdir", args.dir)
print("==> algs", args.algs)
print("==> iters", args.iters)

def get_name(args, alg, conns, it, isBundler):
    return "./{0}/{1}-96M50ms_{2}flows-{3}".format(
        args.dir,
        alg + '-bundler' if isBundler else '-e2e',
        conns,
        it,
    )

def run_bundler(qdisc_type, qdisc):
    exps = itertools.product(range(args.iters), args.conns, args.algs)
    for (i, cs, alg) in tqdm(exps):
        if alg == 'nobundler':
            continue

        outdir_name = get_name(args, alg, cs, i, True)
        if os.path.exists(outdir_name):
            print("==> Done {}".format(outdir_name))
        else:
            print("==> Running {}".format(outdir_name))
            sh.run(
                "python3 ./iperf-exp.py \
                    --time 30 \
                    --outdir {0} \
                    --qdisc {1} \
                    --conns {2} \
                    --alg {3}".format(
                    outdir_name,
                    qdisc,
                    cs,
                    alg,
                ),
                shell=True,
            )
            print("==> Done {}".format(outdir_name))


def run_no_bundler():
    exps = itertools.product(range(args.iters), args.conns, args.algs)
    for (i, cs, alg) in tqdm(exps):
        outdir_name = get_name(args, alg, cs, i, False)
        if os.path.exists(outdir_name):
            print("==> Done {}".format(outdir_name))
        else:
            print("==> Running {}".format(outdir_name))
            sh.run(
                "python3 ./iperf-nobundler-exp.py \
                    --time 30 \
                    --outdir {0} \
                    --conns {1} \
                    --alg {2}".format(
                    outdir_name,
                    cs,
                    alg,
                ),
                shell=True,
            )
            print("==> Done {}".format(outdir_name))


qdisc = sh.check_output("ssh 10.1.1.2 \"cd ~/bundler/qdisc && ./setup-bundler-qdisc.sh fifo 15mbit\" | grep bundle_inbox | awk '{print $3}'", shell=True)
qdisc = "0x{}".format(qdisc.decode('utf-8').strip().split("\n")[-1][:-1])
run_bundler("fifo", qdisc)

sh.run("ssh 10.1.1.2 ~/bundler/qdisc/setup-no-bundler-qdisc.sh 15mbit", shell=True)
run_no_bundler()
