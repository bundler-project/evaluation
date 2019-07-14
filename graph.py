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

    commits_md = os.path.join(experiment_root, 'commits.md')
    with open(commits_md, 'r') as f:
        commits = f.read()

    grid = []
    if rows:
        rows = 'rows=vars({})'.format(rows)
        grid.append(rows)
    if cols:
        cols = 'cols=vars({})'.format(cols)
        grid.append(cols)
    grid_str = ','.join(grid)

    mm_plt_fmt = """
```{{r mm{i}, fig.width=15, fig.align='center', echo=FALSE}}
df_m_{i} <- read.csv("{path}", sep=" ")  # header=FALSE, col.names=c("t", "total", "delay","bundle", "cross"))
df_m_{i} <- df_m_{i} %>% gather("measurement", "value", total, delay, bundle, cross)
plt_m_{i} <- ggplot(df_m_{i}, aes(x=t, y=value, color=measurement)) + geom_line() + ggtitle("{title}")
ggplotly(plt_m_{i})
```"""
    
    g = glob.glob(experiment_root + '/**/mm-graph.tmp', recursive=True)
    mm_plots = "\n".join([
        mm_plt_fmt.format(i=i,path=path,title=path.split(experiment_name)[1])
        for (i,path) in enumerate(g)
    ])



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

### Plots

#### Overview
```{{r plot1, fig.width=15, fig.align='center', echo=FALSE}}
suppressWarnings(suppressMessages(library(ggplot2)))
suppressWarnings(suppressMessages(library(plotly)))
suppressWarnings(suppressMessages(library(dplyr)))
suppressWarnings(suppressMessages(library(tidyr)))

df <- read.csv("{csv}", sep=",", na.strings=c("","none"))
df$curr_q <- df$curr_q * 1000000
df <- df %>% gather("measurement", "value", {fields})
plt <- ggplot(df, aes(x=elapsed, y=value, color=measurement)) + facet_grid({grid_str}) + geom_line() +
    scale_x_continuous(breaks=seq(0, max(df$elapsed), by=2))
ggplotly(plt)
```

#### Mahimahi
{mm_plots}

### Results
```{{r child='{results}'}}
```

### Config
```{{r config, eval=FALSE}}
{config}
```

### Commits
```{{r commits, eval=FALSE}}
{commits}
```

""".format(
        title = experiment_name,
        summary = summary,
        csv = os.path.join(experiment_root, csv_name),
        fields = fields,
        config = config,
        grid_str = grid_str,
        results = results,
        commits = commits,
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
