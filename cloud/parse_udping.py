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
        try:
            for l in f.readlines():
                if 'Ping' in l:
                    sp = l.strip().split(" ")
                    rtt = float(sp[7].replace(",",""))
                    _, srcport = sp[9].replace(",","").split(":")
                    port_pings[srcport].append(rtt)
            return(port_pings)
        except Exception as e:
            print(f"error: failed to parse udping for {fname}: {e}")

# expected format:
# [iface] [rxrate_bytes]
def parse_bmon(fname):
    if not os.path.isfile(fname):
        #print(f"error: missing {fname}")
        return
    rates = []
    with open(fname) as f:
        try:
            for l in f.readlines():
                _, rxrate = l.strip().split(" ")
                rxrate = float(rxrate) * 8
                rates.append(rxrate)
        except Exception as e:
            print(f"error: failed to parse udping for {fname}: {e}")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: python parse.py [path/to/results_dir] [mean_diff_threshold]")

    results_dir = sys.argv[1]
    out = open('udping_results.out', 'w')
    out.write("src dst port ratio\n")

    mean_diff_threshold = int(sys.argv[2])

    paths = os.listdir(results_dir)
    for path in paths:
        sp = path.split('-')
        if not os.path.isdir(path) or len(sp) != 2:
            continue
        src, dst = sp
        control_pings = parse_udping(os.path.join(results_dir, path, 'control', 'udping.log'))
        iperf_pings = parse_udping(os.path.join(results_dir, path, 'iperf', 'udping.log'))
        #iperf_rates = parse_bmon(os.path.join(results_dir, path, 'iperf', 'bmon.log'))

        if control_pings:
            for srcport in control_pings.keys():
                try:
                    control = control_pings[srcport]
                    iperf = iperf_pings[srcport]

                    control_mean = np.mean(control)
                    iperf_mean = np.mean(iperf)

                    diff = (iperf_mean / control_mean)

                    if ((diff - 1.0) * 100) >= mean_diff_threshold:
                        print(f"src={src} dst={dst} port={srcport} control={control_mean:.1f} iperf={iperf_mean:.1f}")

                    out.write(f"{src} {dst} {srcport} {diff}\n")
                except:
                    continue


        # Output for ggplot
        #if control_pings:
        #    for (srcport, samples) in control_pings.items():
        #        for sample in samples:
        #            out.write(f"{src} {dst} control {srcport} {sample}\n")
        #if iperf_pings:
        #    for (srcport, samples) in iperf_pings.items():
        #        for sample in samples:
        #            out.write(f"{src} {dst} iperf {srcport} {sample}\n")

    out.close()
