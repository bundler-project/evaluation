# Reproduce Bundler Experiments

This repository contains scripts that help run the Bundler experiments from our [EuroSys '21 paper](https://arxiv.org/pdf/2011.01258.pdf). [`eval.py`](eval.py) takes as input a toml file describing an experiment (like [`configs/fig7.toml`](configs/fig7.toml)) and produces an HTML report of the experiment you ran which you can view in a web browser. We provide a separate config file for each experiment in `configs/fig*.toml`

## Overview

1. Decide which machines you will use for the experiment (see ["What machines?"](#what-machines) for discussion)
2. Install dependencies on the machine that will be orchestrating the experiments and plotting graphs, e.g. your local machine (see ["Local dependencies"](#local-dependencies)). Running an experiment will automatically clone this repository and install necessary experiment dependencies (Rust, mahimahi, etc) on the experiment hosts.
3. Pick an experiment to run / config file to use, and edit the top of the config file with your credentials or host details. See below for an example.
4. Run an instance of `eval.py` (see ["Running an Experiment"](#running-an-experiment)) with your config, wait patiently (some of them take multiple hours!), then view results in a web browser.
5. (Optional): To match the aesthetics of the paper graphs and axes, copy the experiment data into the [paper repo](https://github.com/bundler-project/writing) and build the paper (see ["Matching paper aesthetics"](#matching-paper-aesthetics)).

## Local dependencies

These are local dependencies to run the experiment script and parse the outputs into a report with a graph.

- [Python 3.9.0](https://www.python.org/)
  - See [requirements.txt](requirements.txt)
- [R 4.0.3](https://www.r-project.org/) (packages all available on cran)
  - ggplot2
  - dplyr
  - tidyr
  - patchwork
  - rmarkdown
  - plotly
- ChromeDriver 88.0.4324.96 (required to use cloudlab/cloudlab.py)
  - The `chromedriver` binary should be put in the toplevel directory of this repo.

## What machines?

All of our experiments require multiple machines. 

The "blessed path" is to run the experiments with [Cloudlab](https://www.cloudlab.us/). We have created a ["profile"](https://www.cloudlab.us/show-profile.php?uuid=84aa948d-5b67-11eb-a9ff-e4434b2381fc) which [`cloudlab/cloudlab.py`](cloudlab/cloudlab.py) can help instantiating and managing (using chromedriver to click things). 
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

Whatever machines you use, they should have Linux kernel 5.4 for Bundler's qdisc kernel module to work (and you of course have to be able and willing to install the kernel module).
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

### cloudlab.py pitflls

- You might have to edit cloudlab.py a bit (near [the top](https://github.com/bundler-project/evaluation/blob/master/cloudlab/cloudlab.py#L38) of the file) to point to your Chrome.
- The sleeps waiting for the page to load might be miscalibrated. We generally just try again.
- `--headless` can be useful to prevent the Chrome window from popping up every time, but when first launching the cluster you don't want this, since you have to select a region. 
- We suggest running a shorter experiment first to get the cluster up before moving on to the paper experiments. The experiment script automatically checks for and installs any missing dependencies on each run, so there is no explicit setup script.

## Running an experiment

The experiment script can be launched from any machine (including one of the experiment hosts). The only requirement is that this machine has password-less ssh access to all of the experiments hosts. It will internally create an ssh shell with each host at the beginning and use this to orchestrate the experiment.

For example, to recreate 

```
python3 eval.py --name fig7 config/fig7.toml (--headless) (--verbose)
```

The `.toml` file controls the experiment. You can add bundle traffic, cross traffic, change parameters, etc. The lists in the `[experiment]` section will be run in all-combinations, so, for example, the currently committed version of Figure 7 will run (10 iterations) * (2 scheduling algs) * (2 algorithms) = 40 experiments. 100k poisson flows at 7/8ths load on a 96Mbps link generally takes around 5 minutes, so this is a 200 minute experiment in total.

The result will get written to `./experiments/fig7/index.html`, which you can open in a web browser. The graphs are noninteractive by default, but if you (optionally) then run 

```
python3 parse_outputs.py experiments/fig7 --bundler_root=`pwd` --interact
```

the graphs will become interactive (panning, zooming, etc). If there are many graphs in the experiment, this can be slow, so it is not the default.

### What from the paper can I reproduce?

By using various config files (`configs/fig*.toml`), you can reproduce the data from Figures 6-13, except 11. Figure 11 involved manual setup (and more machines), so we don't offer a script for it. Code to run the Figure 14 measurements is in [`cloud/`](./cloud), but these experiments are both expensive and prone to random variance since they run on the real Internet. If you want to run these experiments, please get in touch.

### Matching Paper Aesthetics

Generally, the experiment report will plot a CDF, while the paper graphs use boxplots. This is the correspondence from graph to expected data filename in [that repo](https://github.com/bundler-project/writing):

#### Fig 7

|  Info                          |  File                                  |
|  -----                         |  -----                                 |
|  Config file                   |  `config/fig7.toml`                    |
|  Relevant experiment data      |  `experiments/<expname>/fcts.data`     |
|  Paper expected data location  |  `graphs/data/overview benefits.data`  |
|  Paper plotting script         |  `graphs/overview benefits.Rnw`        |

#### Fig 8

|  Info                          |  File                                  |
|  -----                         |  -----                                 |
|  Config file                   |  `config/fig8.toml`                    |
|  Relevant experiment data      |  `experiments/<expname>/<iteration_dir>/downlink.log`,`experiments/<expname>/fcts.data`  |
|  Paper expected data location  |  `big_exp/big_exp_41/bundler.mm`,`big_exp/big_exp_41/fcts.data` |

#### Fig 9

|  Info                          |  File                               |
|  -----                         |  ------                             |
|  Config file                   |  `config/fig9 bundler.toml`,`config/fig9 status quo.toml` (put results in  same experiment dir with   skip existing)  |
|  Relevant experiment data      |  `experiments/<expname>/fcts.data`  |
|  Paper expected data location  |  `graphs/data/vary_inelastic.data`  |
|  Paper plotting script         |  `graphs/inelastic cross.Rnw`       |

#### Fig 10

|  Info                          |  File                             |
|  -----                         |  ------                           |
|  Config file                   |  `config/fig10.toml`              |
|  Relevant experiment data      |  TODO                             |
|  Paper expected data location  |  `graphs/data/vary_elastic.data`  |
|  Paper plotting script         |  `graphs/elastic-cross.Rnw`       |

#### Fig 12

|  Info                          |  File                                      |
|  -----                         |  ------                                    |
|  Config file                   |  `config/fig11.toml`                       |
|  Relevant experiment data      |  `experiments/<expname>/fcts.data`         |
|  Paper expected data location  |  `graphs/data/bundler_cc_alg_choice.data`  |
|  Paper plotting script         |  `graphs/congestion control.Rnw`           |

#### Fig 13

|  Info                          |  File
|  -----                         |  ------
|  Config file                   |  `config/fig13.toml`                |
|  Relevant experiment data      |  `experiments/<expname>/fcts.data`  |
|  Paper expected data location  |  `graphs/proxy.data`                |
|  Paper plotting script         |  `graphs/proxy.Rnw`                 |
