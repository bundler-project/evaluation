library(ggplot2)
library(tidyr)

args <- commandArgs(trailingOnly=TRUE)
df <- read.csv(args[1])
df <- gather(df, "measurement", "value", -a, -elapsed)

ggplot(df, aes(x=elapsed, y=value, colour=measurement)) + geom_line() + coord_cartesian(xlim=c(0,120))

ggsave(args[2])
