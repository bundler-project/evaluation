#!/usr/bin/python3

import argparse
import subprocess as sh
import time
import sys

parser = argparse.ArgumentParser()
parser.add_argument('--outdir', type=str, dest='outdir')

parser.add_argument('--conns', type=int, dest='conns')
parser.add_argument('--load', type=str, dest='load')
parser.add_argument('--seed', type=int, dest='seed')
parser.add_argument('--reqs', type=int, dest='reqs')

def kill_everything():
    sh.run('ssh 10.1.1.2 sudo pkill -9 -f ./bin/server', shell=True)

def write_etg_config(name, args):
    with open(name, 'w') as f:
        for p in range(5000, 5000 + args.conns):
            f.write("server 10.1.1.2 {}\n".format(p))
        f.write("req_size_dist ./CAIDA_CDF\n")
        f.write("fanout 1 100\n")
        f.write("persistent_servers 1\n")
        f.write("load {}\n".format(args.load))
        f.write("num_reqs {}\n".format(args.reqs))

def remote_script(args):
    exc = 'cd ~/bundler/scripts && ./run-multiple-server.sh 5000 {}'.format(args.conns)
    print(exc)

    with open('remote.sh', 'w') as f:
        f.write('#!/bin/bash\n\n')
        f.write('rm -rf ~/{}\n'.format(args.outdir))
        f.write('mkdir -p ~/{}\n'.format(args.outdir))
        f.write(exc + '\n')

    sh.run('chmod +x remote.sh', shell=True)
    sh.run('scp ./remote.sh 10.1.1.2:', shell=True)

    sh.Popen('ssh 10.1.1.2 ~/remote.sh' , shell=True)

def local_script(args):
    exc = '~/bundler/scripts/empiricial-traffic-gen/bin/client -c ~/bundler/scripts/bundlerConfig -l {}/ -s {}'.format(
        args.outdir,
        args.seed,
    )

    print(exc)

    with open('local.sh', 'w') as f:
        f.write('#!/bin/bash\n\n')
        f.write('sleep 1\n')
        f.write('sudo tc qdisc add root dev ingress sfq flows 255 limit 1200\n')
        f.write('echo "starting client: $(date)"\n')
        f.write(exc + '\n')

    sh.run('chmod +x local.sh', shell=True)
    sh.run('rm -rf ./{}\n'.format(args.outdir), shell=True)
    sh.run('mkdir -p ./{}\n'.format(args.outdir), shell=True)
    mahimahi = 'mm-delay 25 mm-link --cbr 96M 96M --downlink-queue="akshayfq" --downlink-queue-args="queues=511,packets=200" --uplink-queue="droptail" --uplink-queue-args="packets=1200" --downlink-log={}/mahimahi.log ./local.sh'.format(args.outdir)
    sh.run(mahimahi, shell=True)


def run_single_experiment(args):
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

    sh.run("mv ./bundlerConfig ./{}".format(args.outdir), shell=True)
    kill_everything()

    sh.run('mm-graph {}/mahimahi.log 50'.format(args.outdir), shell=True)

if __name__ == '__main__':
    args = parser.parse_args()
    run_single_experiment(args)
