#!/usr/bin/python3

import argparse
import subprocess as sh
import time

parser = argparse.ArgumentParser()
parser.add_argument('--time', type=int, dest='time')
parser.add_argument('--qdisc', type=str, dest='qdisc')
parser.add_argument('--outdir', type=str, dest='outdir')
parser.add_argument('--alg', type=str, dest='alg')
parser.add_argument('--samplerate', type=int, dest='samplerate')
parser.add_argument('--conns', type=int, dest='conns')
parser.add_argument('--no_bundler', action='store_false', dest='usebundler')
parser.add_argument('--static_epoch', action='store_false', dest='dynamic_epoch')
parser.add_argument('--three_machines', action='store_true', dest='three_machines')
parser.add_argument('--fct_experiment', action='store_true', dest='do_fct_experiment')
parser.add_argument('--cross_traffic', action='store_true', dest='cross_traffic')

nimbus = 'sudo ~/nimbus/target/release/nimbus --ipc=unix --use_switching=false --flow_mode=Delay --bw_est_mode=false --pulse_size=0.01 2> {}/nimbus.out'
bbr = 'sudo ~/bbr/target/release/bbr --ipc=unix 2> {}/bbr.out'
osc = 'sudo python ~/portus/python/osc.py'
algs = {
    'nimbus': nimbus,
    'bbr': bbr,
    'osc': osc,
}

def remote_script(args):
    inbox = 'sudo ~/bundler/box/target/release/inbox --iface=10gp1 --handle_major={} --handle_minor=0x0 --port=28316 --use_dynamic_sample_rate={} --sample_rate={} 2> {}/inbox.out'.format(args.qdisc, args.dynamic_samplerate, args.samplerate, args.outdir)
    if not args.do_fct_experiment:
        exc = '~/iperf/src/iperf -s -p 5000 --reverse -i 1 -t {} -P {} > {}/iperf-server.out'.format(args.time, args.conns, args.outdir)
    else:
        exc = '~/bundler/scripts/empiricial-traffic-gen/run-multiple-server.sh 50'

    print(inbox)
    print(exc)

    with open('remote.sh', 'w') as f:
        f.write('#!/bin/bash\n\n')
        f.write('rm -rf ~/{}\n'.format(args.outdir))
        f.write('mkdir -p ~/{}\n'.format(args.outdir))
        if args.use_bundler:
            f.write(inbox + ' &\n')
            f.write('sleep 1\n')
            f.write(args.alg.format(args.outdir) + ' &\n')
        if not args.three_machines:
            f.write(exc + '\n')

    sh.run('chmod +x remote.sh', shell=True)
    sh.run('scp ./remote.sh 10.1.1.2:', shell=True)

    if args.three_machines:
        with open('remote.sh', 'w') as f:
            f.write('#!/bin/bash\n\n')
            f.write('rm -rf ~/{}\n'.format(args.outdir))
            f.write('mkdir -p ~/{}\n'.format(args.outdir))
            f.write(exc + '\n')
        sh.run('chmod +x remote.sh', shell=True)
        sh.run('scp ./remote.sh 192.168.1.5:', shell=True)

    if args.cross_traffic:
        with open('remote.sh', 'w') as f:
            f.write('#!/bin/bash\n\n')
            exc = '~/bundler/scripts/empiricial-traffic-gen/run-multiple-server.sh 50'
            f.write(exc + "\n")
        sh.run('chmod +x remote.sh', shell=True)
        sh.run('scp ./remote.sh 192.168.1.1:', shell=True)

    sh.Popen('ssh 10.1.1.2 ~/remote.sh' , shell=True)
    sh.Popen('ssh 192.168.1.5 ~/remote.sh' , shell=True)
    sh.Popen('ssh 192.168.1.1 ~/remote.sh' , shell=True)

def local_script(args):
    outbox = 'sudo ~/bundler/box/target/release/outbox --filter "portrange 5000-5100" --iface ingress --inbox 10.1.1.2:28316 {} --sample_rate {} 2> {}/outbox.out'.format(
        "--no_ethernet",
        args.samplerate,
        args.outdir,
    )
    if not args.do_fct_experiment:
        exc = '~/iperf/src/iperf -c {} -p 5000 --reverse -i 1 -P {} > {}/iperf-client.out'.format(
            '192.168.1.5' if args.three_machines else '10.1.1.2',
            args.conns,
            args.outdir,
        )
    else:
        exc = '~/bundler/scripts/empiricial-traffic-gen/bin/client -c ~/bundler/scripts/empiricial-traffic-gen/bundlerConfig -l {} -s 42'.format(
            args.outdir,
        )

    print(outbox)
    print(exc)

    with open('local.sh', 'w') as f:
        f.write('#!/bin/bash\n\n')
        if args.use_bundler:
            f.write('sleep 1\n')
            f.write(outbox + ' &\n')
        f.write('sleep 1\n')
        f.write('echo \'starting iperf client\'\n')
        f.write(exc + '\n')
        if args.cross_traffic:
            f.write("~/bundler/scripts/empiricial-traffic-gen/bin/client -c ~/bundler/scripts/empiricial-traffic-gen/crossTrafficConfig -l {} -s 42".format(
                args.outdir + "/cross"
            ))

    sh.run('chmod +x local.sh', shell=True)
    sh.run('rm -rf ./{}\n'.format(args.outdir), shell=True)
    sh.run('mkdir -p ./{}\n'.format(args.outdir), shell=True)
    mahimahi = 'mm-delay 25 mm-link --cbr 96M 96M --downlink-queue="droptail" --downlink-queue-args="packets=1200" --uplink-queue="droptail" --uplink-queue-args="packets=1200" --downlink-log={}/mahimahi.log ./local.sh'.format(args.outdir)
    sh.run(mahimahi, shell=True)

args = parser.parse_args()
args.dynamic_samplerate = 'true' if args.dynamic_epoch else 'false'
args.use_bundler = args.usebundler
args.alg = algs[args.alg]

sh.run('ssh 10.1.1.2 sudo pkill -9 inbox', shell=True)
sh.run('ssh 10.1.1.2 sudo pkill -9 nimbus', shell=True)
sh.run('ssh 10.1.1.2 sudo pkill -9 bbr', shell=True)
sh.run('ssh 10.1.1.2 sudo pkill -9 iperf', shell=True)
sh.run('ssh 10.1.1.2 sudo pkill -9 -f ./bin/server', shell=True)
sh.run('ssh 192.168.1.5 sudo pkill -9 iperf', shell=True)
sh.run('sudo pkill -9 outbox', shell=True)
sh.run('sudo pkill -9 iperf', shell=True)

a = vars(args)
commit = sh.check_output('git rev-parse HEAD', shell=True)
commit = commit.decode('utf-8')[:-1]
print('commit {}'.format(str(commit)))
for k in sorted(a):
    print(k, a[k])

remote_script(args)
local_script(args)

sh.run('scp 10.1.1.2:~/{0}/* ./{0}'.format(args.outdir), shell=True)
if args.three_machines:
    sh.run('scp 192.168.1.5:~/{0}/* ./{0}'.format(args.outdir), shell=True)

sh.run('mm-graph {}/mahimahi.log 50'.format(args.outdir), shell=True)
