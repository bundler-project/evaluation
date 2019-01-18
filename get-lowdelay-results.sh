#!/bin/bash

dir=$1
algs=("nobundler_fifo" "copa_sfq" "copa_fqcodel" "copa_fifo")

rm -r $1/lowdelay.data
for exp in "${algs[@]}"; do
    awk "{print \"conns=3 alg=$exp time=\"\$1,\"connection=\"\$3,\"rtt=\"\$(NF-1)}" lowdelay/3-$exp/tcpprobe.out  | python3 columnize.py '=' > $1/$exp.data
done

rm -f $dir/lowdelays.data
exps=($(find $dir -name "*.data"))
head -n 1 ${exps[0]} > $dir/lowdelays.data
for exp in ${exps[@]}; do
    tail -n +2 $exp >> $dir/lowdelays.data
    rm $exp
done
