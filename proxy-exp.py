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
parser.add_argument('--static_epoch', action='store_false', dest='dynamic_epoch')
parser.add_argument('--samplerate', type=int, dest='samplerate')

parser.add_argument('--conns', type=int, dest='conns')
parser.add_argument('--load', type=str, dest='load')
parser.add_argument('--seed', type=int, dest='seed')
parser.add_argument('--reqs', type=int, dest='reqs')
parser.add_argument('--backlogged_bundle', action='store_true', dest='backlogged_bundle')

nimbus = 'sudo ~/nimbus/target/release/nimbus --ipc=unix --use_switching=false --flow_mode=Delay --bw_est_mode=false --pulse_size=0.01 2> {}/nimbus.out'
bbr = 'sudo ~/bbr/target/release/bbr --ipc=unix 2> {}/bbr.out'
osc = 'sudo python ~/portus/python/osc.py'
copa = 'sudo ~/ccp_copa/target/debug/copa --ipc=unix --delta_mode=NoTCP --default_delta=0.125 2> {}/copa.out'
algs = {
    'nimbus': nimbus,
    'bbr': bbr,
    'osc': osc,
    'copa': copa,
}

def kill_everything():
    sh.run('ssh 10.1.1.2 sudo pkill -9 inbox', shell=True)
    sh.run('ssh 10.1.1.2 sudo pkill -9 nimbus', shell=True)
    sh.run('ssh 10.1.1.2 sudo pkill -9 bbr', shell=True)
    sh.run('ssh 192.168.1.5 sudo pkill -9 -f ./bin/server', shell=True)
    sh.run('sudo pkill -9 outbox', shell=True)
    sh.run('sudo pkill -9 iperf', shell=True)

def write_etg_config(name, args):
    with open(name, 'w') as f:
        for p in range(5000, 5000 + args.conns):
            f.write("server 192.168.1.5 {}\n".format(p))
        f.write("req_size_dist ./CAIDA_CDF\n")
        f.write("fanout 1 100\n")
        if args.backlogged_bundle:
            f.write("persistent_servers 1\n")
        f.write("load {}\n".format(args.load))
        f.write("num_reqs {}\n".format(args.reqs))

def remote_script(args):
    inbox = 'sudo ~/bundler/box/target/release/inbox --iface=10gp1 --handle_major={} --handle_minor=0x0 --port=28316 --use_dynamic_sample_rate={} --sample_rate={} 2> {}/inbox.out'.format(args.qdisc, args.dynamic_samplerate, args.samplerate, args.outdir)
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
        f.write('sudo dd if=/dev/null of=/proc/net/tcpprobe bs=256 &\n')
        f.write('sudo dd if=/proc/net/tcpprobe of={}/tcpprobe.out bs=256 &\n'.format(args.outdir))
        f.write(exc + '\n')
        f.write('sudo killall dd\n')
    sh.run('chmod +x remote.sh', shell=True)
    sh.run('scp ./remote.sh 192.168.1.5:', shell=True)

    sh.Popen('ssh 10.1.1.2 ~/remote.sh' , shell=True)
    sh.Popen('ssh 192.168.1.5 ~/remote.sh' , shell=True)

def local_script(args):
    outbox = 'sudo ~/bundler/box/target/release/outbox --filter "src portrange 5000-6000" --iface ingress --inbox 10.1.1.2:28316 {} --sample_rate {} 2> {}/outbox.out'.format(
        "--no_ethernet",
        args.samplerate,
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
        f.write('echo "starting client: $(date)"\n')
        f.write(exc + '\n')

    sh.run('chmod +x local.sh', shell=True)
    sh.run('rm -rf ./{}\n'.format(args.outdir), shell=True)
    sh.run('mkdir -p ./{}\n'.format(args.outdir), shell=True)
    mahimahi = 'mm-delay 25 mm-link --cbr 96M 96M --downlink-queue="droptail" --downlink-queue-args="packets=1200" --uplink-queue="droptail" --uplink-queue-args="packets=1200" --downlink-log={}/mahimahi.log ./local.sh'.format(args.outdir)
    sh.run(mahimahi, shell=True)


def run_single_experiment(args):
    if args.samplerate is None:
        args.samplerate = 128
    args.dynamic_samplerate = 'true'
    args.use_bundler = args.usebundler
    args.alg = algs[args.alg]

    kill_everything()
    a = vars(args)
    commit = sh.check_output('git rev-parse HEAD', shell=True)
    commit = commit.decode('utf-8')[:-1]
    print('commit {}'.format(str(commit)))
    for k in sorted(a):
        print(k, a[k])

    write_etg_config('bundlerConfig', args)
    remote_script(args)
    local_script(args)

    sh.run('ssh 10.1.1.2 "grep "sch_bundle_inbox" /var/log/syslog > ~/{}/qdisc.log"'.format(args.outdir), shell=True)
    sh.run('scp 10.1.1.2:~/{0}/* ./{0}'.format(args.outdir), shell=True)
    sh.run("mv ./bundlerConfig ./{}".format(args.outdir), shell=True)

    kill_everything()

    sh.run('mm-graph {}/mahimahi.log 50'.format(args.outdir), shell=True)

if __name__ == '__main__':
    args = parser.parse_args()
    run_single_experiment(args)
