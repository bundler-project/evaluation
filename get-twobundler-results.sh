#!/bin/bash

set -x

dir=$1
algs=("nobundler_fifo" "nimbus_sfq" "copa_sfq")
#seeds=("0" "17" "26" "28" "41" "62" "67" "68" "88" "99")
seeds=("0")

l="48Mbps"

for alg in "${algs[@]}"; do
    for i in "${seeds[@]}"; do
        awk "{print \$0\", Load:$l Alg:$alg Iter:$i BundleId:0\"}" $dir/$l-10000-$alg-$i/bund1/_reqs.out | python3 columnize.py | python3 categorize.py 5000 > $dir/$l-10000-$alg-$i/$alg-$i-b1-flows.data
        awk "{print \$0\", Load:$l Alg:$alg Iter:$i BundleId:1\"}" $dir/$l-10000-$alg-$i/bund2/_reqs.out | python3 columnize.py | python3 categorize.py 5000 > $dir/$l-10000-$alg-$i/$alg-$i-b2-flows.data
    done
done

rm -f $dir/twobundler.data
exps=($(find $dir -name "*flows.data"))
head -n 1 ${exps[0]} > $dir/twobundler.data
for exp in ${exps[@]}; do
    tail -n +2 $exp >> $dir/twobundler.data
    rm $exp
done
