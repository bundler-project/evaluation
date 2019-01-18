#!/usr/bin/python3

import argparse
import subprocess as sh
import time
import sys

parser = argparse.ArgumentParser()
parser.add_argument('--outdir', type=str, dest='outdir')

parser.add_argument('--qdisc', type=str, dest='qdisc')
parser.add_argument('--alg', type=str, dest='alg')
parser.add_argument('--kernel_alg', type=str, dest='alg')

parser.add_argument('--time', type=int, dest='time')
parser.add_argument('--conns', type=int, dest='conns')

nimbus = 'sudo ~/nimbus/target/release/nimbus --ipc=unix --use_switching=false --flow_mode=Delay --bw_est_mode=false --pulse_size=0.01 2> {}/nimbus.out'
bbr = 'sudo ~/bbr/target/release/bbr --ipc=unix 2> {}/bbr.out'
copa = 'sudo ~/ccp_copa/target/debug/copa --ipc=unix --delta_mode=NoTCP --default_delta=0.125 2> {}/copa.out'
algs = {
    'nimbus': nimbus,
    'bbr': bbr,
    'copa': copa,
}

def kill_everything():
    sh.run('ssh 10.1.1.2 sudo pkill -9 inbox', shell=True)
    sh.run('ssh 10.1.1.2 sudo pkill -9 nimbus', shell=True)
    sh.run('ssh 10.1.1.2 sudo pkill -9 bbr', shell=True)
    sh.run('ssh 10.1.1.2 sudo pkill -9 copa', shell=True)
    sh.run('ssh 10.1.1.2 sudo pkill -9 iperf', shell=True)
    sh.run('ssh 192.168.1.5 sudo pkill -9 iperf', shell=True)
    sh.run('sudo pkill -9 outbox', shell=True)
    sh.run('sudo pkill -9 iperf', shell=True)

def remote_script(args):
    inbox = 'sudo ~/bundler/box/target/release/inbox --iface=10gp1 --handle_major={} --handle_minor=0x0 --port=28316 --use_dynamic_sample_rate={} --sample_rate={} 2> {}/inbox.out'.format(args.qdisc, args.dynamic_samplerate, args.samplerate, args.outdir)

    exc = '~/iperf/src/iperf -s -p 5000 --reverse -i 1 -t {} -P {}'.format(args.time, args.conns) + \
        '-Z {} '.format(args.kernel_alg[1]) + \
        '> {}/iperf-server.out'.format(args.outdir)

    print(inbox)
    print(exc)

    with open('remote.sh', 'w') as f:
        f.write('#!/bin/bash\n\n')
        f.write('rm -rf ~/{}\n'.format(args.outdir))
        f.write('mkdir -p ~/{}\n'.format(args.outdir))
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

    sh.Popen('ssh 10.1.1.2 ~/remote.sh' , shell=True)
    sh.Popen('ssh 192.168.1.5 ~/remote.sh' , shell=True)

def local_script(args):
    outbox = 'sudo ~/bundler/box/target/release/outbox --filter "src portrange 5000-6000" --iface ingress --inbox 10.1.1.2:28316 {} --sample_rate {} 2> {}/outbox.out'.format(
        "--no_ethernet",
        args.samplerate,
        args.outdir,
    )
    exc = '~/iperf/src/iperf -c {} -p 5000 --reverse -i 1 -P {} > {}/iperf-client.out'.format(
        '192.168.1.5',
        args.conns,
        args.outdir,
    )

    print(outbox)
    print(exc)

    with open('local.sh', 'w') as f:
        f.write('#!/bin/bash\n\n')
        f.write('sleep 1\n')
        f.write(outbox + ' &\n')
        f.write('sleep 1\n')
        f.write('echo "starting iperf client: $(date)"\n')
        f.write(exc + '\n')

    sh.run('chmod +x local.sh', shell=True)
    sh.run('rm -rf ./{}\n'.format(args.outdir), shell=True)
    sh.run('mkdir -p ./{}\n'.format(args.outdir), shell=True)
    mahimahi = 'mm-delay 25 mm-link --cbr 96M 96M --downlink-queue="droptail" --downlink-queue-args="packets=1200" --uplink-queue="droptail" --uplink-queue-args="packets=1200" --downlink-log={}/mahimahi.log ./local.sh'.format(args.outdir)
    sh.run(mahimahi, shell=True)


def run_single_experiment(args):
    if args.time is None:
        print('please give a time')
        sys.exit(1)
    if args.conns > 32:
        print("are you sure? running 32 parallel iperf connections")
        sys.exit(1)
    args.samplerate = 128
    args.dynamic_samplerate = 'true'
    args.alg = algs[args.alg]

    kill_everything()
    a = vars(args)
    commit = sh.check_output('git rev-parse HEAD', shell=True)
    commit = commit.decode('utf-8')[:-1]
    print('commit {}'.format(str(commit)))
    for k in sorted(a):
        print(k, a[k])

    remote_script(args)
    local_script(args)

    sh.run('ssh 10.1.1.2 "grep "sch_bundle_inbox" /var/log/syslog > ~/{}/qdisc.log"'.format(args.outdir), shell=True)
    sh.run('scp 10.1.1.2:~/{0}/* ./{0}'.format(args.outdir), shell=True)
    sh.run('scp 192.168.1.5:~/{0}/* ./{0}'.format(args.outdir), shell=True)

    kill_everything()

    sh.run('mm-graph {}/mahimahi.log 50'.format(args.outdir), shell=True)

if __name__ == '__main__':
    args = parser.parse_args()
    run_single_experiment(args)
