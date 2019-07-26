import agenda
import os
import re
import time
import selenium
from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
mport subprocess
from pyspin.spin import make_spin, Default

@make_spin(Default, "Waiting to load cluster selection...")
def cluster_select(driver):
    while True:
        try:
            driver.execute_script("$(\"[value='Cloudlab Utah']\")[1].click()")
            time.sleep(1)
            driver.execute_script("$(\"[value='OneLab']\")[3].click()")
            return
        except selenium.common.exceptions.JavascriptException:
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
    if os.path.exists("./cloudlab/chromedriver"):
        return

    subprocess.call("wget https://chromedriver.storage.googleapis.com/75.0.3770.140/chromedriver_mac64.zip -O ./cloudlab/chromedriver.zip", shell=True)
    subprocess.call("unzip ./cloudlab/chromedriver.zip -d ./cloudlab", shell=True)
    subprocess.call("rm ./cloudlab/chromedriver.zip", shell=True)

def launch(headless=False):
    get_chromedriver()

    chrome_options = Options()
    chrome_options.add_argument("--incognito")
    if headless:
        chrome_options.add_argument("--headless")

    #currently OSX only
    chrome_options.binary_location = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    driver = webdriver.Chrome(executable_path=os.path.abspath("chromedriver"), chrome_options=chrome_options)
    driver.get("https://www.cloudlab.us/instantiate.php#")

    agenda.task("Login")
    time.sleep(2)

    driver.find_element_by_name("uid").send_keys("akshayn")
    driver.find_element_by_name("password").send_keys("exceed-dauphin-triangle-twinkly-gasify")
    driver.find_element_by_name("login").click()

    agenda.task("Select bundler profile")
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

    time.sleep(2)
    driver.execute_script("$(\"[href='#next']\").click()")

    time.sleep(2)
    driver.find_element_by_id("experiment_duration").clear()
    driver.find_element_by_id("experiment_duration").send_keys("8")

    agenda.subprompt("Press [Enter] to launch")

    time.sleep(2)
    driver.execute_script("$(\"[href='#finish']\").click()")

    agenda.task("Launch")
    launch_wait(driver)

    driver.find_element_by_id("show_listview_tab").click()
    time.sleep(1)
    machines = [m.text for m in driver.find_elements_by_name("sshurl")]
    return machines

cloudlab_conn_rgx = re.compile(r"ssh -p (?P<port>[0-9]+) (?P<user>[a-z0-9]+)@(?P<name>[a-z0-9\.]+)")
# populate the top level of the topology with cloudlab nodes
# sender, inbox, outbox, receiver
def make_cloudlab_topology(config, headless=False):
    agenda.section("Launch Cloudlab nodes")
    machines = launch(headless=headless)
    senders = [cloudlab_conn_rgx.match(m).groupdict() for m in machines if 'cloudlab.us' in m]
    receivers = [cloudlab_conn_rgx.match(m).groupdict() for m in machines if 'onelab.eu' in m]
    config['topology']['sender'] = senders[0]
    config['topology']['inbox'] = senders[1]
    config['topology']['outbox'] = receivers[0]
    config['topology']['receiver'] = receivers[1]
    return config

ip_addr_rgx = re.compile(r"(?P<dev>[a-z0-9]+)\W*inet\W*(?P<addr>[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)/[0-9]+")
# populate interface names and ips
def get_interfaces(config, machines):
    for m in machines:
        conn = machines[m]
        ifaces = conn.run("ip -4 -o addr").stdout.strip().split()
        ifaces = [ip_addr_rgx.match(i).groupdict() for i in ifaces]
        config['topology'][m].update(ifaces)

    return config

# clone the bundler repository
def init_repo(config, machines):
    root = config['structure']['bundler_root']
    clone = f'git clone --recurse-submodules https://github.com/bundler-project/evaluation {root}'

    for m in machines:
        machines[m].run(clone)
        machines[m].run(f"make -C {root}")

def bootstrap_cloudlab_topology(config, machines):
    config = get_interfaces(config, machines)
    init_repo(config, machines)
    return config
