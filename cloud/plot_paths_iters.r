#!/usr/local/bin/Rscript

library(ggplot2)
library(patchwork)
library(dplyr)

df <- read.csv("udping_results.out", sep=" ")
bw <- read.csv("bmon_results.out", sep=" ")

bw <- bw %>% group_by(src, dst, iter, Throughput) %>% summarize(mean=mean(bw))

f <- function(x) {
  r <- quantile(x, probs = c(0.01, 0.25, 0.5, 0.75, 0.99))
  names(r) <- c("ymin", "lower", "middle", "upper", "ymax")
  r
}

#ggplot(df, aes(x=rtt, colour=Latency)) + stat_ecdf() + facet_grid(src~dst) + coord_cartesian(xlim=c(0,500)) + 
#    ggplot(bw, aes(x=Throughput, y=mean, fill=Throughput)) + geom_col() + facet_grid(src~dst) + coord_cartesian(ylim=c(0,10e9))
    #geom_violin() + 
ggplot(df, aes(x=factor(port), y = rtt, fill = Latency, colour = Latency)) +
    stat_summary(fun.data = f, geom="boxplot", position="dodge") +
    facet_grid(iter ~ interaction(src, dst)) + 
    coord_cartesian(ylim = c(0, 300)) + 
    ylab("Latency") + xlab("Unique 5-tuple") + 
    theme_minimal() + 
    theme(axis.text.x = element_blank()) +
ggplot(bw, aes(x=Throughput, y=mean, fill=Throughput)) + geom_col() + 
    facet_grid(iter ~ interaction(src, dst)) + 
    coord_cartesian(ylim=c(0,10e9))

ggsave("results.pdf", width=16, height=8)
