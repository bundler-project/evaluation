import os, sys, json
from itertools import permutations

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

if len(sys.argv) != 2:
    print(f"usage: python3 {sys.argv[0]} [machines.json]")
filename = sys.argv[1]

with open(filename) as f:
    machines = json.loads(f.read())

machines = {i: m for i,m in zip(range(len(machines)), machines)}

all_pairs = list(permutations(machines.keys(), 2))
pairs_done = set()
num_pairs = len(all_pairs)
groups = []
group_size = 7

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
            #if lookup_pair_rtt(src, dst):
            if not already_done(machines[src], machines[dst]):
                print('phase', len(groups), 'adding', name(machines[src]), name(machines[dst]))
                pairs_done.add(pair)
                curr_group.append(pair)
                machines_in_use.add(src)
                machines_in_use.add(dst)
            else:
                print('phase', len(groups), 'skipping', name(machines[src]), name(machines[dst]))
        else:
            i+=1

    groups.append(curr_group)

phase = 1
for group in groups:
    if len(group) > 0:
        with open(f"phase_{phase}.json", 'w') as f:
            objs = []
            for (src,dst) in group:
                obj = {"from" : machines[src], "to" : machines[dst]}
                objs.append(obj)
            f.write(json.dumps(objs))
        phase+=1
