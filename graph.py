import glob
import os
import subprocess

def write_rmd(experiment_root, csv_name):
    experiment_name = os.path.basename(experiment_root)

    summary = os.path.join(experiment_root, 'details.md')
    results = os.path.join(experiment_root, 'results.md')

    tomls = glob.glob(os.path.join(experiment_root, '*.toml'))
    assert len(tomls) == 1, "there should be exactly 1 .toml (config) in the experiment directory"
    with open(tomls[0], 'r') as f:
        config = f.read()

    fields = "zt, rout, rin, curr_rate"
    rows = 'cross'
    cols = None

    grid = []
    if rows:
        rows = 'rows=vars({})'.format(rows)
        grid.append(rows)
    if cols:
        cols = 'cols=vars({})'.format(cols)
        grid.append(cols)
    grid_str = ','.join(grid)


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

## Summary
```{{r child='{summary}'}}
```

## Plots
```{{r plot1, fig.width=15, fig.align='center', echo=FALSE}}
suppressWarnings(suppressMessages(library(ggplot2)))
suppressWarnings(suppressMessages(library(plotly)))
suppressWarnings(suppressMessages(library(dplyr)))
suppressWarnings(suppressMessages(library(tidyr)))

df <- read.csv("{csv}", sep=",", na.strings=c("","none"))
df <- df %>% gather("measurement", "value", {fields})
plt <- ggplot(df, aes(x=elapsed, y=value, color=measurement)) + facet_grid({grid_str}) + geom_line()
ggplotly(plt)
```

## Config
```{{r code, eval=FALSE}}
{config}
```

## Results
```{{r child='{results}'}}
```
""".format(
        title = experiment_name,
        summary = summary,
        csv = os.path.join(experiment_root, csv_name),
        fields = fields,
        config = config,
        grid_str = grid_str,
        results = results
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
        print(e.output)
