#!/bin/bash

set -x

#load
#python3 fct-exps.py --iters=10 --load 48Mbps --load 72Mbps  --load 84Mbps --alg copa --sch sfq --alg nobundler --reqs 10000 --dir results/caida
##vs fifo
#python3 fct-exps.py --iters=10 --load 84Mbps --alg copa --sch sfq --sch fifo --alg nobundler --reqs 10000 --dir results/caida
##algs
#python3 fct-exps.py --iters=10 --load 84Mbps --alg copa --alg nimbus --alg bbr --sch sfq --alg nobundler --reqs 10000 --dir results/caida

python3 fct-exps.py --iters=10 --load 84Mbps --alg nobundler_sfq --sch sfq --reqs 10000 --dir results/caida

curl -X POST https://maker.ifttt.com/trigger/text_me/with/key/cTyEB1Uga6onvmR6HioIs-
