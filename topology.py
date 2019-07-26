import agenda
from util import *
from cloudlab.cloudlab import make_cloudlab_topology

def create_ssh_connections(config):
    agenda.task("Creating SSH connections")
    conns = {}
    machines = {}
    args = config['args']
    for (role, details) in config['topology'].items():
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

class MahimahiTopo:
    def __init__(self, config):
        conns, machines = create_ssh_connections(config)
        self.conns = conns
        self.machines = machines

    def setup_routing(self, config):
        """
        sender --> inbox --> (mahimahi --> outbox   )
                             (         \            )
                             (          -> receiver )
        """
        agenda.task("Setting up routing tables")
        machines = self.machines

        agenda.subtask("sender")
        expect(
            machines['sender'].run(
                "ip route del {receiver}; ip route add {receiver} via {inbox} src {sender}".format(
                    sender   = config['topology']['sender']['ifaces'][0]['addr'],
                    receiver = config['topology']['receiver']['ifaces'][0]['addr'],
                    inbox    = config['topology']['inbox']['ifaces'][0]['addr']
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
                    receiver = config['topology']['receiver']['ifaces'][0]['addr'],
                    inbox_send_iface = config['topology']['inbox']['ifaces'][1]['dev']
                ),
                sudo=True
            ),
            "Failed to set forward route at inbox"
        )
        expect(
            machines['inbox'].run(
                "ip route del {sender}; ip route add {sender} dev {inbox_recv_iface}".format(
                    sender = config['topology']['sender']['ifaces'][0]['addr'],
                    inbox_recv_iface = config['topology']['inbox']['ifaces'][0]['dev']
                ),
                sudo=True
            ),
            "Failed to set reverse route at inbox"
        )

        agenda.subtask("outbox")
        expect(
            machines['outbox'].run(
                "ip route del {sender_addr}; ip route add {sender_addr} via {inbox_addr}".format(
                    sender_addr = config['topology']['sender']['ifaces'][0]['addr'],
                    inbox_addr = config['topology']['inbox']['ifaces'][1]['addr']
                ), sudo=True
            ),
            "Failed to set routing tables at outbox"
        )

class CloudlabTopo:
    def __init__(self, config):
        config = make_cloudlab_topology(config)
        conns, machines = create_ssh_connections(config)
        self.conns = conns
        self.machines = machines
        config = bootstrap_cloudlab_topology(config, machines)

    def setup_routing(self, config, machines):
        """
        sender --> inbox --> outbox --> receiver

        Don't bother with the reverse path
        """
        agenda.task("Setting up routing tables")

        agenda.subtask("sender")
        expect(
            machines['sender'].run(
                "ip route del {receiver}; ip route add {receiver} via {inbox} src {sender}".format(
                    sender   = config['topology']['sender']['ifaces'][0]['addr'],
                    receiver = config['topology']['receiver']['ifaces'][0]['addr'],
                    inbox    = config['topology']['inbox']['ifaces'][0]['addr']
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
                "ip route del {receiver}; ip route add {receiver} via {outbox}".format(
                    receiver = config['topology']['receiver']['ifaces'][0]['addr'],
                    outbox = config['topology']['outbox']['ifaces'][0]['addr'],
                ),
                sudo=True
            ),
            "Failed to set forward route at inbox"
        )

        agenda.subtask("outbox")
        expect(
            machines['outbox'].run(
                "sysctl net.ipv4.ip_forward=1",
                sudo=True
            ),
            "Failed to set IP forwarding at inbox"
        )
