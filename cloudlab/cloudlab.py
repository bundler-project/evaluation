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
        agenda.failure("Could not attempt login")
        return

    time.sleep(2)
    try:
        # if things worked, this will throw an exception
        driver.find_element_by_name("login")
    except:
        return

    agenda.failure("Login attempt failed, check username/password")
    raise Exception("Login failed")

def launch(driver):
    agenda.task("Launch new cloudlab experiment")
    driver.get("https://www.cloudlab.us/instantiate.php#")

    agenda.subtask("Select bundler profile")
    time.sleep(2)
    driver.find_element_by_id("change-profile").click()
    time.sleep(2)
    driver.find_element_by_name("bundler-local").click()
    time.sleep(2)
    driver.find_element_by_id("showtopo_select").click()

    #click through
    time.sleep(2)
    driver.execute_script("$(\"[href='#next']\").click()")
    time.sleep(2)
    driver.execute_script("$(\"[href='#next']\").click()")

    agenda.subprompt("Press [Enter] to verify cluster availability>")
    input()

    time.sleep(2)
    driver.execute_script("$(\"[href='#next']\").click()")

    time.sleep(2)
    driver.find_element_by_id("experiment_duration").clear()
    driver.find_element_by_id("experiment_duration").send_keys("16")

    agenda.subprompt("Press [Enter] to launch")
    input()

    time.sleep(2)
    driver.execute_script("$(\"[href='#finish']\").click()")

    agenda.subtask("Launch")
    launch_wait(driver)

    return get_machines_from_experiment(driver)

def check_existing_experiment(driver):
    agenda.task("Check for existing experiment")
    driver.get("https://www.cloudlab.us/user-dashboard.php#experiments")
    table = None
    try:
        table = driver.find_element_by_id("experiments_table")
    except:
        agenda.subfailure("No existing experiment found")
        return None

    elements = [e.text.split()[0] for e in table.find_elements_by_xpath("//table/tbody") if len(e.text.split()) > 0]
    agenda.subtask("Existing experiment found")
    driver.find_element_by_link_text(elements[0]).click()
    time.sleep(4)
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
    listen_port = config['topology']['inbox']['listen_port']

    agenda.subtask(f"headless: {headless}")
    driver = init_driver(
        config['topology']['cloudlab']['username'],
        config['topology']['cloudlab']['password'],
        headless=headless,
    )

    machines = check_existing_experiment(driver)
    if machines is None:
        machines = launch(driver)

    machines = [cloudlab_conn_rgx.match(m).groupdict() for m in machines if 'cloudlab.us' in m]
    config['topology']['sender'] = machines[0]
    config['topology']['inbox'] = machines[1]
    config['topology']['inbox']['listen_port'] = listen_port
    config['topology']['outbox'] = machines[2]
    config['topology']['receiver'] = machines[2]
    return config
