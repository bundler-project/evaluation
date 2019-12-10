#!/usr/local/bin/Rscript

library(ggplot2)
library(patchwork)
library(dplyr)

df <- read.csv("udping_results.out", sep=" ")
bw <- read.csv("bmon_results.out", sep=" ")

bw <- bw %>% group_by(src, dst, Throughput) %>% summarize(mean=mean(bw))

ggplot(df, aes(x=rtt, colour=Latency)) + stat_ecdf() + facet_grid(src~dst) + coord_cartesian(xlim=c(0,500)) + 
    ggplot(bw, aes(x=Throughput, y=mean, fill=Throughput)) + geom_col() + facet_grid(src~dst) + coord_cartesian(ylim=c(0,10e9))

ggsave("results.pdf", width=16, height=8)