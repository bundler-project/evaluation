#!/usr/bin/python3

import sys
import itertools

expdir = sys.argv[1]

exps = (("48Mbps", "36Mbps"), ("60Mbps", "24Mbps"), ("72Mbps", "12Mbps"))
reqs = 10000
algs = ("bbr_sfq", "copa_sfq", "nimbus_sfq", "nimcopa_sfq", "nobundler_fifo")
#seeds = ("0", "17", "26", "28", "41", "62", "67", "68", "88", "99")
seeds= ("0")

def get_exps(expdir, exps, algs, seeds):
    for ((l, cr), a, s) in itertools.product(exps, algs, seeds):
        yield ((l, cr, a, s), '{}/{}-inelastic-{}-{}-{}-{}/_flows.out'.format(expdir, l, cr, reqs, a, s))

def process_exp(exp, fl):
    l, cr, a, s = exp
    with open(fl, 'r') as f:
        for line in f:
            n = line.strip()
            print("{}, Load:{}, Cross:{}, Alg:{}, Iter:{}".format(n, l, cr, a, s))

for ex, fl in get_exps(expdir, exps, algs, seeds):
    process_exp(ex, fl)
