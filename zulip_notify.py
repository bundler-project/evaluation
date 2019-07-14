import zulip

client = zulip.Client(config_file="~/zuliprc")

def zulip_notify(msg, dry=False):

    if dry:
        req = {
            "type" : "private",
            "to" : "frankc@csail.mit.edu",
            "content" : msg
        }
    else:
        req = {
            "type" : "stream",
            "to" : "nebula (bundlecc)",
            "subject" : "bundler experiments",
            "content" : msg
        }

    res = client.send_message(req)

    return res
