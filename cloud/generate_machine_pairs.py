import os, sys, json
from itertools import permutations

if len(sys.argv) != 2:
    print(f"usage: python3 {sys.argv[0]} [machines.json]")
filename = sys.argv[1]

with open(filename) as f:
    machines = json.loads(f.read())

def lookup_pair_rtt(src, dst):
    with open("minrtts.out", 'r') as f:
        for line in f:
            frm, to, _, _ = line.split()
            if src not in machines or dst not in machines:
                continue
            print(src, dst, frm, to)
            if frm == list(machines[src].values())[0]['name'] and to == list(machines[dst].values())[0]['name']:
                return True
        return False

machines = {i: m for i,m in zip(range(len(machines)), machines)}

all_pairs = list(permutations(machines.keys(), 2))
pairs_done = set()
num_pairs = len(all_pairs)
groups = []
group_size = 5

while len(all_pairs) > 0:
    i = 0
    curr_group = []
    machines_in_use = set()

    while len(curr_group) < group_size:
        if i >= len(all_pairs):
            break
        src, dst = all_pairs[i]
        if not src in machines_in_use and not dst in machines_in_use:
            pair = all_pairs.pop(i)
            if lookup_pair_rtt(src, dst):
                pairs_done.add(pair)
                curr_group.append(pair)
                machines_in_use.add(src)
                machines_in_use.add(dst)
        else:
            i+=1

    groups.append(curr_group)

phase = 1
for group in groups:
    with open(f"phase_{phase}.json", 'w') as f:
        objs = []
        for (src,dst) in group:
            obj = {"from" : machines[src], "to" : machines[dst]}
            objs.append(obj)
        f.write(json.dumps(objs))
    phase+=1
