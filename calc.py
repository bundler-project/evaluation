# This script (roughly) calculates the maximum difference in curr_rate over a given period of each trace

import sys
import os
import glob
from tqdm import tqdm
import re


# grep "rin" nimbus.out| awk '{print $9,$13,$15,$17,$21,$23}' | tr -d ','
def parse_ccp_log(f, grps):
    min_rate = None
    max_rate = None
    for l in f:
        if 'rin' in l:
            sp = l.strip().replace(",", "").split(" ")
            elapsed = float(sp[9-1])
            curr_rate = float(sp[35-1])
            if elapsed > int(sys.argv[2]) and elapsed < int(sys.argv[3]):
                if min_rate:
                    min_rate = min(min_rate, curr_rate)
                else:
                    min_rate = curr_rate
                if max_rate:
                    max_rate = max(max_rate, curr_rate)
                else:
                    max_rate = curr_rate
    min_rate = min_rate / 1000000.0
    max_rate = max_rate / 1000000.0
    print(grps[3], grps[4], min_rate, max_rate, max_rate-min_rate)


pattern = re.compile('fifo_(?P<bw>[\d]+)_(?P<delay>[\d]+)/nimbus.bundler_qlen=(?P<qlen>[\d]+).bundler_qlen_alpha=(?P<alpha>[\d]+).bundler_qlen_beta=(?P<beta>[\d]+)/b=(?P<bg>[^_]*)_c=(?P<cross>[^/]*)/(?P<seed>[\d]+)/ccp.log')
def post_process_dir(d):
    g = glob.glob(d + "/**/ccp.log", recursive=True)
    for exp in g:
        exp_root = "/".join(exp.split("/")[:-1])
        with open(exp) as f:
            matches = pattern.search(exp)
            grps = matches.groups()
            parse_ccp_log(f, grps)


experiment_root = os.path.abspath(sys.argv[1])
post_process_dir(experiment_root)
