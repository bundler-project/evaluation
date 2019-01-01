#!/usr/bin/python3

import argparse
import subprocess as sh
import time

parser = argparse.ArgumentParser()
parser.add_argument('--qdisc', type=str, dest='qdisc')
parser.add_argument('--outdir', type=str, dest='outdir')
parser.add_argument('--alg', type=str, dest='alg')
parser.add_argument('--conns', type=int, dest='conns')

nimbus = 'sudo ~/nimbus/target/release/nimbus --ipc=unix --use_switching=false --flow_mode=Delay 2> {}/nimbus.out'
bbr = 'sudo ~/bbr/target/release/bbr --ipc=unix 2> {}/bbr.out'
osc = 'sudo python ~/portus/python/osc.py'
algs = {
    'nimbus': nimbus,
    'bbr': bbr,
    'osc': osc,
}

def remote_script(outdir, qdisc, alg, conns):
    inbox = 'sudo ~/bundler/box/target/release/inbox --iface=10gp1 --handle_major={} --handle_minor=0x0 --port=28316 --sample_rate=128 2> {}/inbox.out'.format(qdisc, outdir)
    iperf = '~/iperf/src/iperf -s -p 5000 --reverse -i 1 -t 30 -P {} > {}/iperf-server.out'.format(conns, outdir)
    with open('remote.sh', 'w') as f:
        f.write('#!/bin/bash\n\n')
        f.write('rm -rf ~/{}\n'.format(outdir))
        f.write('mkdir -p ~/{}\n'.format(outdir))
        f.write(inbox + ' &\n')
        f.write('sleep 1\n')
        f.write(alg.format(outdir) + ' &\n')
        f.write(iperf + '\n')

    sh.run('chmod +x remote.sh', shell=True)
    sh.run('scp ./remote.sh 10.1.1.2:', shell=True)
    sh.Popen('ssh 10.1.1.2 ~/remote.sh' , shell=True)

def local_script(outdir, conns):
    outbox = 'sudo ~/bundler/box/target/release/outbox --filter "port 5000" --iface ingress --inbox 10.1.1.2:28316 --no_ethernet --sample_rate 128 > {}/outbox.out'.format(outdir)
    iperf = 'iperf -c 10.1.1.2 -p 5000 --reverse -i 1 -P {} > {}/iperf-client.out'.format(conns, outdir)

    with open('local.sh', 'w') as f:
        f.write('#!/bin/bash\n\n')
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
remote_script(args.outdir, args.qdisc, algs[args.alg], args.conns)
local_script(args.outdir, args.conns)

sh.run('ssh 10.1.1.2 sudo pkill inbox', shell=True)
sh.run('ssh 10.1.1.2 sudo pkill nimbus', shell=True)
sh.run('ssh 10.1.1.2 sudo pkill bbr', shell=True)
sh.run('ssh 10.1.1.2 sudo pkill iperf', shell=True)
sh.run('sudo pkill outbox', shell=True)
sh.run('sudo pkill iperf', shell=True)
sh.run('scp 10.1.1.2:~/{0}/* ./{0}'.format(args.outdir), shell=True)

sh.run('mm-graph {}/mahimahi.log 50'.format(args.outdir), shell=True)

# impl dual mahimahi
