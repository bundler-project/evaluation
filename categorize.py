#!/usr/bin/python3

import sys

threshs = list(zip(range(0, len(sys.argv) - 1), sorted((float(i) for i in sys.argv[1:]))))

first = True
for line in sys.stdin:
    if first:
        sp = line.strip().split()
        sp.append("Category")
        print(" ".join(sp))
        first = False
    else:
        sp = line.strip().split()
        v = float(sp[0])
        found = False
        for i, t in threshs:
            if v < t:
                sp.append("<{}".format(int(t)))
                print(" ".join(str(i) for i in sp))
                found = True
                break
            last = t
        if not found:
            last_thresh = threshs[len(threshs)-1][1]
            sp.append(">{}".format(int(last_thresh)))
            print(" ".join(str(i) for i in sp))
