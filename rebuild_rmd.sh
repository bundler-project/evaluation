#!/bin/sh

cd $1
R -e rmarkdown::render"('exp.Rmd', output_file='index.html')"
cd -
