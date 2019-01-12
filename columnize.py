#!/usr/bin/python3

import sys

def flds(line):
    for f in line:
        sp = f.split(":")
        yield sp[0], sp[1].split(",")[0]

head = None
for line in sys.stdin:
    sp = line.strip().split()
    if head is None:
        fields, vals = zip(*flds(sp))
        head = fields
        print(" ".join(head))
    else:
        fields, vals = zip(*flds(sp))
        if head == fields:
            print(" ".join(vals))
        else:
            sys.stderr.write("non-standard schema")
            sys.exit(1)
