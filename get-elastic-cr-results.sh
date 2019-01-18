#!/bin/bash

set -x

dir=$1
algs=("nimbus_sfq" "bbr_sfq" "copa_sfq" "nimcopa_sfq" "nobundler_fifo")
#seeds=("0" "17" "26" "28" "41" "62" "67" "68" "88" "99")
seeds=("0")
elastics=("1" "2" "3" "4")

for l in "84Mbps"; do
    for exp in "${algs[@]}"; do
        for cross in "${elastics[@]}"; do
            for i in "${seeds[@]}"; do
                awk "{print \$0\", Load:$l Alg:$exp Cross:$cross Iter:$i\"}" $dir/$l-elastic-$cross-10000-$exp-$i/_flows.out | python3 columnize.py | python3 categorize.py 10000 > $dir/elastic-$cross-10000-$exp-$i-flows.out
            done
        done
    done
done

rm -f $dir/elastic-flows.out
exps=($(find $dir -name "elastic-*-flows.out"))
head -n 1 ${exps[0]} > $dir/elastic-flows.out
for exp in ${exps[@]}; do
    tail -n +2 $exp >> $dir/elastic-flows.out
    rm $exp
done

Rscript fcts.r $dir/elastic-flows.out $dir/elastic-flows.pdf
