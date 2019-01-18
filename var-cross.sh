#!/bin/bash

# inelastic varying fraction
python3 cross-exps.py --iters 1 --reqs 10000 --load 72Mbps --alg nimcopa --alg bbr --alg nimbus --alg copa --alg nobundler --sch sfq --dir cr-inelastic --cross_type=inelastic --cross_load 12Mbps
python3 cross-exps.py --iters 1 --reqs 10000 --load 60Mbps --alg nimcopa --alg bbr --alg nimbus --alg copa --alg nobundler --sch sfq --dir cr-inelastic --cross_type=inelastic --cross_load 24Mbps
python3 cross-exps.py --iters 1 --reqs 10000 --load 48Mbps --alg nimcopa --alg bbr --alg nimbus --alg copa --alg nobundler --sch sfq --dir cr-inelastic --cross_type=inelastic --cross_load 36Mbps

# elastic varying number
python3 cross-exps.py --iters 1 --reqs 10000 --load 84Mbps --alg nimcopa --alg bbr --alg nimbus --alg copa --alg nobundler --sch sfq --dir cr-elastic --cross_type=elastic --cross_load 1
python3 cross-exps.py --iters 1 --reqs 10000 --load 84Mbps --alg nimcopa --alg bbr --alg nimbus --alg copa --alg nobundler --sch sfq --dir cr-elastic --cross_type=elastic --cross_load 2
python3 cross-exps.py --iters 1 --reqs 10000 --load 84Mbps --alg nimcopa --alg bbr --alg nimbus --alg copa --alg nobundler --sch sfq --dir cr-elastic --cross_type=elastic --cross_load 3
python3 cross-exps.py --iters 1 --reqs 10000 --load 84Mbps --alg nimcopa --alg bbr --alg nimbus --alg copa --alg nobundler --sch sfq --dir cr-elastic --cross_type=elastic --cross_load 4

curl -X POST https://maker.ifttt.com/trigger/text_me/with/key/cTyEB1Uga6onvmR6HioIs-
