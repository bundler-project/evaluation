import sys
import os
import glob
from tqdm import tqdm
import re
from graph import write_rmd
import subprocess

class DoubleWriter(object):
    def __init__(self, fs):
        self.fs = fs

    def write(self, data):
        for f in self.fs:
            f.write(data)

def parse_ccp_log(f, out, out_switch, header, prepend, fields, sample_rate):
    i=0
    e2 = None
    xtcp_regions = []
    to_mode = None
    last_switch = 0
    for l in f:
        if 'elasticity_inf' in l:
            if i % sample_rate == 0:
                try:
                    sp = l.strip().split(" ")
                    e2 = round(float(sp[13].replace(",", "")),3)
                except:
                    pass
        if 'rin' in l:
            if i % sample_rate == 0:
                sp = l.strip().replace(",", "").split(" ")
                out.write(
                    prepend + "," +
                    ','.join([str(round(float(sp[field-1]),3)) for field in fields]) +
                    ',' + (str(e2) if e2 else '') +
                    "\n"
                )
            e2=None
            i+=1
        if 'switched mode' in l:
            sp = l.strip().split(" ")

            if sp[7] == 'XTCP,':
                elapsed = float(sp[11].replace(",", ""))
                from_mode = 'delay'
                to_mode = 'xtcp'
                delay_threshold = ''
            else:
                elapsed = float(sp[13].replace(",", ""))
                from_mode = 'xtcp'
                to_mode = 'delay'
                delay_threshold = float(sp[7].replace(",", ""))

            if from_mode == 'xtcp':
                xtcp_regions.append((last_switch, elapsed))
            last_switch = elapsed
            #out_switch.write("{elapsed},{from_mode},{to_mode},{thresh}\n".format(
            #    elapsed=elapsed,
            #    from_mode=from_mode,
            #    to_mode=to_mode,
            #    thresh=delay_threshold,
            #))
    if to_mode == 'xtcp':
        xtcp_regions.append((last_switch, 'Inf'))

    out_switch.write("xmin,xmax,ymin,ymax\n")
    for (xmin,xmax) in xtcp_regions:
        out_switch.write("{},{},-Inf,Inf\n".format(xmin,xmax))

def parse_ccp_logs(dirname, sample_rate):
    global_out_fname = os.path.join(dirname, 'ccp.parsed')
    fields = [9,17,19,27,29,35,13]
    exp_header = "bw,delay,qlen,alpha,beta,bundle,cross,seed"
    log_header = "elapsed,rtt,zt,rout,rin,curr_rate,curr_q,elasticity2"
    header = exp_header + "," + log_header
    pattern = re.compile('fifo_(?P<bw>[\d]+)_(?P<delay>[\d]+)/nimbus.bundler_qlen=(?P<qlen>[\d]+).bundler_qlen_alpha=(?P<alpha>[\d]+).bundler_qlen_beta=(?P<beta>[\d]+)/b=(?P<bg>[^_]*)_c=(?P<cross>[^/]*)/(?P<seed>[\d]+)/ccp.log')

    g = glob.glob(dirname + "/**/ccp.log", recursive=True)
    global_out = open(global_out_fname, "w")
    global_out.write(header + "\n")
    for exp in tqdm(g):
        print(exp)
        exp_root = "/".join(exp.split("/")[:-1])
        with open(exp) as f, open(os.path.join(exp_root, "ccp.parsed"), 'w') as out, open(os.path.join(exp_root, "ccp_switch.parsed"), 'w') as out_switch:
            out.write(header + "\n")
            matches = pattern.search(exp)
            if matches is not None:
                prepend = ','.join(matches.groups())
                w = DoubleWriter([global_out, out])
                parse_ccp_log(f, w, out_switch, header, prepend, fields, sample_rate)
    global_out.close()

def parse_mahimahi_logs(dirname, sample_rate):
    g = glob.glob(dirname + "/**/downlink.log", recursive=True)
    for exp in tqdm(g):
        print(exp)
        exp_root = "/".join(exp.split("/")[:-1])
        exp_root = os.path.dirname(exp)
        subprocess.check_output("mm-graph {} 50 --fake --plot-direction ingress --agg \"5000:6000=bundle,8001:8004=cross\"".format(exp), shell=True, executable="/bin/bash")
        subprocess.check_output("mv /tmp/mm-graph.tmp {}".format(exp_root), shell=True)

def parse_etg_logs(dirname):
    outf = os.path.join(dirname, "fcts.data")
    g = glob.glob(dirname + "/**/*reqs.out", recursive=True)
    for exp in tqdm(g):
        print(exp)
        exp_root = "/".join(exp.split("/")[:-1])
        exp_root = os.path.dirname(exp)
        exp_root = exp_root.split(dirname)[-1]
        _, setup, alg, traffic, seed = exp_root.split("/")
        sch, bw, rtt = setup.split("_")
        subprocess.check_output(f"awk '{{print \"sch:{sch}, bw:{bw}, rtt:{rtt}, alg:{alg}, traffic:{traffic}, seed:{seed} \"$0}}' {exp} | python3 columnize.py >> {outf}", shell=True)

def parse_outputs(root_path, graph_kwargs={}):
    experiment_root = os.path.abspath(os.path.expanduser(root_path))

    if 'downsample' in graph_kwargs:
        sample_rate = graph_kwargs['downsample']
    else:
        sample_rate = 1

    parse_ccp_logs(experiment_root, sample_rate)
    parse_mahimahi_logs(experiment_root, sample_rate)
    parse_etg_logs(experiment_root)

    #write_rmd(experiment_root, global_out_fname, **graph_kwargs)

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Parse bundler experiment logs and graph results")
    parser.add_argument("root", help="Root directory containing all experiments to be plotted")
    parser.add_argument("--downsample", type=int, help="Downsamples to 1/N of all log lines for faster plotting")
    parser.add_argument("--fields", help="Which fields to plot")
    parser.add_argument("--rows", help="(Column name) by which to split into a grid vertically")
    parser.add_argument("--cols", help="(Column name) by which to split into a grid horizontally")
    args = parser.parse_args()
    graph_kwargs = dict((k,v) for k,v in vars(args).items() if (v and not k=='root'))

    parse_outputs(args.root, graph_kwargs=graph_kwargs)
