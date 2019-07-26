from collections import namedtuple
import agenda
import itertools
import random
import toml

def read_config(args):
    agenda.task("Reading config file: {}".format(args.config))
    with open(args.config) as f:
        try:
            config = toml.loads(f.read())
            config['experiment_name'] = args.name #args.config.split(".toml")[0]
        except Exception as e:
            print(e)
            fatal_error("Failed to parse config")
            raise e
        check_config(config)
    return config

def check_config(config):
    agenda.task("Checking config file")
    topology = config['topology']
    if 'cloudlab' not in topology:
        nodes = ['sender', 'inbox', 'outbox', 'receiver']
        for node in nodes:
            assert node in topology, "Missing key topology.{}".format(node)
            assert 'name' in topology[node], "topology.{} is missing 'name' key".format(node)
            assert 'ifaces' in topology[node], "topology.{} is missing 'ifaces' key".format(node)
            assert len(topology[node]['ifaces']) > 0, "topology.{} must have at least 1 interface".format(node)
            for i,iface in enumerate(topology[node]['ifaces']):
                assert 'dev' in iface, "topology.{} iface {} is missing 'dev' key".format(node, i)
                assert 'addr' in iface, "topology.{} iface {} is missing 'addr' key".format(node, i)
        assert len(topology['inbox']['ifaces']) > 1, "topology.inbox must have at least 2 interaces"

        assert 'listen_port' in topology['inbox'], "topology.inbox must define listen_port"

        num_self = 0
        for node in topology:
            if 'self' in topology[node] and topology[node]['self']:
                num_self += 1
        assert num_self > 0, "One node in topology section must be labeled with \"self = true\""
        assert num_self == 1, "Only one node in topology section can be labeled self"
    else:
        nodes = ['sender', 'inbox', 'outbox', 'receiver']
        for node in nodes:
            assert node not in topology, "Don't use key topology.{} with cloudlab; it will be auto-populated".format(node)

    for k in config['sysctl']:
        v = config['sysctl'][k]
        assert type(v) == str, "key names with dots must be enclosed in quotes (sysctl)"

    assert 'initial_sample_rate' in config['parameters'], "parameters must include initial_sample_rate"
    assert 'bg_port_start' in config['parameters'], "parameters must include bg_port_start"

    structure_fields = [
        ('bundler_root', 'root directory for all experiments and code'),
    ]

    for (field,detail) in structure_fields:
        assert field in config['structure'], "[structure] missing key '{}': {}".format(field, detail)

    assert len(config['experiment']['seed']) > 0, "must specify at least one seed"
    assert len(config['experiment']['sch']) > 0, "must specify at least one scheduler (sch)"
    assert len(config['experiment']['alg']) > 0, "must specify at least one algorithm (alg)"
    assert all('name' in a for a in config['experiment']['alg']), "algs must have key name"
    assert len(config['experiment']['rate']) > 0, "must specify at least one rate"
    assert len(config['experiment']['rtt']) > 0, "must specify at least one rtt"
    assert len(config['experiment']['bdp']) > 0, "must specify at least one bdp"

    assert 'bundle_traffic' in config['experiment'], "must specify at least one type of bundle traffic"
    assert len(config['experiment']['bundle_traffic']) > 0, "must specify at least one type of bundle traffic"
    assert 'cross_traffic' in config['experiment'], "must specify at least one type of cross traffic"
    assert len(config['experiment']['cross_traffic']) > 0, "must specify at least one type of cross traffic"

    sources = ['iperf', 'poisson', 'cbr']
    for traffic_type in ['bundle_traffic', 'cross_traffic']:
        for traffic in config['experiment'][traffic_type]:
            for t in traffic:
                print(t)
                assert t['source'] in sources, "{} traffic source must be one of ({})".format(traffic_type, "|".join(sources))
                assert 'start_delay' in t, "{} missing start_delay (int)".format(traffic_type)
                if t['source'] == 'iperf':
                    assert t['alg'], "{} missing 'alg' (str)".format(traffic_type)
                    assert t['flows'], "{} missing 'flows' (int)".format(traffic_type)
                    assert t['length'], "{} missing 'length' (int)".format(traffic_type)
                if t['source'] == 'poisson':
                    assert t['conns'], "{} missing 'conns' (int)".format(traffic_type)
                    assert t['reqs'], "{} missing 'reqs' (int)".format(traffic_type)
                    assert t['dist'], "{} missing 'dist' (str)".format(traffic_type)
                    assert t['load'], "{} missing 'load' (str)".format(traffic_type)
                    assert t['alg'], "{} missing 'alg' (str)".format(traffic_type)
                    assert 'backlogged' in t, "{} missing 'backlogged' (int)".format(traffic_type)
                if t['source'] == 'cbr':
                    assert t['length'], "{} missing 'length (int)'".format(traffic_type)
                    assert t['port'], "{} missing 'port (int)'".format(traffic_type)
                    assert t['rate'], "{} missing 'rate (int)'".format(traffic_type)

def flatten(exps, dim):
    def f(dct):
        xs = [(k, dct[k]) for k in dct]
        expl = [(a,b) for a,b in xs if type(b) == type([])]
        done = [(a,b) for a,b in xs if type(b) != type([])]
        if len(expl) > 0:
            ks, bs = zip(*expl)
        else:
            ks, bs = ([], [])
        bs = list(itertools.product(*bs))
        expl = [dict(done + list(zip(ks, b))) for b in bs]
        return expl

    for e in exps:
        es = f(e[dim])
        for a in es:
            n = e
            n[dim] = a
            yield n

def enumerate_experiments(config):
    agenda.section("Starting experiments")
    exp_args = config['experiment']
    axes = list(exp_args.values())
    ps = list(itertools.product(*axes))
    exps = [dict(zip(exp_args.keys(), p)) for p in ps]
    Experiment = namedtuple("Experiment", exp_args.keys())
    exps = [Experiment(**x) for x in flatten(exps, 'alg')]
    random.shuffle(exps)
    return exps
