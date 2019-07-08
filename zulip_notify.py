import zulip

client = zulip.Client(config_file="~/zuliprc")

def zulip_notify(msg):

    req = {
        "type" : "private",
        "to" : "frankc@csail.mit.edu",
        "content" : msg
    }

    res = client.send_message(req)

    return res
