import glob
import os
import subprocess

def write_rmd(experiment_root, csv_name, downsample=None, fields="zt, rout, rin, curr_rate, curr_q, elasticity2", rows=None, cols=None):
    experiment_root = os.path.abspath(os.path.expanduser(experiment_root))
    experiment_name = os.path.basename(experiment_root)

    summary = os.path.join(experiment_root, 'details.md')
    results = os.path.join(experiment_root, 'results.md')

    tomls = glob.glob(os.path.join(experiment_root, '*.toml'))
    assert len(tomls) == 1, "there should be exactly 1 .toml (config) in the experiment directory"
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

    def format_title(experiment_name):
        return experiment_name

    mm_plt_fmt = """
**{title}**
```{{r mm{i}, fig.width=15, fig.align='center', echo=FALSE}}
df_m_{i} <- read.csv("{path}", sep=" ")  # header=FALSE, col.names=c("t", "total", "delay","bundle", "cross"))
df_m_{i} <- df_m_{i} %>% gather("measurement", "value", total, delay, bundle, cross)
df_switch <- read.csv("{switch_path}", sep=",")
plt_m_{i} <- ggplot(df_m_{i}, aes(x=t, y=value, color=measurement)) +
    geom_line() +
    geom_rect(data=df_switch, inherit.aes=FALSE, aes(xmin=xmin,xmax=xmax,ymin=0,ymax=max(df_m_{i}$value),fill="xtcp"), alpha=0.2) +
    scale_fill_manual('Mode', values="black", labels=c("xtcp"))
ggplotly(plt_m_{i})
```"""

    g = glob.glob(experiment_root + '/**/mm-graph.tmp', recursive=True)
    mm_plots = "\n".join([
        mm_plt_fmt.format(i=i,path=path,title=format_title(path.split(experiment_name)[1]), switch_path="/".join(path.split("/")[:-1])+"/ccp_switch.parsed")
        for (i,path) in enumerate(g)
    ])

    if len(g) < 3:
        overview_fig_height = len(g) * 4
    elif len(g) < 10:
        overview_fig_height = len(g) * 2
    elif len(g) < 50:
        overview_fig_height = len(g) * 0.5
    else:
        overview_fig_height = 30

    overview = """
```{{r plot1, fig.width=15, fig.height={fig_height}, fig.align='center', echo=FALSE}}
df <- read.csv("{csv}", sep=",", na.strings=c("","none"))
df <- df %>% gather("measurement", "value", {fields})
plt <- ggplot(df, aes(x=elapsed, y=value, color=measurement)) +
    facet_wrap(vars({wrap_str}), labeller = labeller(.default=label_both, .multi_line=FALSE), nrow={nrow}, ncol=1) +
    geom_line() +
    scale_x_continuous(breaks=seq(0, max(df$elapsed), by=5))
    #scale_y_continuous(breaks=seq(0, 1e+09,   by=10000000))
ggplotly(plt)
```
""".format(
        csv = os.path.join(experiment_root, csv_name),
        fields = fields,
        wrap_str = wrap_str,
        nrow = len(g),
        fig_height = overview_fig_height
    )

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

```{{r child='{summary}'}}
```

```{{r, echo=FALSE}}
suppressWarnings(suppressMessages(library(ggplot2)))
suppressWarnings(suppressMessages(library(plotly)))
suppressWarnings(suppressMessages(library(dplyr)))
suppressWarnings(suppressMessages(library(tidyr)))
```

### Plots

Note: curr_q and elasticity2 have much smaller ranges. To see them on this plot,
turn off (click on) the other measurements in the key to the right and then click
on the "autoscale" button. You can hover to see exact values.

#### Overview
{overview}

#### Mahimahi
{mm_plots}

### Results
```{{r child='{results}'}}
```

### Config
```{{r config, eval=FALSE}}
{config}
```
""".format(
        title = experiment_name,
        summary = summary,
        config = config,
        grid_str = grid_str,
        results = results,
        overview = overview,
        mm_plots = mm_plots,
    )

    rmd = os.path.join(experiment_root, 'exp.Rmd')
    html = os.path.join(experiment_root, 'index.html')
    with open(rmd, 'w') as f:
        f.write(contents)

    print("> Rendering Rmd as HTML...")
    try:
        out = subprocess.check_output("R -e rmarkdown::render\"('{}', output_file='{}')\"".format(
            rmd,
            html
        ), shell=True)
    except subprocess.CalledProcessError as e:
        print("!!! Failed to render Rmd as HTML:")
        print(e.output.decode())
