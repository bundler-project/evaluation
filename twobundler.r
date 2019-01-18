#!/usr/local/bin/Rscript

library(ggplot2)

args <- commandArgs(trailingOnly=TRUE)
df <- read.csv(args[1], sep=" ")
df$Duration <- df$Duration.usec. / 1e6
bw <- 12e6
df$ofct <- (df$Size / bw) + 0.05
df$NormFct <- df$Duration / df$ofct
df$Bundle <- as.factor(df$BundleId)

ggplot(df, aes(x=Duration, colour=Bundle, linetype=Alg)) + 
    stat_ecdf() + 
    scale_x_log10()

ggsave(args[2], width=15, height=3)
