#!/usr/bin/python3

import argparse
import itertools
import os
import random
import subprocess as sh
from tqdm import tqdm

parser = argparse.ArgumentParser()
parser.add_argument('--conns', type=int, dest='conns')
parser.add_argument('--alg', type=str, action='append', dest='algs', default=[])
parser.add_argument('--sch', type=str, action='append', dest='sch', default=[])
parser.add_argument('--dir', type=str, dest='dir')
parser.add_argument('--dry-run', action="store_true", dest='dryrun')

args = parser.parse_args()

num_exps = len(args.algs) * len(args.sch)
print("==> outdir", args.dir)
print("==> schs", args.sch)
print("==> algs", args.algs)
input("Running {} experiments.  Ok?".format(num_exps))

def get_name(args, name, conns):
    return "./{0}/{1}-{2}".format(
        args.dir,
        conns,
        name,
    )

def run_no_bundler(scheme):
    exp_name = get_name(args, scheme, args.conns)
    if os.path.exists(exp_name) or args.dryrun:
        print("==> Done {}".format(exp_name))
    else:
        print("==> Running {}".format(exp_name))
        sh.run(
            "python3 ./bundler-exp.py \
                --three_machines \
                --conns {1} \
                --outdir {0} \
                --no_bundler \
                --alg copa \
                --time 30 \
                --samplerate=512".format(
                exp_name,
                args.conns
            ),
            shell=True,
        )
        print("==> Done {}".format(exp_name))


if "nobundler" in args.algs:
    # no bundler
    sh.run("ssh 10.1.1.2 ~/bundler/qdisc/setup-no-bundler-qdisc.sh 15mbit", shell=True)
    run_no_bundler("nobundler_fifo")
    args.algs = [a for a in args.algs if a is not "nobundler"]


def run_bundler(qdisc_type, qdisc):
    exps = args.algs
    for alg in tqdm(exps):
        if alg == 'nobundler':
            continue
        outdir_name = get_name(args, "{}_{}".format(alg, qdisc_type), args.conns)
        if os.path.exists(outdir_name) or args.dryrun:
            print("==> Done {}".format(outdir_name))
        else:
            print("==> Running {}".format(outdir_name))
            sh.run(
                "python3 ./bundler-exp.py \
                    --three_machines \
                    --conns {1} \
                    --outdir {0} \
                    --qdisc {2} \
                    --alg {3} \
                    --time 30 \
                    --samplerate=512".format(
                    outdir_name,
                    args.conns,
                    qdisc,
                    alg,
                ),
                shell=True,
            )
            print("==> Done {}".format(outdir_name))


if "fqcodel" in args.sch:
    qdisc = sh.check_output("ssh 10.1.1.2 \"cd ~/bundler/qdisc && ./setup-bundler-qdisc.sh fq_codel 15mbit\" | grep bundle_inbox | awk '{print $3}'", shell=True)
    qdisc = "0x{}".format(qdisc.decode('utf-8').strip().split("\n")[-1][:-1])
    run_bundler("fqcodel", qdisc)

if "fifo" in args.sch:
    qdisc = sh.check_output("ssh 10.1.1.2 \"cd ~/bundler/qdisc && ./setup-bundler-qdisc.sh fifo 15mbit\" | grep bundle_inbox | awk '{print $3}'", shell=True)
    qdisc = "0x{}".format(qdisc.decode('utf-8').strip().split("\n")[-1][:-1])
    run_bundler("fifo", qdisc)

if "sfq" in args.sch:
    qdisc = sh.check_output("ssh 10.1.1.2 \"cd ~/bundler/qdisc && ./setup-bundler-qdisc.sh sfq 15mbit\" | grep bundle_inbox | awk '{print $3}'", shell=True)
    qdisc = "0x{}".format(qdisc.decode('utf-8').strip().split("\n")[-1][:-1])
    run_bundler("sfq", qdisc)
