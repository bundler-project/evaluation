#!/bin/bash

set -x

dir=$1
algs=("nobundler_fifo" "nobundler_sfq" "copa_sfq" "copa_fifo" "nimbus_sfq" "bbr_sfq")
seeds=("0" "17" "26" "28" "41" "62" "67" "68" "88" "99")

for l in "84Mbps"; do
    for exp in "${algs[@]}"; do
        for i in "${seeds[@]}"; do
            awk "{print \$0\", Alg:$exp Iter:$i\"}" $dir/$l-10000-$exp-$i-bk/_flows.out | python3 columnize.py | python3 categorize.py 10000 > $dir/$l-10000-$exp-$i-bk-flows.out
        done
    done
    
    rm -f $dir/$l-bk-flows.out
    exps=($(find $dir -name "$l-*-bk-flows.out"))
    head -n 1 ${exps[0]} > $dir/$l-bk-flows.out
    for exp in ${exps[@]}; do
        tail -n +2 $exp >> $dir/$l-bk-flows.out
    done

    Rscript fcts.r $dir/$l-bk-flows.out $dir/$l-bk-flows.pdf
done
