#!/bin/bash

set -x

dir=$1
algs=("copa_sfq" "proxy_copa_sfq")
seeds=("0" "17" "26" "28" "41" "62" "67" "68" "88" "99")

for l in "84Mbps"; do
    for exp in "${algs[@]}"; do
        for i in "${seeds[@]}"; do
            awk "{print \$0\", Alg:$exp Iter:$i\"}" $dir/$l-10000-$exp-$i-pl/_flows.out | python3 columnize.py | python3 categorize.py 10000 > $dir/$l-10000-$exp-$i-pl-flows.out
        done
    done
    
    rm -f $dir/$l-pl-flows.out
    exps=($(find $dir -name "$l-*-pl-flows.out"))
    head -n 1 ${exps[0]} > $dir/$l-pl-flows.out
    for exp in ${exps[@]}; do
        tail -n +2 $exp >> $dir/$l-pl-flows.out
    done

    Rscript fcts.r $dir/$l-pl-flows.out $dir/$l-pl-flows.pdf
done
