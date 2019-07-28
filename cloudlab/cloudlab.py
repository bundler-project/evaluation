import agenda
import os
import re
import time
import selenium
from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
import subprocess
from pyspin.spin import make_spin, Default

@make_spin(Default, "Waiting to load cluster selection...")
def cluster_select(driver):
    while True:
        try:
            time.sleep(1)
            driver.execute_script("$(\"[value='Cloudlab Utah']\")[1].click()")
            time.sleep(1)
            driver.execute_script("$(\"[value='OneLab']\")[3].click()")
            return
        except:
            time.sleep(2)

@make_spin(Default, "Cluster launching...")
def launch_wait(driver):
    while True:
        try:
            if driver.find_element_by_id("quickvm_status").text == 'ready':
                return
        except:
            pass
        time.sleep(2)

def get_chromedriver():
    if os.path.exists("./chromedriver"):
        return

    subprocess.call("wget https://chromedriver.storage.googleapis.com/75.0.3770.140/chromedriver_mac64.zip -O ./cloudlab/chromedriver.zip", shell=True)
    subprocess.call("unzip ./cloudlab/chromedriver.zip", shell=True)
    subprocess.call("rm ./cloudlab/chromedriver.zip", shell=True)

def init_driver(username, pw, headless=False):
    get_chromedriver()

    chrome_options = Options()
    chrome_options.add_argument("--incognito")
    if headless:
        chrome_options.add_argument("--headless")

    #currently OSX only
    chrome_options.binary_location = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    driver = webdriver.Chrome(executable_path=os.path.abspath("chromedriver"), chrome_options=chrome_options)
    driver.get("https://www.cloudlab.us/user-dashboard.php#experiments")
    login(driver, username, pw)
    return driver

def login(driver, username, pw):
    try:
        # will except and return if not present
        driver.find_element_by_name("login")

        agenda.task("Login")
        time.sleep(2)

        driver.find_element_by_name("uid").send_keys(username)
        driver.find_element_by_name("password").send_keys(pw)
        driver.find_element_by_name("login").click()
    except:
        return

def launch(driver):
    agenda.task("Launch new cloudlab experiment")
    driver.get("https://www.cloudlab.us/instantiate.php#")

    agenda.subtask("Select bundler profile")
    time.sleep(2)
    driver.find_element_by_id("change-profile").click()
    time.sleep(2)
    driver.find_element_by_name("bundler").click()
    time.sleep(2)
    driver.find_element_by_id("showtopo_select").click()

    #click through
    time.sleep(2)
    driver.execute_script("$(\"[href='#next']\").click()")
    time.sleep(2)
    driver.execute_script("$(\"[href='#next']\").click()")

    cluster_select(driver)
    agenda.subprompt("Press [Enter] to verify cluster availability>")
    input()

    time.sleep(2)
    driver.execute_script("$(\"[href='#next']\").click()")

    time.sleep(2)
    driver.find_element_by_id("experiment_duration").clear()
    driver.find_element_by_id("experiment_duration").send_keys("8")

    agenda.subprompt("Press [Enter] to launch")
    input()

    time.sleep(2)
    driver.execute_script("$(\"[href='#finish']\").click()")

    agenda.subtask("Launch")
    launch_wait(driver)

    return get_machines_from_experiment(driver)

def check_exisiting_experiment(driver):
    agenda.task("Check for existing experiment")
    driver.get("https://www.cloudlab.us/user-dashboard.php#experiments")
    table = driver.find_element_by_id("experiments_table")
    elements = [e.text.split()[0] for e in table.find_elements_by_xpath("//table/tbody") if len(e.text.split()) > 0]
    if len(elements) == 0:
        agenda.subfailure("No existing experiment found")
        return None
    else:
        agenda.subtask("Existing experiment found")
        driver.find_element_by_link_text(elements[0]).click()
        time.sleep(1)
        return get_machines_from_experiment(driver)

def get_machines_from_experiment(driver):
    driver.find_element_by_id("show_listview_tab").click()
    time.sleep(1)
    machines = [m.text for m in driver.find_elements_by_name("sshurl")]
    agenda.subtask("Got machines")
    for m in machines:
        agenda.subtask(m)
    return machines

cloudlab_conn_rgx = re.compile(r"ssh -p (?P<port>[0-9]+) (?P<user>[a-z0-9]+)@(?P<name>[a-z0-9\.]+)")
# populate the top level of the topology with cloudlab nodes
# sender, inbox, outbox, receiver
def make_cloudlab_topology(config, headless=False):
    agenda.section("Setup Cloudlab topology")
    driver = init_driver(
        config['topology']['cloudlab']['username'],
        config['topology']['cloudlab']['password'],
        headless=headless,
    )

    machines = check_exisiting_experiment(driver)
    if machines is None:
        machines = launch(driver)

    senders = [cloudlab_conn_rgx.match(m).groupdict() for m in machines if 'cloudlab.us' in m]
    receivers = [cloudlab_conn_rgx.match(m).groupdict() for m in machines if 'onelab.eu' in m]
    config['topology']['sender'] = senders[0]
    config['topology']['inbox'] = senders[1]
    config['topology']['outbox'] = receivers[0]
    config['topology']['receiver'] = receivers[1]
    return config

ip_addr_rgx = re.compile(r"\w+:\W*(?P<dev>\w+).*inet (?P<addr>[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)")
# populate interface names and ips
def get_interfaces(config, machines):
    agenda.section("Get Cloudlab node interfaces")
    for m in machines:
        agenda.task(machines[m].addr)
        conn = machines[m]
        ifaces = conn.run("ip -4 -o addr").stdout.strip().split("\n")
        ifaces = [ip_addr_rgx.match(i) for i in ifaces]
        ifaces = [i.groupdict() for i in ifaces if i is not None and i["dev"] != "lo"]
        config['topology'][m]['ifaces'] = ifaces

    return config

# clone the bundler repository
def init_repo(config, machines):
    agenda.section("Init cloudlab nodes")
    root = config['structure']['bundler_root']
    clone = f'git clone --recurse-submodules -b cloudlab https://github.com/bundler-project/evaluation {root}'

    for m in machines:
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

def bootstrap_cloudlab_topology(config, machines):
    config = get_interfaces(config, machines)
    init_repo(config, machines)
    return config
