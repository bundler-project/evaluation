import agenda
import re
from util import *
from cloudlab.cloudlab import make_cloudlab_topology
from traffic import *

def create_ssh_connections(config):
    agenda.task("Creating SSH connections")
    conns = {}
    machines = {}
    args = config['args']
    for (role, details) in [(r, d) for r, d in config['topology'].items() if r in ("sender", "inbox", "outbox", "receiver")]:
        hostname = details['name']
        is_self = 'self' in details and details['self']
        if is_self:
            agenda.subtask(hostname)
            conns[hostname] = ConnectionWrapper('localhost', nickname=role, dry=args.dry_run, verbose=args.verbose, interact=args.interact)
            config['self'] = conns[hostname]
        elif not hostname in conns:
            agenda.subtask(hostname)
            user = None
            port = None
            if 'user' in details:
                user = details['user']
            if 'port' in details:
                port = details['port']
            conns[hostname] = ConnectionWrapper(hostname, nickname=role, user=user, port=port, dry=args.dry_run, verbose=args.verbose, interact=args.interact)
        machines[role] = conns[hostname]

    return (conns, machines)

def get_inbox_binary(config):
   return os.path.join(config['structure']['bundler_root'], "bundler/target/debug/inbox")

def get_outbox_binary(config):
   return os.path.join(config['structure']['bundler_root'], "bundler/target/debug/outbox")

def outbox_output_location(config):
    return os.path.join(config['iteration_dir'], 'outbox.log')

def get_iface(cfg, node_key):
    ifaces = cfg['topology'][node_key]['ifaces']
    for i in ifaces:
        if i['dev'] != 'lo':
            return i
    raise Exception(f"no valid interface found on {node_key}")

ip_addr_rgx = re.compile(r"\w+:\W*(?P<dev>\w+).*inet (?P<addr>[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)")
# populate interface names and ips
def get_interfaces(config, machines):
    agenda.section("Get node interfaces")
    for m in machines:
        if m == 'self' or 'ifaces' in config['topology'][m]:
            agenda.subtask(f"{machines[m].addr}: skipping get_interfaces")
            continue
        agenda.task(machines[m].addr)
        conn = machines[m]
        ifaces_raw = conn.run("ip -4 -o addr").stdout.strip().split("\n")
        ifaces = [ip_addr_rgx.match(i) for i in ifaces_raw]
        ifaces = [i.groupdict() for i in ifaces if i is not None and i["dev"] != "lo"]
        if len(ifaces) == 0:
            raise Exception(f"Could not find ifaces on {conn.addr}: {ifaces_raw}")
        config['topology'][m]['ifaces'] = ifaces

    return config

# clone the bundler repository
def init_repo(config, machines):
    agenda.section("Init nodes")
    root = config['structure']['bundler_root']
    clone = f'git clone --recurse-submodules https://github.com/bundler-project/evaluation {root}'

    for m in machines:
        if m == 'self':
            continue
        agenda.task(machines[m].addr)
        agenda.subtask("cloning eval repo")
        machines[m].verbose = True
        if not machines[m].file_exists(root):
            res = machines[m].run(clone)
        else:
            # previously cloned, update to latest commit
            machines[m].run(f"cd {root} && git pull origin cloudlab")
            machines[m].run(f"cd {root} && git submodule update --init --recursive")
        agenda.subtask("compiling experiment tools")
        machines[m].run(f"make -C {root}")
        machines[m].verbose = False

def bootstrap_topology(config, machines):
    config = get_interfaces(config, machines)
    init_repo(config, machines)
    return config

class MahimahiTopo:
    MahimahiConfig = namedtuple('MahimahiConfig', ['rtt', 'rate', 'ecmp', 'sfq', 'num_bdp'])

    def __init__(self, config):
        conns, machines = create_ssh_connections(config)
        self.conns = conns
        self.machines = machines
        self.config = config
        self.config = bootstrap_topology(config, machines)

    def setup_routing(self, config):
        """
        sender --> inbox --> (mahimahi --> outbox   )
                             (         \            )
                             (          -> receiver )
        """
        agenda.task("Setting up routing tables")
        machines = self.machines

        initcwnd = 10
        if 'initcwnd' in config['topology']['sender']:
            initcwnd = config['topology']['sender']['initcwnd']

        agenda.subtask("sender")
        expect(
            machines['sender'].run(
                "ip route del {receiver}; ip route add {receiver} via {inbox} src {sender} initcwnd {initcwnd}".format(
                    sender   = get_iface(config, 'sender')['addr'],
                    receiver = get_iface(config, 'receiver')['addr'],
                    inbox    = get_iface(config, 'inbox')['addr'],
                    initcwnd = initcwnd
                ),
                sudo=True
            ),
            "Failed to set routing tables at sender"
        )

        agenda.subtask("inbox")
        expect(
            machines['inbox'].run(
                "sysctl net.ipv4.ip_forward=1",
                sudo=True
            ),
            "Failed to set IP forwarding at inbox"
        )
        expect(
            machines['inbox'].run(
                "ip route del {receiver}; ip route add {receiver} dev {inbox_send_iface}".format(
                    receiver = get_iface(config, 'receiver')['addr'],
                    inbox_send_iface = get_iface(config, 'inbox')['dev']
                ),
                sudo=True
            ),
            "Failed to set forward route at inbox"
        )
        expect(
            machines['inbox'].run(
                "ip route del {sender}; ip route add {sender} dev {inbox_recv_iface}".format(
                    sender = get_iface(config, 'sender')['addr'],
                    inbox_recv_iface = get_iface(config, 'inbox')['dev']
                ),
                sudo=True
            ),
            "Failed to set reverse route at inbox"
        )

        agenda.subtask("outbox")
        expect(
            machines['outbox'].run(
                "ip route del {sender_addr}; ip route add {sender_addr} via {inbox_addr}".format(
                    sender_addr = get_iface(config, 'sender')['addr'],
                    inbox_addr = get_iface(config, 'inbox')['addr']
                ), sudo=True
            ),
            "Failed to set routing tables at outbox"
        )

        expect(
            machines['outbox'].run(
                "sysctl net.ipv4.ip_forward=1",
                sudo=True
            ),
            "Failed to set IP forwarding at outbox"
        )

    def run_traffic(self, config, exp, bundle_traffic, cross_traffic):
        machines = self.machines
        mahimahiCfg = MahimahiTopo.MahimahiConfig(
            rate=exp.rate,
            rtt=exp.rtt,
            num_bdp=exp.bdp,
            sfq=(exp.alg['name'] == "nobundler" and exp.sch == "sfq"),
            ecmp=None
        )

        bundle_out = list(start_multiple_server(config, machines['sender'], bundle_traffic))
        cross_out = list(start_multiple_server(config, machines['receiver'], cross_traffic))

        bundle_client = list(start_multiple_client(
            config,
            machines['receiver'],
            bundle_traffic,
            True,
            execute=False,
        ))
        cross_client = list(start_multiple_client(
            config,
            machines['receiver'],
            cross_traffic,
            False,
            execute=False,
        ))
        return self.start_in_mahimahi(
            config,
            machines['receiver'],
            emulation_env=mahimahiCfg,
            bundle_client=bundle_client,
            cross_client=cross_client,
            nobundler = (exp.alg['name'] == "nobundler"),
        )

    def start_inbox(self, qtype, q_buffer_size):
        config = self.config
        inbox = self.machines['inbox']

        agenda.subtask("Starting inbox")

        inbox_out = os.path.join(config['iteration_dir'], "inbox.log")
        res = inbox.run(
            "{path} --iface={iface} --port={port} --sample_rate={sample} --qtype={qtype} --buffer={buf}".format(
                path=get_inbox_binary(config),
                iface=get_iface(config, 'inbox')['dev'],
                port=config['topology']['inbox']['listen_port'],
                sample=config['parameters']['initial_sample_rate'],
                qtype=qtype,
                buf=q_buffer_size
            ),
            sudo=True,
            background=True,
            stdout=inbox_out,
            stderr=inbox_out,
        )

        if not config['args'].dry_run:
            time.sleep(10)
        inbox.check_proc('inbox', inbox_out)
        inbox.check_file('Wait for CCP to install datapath program', inbox_out)

        config['iteration_outputs'].append((inbox, inbox_out))
        return inbox_out

    def start_outbox(self, config):
        outbox_output = outbox_output_location(config)
        outbox_cmd = "sudo {path} --filter \"{pcap_filter}\" --iface {iface} --inbox {inbox_addr} --sample_rate {sample_rate} --no_ethernet".format(
            path=get_outbox_binary(config),
            pcap_filter="src portrange {}-{}".format(config['parameters']['bg_port_start'], config['parameters']['bg_port_end']),
            iface="ingress",
            inbox_addr='{}:{}'.format(
                get_iface(config, 'inbox')['addr'],
                config['topology']['inbox']['listen_port'],
            ),
            sample_rate=config['parameters']['initial_sample_rate'],
        )
        outbox_run = f"{outbox_cmd} > {outbox_output} 2> {outbox_output} &"
        return outbox_run

    def start_in_mahimahi(self, config, outbox, emulation_env, bundle_client, cross_client, nobundler):
        mm_inner = io.StringIO()
        mm_inner.write("""#!/bin/bash
set -x

{outbox_run}

sleep 1

pids=()
{cross_clients}
{bundle_clients}

for pid in ${{pids[*]}}; do
    wait $pid
done
    """.format(
            outbox_run=self.start_outbox(config) if not nobundler else '',
            cross_clients='\n'.join(["({}) &\npids+=($!)".format(c) for c in cross_client]),
            bundle_clients='\n'.join(["({}) &\npids+=($!)".format(c) for c in bundle_client]),
        ))

        mm_inner_path = os.path.join(config['iteration_dir'], 'mm_inner.sh')
        outbox.put(mm_inner, remote=mm_inner_path)
        outbox.run("chmod +x {}".format(mm_inner_path))

        agenda.subtask("Starting traffic in emulation env ({})".format(emulation_env))
        queue_args = ''
        if emulation_env.num_bdp != 'inf':
            bdp = int((emulation_env.rate * 1000000.00 / 8.0) * (emulation_env.rtt / 1000.0) / 1500.0)
            buf_pkts = emulation_env.num_bdp * bdp
            if emulation_env.ecmp:
                queue_args = f'--downlink-queue="ecmp" --uplink-queue="droptail" \
                    --downlink-queue-args="packets={buf_pkts},\
                    queues={emulation_env.ecmp.queues},\
                    mean_jitter={emulation_env.ecmp.mean_jitter},\
                    nonworkconserving={(1 if emulation_env.ecmp.nonworkconserving else 0)}"\
                    --uplink-queue-args="packets={buf_pkts}"'
            elif emulation_env.sfq:
                # !!!
                # NOTE hardcoded at 500 queues
                # !!!
                queue_args = f'--downlink-queue="akshayfq"\
                    --downlink-queue-args="queues={500},packets={buf_pkts}"\
                    --uplink-queue="droptail"\
                    --uplink-queue-args="packets={buf_pkts}"'
            else:
                downlink = config['parameters']['fifo_downlink']
                dlq = downlink['queue']
                if 'args' in downlink:
                    dlq_args = downlink['args']
                else:
                    dlq_args = f"packets={buf_pkts}"
                uplink = config['parameters']['fifo_uplink']
                ulq = uplink['queue']
                if 'args' in uplink:
                    ulq_args = uplink['args']
                else:
                    ulq_args = f"packets={buf_pkts}"
                queue_args = f'--downlink-queue="{dlq}"\
                    --uplink-queue="{ulq}"\
                    --downlink-queue-args="{dlq_args}"\
                    --uplink-queue-args="{ulq_args}"'
        if config['args'].dry_run:
            print("cat mm_inner.sh\n{}".format(mm_inner.getvalue()))
        expect(
            outbox.run(
                "mm-delay {delay} mm-link --cbr {rate}M {rate}M {queue_args} --downlink-log=downlink.log {inner}".format(
                    delay=int(emulation_env.rtt / 2),
                    rate=emulation_env.rate,
                    queue_args=queue_args,
                    inner=mm_inner_path,
                ),
                wd=config['iteration_dir'],
            ),
            "Failed to start mahimahi shell on receiver"
        )
        config['iteration_outputs'].append((outbox, os.path.join(config['iteration_dir'], 'downlink.log')))
        if not nobundler:
            config['iteration_outputs'].append((outbox, outbox_output_location(config)))
        return config
