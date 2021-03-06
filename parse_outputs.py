from graph import write_rmd
import agenda
import glob
import os
import re
import subprocess
import sys

def parse_nimbus_log(f, out, out_switch, header, prepend, fields, sample_rate):
    i=0
    e2 = None
    xtcp_regions = []
    to_mode = None
    last_switch = 0
    xmax = 0
    starting_mode = None
    for l in f:
        if '[nimbus] starting' in l:
            mode_expr = re.compile("flow_mode: ([^,]+)")
            res = mode_expr.search(l)
            starting_mode = res.groups()[0]
        if 'elasticity_inf' in l:
            if i % sample_rate == 0:
                try:
                    sp = l.strip().split(" ")
                    e2 = round(float(sp[13].replace(",", "")),3)
                except:
                    pass
        if 'rin' in l:
            try:
                if i % sample_rate == 0:
                    sp = l.strip().replace(",", "").split(" ")
                    xmax = float(sp[8])
                    out.write(
                        prepend + "," +
                        ','.join([str(round(float(sp[field-1]),3)) for field in fields]) +
                        ',' + (str(e2) if e2 else '') +
                        "\n"
                    )
                e2=None
                i+=1
            except:
                continue
        if 'switched mode' in l:
            sp = l.strip().split(" ")

            if sp[7] == 'XTCP,':
                elapsed = float(sp[11].replace(",", ""))
                from_mode = 'delay'
                to_mode = 'xtcp'
                #delay_threshold = ''
            else:
                elapsed = float(sp[13].replace(",", ""))
                from_mode = 'xtcp'
                to_mode = 'delay'
                #delay_threshold = float(sp[7].replace(",", ""))

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
    if not xtcp_regions and starting_mode == "XTCP":
        out_switch.write("{},{},-Inf,Inf\n".format(0, xmax))

def parse_ccp_logs(dirname, sample_rate, replot):
    agenda.subtask("ccp logs")
    fields = [9,17,19,27,29,35,13]
    log_header = "elapsed,rtt,zt,rout,rin,curr_rate,curr_q,elasticity2"
    pattern = re.compile(r'(?P<sch>[a-z]+)_(?P<bw>[\d]+)_(?P<delay>[\d]+)/(?P<alg>[a-z_]+).(?P<args>[a-z_]+=[a-zA-Z_0-9].+)?/b=(?P<bg>[^_]*)_c=(?P<cross>[^/]*)/(?P<seed>[\d]+)/ccp.log')

    g = glob.glob(dirname + "/**/ccp.log", recursive=True)

    global_out_fname = os.path.join(dirname, 'ccp.parsed')
    if not replot and os.path.isfile(global_out_fname):
        return global_out_fname, len(g)

    for exp in g:
        exp_root = "/".join(exp.split("/")[:-1])
        old_header = None
        matches = pattern.search(exp)
        if matches is not None and 'nimbus' in exp:
            print(exp)
            with open(exp) as f, open(os.path.join(exp_root, "ccp.parsed"), 'w') as out, open(os.path.join(exp_root, "ccp_switch.parsed"), 'w') as out_switch:
                sch, bw, delay, args, bg, cross, seed, alg = matches.group('sch', 'bw', 'delay', 'args', 'bg', 'cross', 'seed', 'alg')
                args = [a.split("=") for a in args.split(".")] if args else []
                exp_header = f"sch,alg,rate,rtt,{','.join(a[0] for a in args)},bundle,cross,seed"
                header = exp_header + "," + log_header
                if old_header and old_header != header:
                    exit("headers do not align")
                old_header = header
                out.write(header + "\n")
                bg = bg if bg != '' else 'None'
                cross = cross if cross != '' else 'None'
                prepend = f"{sch},{alg},{bw},{delay},{','.join(a[1] for a in args)},{bg},{cross},{seed}"
                parse_nimbus_log(f, out, out_switch, header, prepend, fields, sample_rate)
        else:
            print(f"skipping {exp}, no regex match")

    global_out_fname = os.path.join(dirname, 'ccp.parsed')
    subprocess.call(f"rm -f {global_out_fname}", shell=True)
    g = glob.glob(dirname + "/**/ccp.parsed", recursive=True)
    tail = 1
    for exp in g:
        if exp != global_out_fname:
            subprocess.call(f"tail -n +{tail} {exp} >> {global_out_fname}", shell=True)
            if tail == 1:
                tail = 2

    return global_out_fname, len(g)

def parse_mahimahi_logs(dirname, sample_rate, replot, bundler_root):
    agenda.subtask("mahimahi logs")
    pattern = re.compile(r'(?P<sch>[a-z]+)_(?P<bw>[\d]+)_(?P<delay>[\d]+)/(?P<alg>[a-zA-Z]+).(?P<args>[a-z_]+=[a-zA-Z_0-9].+)?/b=(?P<bg>[^_]*)_c=(?P<cross>[^/]*)/(?P<seed>[\d]+)/downlink.log')
    g = glob.glob(dirname + "/**/downlink.log", recursive=True)
    for exp in g:
        matches = pattern.search(exp)
        if matches is not None:
            delay = int(matches.group('delay'))
            rtt = int(delay*2)
            print(rtt,exp)
            exp_root = "/".join(exp.split("/")[:-1])
            exp_root = os.path.dirname(exp)
            if not replot and os.path.isfile(os.path.join(exp_root, 'mm-graph.tmp')):
                continue
            subprocess.check_output(f"{bundler_root}/mahimahi/scripts/mm-graph {exp} {rtt} --fake --plot-direction ingress --agg \"5000:6000=bundle,8000:9000=cross\"", shell=True, executable="/bin/bash")
            subprocess.check_output("mv /tmp/mm-graph.tmp {}".format(exp_root), shell=True)
        else:
            print(f"skipping {exp}, no regex match")

def parse_etg_logs(dirname, replot):
    agenda.subtask("etg logs")
    outf = os.path.join(dirname, "fcts.data")
    if not replot and os.path.isfile(outf):
        return
    if replot and os.path.isfile(outf):
        os.remove(outf)
    g = glob.glob(dirname + "/**/*reqs.out", recursive=True)
    some = None
    cross_traffic_pattern = "0:60=empty1,60:120=iperfc1,120:150=empty2,150:210=cbr32,210:250=empty3"
    print_head = True
    for exp in g:
        print(exp)
        some = True
        exp_root = "/".join(exp.split("/")[:-1])
        exp_root = os.path.dirname(exp)
        exp_root = exp_root.split(dirname)[-1].split("/")
        try:
            _, setup, alg, traffic, seed = exp_root
        except Exception as e:
            print(exp_root)
            raise e
        alg_sp = alg.split(".")
        if not alg_sp:
            alg = alg_sp[0]
        sch, bw, rtt = setup.split("_")
        subprocess.check_output(f"awk '{{print \"sch:{sch}, bw:{bw}, rtt:{rtt}, alg:{alg}, traffic:{traffic}, seed:{seed} \"$0}}' {exp} | python3 columnize.py \"{cross_traffic_pattern}\" {print_head}>> tmp", shell=True)
        print_head = False
    if some:
        subprocess.call(f"mv tmp {outf}", shell=True)

def parse_outputs(config, replot=False, interact=False, graph_kwargs={}):
    experiment_root = os.path.abspath(os.path.expanduser(config['local_experiment_dir']))
    agenda.task(f'parsing experiment_root: {experiment_root}')

    if 'downsample' in graph_kwargs:
        sample_rate = graph_kwargs['downsample']
    else:
        sample_rate = 1

    global_out_fname, num_ccp = parse_ccp_logs(experiment_root, sample_rate, replot)
    parse_mahimahi_logs(experiment_root, sample_rate, replot, config['structure']['bundler_root'])
    parse_etg_logs(experiment_root, replot)

    write_rmd(experiment_root, global_out_fname, num_ccp, **graph_kwargs)

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Parse bundler experiment logs and graph results")
    parser.add_argument("root", help="Root directory containing all experiments to be plotted")
    parser.add_argument("--bundler_root", type=str, help="Bundler root directory", default="~/bundler-scripts")
    parser.add_argument("--downsample", type=int, help="Downsamples to 1/N of all log lines for faster plotting")
    parser.add_argument("--fields", help="Which fields to plot")
    parser.add_argument("--rows", help="(Column name) by which to split into a grid vertically")
    parser.add_argument("--cols", help="(Column name) by which to split into a grid horizontally")
    parser.add_argument('--replot', help="Force replot",action="store_true")
    parser.add_argument("--interact", help="enable interactive mode for graphs",action="store_true")
    args = parser.parse_args()
    graph_kwargs = dict((k,v) for k,v in vars(args).items() if (v and not k=='root' and not k=='replot'))

    config = {}
    config['local_experiment_dir'] = args.root
    config['structure'] = {'bundler_root': args.bundler_root}
    parse_outputs(config, replot=args.replot, interact=args.interact, graph_kwargs=graph_kwargs)
