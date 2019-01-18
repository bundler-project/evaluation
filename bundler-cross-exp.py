#!/usr/bin/python3

import argparse
import subprocess as sh
import time
import sys

parser = argparse.ArgumentParser()
parser.add_argument('--outdir', type=str, dest='outdir')

parser.add_argument('--no_bundler', action='store_false', dest='usebundler')
parser.add_argument('--qdisc', type=str, dest='qdisc')
parser.add_argument('--alg', type=str, dest='alg')

parser.add_argument('--cross_traffic', type=str, dest='crosstraffic', default=None)
parser.add_argument('--cross_load', type=str, dest='crossload', default=None)
parser.add_argument('--conns', type=int, dest='conns')
parser.add_argument('--load', type=str, dest='load')
parser.add_argument('--seed', type=int, dest='seed')
parser.add_argument('--reqs', type=int, dest='reqs')

nimbus = 'sudo ~/nimbus/target/debug/nimbus --ipc=unix --use_switching=true --flow_mode=XTCP --loss_mode=Bundle --bw_est_mode=false --pulse_size=0.5 2> {}/nimbus.out'
bbr = 'sudo ~/bbr/target/release/bbr --ipc=unix 2> {}/bbr.out'
copa = 'sudo ~/ccp_copa/target/debug/copa --ipc=unix --default_delta=0.125 2> {}/copa.out'
nimcopa = 'sudo ~/nimbus/target/debug/nimbus --ipc=unix --use_switching=true --flow_mode=XTCP --delay_mode=Copa --loss_mode=Bundle --bw_est_mode=false --pulse_size=0.5 2> {}/copa.out'
algs = {
    'nimbus': nimbus,
    'bbr': bbr,
    'copa': copa,
    'nimcopa': nimcopa,
}

def kill_everything():
    sh.run('ssh 10.1.1.2 sudo pkill -9 inbox', shell=True)
    sh.run('ssh 10.1.1.2 sudo pkill -9 nimbus', shell=True)
    sh.run('ssh 10.1.1.2 sudo pkill -9 bbr', shell=True)
    sh.run('ssh 10.1.1.2 sudo pkill -9 iperf', shell=True)
    sh.run('ssh 10.1.1.2 sudo pkill -9 -f ./bin/server', shell=True)
    sh.run('ssh 192.168.1.5 sudo pkill -9 -f ./bin/server', shell=True)
    sh.run('ssh 192.168.1.5 sudo pkill -9 iperf', shell=True)
    sh.run('ssh 192.168.1.1 sudo pkill -9 -f ./bin/server', shell=True)
    sh.run('ssh 192.168.1.1 sudo pkill -9 iperf', shell=True)
    sh.run('sudo pkill -9 outbox', shell=True)
    sh.run('sudo pkill -9 iperf', shell=True)
    sh.run('sudo pkill -9 -f ./bin/client', shell=True)

def write_etg_config(name, start, servers, load, reqs, backlogged, cross):
    with open(name, 'w') as f:
        for p in range(start, start + servers):
            if not cross:
                f.write("server 192.168.1.5 {}\n".format(p))
            else:
                f.write("server 192.168.1.1 {}\n".format(p))
        f.write("req_size_dist ./CAIDA_CDF\n")
        f.write("fanout 1 100\n")
        if backlogged:
            f.write("persistent_servers 1\n")
        f.write("load {}\n".format(load))
        f.write("num_reqs {}\n".format(reqs))

def remote_script(args):
    inbox = 'sudo ~/bundler/box/target/release/inbox --iface=10gp1 --handle_major={} --handle_minor=0x0 --port=28316 --use_dynamic_sample_rate=true --sample_rate=128 2> {}/inbox.out'.format(args.qdisc, args.outdir)
    exc = 'cd ~/bundler/scripts && ./run-multiple-server.sh 5000 {}'.format(args.conns)

    print(inbox)
    print(exc)

    with open('remote.sh', 'w') as f:
        f.write('#!/bin/bash\n\n')
        f.write('rm -rf ~/{}\n'.format(args.outdir))
        f.write('mkdir -p ~/{}\n'.format(args.outdir))
        if args.use_bundler:
            f.write('echo "starting inbox: $(date)"\n')
            f.write(inbox + ' &\n')
            f.write('sleep 1\n')
            f.write('echo "starting alg: $(date)"\n')
            f.write(args.alg.format(args.outdir) + ' &\n')

    sh.run('chmod +x remote.sh', shell=True)
    sh.run('scp ./remote.sh 10.1.1.2:', shell=True)

    with open('remote.sh', 'w') as f:
        f.write('#!/bin/bash\n\n')
        f.write('rm -rf ~/{}\n'.format(args.outdir))
        f.write('mkdir -p ~/{}\n'.format(args.outdir))
        f.write(exc + '\n')
    sh.run('chmod +x remote.sh', shell=True)
    sh.run('scp ./remote.sh 192.168.1.5:', shell=True)

    if args.crosstraffic == 'inelastic':
        with open('remote.sh', 'w') as f:
            f.write('#!/bin/bash\n\n')
            exc = 'cd ~/bundler/scripts && ./run-multiple-server.sh 7000 200'
            f.write(exc + "\n")
        sh.run('chmod +x remote.sh', shell=True)
        sh.run('scp ./remote.sh 192.168.1.1:', shell=True)
    elif args.crosstraffic == 'elastic':
        with open('remote.sh', 'w') as f:
            f.write('#!/bin/bash\n\n')
            f.write('rm -rf ~/{}\n'.format(args.outdir))
            f.write('mkdir -p ~/{}\n'.format(args.outdir))
            exc = '~/iperf/src/iperf -s -p 7000 --reverse -i 1 -t {} -P {} > {}/cross-iperf-server.out'.format(90, args.crossload, args.outdir)
            f.write(exc + "\n")
        sh.run('chmod +x remote.sh', shell=True)
        sh.run('scp ./remote.sh 192.168.1.1:', shell=True)

    sh.Popen('ssh 10.1.1.2 ~/remote.sh' , shell=True)
    sh.Popen('ssh 192.168.1.5 ~/remote.sh' , shell=True)
    sh.Popen('ssh 192.168.1.1 ~/remote.sh' , shell=True)

def local_script(args):
    outbox = 'sudo ~/bundler/box/target/release/outbox --filter "src portrange 5000-6000" --iface ingress --inbox 10.1.1.2:28316 {} --sample_rate 128 2> {}/outbox.out'.format(
        "--no_ethernet",
        args.outdir,
    )
    exc = '~/bundler/scripts/empiricial-traffic-gen/bin/client -c ~/bundler/scripts/bundlerConfig -l {}/ -s {}'.format(
        args.outdir,
        args.seed,
    )

    print(outbox)
    print(exc)

    with open('local.sh', 'w') as f:
        f.write('#!/bin/bash\n\n')
        if args.use_bundler:
            f.write('sleep 1\n')
            f.write(outbox + ' &\n')
        f.write('sleep 1\n')
        if args.crosstraffic == 'inelastic':
            f.write("~/bundler/scripts/empiricial-traffic-gen/bin/client -c ~/bundler/scripts/crossTrafficConfig -l {} -s 42 &\n".format(
                args.outdir + "/cross/"
            ))
        elif args.crosstraffic == 'elastic':
            exc1 = '~/iperf/src/iperf -c {} -p 7000 --reverse -i 1 -P {} > {}/cross-iperf-client.out &'.format(
                '192.168.1.1',
                args.crossload,
                args.outdir,
            )
            f.write('echo "starting elastic crosstraffic: {}: $(date)"\n'.format(exc))
            f.write(exc1 + "\n")
        f.write('echo "starting client: $(date)"\n')
        f.write(exc + ' \n')


    sh.run('chmod +x local.sh', shell=True)
    sh.run('rm -rf ./{}\n'.format(args.outdir), shell=True)
    sh.run('mkdir -p ./{}\n'.format(args.outdir), shell=True)
    if args.crosstraffic is not None:
        sh.run("mkdir -p {}/{}\n".format(args.outdir, "cross"), shell=True)
    mahimahi = 'mm-delay 25 mm-link --cbr 96M 96M --downlink-queue="droptail" --downlink-queue-args="packets=1200" --uplink-queue="droptail" --uplink-queue-args="packets=1200" --downlink-log={}/mahimahi.log ./local.sh'.format(args.outdir)
    print(mahimahi)
    sh.run(mahimahi, shell=True)


def run_single_experiment(args):
    args.use_bundler = args.usebundler
    args.alg = algs[args.alg]

    kill_everything()
    a = vars(args)
    commit = sh.check_output('git rev-parse HEAD', shell=True)
    commit = commit.decode('utf-8')[:-1]
    print('commit {}'.format(str(commit)))
    for k in sorted(a):
        print(k, a[k])

    write_etg_config('bundlerConfig', 5000, args.conns, args.load, args.reqs, True, False)
    if args.crosstraffic == 'inelastic':
        write_etg_config('crossTrafficConfig', 7000, 200, args.crossload, args.reqs, False, True)
    remote_script(args)
    local_script(args)

    sh.run('ssh 10.1.1.2 "grep "sch_bundle_inbox" /var/log/syslog > ~/{}/qdisc.log"'.format(args.outdir), shell=True)
    sh.run('scp 10.1.1.2:~/{0}/* ./{0}'.format(args.outdir), shell=True)
    sh.run('scp 192.168.1.5:~/{0}/* ./{0}'.format(args.outdir), shell=True)
    sh.run("mv ./bundlerConfig ./{}".format(args.outdir), shell=True)
    if args.crosstraffic == 'inelastic':
        sh.run("mv ./crossTrafficConfig ./{}".format(args.outdir + "/cross/"), shell=True)

    kill_everything()

    sh.run('mm-graph {}/mahimahi.log 50'.format(args.outdir), shell=True)

if __name__ == '__main__':
    args = parser.parse_args()
    run_single_experiment(args)
