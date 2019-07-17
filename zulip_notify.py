import zulip

client = None

def zulip_notify(msg, dry=False):
    global client
    if client is None:
        try:
            client = zulip.Client(config_file="~/zuliprc")
        except:
            pass

    if client is None:
        return

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
