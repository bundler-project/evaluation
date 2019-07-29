import sys
import agenda
from fabric import Connection, Result
from termcolor import colored
import os

###################################################################################################
# Helpers
###################################################################################################
class FakeResult(object):
    def __init__(self):
        self.exited = 0
        self.stdout = '(dryrun)'

class ConnectionWrapper(Connection):
    def __init__(self, addr, nickname, user=None, port=None, verbose=True, dry=False, interact=False):
        super().__init__(
            addr,
            forward_agent=True,
            user=user,
            port=port,
        )
        self.addr = addr
        self.nickname = nickname
        self.verbose = verbose
        self.dry = dry
        self.interact = interact

        # Start the ssh connection
        super().open()

    """
    Run a command on the remote machine

    verbose    : if true, print the command before running it, and any output it produces
                 (if not redirected)
                 if false, capture anything produced in stdout and save in result (res.stdout)
    background : if true, start the process in the background via nohup.
                 if output is not directed to a file or pty=True, this won't work
    stdin      : string of filename for stdin (default /dev/stdin as expected)
    stdout     : ""
    stderr     : ""
    ignore_out : shortcut to set stdout and stderr to /dev/null
    wd         : cd into this directory before running the given command
    sudo       : if true, execute this command with sudo (done AFTER changing to wd)

    returns result struct
        .exited = return code
        .stdout = stdout string (if not redirected to a file)
        .stderr = stderr string (if not redirected to a file)
    """
    def run(self, cmd, *args, stdin="/dev/stdin", stdout="/dev/stdout", stderr="/dev/stderr", ignore_out=False, wd=None, sudo=False, background=False, pty=True, **kwargs):
        self.verbose = True
        # Prepare command string
        pre = ""
        if wd:
            pre += "cd {} && ".format(wd)
        if background:
            pre += "screen -d -m "
        #escape the strings
        cmd = cmd.replace("\"", "\\\"")
        pre += "bash -c \""
        if sudo:
            pre += "sudo "
        if ignore_out:
            stdin="/dev/null"
            stdout="/dev/null"
            stderr="/dev/null"
        if background:
            stdin="/dev/null"
        full_cmd = "{pre}{cmd} > {stdout} 2> {stderr} < {stdin}".format(
            pre=pre,
            cmd=cmd,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
        )

        full_cmd += "\""

        # Prepare arguments for invoke/fabric
        if background:
            pty=False

        # Print command if necessary
        if self.dry or self.verbose:
            print("[{}]{} {}".format(self.nickname.ljust(10), " (bg) " if background else "      ", full_cmd))

        # Finally actually run it
        if self.interact:
            input("")

        if not self.dry:
            return super().run(full_cmd, *args, hide=(not self.verbose), warn=True, pty=pty, **kwargs)
        else:
            return FakeResult()

    def file_exists(self, fname):
        res = self.run("ls {}".format(fname))
        return res.exited == 0

    def prog_exists(self, prog):
        res = self.run("which {}".format(prog))
        return res.exited == 0

    def check_proc(self, proc_name, proc_out):
        res = self.run("pgrep {}".format(proc_name))
        if res.exited != 0:
            fatal_warn('failed to find running process with name \"{}\" on {}'.format(proc_name, self.addr), exit=False)
            res = self.run('tail {}'.format(proc_out))
            if not self.verbose and res.exited == 0:
                print(res.command)
                print(res.stdout)
            sys.exit(1)


    def check_file(self, grep, where):
        res = self.run("grep \"{}\" {}".format(grep, where))
        if res.exited != 0:
            fatal_warn("Unable to find search string (\"{}\") in process output file {}".format(
                grep,
                where
            ), exit=False)
            res = self.run('tail {}'.format(where))
            if not self.verbose and res.exited == 0:
                print(res.command)
                print(res.stdout)
            sys.exit(1)

    def put(self, local_file, remote=None, preserve_mode=True):
        if remote and remote[0] == "~":
            remote = remote[2:]
        if self.dry or self.verbose:
            print("[{}] scp localhost:{} -> {}:{}".format(
                self.addr,
                local_file,
                self.addr,
                remote
            ))

        if self.interact:
            input("")

        if not self.dry:
            return super().put(local_file, remote, preserve_mode)
        else:
            return FakeResult()

    def get(self, remote_file, local=None, preserve_mode=True):
        if self.dry or self.verbose:
            print("[{}] scp {}:{} -> localhost:{}".format(
                self.addr,
                self.addr,
                remote_file,
                local
            ))

        if self.interact:
            input("")

        if not self.dry:
            return super().get(remote_file, local, preserve_mode)
        else:
            return FakeResult()

def update_sysctl(conns, config):
    if 'sysctl' in config:
        agenda.task("Updating sysctl")

        for (addr, conn) in conns.items():
            if config['args'].verbose or config['args'].dry_run:
                agenda.subtask(addr)

            for k in config['sysctl']:
                v = config['sysctl'][k]
                expect(
                    conn.run("sysctl -w {k}=\"{v}\"".format(k=k,v=v), sudo=True),
                    "Failed to set {k} on {addr}".format(k=k, addr=addr)
                )

def disable_tcp_offloads(config, machines):
    agenda.task("Turn off TSO, GSO, and GRO")
    for node in ['sender', 'inbox', 'outbox', 'receiver']:
        agenda.subtask(node)
        for i,iface in enumerate(config['topology'][node]['ifaces']):
            expect(
                machines[node].run(
                    "ethtool -K {} tso off gso off gro off".format(
                        config['topology'][node]['ifaces'][i]['dev']
                    ),
                    sudo=True
                ),
                "Failed to turn off optimizations"
            )

def start_tcpprobe(config, sender):
    if config['args'].verbose:
        agenda.subtask("Start tcpprobe")
    if not sender.file_exists("/proc/net/tcpprobe"):
        fatal_warn("Could not find tcpprobe on sender. Make sure the kernel module is loaded.")

    expect(
        sender.run("dd if=/dev/null of=/proc/net/tcpprobe bs=256", sudo=True, background=True),
        "Sender failed to clear tcpprobe buffer"
    )

    tcpprobe_out = os.path.join(config['iteration_dir'], 'tcpprobe.log')
    expect(
        sender.run(
            "dd if=/proc/net/tcpprobe of={} bs=256".format(tcpprobe_out),
            sudo=True,
            background=True
        ),
        "Sender failed to start tcpprobe"
    )

    config['iteration_outputs'].append((sender, tcpprobe_out))

    return tcpprobe_out

def kill_leftover_procs(config, conns, verbose=False):
    agenda.subtask("Kill leftover experiment processes")
    for (addr, conn) in conns.items():
        proc_regex = "|".join(["inbox", "outbox", *config['ccp'].keys(), "iperf", "etgClient", "etgServer", "ccp_const"])
        conn.run(
            "pkill -9 \"({search})\"".format(
                search=proc_regex
            ),
            sudo=True
        )
        res = conn.run(
            "pgrep -c \"({search})\"".format(
                search=proc_regex
            ),
            sudo=True
        )
        if not res.exited and not config['args'].dry_run:
            fatal_warn("Failed to kill all procs on {}.".format(conn.addr))

    # True = some processes remain, therefore there *are* zombies, so we return false
    return (not res.exited)

def expect(res, msg):
    if res and res.exited:
        agenda.subfailure(msg)
        print("exit code: {}\ncommand: {}\nstdout: {}\nstderr: {}".format(
            res.exited,
            res.command,
            res.stdout,
            res.stderr
        ))
    return res

def warn(msg, exit=True):
    print()
    for m in msg.split("\n"):
        print(colored("  -> {}".format(m), 'yellow', attrs=['bold']))
    print()
    if exit:
        sys.exit(1)

def fatal_warn(msg, exit=True):
    print()
    for m in msg.split("\n"):
        agenda.subfailure(m)
    print()
    if exit:
        sys.exit(1)

def fatal_error(msg, exit=True):
    print()
    agenda.failure(msg)
    print()
    if exit:
        sys.exit(1)
