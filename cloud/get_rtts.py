#!/usr/bin/python3

import re
import sys
import glob
import numpy as np

rtt_pattern = re.compile(r"time=(.*)ms")

def rtts(fn):
    with open(fn, 'r') as f:
        for line in f:
            m = rtt_pattern.findall(line)
            if len(m) >= 1:
                yield float(m[0])

def parse_fn(fn):
    sp = fn.split("/")
    _, ends, exp, _ = sp
    with_bundler = ("bundler-exp" == exp)
    src, p1, p2, p3, it = ends.split("-")
    return (src, f"{p1}{p2}{p3}", it, with_bundler)

fs = glob.iglob("./mit*/**/ping.log", recursive=True)
rtts = {fn: list(rtts(fn)) for fn in fs}

print("src", "dst", "iteration", "with_bundler", "avgrtt")
for fn in rtts:
    src, dst, it, with_bundler = parse_fn(fn)
    print(src, dst, it, with_bundler, np.mean(rtts[fn]))

