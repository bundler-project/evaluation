import glob
import os
import subprocess
import agenda

def write_rmd(experiment_root, csv_name, num_ccp, downsample=None, interact=False, fields="zt, rout, rin, curr_rate, curr_q, elasticity2", rows=None, cols=None, **kwargs):
    experiment_root = os.path.abspath(os.path.expanduser(experiment_root))
    experiment_name = os.path.basename(experiment_root)

    tomls = glob.glob(os.path.join(experiment_root, '*.toml'))
    assert len(tomls) == 1, f"there should be exactly 1 .toml (config) in the experiment directory: {experiment_root} -> {tomls}"
    with open(tomls[0], 'r') as f:
        config = f.read()

    wrap_str = rows

    grid = []
    if rows:
        rows = 'rows=vars({})'.format(rows)
        grid.append(rows)
    if cols:
        cols = 'cols=vars({})'.format(cols)
        grid.append(cols)
    grid_str = ','.join(grid)

    if interact:
        interact_str = ""
        static_str = "#"
    else:
        interact_str = "#"
        static_str = ""

    def format_title(experiment_name):
        return experiment_name

    mm_plt_fmt = """
**{title}**
```{{r mm{i}, fig.width=15, fig.align='center', echo=FALSE}}
df_m_{i} <- read.csv("{path}", sep=" ")  # header=FALSE, col.names=c("t", "total", "delay","bundle", "cross"))
df_m_{i} <- df_m_{i} %>% gather("measurement", "value", total, delay, bundle, cross)
{remove}df_switch_{i} <- read.csv("{switch_path}", sep=",")
plt_m_{i} <- ggplot(df_m_{i}, aes(x=t, y=value, color=measurement)) +
    geom_line() +
    {remove}geom_rect(data=df_switch_{i}, inherit.aes=FALSE, aes(xmin=xmin,xmax=xmax,ymin=0,ymax=max(df_m_{i}$value),fill="xtcp"), alpha=0.2) +
    scale_fill_manual('Mode', values="black", labels=c("xtcp"))
{interact_str}ggplotly(plt_m_{i})
{static_str}plt_m_{i}
```"""

    g = glob.glob(experiment_root + '/**/mm-graph.tmp', recursive=True)
    mm_plots = []
    for (i,path) in enumerate(g):
        switch_path = "/".join(path.split("/")[:-1])+"/ccp_switch.parsed"
        try:
            with open(switch_path) as f:
                if sum(1 for _ in f) < 2:
                    raise Exception("") # goto except
            remove = ""
        except:
            remove = "#"
        mm_plots.append(
            mm_plt_fmt.format(
                i=i,
                path=path,
                title=format_title(path.split(experiment_name)[1]),
                switch_path=switch_path,
                remove=remove,
                interact_str=interact_str,
                static_str=static_str,
            )
        )
    mm_plots_str = "\n".join(mm_plots)


    if num_ccp == 0:
        nimbus_plots = ""
    else:
        if len(g) < 3:
            nimbus_fig_height = len(g) * 4
        elif len(g) < 10:
            nimbus_fig_height = len(g) * 2
        elif len(g) < 50:
            nimbus_fig_height = len(g) * 1
        else:
            nimbus_fig_height = 30
        nimbus_fig_height = max(nimbus_fig_height, 15)

        nimbus_plots = """
#### Nimbus

```{{r plot1, fig.width=15, fig.height={fig_height}, fig.align='center', echo=FALSE}}
df <- read.csv("{csv}", sep=",", na.strings=c("","none"))
if (nrow(df) == 0) {{
    print("no ccp output")
}} else {{
df <- df %>% gather("measurement", "value", {fields})
plt <- ggplot(df, aes(x=elapsed, y=value, color=measurement)) +
    geom_line() +
    facet_wrap(~interaction(sch, alg, rate, rtt, bundle, cross, seed), labeller = labeller(.default=label_both, .multi_line=FALSE), nrow={nrow}, ncol=1) +
    scale_x_continuous(breaks=seq(0, max(df$elapsed), by=5))

{interact_str}ggplotly(plt)
{static_str}plt
}}
```
""".format(
            csv = os.path.join(experiment_root, csv_name),
            fields = fields,
            wrap_str_check = "1" if wrap_str is not None else "0",
            wrap_str = wrap_str,
            nrow = len(g),
            fig_height = nimbus_fig_height,
            interact_str=interact_str,
            static_str=static_str,
        )


    fct_path = os.path.join(experiment_root, 'fcts.data')
    if os.path.isfile(fct_path):
        fct_plots = """
#### Flow Completion Times

```{{r fcts, fig.width=15, fig.height=6, fig.align='center', echo=FALSE}}
df_fct <- read.csv("{csv}", sep=" ")
df_fct$Duration <- df_fct$Duration.usec. / 1e6
bw <- 12e6 # TODO make this configurable
df_fct$ofct <- (df_fct$Size / bw) + 0.05
df_fct$NormFct <- df_fct$Duration / df_fct$ofct
df_fct$scheme <- paste(df_fct$sch, "_", df_fct$alg, sep="")
fct_plt <- ggplot(df_fct, aes(x=NormFct, colour=scheme)) + stat_ecdf() + scale_x_log10()
fct_plt
```""".format(
            csv = fct_path,
        )
    else:
        fct_plots = ""

    contents = """
---
title: "{title}"
output: html_document
---
<style type="text/css">
.main-container {{
  max-width: 1400px;
  margin-left: auto;
  margin-right: auto;
}}
</style>

```{{r, echo=FALSE}}
suppressWarnings(suppressMessages(library(ggplot2)))
suppressWarnings(suppressMessages(library(plotly)))
suppressWarnings(suppressMessages(library(dplyr)))
suppressWarnings(suppressMessages(library(tidyr)))
```

### Overall

{fct_plots}

### Per-Experiment

{nimbus_plots}

#### Mahimahi
{mm_plots}

### Config
```{{r config, eval=FALSE}}
{config}
```
""".format(
        title = experiment_name,
        config = config,
        grid_str = grid_str,
        nimbus_plots = nimbus_plots,
        fct_plots = fct_plots,
        mm_plots = mm_plots_str,
    )

    rmd = os.path.join(experiment_root, 'exp.Rmd')
    html = os.path.join(experiment_root, 'index.html')
    with open(rmd, 'w') as f:
        f.write(contents)

    agenda.task("Rendering Rmd as HTML...")
    try:
        out = subprocess.check_output("R -e rmarkdown::render\"('{}', output_file='{}')\"".format(
            rmd,
            html
        ), shell=True)
    except subprocess.CalledProcessError as e:
        agenda.failure("Failed to render Rmd as HTML:")
        print(e.output.decode())
