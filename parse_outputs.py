import sys
import os
import glob
from tqdm import tqdm
import re

class DoubleWriter(object):
    def __init__(self, fs):
        self.fs = fs

    def write(self, data):
        for f in self.fs:
            f.write(data)

sample_rate = int(sys.argv[2])
# grep "rin" nimbus.out| awk '{print $9,$13,$15,$17,$21,$23}' | tr -d ','
def parse_ccp_log(f, out, header, prepend, fields):
    i=0
    for l in f:
        if 'rin' in l:
            if i % sample_rate == 0:
                sp = l.strip().replace(",", "").split(" ")
                out.write(
                    prepend + "," + 
                    ','.join([str(round(float(sp[field-1]),3)) for field in fields]) + 
                    "\n"
                )
            i+=1


#f = open(sys.argv[1])
#out = open('nimbus.out', 'w')
#parse_ccp_log(f,out,header,

#fields = [9,13,15,17,21,23,35]
fields = [9,17,19,27,29,35,13]
exp_header = "bw,delay,qlen,alpha,beta,bg,cross,seed"
#log_header = "elapsed,qlen,uest,rtt,max_ewma_rout,ewma_rout,curr_rate"
log_header = "elapsed,rtt,zt,rout,rin,curr_rate,qlen"
header = exp_header + "," + log_header

pattern = re.compile('fifo_(?P<bw>[\d]+)_(?P<delay>[\d]+)/nimbus.bundler_qlen=(?P<qlen>[\d]+).bundler_qlen_alpha=(?P<alpha>[\d]+).bundler_qlen_beta=(?P<beta>[\d]+)/b=(?P<bg>[^_]*)_c=(?P<cross>[^/]*)/(?P<seed>[\d]+)/ccp.log')
def post_process_dir(d):
    g = glob.glob(d + "/**/ccp.log", recursive=True)
    global_out = open("all_ccp.parsed", "w")
    global_out.write(header + "\n")
    for exp in tqdm(g):
        exp_root = "/".join(exp.split("/")[:-1])
        with open(exp) as f, open(os.path.join(exp_root, "ccp.parsed"), 'w') as out:
            out.write(header + "\n")
            matches = pattern.search(exp)
            prepend = ','.join(matches.groups())
            w = DoubleWriter([global_out, out])
            parse_ccp_log(f, w, header, prepend, fields)
    global_out.close()


experiment_root = os.path.abspath(sys.argv[1])
post_process_dir(experiment_root)
