#!/usr/bin/python3

import argparse
import subprocess as sh
import time
import sys

parser = argparse.ArgumentParser()
parser.add_argument('--outdir', type=str, dest='outdir')

parser.add_argument('--no_bundler', action='store_false', dest='usebundler')
parser.add_argument('--qdisc1', type=str, dest='qdisc1')
parser.add_argument('--qdisc2', type=str, dest='qdisc2')
parser.add_argument('--alg', type=str, dest='alg')

parser.add_argument('--conns', type=int, dest='conns')
parser.add_argument('--load', type=str, dest='load')
parser.add_argument('--seed', type=int, dest='seed')
parser.add_argument('--reqs', type=int, dest='reqs')

nimbus = 'sudo ~/nimbus/target/debug/nimbus --ipc=unix --use_switching=false --flow_mode=XTCP --loss_mode=Bundle --bw_est_mode=false --pulse_size=0.25 2> {}/nimbus.out'
bbr = 'sudo ~/bbr/target/release/bbr --ipc=unix 2> {}/bbr.out'
copa = 'sudo ~/ccp_copa/target/debug/copa --ipc=unix --default_delta=0.125 2> {}/copa.out'
nimcopa = 'sudo ~/nimbus/target/debug/nimbus --ipc=unix --use_switching=false --flow_mode=XTCP --delay_mode=Copa --loss_mode=Bundle --bw_est_mode=false --pulse_size=0.25 2> {}/copa.out'
algs = {
    'nimbus': nimbus,
    'bbr': bbr,
    'copa': copa,
    'nimcopa': nimcopa,
}

def kill_everything():
    # inbox 1
    sh.run('ssh 10.1.1.2 sudo pkill -9 inbox', shell=True)
    sh.run('ssh 10.1.1.2 sudo pkill -9 nimbus', shell=True)
    sh.run('ssh 10.1.1.2 sudo pkill -9 bbr', shell=True)
    sh.run('ssh 10.1.1.2 sudo pkill -9 copa', shell=True)
    # inbox 2
    sh.run('ssh 192.168.1.1 sudo pkill -9 inbox', shell=True)
    sh.run('ssh 192.168.1.1 sudo pkill -9 nimbus', shell=True)
    sh.run('ssh 192.168.1.1 sudo pkill -9 bbr', shell=True)
    sh.run('ssh 192.168.1.1 sudo pkill -9 copa', shell=True)
    # sender 1
    sh.run('ssh 192.168.1.5 sudo pkill -9 -f ./bin/server', shell=True)
    sh.run('ssh 192.168.1.5 sudo pkill -9 iperf', shell=True)
    # sender 2
    sh.run('ssh -p 222 akshay@18.26.5.240 sudo pkill -9 -f ./bin/server', shell=True)
    sh.run('ssh -p 222 akshay@18.26.5.240 sudo pkill -9 iperf', shell=True)
    # local receivers/outboxes
    sh.run('sudo pkill -9 outbox', shell=True)
    sh.run('sudo pkill -9 iperf', shell=True)
    sh.run('sudo pkill -9 -f ./bin/client', shell=True)

def write_etg_config(name, start, servers, load, reqs, backlogged, src):
    with open(name, 'w') as f:
        for p in range(start, start + servers):
            f.write("server {} {}\n".format(src, p))
        f.write("req_size_dist ./CAIDA_CDF\n")
        f.write("fanout 1 100\n")
        if backlogged:
            f.write("persistent_servers 1\n")
        f.write("load {}\n".format(load))
        f.write("num_reqs {}\n".format(reqs))

def server_script(args):
    with open('server.sh', 'w') as f:
        f.write('#!/bin/bash\n\n')
        exc = 'cd ~/bundler/scripts && ./run-multiple-server.sh 5000 {}'.format(args.conns)
        f.write(exc + '\n')
    sh.run('chmod +x server.sh', shell=True)
    sh.run('scp ./server.sh 192.168.1.5:', shell=True)

    with open('server.sh', 'w') as f:
        f.write('#!/bin/bash\n\n')
        exc = 'cd ~/bundler/scripts && ./run-multiple-server.sh 7000 {}'.format(args.conns)
        f.write(exc + "\n")
    sh.run('chmod +x server.sh', shell=True)
    sh.run('scp -P 222 ./server.sh akshay@18.26.5.240:', shell=True)

    sh.run('rm ./server.sh', shell=True)
    sh.Popen('ssh 192.168.1.5 ~/server.sh' , shell=True)
    print("==> started 192.168.1.5 server")
    sh.Popen('ssh -p 222 akshay@18.26.5.240 "/home/akshay/server.sh"' , shell=True)
    print("==> started 18.26.5.240 server")


def inbox_script(args):
    inbox = 'sudo ~/bundler/box/target/release/inbox --iface=10gp1 --handle_major={} --handle_minor=0x0 --port=28316 --use_dynamic_sample_rate=true --sample_rate=128 2> {}/inbox.out'.format(args.qdisc1, args.outdir)

    print(inbox)

    with open('inbox.sh', 'w') as f:
        f.write('#!/bin/bash\n\n')
        f.write('rm -rf ~/{}\n'.format(args.outdir))
        f.write('mkdir -p ~/{}\n'.format(args.outdir))
        if args.use_bundler:
            f.write('echo "starting inbox: $(date)"\n')
            f.write(inbox + ' &\n')
            f.write('sleep 1\n')
            f.write('echo "starting alg: $(date)"\n')
            f.write(args.alg.format(args.outdir) + ' &\n')

    sh.run('chmod +x inbox.sh', shell=True)
    sh.run('scp ./inbox.sh 10.1.1.2:', shell=True)

    inbox = 'sudo ~/bundler/box/target/release/inbox --iface=em2 --handle_major={} --handle_minor=0x0 --port=28316 --use_dynamic_sample_rate=true --sample_rate=128 2> {}/inbox.out'.format(args.qdisc2, args.outdir)

    print(inbox)

    with open('inbox.sh', 'w') as f:
        f.write('#!/bin/bash\n\n')
        f.write('rm -rf ~/{}\n'.format(args.outdir))
        f.write('mkdir -p ~/{}\n'.format(args.outdir))
        if args.use_bundler:
            f.write('echo "starting inbox: $(date)"\n')
            f.write(inbox + ' &\n')
            f.write('sleep 1\n')
            f.write('echo "starting alg: $(date)"\n')
            f.write(args.alg.format(args.outdir) + ' &\n')

    sh.run('chmod +x inbox.sh', shell=True)
    sh.run('scp ./inbox.sh 192.168.1.1:', shell=True)

    sh.run('rm ./inbox.sh', shell=True)
    sh.Popen('ssh 10.1.1.2 ~/remote.sh' , shell=True)
    print("==> started 10.1.1.2 inbox")
    sh.Popen('ssh 192.168.1.1 ~/remote.sh' , shell=True)
    print("==> started 192.168.1.1 inbox")

def local_script(args):
    outbox = 'sudo ~/bundler/box/target/release/outbox --filter "src portrange {}-{}" --iface ingress --inbox {}:28316 --no_ethernet --sample_rate 128 2> {}/outbox.out'

    exc = '~/bundler/scripts/empiricial-traffic-gen/bin/client -c ~/bundler/scripts/{0} -l {1}/' + ' -s {}'.format(args.seed) + ' > {1}/client.log'

    print(outbox)
    print(exc)

    # first client
    with open('local.sh', 'w') as f:
        if args.use_bundler:
            f.write(outbox.format(5000, 6000, "10.1.1.2", args.outdir+"/bund1") + ' &\n')
            f.write(outbox.format(7000, 8000, "192.168.1.1", args.outdir+"/bund2") + ' &\n')
            f.write('sleep 1\n')
        f.write('echo "starting client 1: $(date)"\n')
        f.write(exc.format("client1", args.outdir+"/bund1") + ' &\n')
        f.write('client1=$!\n')
        f.write('echo "starting client 2: $(date)"\n')
        f.write(exc.format("client2", args.outdir+"/bund2") + ' &\n')
        f.write('client2=$!\n')
        f.write('wait $client1 $client2 \n')

    sh.run('chmod +x local.sh', shell=True)

    sh.run('rm -rf ./{}\n'.format(args.outdir), shell=True)
    sh.run('mkdir -p ./{}\n'.format(args.outdir + "/bund1"), shell=True)
    sh.run('mkdir -p ./{}\n'.format(args.outdir + "/bund2"), shell=True)

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

    write_etg_config('client1', 5000, args.conns, args.load, args.reqs, True, '192.168.1.5')
    write_etg_config('client2', 7000, args.conns, args.load, args.reqs, True, '18.26.5.240')
    server_script(args)
    inbox_script(args)
    local_script(args)

    sh.run('scp 10.1.1.2:~/{0}/* ./{0}/bund1/'.format(args.outdir), shell=True)
    sh.run('scp 192.168.1.1:~/{0}/* ./{0}/bund2/'.format(args.outdir), shell=True)

    sh.run("mv ./client1 ./{}/bund1".format(args.outdir), shell=True)
    sh.run("mv ./client2 ./{}/bund2".format(args.outdir), shell=True)

    kill_everything()

    sh.run('mm-graph {}/mahimahi.log 50'.format(args.outdir), shell=True)

if __name__ == '__main__':
    args = parser.parse_args()
    run_single_experiment(args)
