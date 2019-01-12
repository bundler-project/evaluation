#!/bin/bash

set -x

dir=$1
iterations=$2
algs=("nimbus_fifo" "nimbus_sfq" "nobundle_fifo" "nobundle_proxy_sfq")

rm "*-flows.out"
for l in "72Mbps" "84Mbps"; do
    for exp in "${algs[@]}"; do
        for i in `seq 0 $iterations`; do
            awk "{print \$0\", Alg:$exp Iter:$i\"}" $dir/$l-10000req-$exp-$i/_flows.out | python3 columnize.py | python3 categorize.py 5000 > $dir/$l-$exp-$i-flows.out
        done
    done
    
    rm -f $dir/$l-flows.out
    exps=($(find $dir -name "$l-*-flows.out"))
    head -n 1 ${exps[0]} > $dir/$l-flows.out
    for exp in ${exps[@]}; do
        tail -n +2 $exp >> $dir/$l-flows.out
    done

    Rscript fcts.r $dir/$l-flows.out $dir/$l-flows.pdf
done
