import os
import agenda
import time
from util import *

def get_ccp_alg_dir(config, alg):
    alg_config = config['ccp'][alg]
    dir_name = alg_config['repo'].split("/")[-1].split(".git")[0]
    alg_dir = os.path.join(config['ccp_dir'], dir_name)
    return alg_dir

def get_ccp_binary_path(config, alg):
    alg_config = config['ccp'][alg]
    alg_dir = get_ccp_alg_dir(config, alg)

    if alg_config['language'] == 'rust':
        return os.path.join(alg_dir, alg_config['target'])
    elif alg_config['language'] == 'python':
        return "python {}".format(os.path.join(alg_dir, alg_config['target']))
    else:
        fatal_warn("Unknown language for {}: {}".format(alg, alg_config['language']))

def check_ccp_alg(config, node):
    for (alg, details) in config['ccp'].items():
        agenda.subtask(alg)
        alg_dir = get_ccp_alg_dir(config, alg)
        if not node.file_exists(alg_dir):
            expect(
                node.run("git clone {} {}".format(details['repo'], alg_dir)),
                "node failed to clone {}".format(alg)
            )
        branch = node.run("git -C {} rev-parse --abbrev-ref HEAD".format(alg_dir)).stdout.strip()
        if branch != details['branch']:
            expect(
                node.run("git -C {} checkout {}".format(alg_dir, details['branch'])),
                "node failed to checkout branch {} of {}".format(details['branch'], alg)
            )

        commit = node.run("git -C {} rev-parse HEAD".format(alg_dir)).stdout.strip()
        should_recompile = False
        if not details['commit'] in commit:
            pull = expect(
                node.run("git -C {} pull".format(alg_dir)),
                "node failed to pull latest code for {}".format(alg)
            ).stdout.strip()
            if details['commit'] == 'latest':
                if not 'Already up-to-date.' in pull:
                    should_recompile = True
            else:
                expect(
                    node.run("git -C {} checkout {}".format(alg_dir, details['commit'])),
                    "node failed to checkout commit {} of {}".format(details['commit'], alg)
                )
                should_recompile = True

        if details['language'] == 'rust':
            ccp_binary = get_ccp_binary_path(config, alg)
            if not node.file_exists(ccp_binary):
                print("could not find ccp binary")
                should_recompile = True

            if should_recompile:
                new_commit = node.run("git -C {} rev-parse HEAD".format(alg_dir)).stdout.strip()
                if commit.strip() != new_commit.strip():
                    print("updated {} -> {}".format(alg, commit[:6], new_commit[:6]))

                agenda.subtask("compiling ccp algorithm")
                expect(
                    node.run("~/.cargo/bin/cargo build {}".format('--release' if 'release' in ccp_binary else ''), wd=alg_dir),
                    "node failed to build {}".format(alg)
                )

def start_ccp(config, inbox, alg):
    if config['args'].verbose:
        agenda.subtask("Starting ccp")

    ccp_binary = get_ccp_binary_path(config, alg['name'])
    ccp_binary_name = ccp_binary.split('/')[-1]
    ccp_out = os.path.join(config['iteration_dir'], "ccp.log")

    alg_name = alg['name']
    args = list(config['ccp'][alg_name]['args'].items())
    args += [(k,alg[k]) for k in alg]
    alg_args = [f"--{arg}={val}" for arg, val in args if val != "false" and arg != "name"]

    expect(inbox.run(
        "{} --ipc=unix {}".format(
            ccp_binary,
            " ".join(alg_args)
        ),
        sudo=True,
        background=True,
        stdout=ccp_out,
        stderr=ccp_out,
    ), "Failed to start ccp")

    if not config['args'].dry_run:
        time.sleep(1)
    inbox.check_proc(ccp_binary_name, ccp_out)
    inbox.check_file('starting CCP', ccp_out)

    config['iteration_outputs'].append((inbox, ccp_out))

    return ccp_out
