import os, sys, json
from itertools import permutations
from collections import deque

###############################################################################
# Scheduling algorithm from:
# https://en.wikipedia.org/wiki/Round-robin_tournament#Scheduling_algorithm

def build_pairs(ms):
    ms = list(ms)
    # 1 is always in fixed position at the beginning of the line
    ms = [1] + ms
    mid = int(len(ms)/2)
    l,r = ms[:mid], ms[mid:]
    r = r[::-1]
    pairs = [(l[i], r[i]) for i in range(mid)]
    # NOTE: We need `opp` because paths are not necessarily symmetric.
    #       This algorithm was designed for round-robin tournaments and thus
    #       assumes x playing y is the same as y playing x
    opp = [(r[i], l[i]) for i in range(mid)]
    return pairs + opp

def schedule(n):
    schedule = []
    # list of numbers 2,...,n 
    # this is the set that will rotate, 1 is fixed at the front
    ms = deque(range(2,n+1))

    # there are n-1 total rounds
    for rnd in range(n-1):
        pairs = build_pairs(ms)
        schedule.append(pairs)
        ms.rotate(1)

    return schedule

###############################################################################
# Helper functions

def name(m):
    if 'Baremetal' in m:
        return m['Baremetal']['name']
    elif 'Aws' in m:
        reg = m['Aws']['region'].replace('-', '')
        return f'aws_{reg}'
    elif 'Azure' in m:
        reg = m['Azure']['region']
        return f'az_{reg}'
    else:
        assert False

def already_done(src, dst):
    base_dir = os.path.dirname(filename)
    dirname = base_dir.join(f"{name(src)}-{name(dst)}")
    if not os.path.exists(dirname):
        return False
    fs = [[x, 'udping.log'] for x in ['control', 'iperf']]
    return all(os.path.exists(os.path.join(dirname, *f)) for f in fs)

###############################################################################
# Main

if len(sys.argv) != 2:
    print(f"usage: python3 {sys.argv[0]} [machines.json]")
filename = sys.argv[1]

with open(filename) as f:
    machines = json.loads(f.read())

machines = {i+1: m for i,m in zip(range(len(machines)), machines)}
n = len(machines.keys())
print(f"==> Found {n} machines in {filename}\n")

s = schedule(n)

# sanity check that all pairs have been used in the schedule
flat = set(sum(s, []))
all_pairs = set(permutations(machines.keys(), 2))
assert(flat == all_pairs)

# write the schedule to phase files
phase = 1
for pairs in s:
    print(f"Phase {phase}: {len(pairs)} pairs")
    with open(f"phase_{phase}.json", 'w') as f:
        objs = []
        for (src,dst) in pairs:
            if not already_done(machines[src], machines[dst]):
                obj = {"from" : machines[src], "to" : machines[dst]}
                objs.append(obj)
        if len(objs) == 0:
            print("> All pairs in Phase {phase} already completed, file will be empty.")
        f.write(json.dumps(objs))
    phase += 1
