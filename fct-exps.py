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
        name,
        seed,
        'bk' if backlogged else 'pl',
    )

def run_no_bundler(scheme):
    exps = itertools.product(zip(seeds, range(args.iters)), args.loads)
    for ((seed, i), l) in tqdm(exps):
        if l == '84Mbps':
            exp_name = get_name(args, l, scheme, seed, True)
            if os.path.exists(exp_name) or args.dryrun:
                print("==> Done {}".format(exp_name))
            else:
                print("==> Running {}".format(exp_name))
                sh.run(
                    "python3 ./bundler-exp.py \
                        --fct_experiment \
                        --three_machines \
                        --backlogged_bundle \
                        --conns=200 \
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
                print("==> Done {}".format(exp_name))

        exp_name = get_name(args, l, scheme, seed, False)
        if os.path.exists(exp_name) or args.dryrun:
            print("==> Done {}".format(exp_name))
        else:
            print("==> Running {}".format(exp_name))
            sh.run(
                "python3 ./bundler-exp.py \
                    --fct_experiment \
                    --three_machines \
                    --conns=200 \
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
            print("==> Done {}".format(exp_name))


if "nobundler" in args.algs:
    # no bundler
    sh.run("ssh 10.1.1.2 ~/bundler/qdisc/setup-no-bundler-qdisc.sh 15mbit", shell=True)
    run_no_bundler("nobundler_fifo")
    args.algs = [a for a in args.algs if a is not "nobundler"]

if "nobundler_sfq" in args.algs:
    exps = itertools.product(seeds, args.loads)
    for (seed, l) in tqdm(exps):
        name = get_name(args, l, "nobundler_sfq", seed, True)
        sh.run(
            "python3 nobundler-sfq.py \
                --conns=200 \
                --outdir {0} \
                --load {1} \
                --reqs {2} \
                --seed {3}".format(
                name,
                l,
                args.reqs,
                seed,
            ),
            shell=True,
        )
        print("==> Done {}".format(name))
    args.algs = [a for a in args.algs if a is not "nobundler"]

def run_bundler(qdisc_type, qdisc):
    exps = itertools.product(zip(seeds, range(args.iters)), args.loads, args.algs)
    for ((seed, i), l, alg) in tqdm(exps):
        if alg == 'nobundler':
            continue

        if l == '84Mbps': # bk only for 84Mbps exps
            outdir_name = get_name(args, l, "{}_{}".format(alg, qdisc_type), seed, True)
            if os.path.exists(outdir_name) or args.dryrun:
                print("==> Done {}".format(outdir_name))
            else:
                print("==> Running {}".format(outdir_name))
                sh.run(
                    "python3 ./bundler-exp.py \
                        --fct_experiment \
                        --three_machines \
                        --backlogged_bundle \
                        --conns=200 \
                        --outdir {0} \
                        --load {1} \
                        --reqs {2} \
                        --qdisc {3} \
                        --seed {4} \
                        --alg {5} \
                        --time 30 \
                        --samplerate=512".format(
                        outdir_name,
                        l,
                        args.reqs,
                        qdisc,
                        seed,
                        alg if alg is not "proxy_sfq" else "copa",
                    ),
                    shell=True,
                )
                print("==> Done {}".format(outdir_name))

        #outdir_name = get_name(args, l, "{}_{}".format(alg, qdisc_type), seed, False)
        #if os.path.exists(outdir_name) or args.dryrun:
        #    print("==> Done {}".format(outdir_name))
        #else:
        #    print("==> Running {}".format(outdir_name))
        #    sh.run(
        #        "python3 ./bundler-exp.py \
        #            --fct_experiment \
        #            --three_machines \
        #            --conns=200 \
        #            --outdir {0} \
        #            --load {1} \
        #            --reqs {2} \
        #            --qdisc {3} \
        #            --seed {4} \
        #            --alg {5} \
        #            --time 30 \
        #            --samplerate=512".format(
        #            outdir_name,
        #            l,
        #            args.reqs,
        #            qdisc,
        #            seed,
        #            alg,
        #        ),
        #        shell=True,
        #    )
        #    print("==> Done {}".format(outdir_name))

if "fifo" in args.sch:
    qdisc = sh.check_output("ssh 10.1.1.2 \"cd ~/bundler/qdisc && ./setup-bundler-qdisc.sh fifo 15mbit\" | grep bundle_inbox | awk '{print $3}'", shell=True)
    qdisc = "0x{}".format(qdisc.decode('utf-8').strip().split("\n")[-1][:-1])
    run_bundler("fifo", qdisc)

if "fqcodel" in args.sch:
    qdisc = sh.check_output("ssh 10.1.1.2 \"cd ~/bundler/qdisc && ./setup-bundler-qdisc.sh fq_codel 15mbit\" | grep bundle_inbox | awk '{print $3}'", shell=True)
    qdisc = "0x{}".format(qdisc.decode('utf-8').strip().split("\n")[-1][:-1])
    run_bundler("fqcodel", qdisc)

if "sfq" in args.sch:
    qdisc = sh.check_output("ssh 10.1.1.2 \"cd ~/bundler/qdisc && ./setup-bundler-qdisc.sh sfq 15mbit\" | grep bundle_inbox | awk '{print $3}'", shell=True)
    qdisc = "0x{}".format(qdisc.decode('utf-8').strip().split("\n")[-1][:-1])
    run_bundler("sfq", qdisc)
