import sys
import os
import glob
from tqdm import tqdm
import re
from graph import write_rmd

class DoubleWriter(object):
    def __init__(self, fs):
        self.fs = fs

    def write(self, data):
        for f in self.fs:
            f.write(data)

def parse_ccp_log(f, out, header, prepend, fields, sample_rate):
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

def post_process_dir(d, global_out_fname, sample_rate):
    fields = [9,17,19,27,29,35,13]
    exp_header = "bw,delay,qlen,alpha,beta,bg,cross,seed"
    log_header = "elapsed,rtt,zt,rout,rin,curr_rate,qlen"
    header = exp_header + "," + log_header
    pattern = re.compile('fifo_(?P<bw>[\d]+)_(?P<delay>[\d]+)/nimbus.bundler_qlen=(?P<qlen>[\d]+).bundler_qlen_alpha=(?P<alpha>[\d]+).bundler_qlen_beta=(?P<beta>[\d]+)/b=(?P<bg>[^_]*)_c=(?P<cross>[^/]*)/(?P<seed>[\d]+)/ccp.log')

    g = glob.glob(d + "/**/ccp.log", recursive=True)
    global_out = open(global_out_fname, "w")
    global_out.write(header + "\n")
    for exp in tqdm(g):
        exp_root = "/".join(exp.split("/")[:-1])
        with open(exp) as f, open(os.path.join(exp_root, "ccp.parsed"), 'w') as out:
            out.write(header + "\n")
            matches = pattern.search(exp)
            prepend = ','.join(matches.groups())
            w = DoubleWriter([global_out, out])
            parse_ccp_log(f, w, header, prepend, fields, sample_rate)
    global_out.close()


def parse_outputs(root_path, sample_rate=1):
    experiment_root = os.path.expanduser(root_path)
    global_out_fname = os.path.join(experiment_root, 'ccp.parsed')
    post_process_dir(experiment_root, global_out_fname, sample_rate)
    write_rmd(experiment_root, global_out_fname)

if __name__ == "__main__":
    parse_outputs(sys.argv[1], int(sys.argv[2]))
