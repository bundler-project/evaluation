#!/usr/bin/python3

import sys

delim = ":"
cross_traffic_pattern = []
if len(sys.argv) > 1:
    for cross in sys.argv[1].split(","):
        tr, name = cross.split("=")
        start,end = [int(x)*1000 for x in tr.split(":")]
        cross_traffic_pattern.append((start,end,name))
    print_head = eval(sys.argv[2])


def flds(line):
    for f in line:
        sp = f.split(delim)
        try:
            yield sp[0], sp[1].split(",")[0]
        except:
            print('line', line, sp, file=sys.stderr)
            raise Exception()

head = None
start_time_col = None
duration_col = None
init_time = None

for line in sys.stdin:
    sp = line.strip().split()
    if head is None:
        fields, vals = zip(*flds(sp))
        head = fields
        for idx,field in enumerate(head):
            if field == "StartTime(ms)":
                start_time_col = idx
            if field == "Duration(usec)":
                duration_col = idx
        if print_head:
            actual_head = head
            if cross_traffic_pattern:
                actul_head = head + ("start","finish","during",)
            print(" ".join(actual_head))
    else:
        fields, vals = zip(*flds(sp))
        if head == fields:
            real_start = int(vals[start_time_col])
            duration = int(int(vals[duration_col]) / 1000)
            if not init_time:
                init_time = real_start
            start = real_start - init_time
            end = start + duration
            during = "none"
            for (cross_start, cross_end, cross_name) in cross_traffic_pattern:
                if start >= cross_start and end <= cross_end:
                    during = cross_name
                    break
            vals = vals + (str(start),str(end), during)#(during, )
            print(" ".join(vals))
        else:
            sys.stderr.write("non-standard schema")
            sys.exit(1)
