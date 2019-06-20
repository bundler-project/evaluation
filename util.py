import sys
import agenda
from fabric import Connection, Result
from termcolor import colored

###################################################################################################
# Helpers
###################################################################################################
class FakeResult(object):
    def __init__(self):
        self.exited = 0
        self.stdout = '(dryrun)'

class ConnectionWrapper(Connection):
    def __init__(self, addr, nickname, verbose=False, dry=False, interact=False):
        super().__init__(addr)
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
        # Prepare command string
        pre = ""
        if wd:
            pre += "cd {} && ".format(wd)
        if sudo:
            pre += "sudo "
            if ';' in cmd:
                pre += "bash -c \""
        if background:
            pre += "nohup "
        if ignore_out:
            stdin="/dev/null"
            stdout="/dev/null"
            stderr="/dev/null"
        full_cmd = "{pre}{cmd} > {stdout} 2> {stderr} < {stdin} {bg}".format(
            pre=pre,
            cmd=cmd,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            bg=("&" if background else "")
        )
        if sudo and ';' in cmd:
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
