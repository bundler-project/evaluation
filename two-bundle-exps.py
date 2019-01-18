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
parser.add_argument('--dir', type=str, dest='dir')
parser.add_argument('--dry-run', action="store_true", dest='dryrun')

args = parser.parse_args()

seeds = [random.randint(0, 100) for _ in range(args.iters)]
seeds = [0, 17, 26, 28, 41, 62, 67, 68, 88, 99]

num_exps = args.iters * len(args.loads) * len(args.algs)
print("==> outdir", args.dir)
print("==> loads", args.loads)
print("==> algs", args.algs)
print("==> iters", args.iters)
print("===> seeds", seeds)
input("Running {} experiments.  Ok?".format(num_exps))

def get_name(args, load, alg, seed):
    return "./{0}/{1}-{2}-{3}-{4}".format(
        args.dir,
        load,
        args.reqs,
        alg,
        seed
    )

def run_no_bundler(scheme):
    exps = itertools.product(zip(seeds, range(args.iters)), args.loads)
    for ((seed, i), ld) in tqdm(exps):
        exp_name = get_name(args, ld, scheme, seed)
        if os.path.exists(exp_name) or args.dryrun:
            print("==> Done {}".format(exp_name))
        else:
            print("==> Running {}".format(exp_name))
            sh.run(
                "python3 ./two-bundles.py \
                    --conns 200 \
                    --outdir {0} \
                    --no_bundler \
                    --load {1} \
                    --reqs {2} \
                    --seed {3} \
                    --alg copa".format(
                    exp_name,
                    ld,
                    args.reqs,
                    seed,
                ),
                shell=True,
            )
            print("==> Done {}".format(exp_name))


if "nobundler" in args.algs:
    # no bundler
    sh.run("ssh 10.1.1.2 ~/bundler/qdisc/setup-no-bundler-qdisc.sh 15mbit", shell=True)
    sh.run("ssh 192.168.1.1 ~/bundler/qdisc/setup-no-bundler-qdisc.sh 15mbit", shell=True)
    run_no_bundler("nobundler_fifo")
    args.algs = [a for a in args.algs if a is not "nobundler"]

def run_bundler(qdisc_type, qdisc1, qdisc2):
    exps = itertools.product(zip(seeds, range(args.iters)), args.loads, args.algs)
    for ((seed, i), l, alg) in tqdm(exps):
        if alg == 'nobundler':
            continue
        outdir_name = get_name(args, l, "{}_{}".format(alg, qdisc_type), seed)
        if os.path.exists(outdir_name) or args.dryrun:
            print("==> Done {}".format(outdir_name))
        else:
            print("==> Running {}".format(outdir_name))
            sh.run(
                "python3 ./two-bundles.py \
                    --conns 200 \
                    --outdir {0} \
                    --load {1} \
                    --reqs {2} \
                    --qdisc1 {3} \
                    --qdisc2 {4} \
                    --seed {5} \
                    --alg {6}".format(
                    outdir_name,
                    l,
                    args.reqs,
                    qdisc1,
                    qdisc2,
                    seed,
                    alg,
                ),
                shell=True,
            )
            print("==> Done {}".format(outdir_name))

qdisc1 = sh.check_output("ssh 10.1.1.2 \"cd ~/bundler/qdisc && ./setup-bundler-qdisc.sh sfq 15mbit\" | grep bundle_inbox | awk '{print $3}'", shell=True)
qdisc2 = sh.check_output("ssh 192.168.1.1 \"cd ~/bundler/qdisc && ./setup-bundler-qdisc.sh sfq 15mbit\" | grep bundle_inbox | awk '{print $3}'", shell=True)
qdisc1 = "0x{}".format(qdisc1.decode('utf-8').strip().split("\n")[-1][:-1])
qdisc2 = "0x{}".format(qdisc2.decode('utf-8').strip().split("\n")[-1][:-1])
run_bundler("sfq", qdisc1, qdisc2)
