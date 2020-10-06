import os, sys
from collections import defaultdict
import numpy as np
import gzip
from dateutil import parser

MEAN_DIFF_THRESHOLD = 5.0

# expected format
# Sep 04 20:55:50.139 INFO Ping response, time: [rtt], local: 0.0.0.0:[srcport], from: ...
def parse_udping(fname):
    if not os.path.isfile(fname):
        print(f"error: missing {fname}")
        return
    port_pings = defaultdict(list)
    min_time = None
    with gzip.open(fname) as f:
        for l in f:
            l = l.decode('utf-8')
            try:
                if 'Ping' in l:
                    sp = l.strip().split(" ")
                    time = parser.parse(' '.join(sp[:3])).timestamp()
                    if min_time is None or time < min_time:
                        min_time = time
                    rtt = float(sp[7].replace(",",""))
                    _, srcport = sp[9].replace(",","").split(":")
                    port_pings[srcport].append((time, rtt))
            except Exception as e:
                continue
    for port in port_pings:
        port_pings[port] = [(t - min_time, r) for t, r in port_pings[port]]
    return(port_pings)

# expected format:
# [iface] [rxrate_bytes]
def parse_bmon(fname):
    if not os.path.isfile(fname):
        print(f"error: missing {fname}")
        return
    rates = []
    with gzip.open(fname) as f:
        try:
            for l in f:
                _, rxrate = l.strip().split()
                rxrate = float(rxrate) * 8
                rates.append(rxrate)
        except Exception as e:
            print(f"error: failed to parse bmon for {fname}: {e}")
    return rates

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python parse.py [path/to/results_dir]")
        raise Exception()

    results_dir = sys.argv[1]
    ping = open('udping_results.out', 'w')
    ping.write("src dst time port Latency rtt\n")

    bmon = open('bmon_results.out', 'w')
    bmon.write("src dst Throughput bw\n")

    base_rtts = open('minrtts.out', 'w')
    base_rtts.write("src dst port Latency\n")

    paths = os.listdir(results_dir)
    for path in paths:
        sp = path.split('-')
        if not os.path.isdir(path) or len(sp) != 2 or 'ssh' in path:
            continue
        src, dst = sp
        control_pings = parse_udping(os.path.join(results_dir, path, 'control', 'udping.log.gz'))
        iperf_pings = parse_udping(os.path.join(results_dir, path, 'iperf', 'udping.log.gz'))
        bundler_pings = parse_udping(os.path.join(results_dir, path, 'bundler', 'udping.log.gz'))

        iperf_rates = parse_bmon(os.path.join(results_dir, path, 'iperf', 'bmon.log.gz'))
        bundler_rates = parse_bmon(os.path.join(results_dir, path, 'bundler', 'bmon.log.gz'))

        if control_pings is None:
            continue

        for srcport in control_pings.keys():
            try:
                control = control_pings[srcport]
                for time, r in control:
                    ping.write(f"{src} {dst} {time} {srcport} control {r}\n")
            except:
                continue

            if np.mean(control_pings[srcport]) > 50:
                base_rtts.write(f"{src} {dst} {srcport} {np.mean(control_pings[srcport])}\n")

            try:
                iperf = iperf_pings[srcport]
                for time, r in iperf:
                    ping.write(f"{src} {dst} {time} {srcport} iperf {r}\n")
            except:
                continue

            try:
                bundler = bundler_pings[srcport]
                for time, r in bundler:
                    ping.write(f"{src} {dst} {time} {srcport} bundler {r}\n")
            except:
                continue

        try:
            for r in iperf_rates:
                bmon.write(f"{src} {dst} iperf {r}\n")
        except Exception as e:
            print("iperf rates print failed", e)
            pass

        try:
            for r in bundler_rates:
                bmon.write(f"{src} {dst} bundler {r}\n")
        except:
            pass

    ping.close()
    bmon.close()
