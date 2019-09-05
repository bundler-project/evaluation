import os, sys, json
from itertools import permutations

if len(sys.argv) != 2:
    print(f"usage: python3 {sys.argv[0]} [machines.json]")
filename = sys.argv[1]

with open(filename) as f:
    machines = json.loads(f.read())

name_map = {}
for machine in machines:
    if 'Baremetal' in machine:
        name = machine['Baremetal']['name']
    elif 'Aws' in machine:
        name = machine['Aws']['region']
    name_map[name] = machine

names = name_map.keys()

all_pairs = list(permutations(names, 2))
pairs_done = set()
num_pairs = len(all_pairs)
groups = []
group_size = int(len(names) / 2)

while len(pairs_done) < num_pairs:
    i = 0
    curr_group = []
    machines_in_use = set()

    while len(curr_group) < group_size:
        if i >= len(all_pairs):
            break
        src, dst = all_pairs[i]
        if not src in machines_in_use and not dst in machines_in_use:
            pair = all_pairs.pop(i)
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
            obj = {"from" : name_map[src], "to" : name_map[dst]}
            objs.append(obj)
        f.write(json.dumps(objs))
    phase+=1
