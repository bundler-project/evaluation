#!/bin/bash

# sfq vs nobundler
python3 fct-exps.py --iters=10 --load 84Mbps --alg copa --alg nobundler --sch sfq  --reqs 10000 --dir results/caida  || exit
# fifo vs sfq
python3 fct-exps.py --iters=10 --load 84Mbps --alg copa --sch sfq --sch fifo --reqs 10000 --dir results/caida  || exit
curl -X POST https://maker.ifttt.com/trigger/text_me/with/key/cTyEB1Uga6onvmR6HioIs-
