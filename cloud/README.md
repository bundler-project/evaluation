Bundler Cloud Experiments
-------------------------

These experiments run Bundler on cloud machines, over the real internet.

## Build

This experiment is written in Rust. `cargo b --release` to build.

## Running

Given an input like [machines.json](./machines.json), it will create various directories `srcname-dstname`, each with 3 sub-directories, `bundler`, `control`, and `iperf`. Each of these will have `bmon.log` and `udping.log`. 
Note that a machine can only be part of one pair at once, so it can be inefficient or expensive to run a large matrix. 
So, to save money, we can use `generate_machine_pairs.py` to create a schedule of `phase_xx.json`, then run like this:

```
fd "phase_[0-9]+.json" | xargs -I{} cargo run --bin matrix -- --cfg={}
```

Then, use `parse_udping.py` to create data files `bmon_results.out` nd `udping_results.out` followed by `plot_paths.r` to get a plot of the latencies and throughput for all the paths.
