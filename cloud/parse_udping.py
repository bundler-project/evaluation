import os, sys
from collections import defaultdict
import numpy as np


MEAN_DIFF_THRESHOLD = 5.0


# expected format
# Sep 04 20:55:50.139 INFO Ping response, time: [rtt], local: 0.0.0.0:[srcport], from: ...
def parse_udping(fname):
    if not os.path.isfile(fname):
        #print(f"error: missing {fname}")
        return
    port_pings = defaultdict(list)
    with open(fname) as f:
        for l in f.readlines():
            try:
                if 'Ping' in l:
                    sp = l.strip().split(" ")
                    rtt = float(sp[7].replace(",",""))
                    _, srcport = sp[9].replace(",","").split(":")
                    port_pings[srcport].append(rtt)
            except Exception as e:
                continue
        return(port_pings)

# expected format:
# [iface] [rxrate_bytes]
def parse_bmon(fname):
    if not os.path.isfile(fname):
        print(f"error: missing {fname}")
        return
    rates = []
    with open(fname) as f:
        try:
            for l in f.readlines():
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
    ping.write("src dst port Latency rtt\n")

    bmon = open('bmon_results.out', 'w')
    bmon.write("src dst Throughput bw\n")

    paths = os.listdir(results_dir)
    for path in paths:
        sp = path.split('-')
        if not os.path.isdir(path) or len(sp) != 2:
            continue
        src, dst = sp
        control_pings = parse_udping(os.path.join(results_dir, path, 'control', 'udping.log'))
        iperf_pings = parse_udping(os.path.join(results_dir, path, 'iperf', 'udping.log'))
        bundler_pings = parse_udping(os.path.join(results_dir, path, 'bundler', 'udping.log'))

        iperf_rates = parse_bmon(os.path.join(results_dir, path, 'iperf', 'bmon.log'))
        bundler_rates = parse_bmon(os.path.join(results_dir, path, 'bundler', 'bmon.log'))

        if bundler_pings:
            for srcport in control_pings.keys():
                try:
                    control = control_pings[srcport]
                    for r in control:
                        ping.write(f"{src} {dst} {srcport} control {r}\n")
                except:
                    continue

                try:
                    iperf = iperf_pings[srcport]
                    for r in iperf:
                        ping.write(f"{src} {dst} {srcport} iperf {r}\n")
                except:
                    continue

                try:
                    bundler = bundler_pings[srcport]
                    for r in bundler:
                        ping.write(f"{src} {dst} {srcport} bundler {r}\n")
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
