#!/usr/bin/python3

import subprocess as sh
import os

cmd = "cargo run --bin cloud_dst -- --inbox_queue_type=sfq --inbox_buffer_size=25mbit -r={}"

regions = [
	"us-east-2",
	"us-west-1",
	"us-west-2",
	"ca-central-1",
	"eu-central-1",
	"eu-west-1",
	"eu-west-2",
	#"eu-west-3",
	"eu-north-1",
	"ap-northeast-1",
	#"ap-northeast-2",
	#"ap-northeast-3",
	"ap-southeast-1",
	"ap-southeast-2",
	"ap-south-1",
	#"sa-east-1",
]

for i in range(5):
    for r in regions:
        if not os.path.isdir(f"mit-{r}-{i}"):
            print(r, i)
            c = cmd.format(r)
            print(cmd)
            sh.run(c, shell=True)
            sh.run(f"mkdir mit-{r}-{i}", shell=True)
            sh.run(f"mv nobundler-exp mit-{r}-{i}", shell=True)
            sh.run(f"mv bundler-exp mit-{r}-{i}", shell=True)
        else:
            print('done', r, i)
