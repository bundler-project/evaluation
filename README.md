# Reproduce Bundler Experiments

This repository contains scripts that help run the Bundler experiments from our [EuroSys '21 paper](https://arxiv.org/pdf/2011.01258.pdf). The scripts in this repo (primarily `eval.py`) will take you from a toml config file (like `cloudlab.toml`, in the root of this repo) and give you an HTML report of the experiment you ran. We provide a separate config file for each experiment in `configs/fig*.toml`

Our scripts for re-creating the plots exactly as they appeared in the paper are in our [paper repo](https://github.com/bundler-project/writing). The easiest way to run them is to (1) copy your experiment output files into `[paper_repo]/graphs/data`, then (2) build the paper (i.e. run `make` in the root of the paper repo). This will automatically create the graphs.

## Overview

1. Decide which machines you will use for the experiment ("What machines?")
2. Install dependencies on the machine that will be orchestrating the experiments and plotting graphs, e.g. your local machine ("Local dependencies"). Running an experiment will automatically install necessary dependencies on the experiment hosts.
3. Run an instance of `eval.py` ("Running an experiment") with the `--dry-run` flag to start. If you run into any issues with launching an experiment, return to this step to debug.
4. Run an instance of `eval.py` with a very simple config to ensure everything is working properly.
5. Run an instance of `eval.py` with one of the paper experiment configs, then view results in a web browser.
6. (Optional): to match the aesthetics of the paper graphs and axes, copy the experiment data into the paper repo (see above) and build the paper.

### What machines?

All of our experiments require multiple machines. 

The "blessed path" is to run the experiments with [Cloudlab](https://www.cloudlab.us/). We have created a ["profile"](https://www.cloudlab.us/show-profile.php?uuid=84aa948d-5b67-11eb-a9ff-e4434b2381fc) which `cloudlab/cloudlab.py` can help instantiating and managing (using chromedriver to click things). 
This is of course optional (and `cloudlab.py` is somewhat finicky) - if you want, you can of course bring your own machines (note that AWS, Azure, GCP, etc *won't work* because the scripts need to set routing table rules) and specify in your `.toml` like so:
```
# manual configuration way
[topology]
    [topology.sender]
        name = "host0"
        ifaces = [{dev = "eth0", addr = "10.0.0.1"}]
    [topology.inbox]
        name = "host1"
        user = "my-username"
        ifaces = [
            {dev = "eth0", addr = "10.0.0.2"},
            {dev = "eth1", addr = "10.0.1.1"},
        ]
        listen_port = 28316
    [topology.outbox]
        name = "host2"
        ifaces = [{dev = "eth0", addr = "10.0.1.2"}]
    [topology.receiver]
        name = "host2"
        ifaces = [{dev = "eth0", addr = "10.0.1.2"}]
```

Whatever machines you use, they must have Linux kernel 5.4 for Bundler's qdisc kernel module to work (and you of course have to be able and willing to install the kernel module).
Keep in mind that in this set of scripts, the outbox and receiver are on the same machine so that we can use mahimahi for link emulation, which gives us nice instrumentation.

The cloudlab way looks like this. Note that if you already have an experiment running, it will use that and not spawn a new one.
```
# cloudlab.py chromedriver way
[topology]
    [topology.cloudlab]
        username = "my-username"
        password = "my-cloudlab-password"
    [topology.inbox]
        listen_port = 28316
```

#### cloudlab.py pitflls

- You might have to edit cloudlab.py a bit (near the top of the file) to point to your Chrome.
- The sleeps waiting for the page to load might be miscalibrated. We generally just try again.
- `--headless` can be useful to prevent the Chrome window from popping up every time, but when first launching the cluster you don't want this, since you have to select a region. 
- We suggest running a shorter experiment first to get the cluster up before moving on to the paper experiments. The experiment script automatically checks for and installs any missing dependencies on each run, so there is no explicit setup script.

### What from the paper can I reproduce?

By using various config files (`configs/fig*.toml`), you can reproduce Figures 7, 8, 9, 10, and 12. Figures 11 and 13 involved manual setup (and more machines, for Fig 11) and we don't offer a script for them. Code to run the Fig 14 measurements is in `cloud/`, but these experiments are both expensive and prone to random variance since they run on the real Internet. If you want to run these experiments, please get in touch.

### Local dependencies

These are local dependencies to run the experiment script and parse the outputs into a report with a graph.

- Python 3.9.0
  - See requirements.txt
- R 4.0.3 (packages all available on cran)
  - ggplot2
  - dplyr
  - tidyr
  - patchwork
  - rmarkdown
  - plotly
- ChromeDriver 88.0.4324.96 (optional, but cloudlab/cloudlab.py assumes it exists)
  - The `chromedriver` binary should be put in the toplevel directory of this repo.

### Running an experiment

The experiment script can be launched from any machine (including one of the experiment hosts). The only requirement is that this machine has password-less ssh access to all of the experiments hosts. It will internally create an ssh shell with each host at the beginning and use this to orchestrate the experiment.

```
python3 eval.py --name fig7 recreate.toml (--headless) (--verbose)
```

The `.toml` file controls the experiment. You can add bundle traffic, cross traffic, change parameters, etc. The lists in the `[experiment]` section will be run in all-combinations, so, for example, the currently committed version of Figure 7 will run (10 iterations) * (2 scheduling algs) * (2 algorithms) = 40 experiments. 100k poisson flows at 7/8ths load generally takes around 5 minutes, so this is a 200 minute experiment in total.

The result will get written to `./experiments/fig7/index.html`, which you can open in a web browser. The graphs are noninteractive by default, but if you (optionally) then run 

```
python3 parse_outputs.py experiments/fig7 --bundler_root=`pwd` --interact
```

the graphs will become interactive. If there are many graphs in the experiment, this can be slow, so it is not the default.
