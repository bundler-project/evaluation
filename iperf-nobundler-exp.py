#!/usr/bin/python3

import argparse
import subprocess as sh
import time
import sys

parser = argparse.ArgumentParser()
parser.add_argument('--outdir', type=str, dest='outdir')
parser.add_argument('--alg', type=str, dest='alg')
parser.add_argument('--time', type=int, dest='time')
parser.add_argument('--conns', type=int, dest='conns')

kernel_algs = {
    'bbr': ('echo "kernel BBR - no output to {}"', 'bbr'),
    'copa': ('sudo ~/ccp_copa/target/debug/copa --ipc=netlink --default_delta=0.125 2> {}/copa.out', 'ccp'),
    'nimbus': ('sudo ~/nimbus/target/release/nimbus --ipc=netlink --use_switching=false --flow_mode=Delay --bw_est_mode=false --pulse_size=0.01 2> {}/nimbus.out', 'ccp')
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
    exc = '~/iperf/src/iperf -s -p 5000 --reverse -i 1 -t {} -P {} '.format(args.time, args.conns) + \
        '-Z {} '.format(args.alg[1]) + \
        '> {}/iperf-server.out'.format(args.outdir)

    print(exc)

    with open('remote.sh', 'w') as f:
        f.write('#!/bin/bash\n\n')
        f.write('rm -rf ~/{}\n'.format(args.outdir))
        f.write('mkdir -p ~/{}\n'.format(args.outdir))
        f.write(args.alg[0].format(args.outdir) + ' &\n')
        f.write(exc + '\n')
    sh.run('chmod +x remote.sh', shell=True)
    sh.run('scp ./remote.sh 192.168.1.5:', shell=True)

    sh.Popen('ssh 192.168.1.5 ~/remote.sh' , shell=True)

def local_script(args):
    exc = '~/iperf/src/iperf -c {} -p 5000 --reverse -i 1 -P {} > {}/iperf-client.out'.format(
        '192.168.1.5',
        args.conns,
        args.outdir,
    )

    print(exc)

    with open('local.sh', 'w') as f:
        f.write('#!/bin/bash\n\n')
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
        print("are you sure? running > 32 parallel iperf connections")
        sys.exit(1)
    args.alg = kernel_algs[args.alg]

    kill_everything()
    a = vars(args)
    commit = sh.check_output('git rev-parse HEAD', shell=True)
    commit = commit.decode('utf-8')[:-1]
    print('commit {}'.format(str(commit)))
    for k in sorted(a):
        print(k, a[k])

    remote_script(args)
    local_script(args)

    sh.run('scp 192.168.1.5:~/{0}/* ./{0}'.format(args.outdir), shell=True)

    kill_everything()

    sh.run('mm-graph {}/mahimahi.log 50'.format(args.outdir), shell=True)

if __name__ == '__main__':
    args = parser.parse_args()
    run_single_experiment(args)
