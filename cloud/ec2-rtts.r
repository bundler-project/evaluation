#!/usr/local/bin/Rscript

library(ggplot2)
library(ggrepel)

df <- read.csv("ec2-rtts.data", sep=" ")
df$outlier <- ifelse(df$avgrtt > 1000, sprintf("%.0f", df$avgrtt), as.numeric(NA))

ggplot(df, aes(y=dst, x=avgrtt, colour=with_bundler)) + geom_point() + coord_cartesian(xlim=c(0,1000)) + geom_text_repel(aes(x=1100, label=outlier))
ggsave("ec2-rtts.pdf")
