#!/usr/bin/python3

import subprocess as sh
import os

cmd = "cargo run --bin cloud_src -- --inbox_queue_type=sfq --inbox_buffer_size=25mbit -s={} --recv_ip=169.229.49.104 --recv_iface=eth8 --recv_user=akshay"

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
        dirname = f"{r}-berkeley-{i}"
        if not os.path.isdir(dirname):
            print(r, i)
            c = cmd.format(r)
            print(cmd)
            sh.run(c, shell=True)
            sh.run(f"mkdir {dirname}", shell=True)
            sh.run(f"mv nobundler-exp {dirname}", shell=True)
            sh.run(f"mv bundler-exp {dirname}", shell=True)
        else:
            print('done', r, i)
