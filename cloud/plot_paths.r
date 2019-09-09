#!/usr/local/bin/Rscript

library(ggplot2)
library(patchwork)

df <- read.csv("udping_results.out", sep=" ")
bw <- read.csv("bmon_results.out", sep=" ")

ggplot(df, aes(x=rtt, colour=Latency)) + stat_ecdf() + facet_grid(src~dst) + coord_cartesian(xlim=c(0,500)) + 
    ggplot(bw, aes(x=bw, colour=Throughput)) + stat_ecdf() + facet_grid(src~dst)

ggsave("results.pdf", width=16, height=8)
