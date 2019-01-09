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
parser.add_argument('--three_machines', action='store_true', dest='use_three_machines')

nimbus = 'sudo ~/nimbus/target/release/nimbus --ipc=unix --use_switching=false --flow_mode=Delay --bw_est_mode=false --pulse_size=0.01 2> {}/nimbus.out'
bbr = 'sudo ~/bbr/target/release/bbr --ipc=unix 2> {}/bbr.out'
osc = 'sudo python ~/portus/python/osc.py'
algs = {
    'nimbus': nimbus,
    'bbr': bbr,
    'osc': osc,
}

def remote_script(time, use_bundler, three_machines, outdir, qdisc, alg, conns, samplerate, dynamic_samplerate):
    inbox = 'sudo ~/bundler/box/target/release/inbox --iface=10gp1 --handle_major={} --handle_minor=0x0 --port=28316 --use_dynamic_sample_rate={} --sample_rate={} 2> {}/inbox.out'.format(qdisc, dynamic_samplerate, samplerate, outdir)
    iperf = '~/iperf/src/iperf -s -p 5000 --reverse -i 1 -t {} -P {} > {}/iperf-server.out'.format(time, conns, outdir)

    print(inbox)
    print(iperf)

    with open('remote.sh', 'w') as f:
        f.write('#!/bin/bash\n\n')
        f.write('rm -rf ~/{}\n'.format(outdir))
        f.write('mkdir -p ~/{}\n'.format(outdir))
        if use_bundler:
            f.write(inbox + ' &\n')
            f.write('sleep 1\n')
            f.write(alg.format(outdir) + ' &\n')
        if not three_machines:
            f.write(iperf + '\n')

    sh.run('chmod +x remote.sh', shell=True)
    sh.run('scp ./remote.sh 10.1.1.2:', shell=True)

    if three_machines:
        with open('remote.sh', 'w') as f:
            f.write('#!/bin/bash\n\n')
            f.write('rm -rf ~/{}\n'.format(outdir))
            f.write('mkdir -p ~/{}\n'.format(outdir))
            f.write(iperf + '\n')
        sh.run('chmod +x remote.sh', shell=True)
        sh.run('scp ./remote.sh 10.1.1.5:', shell=True)

    sh.Popen('ssh 10.1.1.2 ~/remote.sh' , shell=True)
    sh.Popen('ssh 192.168.1.5 ~/remote.sh' , shell=True)

def local_script(use_bundler, three_machines, outdir, conns, samplerate):
    outbox = 'sudo ~/bundler/box/target/release/outbox --filter "port 5000" --iface ingress --inbox 10.1.1.2:28316 {} --sample_rate {} 2> {}/outbox.out'.format(
        "--no_ethernet",
        samplerate,
        outdir,
    )
    iperf = 'iperf -c {} -p 5000 --reverse -i 1 -P {} > {}/iperf-client.out'.format(
        '192.168.1.5' if three_machines else '10.1.1.2',
        conns,
        outdir,
    )

    print(outbox)
    print(iperf)
    with open('local.sh', 'w') as f:
        f.write('#!/bin/bash\n\n')
        if use_bundler:
            f.write('sleep 1\n')
            f.write(outbox + ' &\n')
        f.write('sleep 1\n')
        f.write('echo \'starting iperf client\'\n')
        f.write(iperf + '\n')

    sh.run('chmod +x local.sh', shell=True)
    sh.run('rm -rf ./{}\n'.format(outdir), shell=True)
    sh.run('mkdir -p ./{}\n'.format(outdir), shell=True)
    mahimahi = 'mm-delay 25 mm-link --cbr 96M 96M --downlink-queue="droptail" --downlink-queue-args="packets=1200" --uplink-queue="droptail" --uplink-queue-args="packets=1200" --downlink-log={}/mahimahi.log ./local.sh'.format(outdir)
    sh.run(mahimahi, shell=True)

args = parser.parse_args()

sh.run('ssh 10.1.1.2 sudo pkill inbox', shell=True)
sh.run('ssh 10.1.1.2 sudo pkill nimbus', shell=True)
sh.run('ssh 10.1.1.2 sudo pkill bbr', shell=True)
sh.run('ssh 10.1.1.2 sudo pkill iperf', shell=True)
sh.run('ssh 192.168.1.5 sudo pkill iperf', shell=True)
sh.run('sudo pkill outbox', shell=True)
sh.run('sudo pkill iperf', shell=True)

a = vars(args)
commit = sh.check_output('git rev-parse HEAD', shell=True)
commit = commit.decode('utf-8')[:-1]
print('commit {}'.format(str(commit)))
for k in sorted(a):
    print(k, a[k])

remote_script(
    args.time,
    args.usebundler,
    args.use_three_machines,
    args.outdir,
    args.qdisc,
    algs[args.alg],
    args.conns,
    args.samplerate,
    'true' if args.dynamic_epoch else 'false',
)

local_script(
    args.usebundler,
    args.use_three_machines,
    args.outdir,
    args.conns,
    args.samplerate,
)

sh.run('scp 10.1.1.2:~/{0}/* ./{0}'.format(args.outdir), shell=True)
if args.use_three_machines:
    sh.run('scp 192.168.1.5:~/{0}/* ./{0}'.format(args.outdir), shell=True)

sh.run('mm-graph {}/mahimahi.log 50'.format(args.outdir), shell=True)
