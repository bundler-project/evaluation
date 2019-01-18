#!/bin/bash

set -x

dir=$1
algs=("nobundler_fifo" "copa_sfq")
seeds=("0" "17" "26" "28" "41" "62" "67" "68" "88" "99")

for l in "48Mbps" "72Mbps" "84Mbps"; do
    for exp in "${algs[@]}"; do
        for i in "${seeds[@]}"; do
            awk "{print \$0\", Alg:$exp Iter:$i Load:$l\"}" $dir/$l-10000-$exp-$i-pl/_flows.out | python3 columnize.py | python3 categorize.py 10000 > $dir/$l-10000-$exp-$i-pl-flows.out
        done
    done
    
done

rm -f $dir/pl-flows.out
exps=($(find $dir -name "*-pl-flows.out"))
head -n 1 ${exps[0]} > $dir/pl-flows.out
for exp in ${exps[@]}; do
    tail -n +2 $exp >> $dir/pl-flows.out
done
