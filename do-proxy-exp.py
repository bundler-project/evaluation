#!/usr/bin/python3

import argparse
import itertools
import os
import random
import subprocess as sh
from tqdm import tqdm

parser = argparse.ArgumentParser()
parser.add_argument('--iters', type=int, dest='iters')
parser.add_argument('--reqs', type=int, dest='reqs')
parser.add_argument('--load', type=str, action='append', dest='loads', default=[])
parser.add_argument('--alg', type=str, action='append', dest='algs', default=[])
parser.add_argument('--sch', type=str, action='append', dest='sch', default=[])
parser.add_argument('--dir', type=str, dest='dir')
parser.add_argument('--dry-run', action="store_true", dest='dryrun')

args = parser.parse_args()

seeds = [random.randint(0, 100) for _ in range(args.iters)]
seeds = [0, 17, 26, 28, 41, 62, 67, 68, 88, 99]

num_exps = args.iters * len(args.loads) * len(args.algs) * len(args.sch) * 2
print("==> outdir", args.dir)
print("==> loads", args.loads)
print("==> schs", args.sch)
print("==> algs", args.algs)
print("==> iters", args.iters)
print("===> seeds", seeds)
input("Running {} experiments.  Ok?".format(num_exps))

def get_name(args, load, name, seed, backlogged):
    return "./{0}/{1}-{2}-{3}-{4}-{5}".format(
        args.dir,
        load,
        args.reqs,
        'proxy_'+name,
        seed,
        'bk' if backlogged else 'pl',
    )

def run_bundler(qdisc_type, qdisc):
    exps = itertools.product(zip(seeds, range(args.iters)), args.loads, args.algs)
    for ((seed, i), l, alg) in tqdm(exps):
        if alg == 'nobundler':
            continue

        outdir_name = get_name(args, l, "{}_{}".format(alg, qdisc_type), seed, False)
        if os.path.exists(outdir_name) or args.dryrun:
            print("==> Done {}".format(outdir_name))
        else:
            print("==> Running {}".format(outdir_name))
            sh.run(
                "python3 ./proxy-exp.py \
                    --conns 200 \
                    --outdir {0} \
                    --load {1} \
                    --reqs {2} \
                    --qdisc {3} \
                    --seed {4} \
                    --alg {5}".format(
                    outdir_name,
                    l,
                    args.reqs,
                    qdisc,
                    seed,
                    alg,
                ),
                shell=True,
            )
            print("==> Done {}".format(outdir_name))

if "fifo" in args.sch:
    qdisc = sh.check_output("ssh 10.1.1.2 \"cd ~/bundler/qdisc && ./setup-bundler-qdisc.sh fifo 150mbit\" | grep bundle_inbox | awk '{print $3}'", shell=True)
    qdisc = "0x{}".format(qdisc.decode('utf-8').strip().split("\n")[-1][:-1])
    run_bundler("fifo", qdisc)

if "fqcodel" in args.sch:
    qdisc = sh.check_output("ssh 10.1.1.2 \"cd ~/bundler/qdisc && ./setup-bundler-qdisc.sh fq_codel 150mbit\" | grep bundle_inbox | awk '{print $3}'", shell=True)
    qdisc = "0x{}".format(qdisc.decode('utf-8').strip().split("\n")[-1][:-1])
    run_bundler("fqcodel", qdisc)

if "sfq" in args.sch:
    qdisc = sh.check_output("ssh 10.1.1.2 \"cd ~/bundler/qdisc && ./setup-bundler-qdisc.sh sfq 150mbit\" | grep bundle_inbox | awk '{print $3}'", shell=True)
    qdisc = "0x{}".format(qdisc.decode('utf-8').strip().split("\n")[-1][:-1])
    run_bundler("sfq", qdisc)
