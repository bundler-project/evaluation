import sys
import os

sys.path.append("..")
from parse_outputs import parse_nimbus_log

import glob

fs = glob.iglob("./**/nimbus.log", recursive=True)
for f in fs:
    ccp_log = open(f, 'r')
    out_dir =  os.path.dirname(f)
    ccp_parsed_fn = os.path.join(out_dir, "nimbus.data")
    ccp_parsed = open(ccp_parsed_fn, 'w')
    ccp_switches = open(os.path.join(out_dir, "nimbus_switches.data"), 'w')

    fields = [9,17,19,27,29,35,13]
    ccp_parsed.write("a,elapsed,rtt,zt,rout,rin,curr_rate,curr_q,elasticity2\n")
    parse_nimbus_log(ccp_log, ccp_parsed, ccp_switches, "", "a", fields, 1)

    import subprocess as sh

    ccp_parsed_plot = os.path.join(out_dir, "nimbus.pdf")
    sh.call(f"Rscript plot_ccp_log.r {ccp_parsed_fn} {ccp_parsed_plot}", shell=True)
