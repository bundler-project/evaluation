#!/bin/bash

for i in `seq 1 $1`; do
    ./empirical-traffic-gen/bin/server -t reno -p $((5000 + $i)) >> /dev/null &
done
