#!/bin/bash

for i in `seq 0 $2`; do
    ./empiricial-traffic-gen/bin/server -t reno -p $(($1 + $i)) >> /dev/null &
done
