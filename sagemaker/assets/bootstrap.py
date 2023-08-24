"""Bootstrap script for setting Glue DevEndpoint SageMaker notebook.

**reconnect_daemon** checks if notebook and DevEndpoint disconnected,
reconnect if necessary.
**switch_daemon** checks if notebook's DevEndpoint is switched
(Glue SageMaker switch DevEndpoint function), switch the DevEndpoint
if necessary, it also does the initialization of notebook very first
time.

reconnect_daemon and switch_daemon are called from crontab jobs of
SageMaker LifeCycleConfiguration script, when they detect DevEndpoint
not found(deleted) or keep having exceptions for a while, they will
stop themselves to avoid massive API requests to SageMaker and Glue.

As the revokers are from crontab jobs scheduled to be executed every
minute, even we proactively stop the daemons, they will be restarted
within 1 minute, we did NOT change cx behavior and provide the
capability to stop the daemons as improvements in future.

Standard retry policy applied to both SageMaker and Glue clients to
handle throttling or HTTP 500s.

@author: zhenpenz
@version: v1.0
"""
import argparse
import pathlib
import subprocess
import time
import json
import os
import logging
from logging import handlers
import requests
import boto3
from botocore.config import Config

RECONNECT_INTERVAL_IN_SEC = 300
SWITCH_INTERVAL_IN_SEC = 30
MAX_FAIL_DURATION_IN_HOUR = 48
HOUR_IN_SEC = 3600
DEV_ENDPOINT_HEARTBEAT_INTERVAL_IN_SEC = 3600
RECONNECT_MAX_FAIL_COUNT = ((HOUR_IN_SEC / RECONNECT_INTERVAL_IN_SEC) *
                            MAX_FAIL_DURATION_IN_HOUR)
SWITCH_MAX_FAIL_COUNT = ((HOUR_IN_SEC / SWITCH_INTERVAL_IN_SEC) *
                         MAX_FAIL_DURATION_IN_HOUR)
UPDATE_DEV_ENDPOINT_TIMEOUT_IN_SEC = 600
LIVY_SERVER_TIMEOUT_IN_SEC = 300
LIVY_PING_TIMEOUT_IN_SEC = 10
WAIT_DEV_ENDPOINT_READY_INTERVAL_IN_SEC = 5

SSH_KEY_DIR = "/home/ec2-user/glue/ssh/"
SSH_KEY_NAME = "glue_key"
SSH_KEY_PRIVATE_PATH = SSH_KEY_DIR + SSH_KEY_NAME
SSH_KEY_PUBLIC_PATH = SSH_KEY_PRIVATE_PATH + ".pub"
AUTO_SSH_HOST_PATH = "/home/ec2-user/glue/autossh.host"
NOTEBOOK_ARN_PATH = "/opt/ml/metadata/resource-metadata.json"
GLUE_ENDPOINT_PATH = "/home/ec2-user/glue/glue_endpoint.txt"
CURRENT_DEV_ENDPOINT_PATH = "/home/ec2-user/glue/current_dev_endpoint"
LIVY_SERVER_URL = "http://localhost:8998"

PUBLIC_KEY = "PublicKey"
PUBLIC_KEYS = "PublicKeys"
DEV_ENDPOINT = "DevEndpoint"
LAST_UPDATE_STATUS = "LastUpdateStatus"
COMPLETED = "COMPLETED"
FAILED = "FAILED"
PRIVATE_ADDRESS = "PrivateAddress"
PUBLIC_ADDRESS = "PublicAddress"

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
# backup up to 5 logs with max size 100MB
fh = handlers.RotatingFileHandler(filename="/var/log/sagemaker-bootstrap.log",
                                  maxBytes=1024 * 1024 * 100,
                                  backupCount=5, encoding="utf-8")
formatter = logging.Formatter(
    "%(asctime)s - %(process)s - %(levelname)s - %(funcName)s - %(message)s",
    datefmt='%Y/%m/%d %H:%M:%S')
fh.setFormatter(formatter)
logger.addHandler(fh)

retry_config = Config(
    retries={
        "max_attempts": 20
    }
)


def get_glue_endpoint():
    """Get Glue service endpoint.

    :return: Glue service endpoint.
    """
    with open(GLUE_ENDPOINT_PATH) as file:
        result = file.readline().strip()
        if result:
            return result
        raise ValueError(f"Glue endpoint is not set in {GLUE_ENDPOINT_PATH}")


def get_autossh_host():
    """Get autossh host.

    :return: autossh host.
    """
    try:
        with open(AUTO_SSH_HOST_PATH, "r") as file:
            autossh_host = file.read()
            if autossh_host:
                return autossh_host
            raise ValueError("autossh_host is empty")
    except IOError:
        logger.error(f"Failed to read autossh_host from {AUTO_SSH_HOST_PATH}",
                     exc_info=True)
        raise


def get_public_key():
    """Get notebook's Public Key.

    :return: notebook's Public Key.
    """
    try:
        with open(SSH_KEY_PUBLIC_PATH, "r") as file:
            public_key = file.read()
            if public_key:
                return public_key
            raise ValueError("SSH public_key is empty")
    except IOError:
        logger.error(
            f"Failed to read SSH public_key from {SSH_KEY_PUBLIC_PATH}"
            , exc_info=True)
        raise


def get_notebook_arn():
    """Get notebook arn.

    :return: Notebook arn.
    """
    with open(NOTEBOOK_ARN_PATH) as json_file:
        data = json.load(json_file)
        return data.get("ResourceArn")


def get_notebook_name():
    """Get notebook name.

    :return: Notebook name.
    """
    with open(NOTEBOOK_ARN_PATH) as json_file:
        data = json.load(json_file)
        return data.get("ResourceName")


def get_current_dev_endpoint():
    """Get DevEndpoint name from current_dev_endpoint file.

    :return: DevEndpoint name notebook is currently connected.
    """
    try:
        if os.path.exists(CURRENT_DEV_ENDPOINT_PATH):
            with open(CURRENT_DEV_ENDPOINT_PATH) as file:
                return file.read()
    except IOError:
        logger.warning("Failed to load current_dev_endpoint", exc_info=True)
    return None


def save_current_dev_endpoint(dev_endpoint_name):
    """Save DevEndpoint name to current_dev_endpoint file.

    :param dev_endpoint_name: DevEndpoint name.
    """
    logger.info(f"Saving current_dev_endpoint={dev_endpoint_name}")
    try:
        with open(CURRENT_DEV_ENDPOINT_PATH, "w") as file:
            file.write(dev_endpoint_name)
        logger.info(f"Saved current_dev_endpoint={dev_endpoint_name}")
    except IOError:
        logger.error(
            f"Failed to save current_dev_endpoint={dev_endpoint_name}"
            , exc_info=True)
        raise


def remove_dev_endpoint(dev_endpoint_name):
    """Remove current_dev_endpoint file from disk.

    delete_current_dev_endpoint should be called each time disconnecting
    DevEndpoint from switch_daemon to avoid concurrent update from
    reconnect_daemon, as the connection will be lost when switching,
    reconnect_daemon will try to reconnect to current_dev_endpoint
    (if present) thus above daemons may fall into a loop, switch_daemon
    keeps switching and reconnect_daemon keeps reconnecting.

    :param dev_endpoint_name: DevEndpoint name.
    """
    if os.path.exists(CURRENT_DEV_ENDPOINT_PATH):
        logger.info(f"Removing current_dev_endpoint={dev_endpoint_name}")
        try:
            os.remove(CURRENT_DEV_ENDPOINT_PATH)
            logger.info(f"Removed current_dev_endpoint={dev_endpoint_name}")
        except IOError:
            logger.error(
                f"Failed to remove current_dev_endpoint={dev_endpoint_name}",
                exc_info=True)
            raise
    else:
        logger.info(f"current_dev_endpoint={dev_endpoint_name} absent")


def get_latest_dev_endpoint():
    """Get latest DevEndpoint notebook should connect to.

    It is from notebook tag **aws-glue-dev-endpoint**
    Daemons will crash without it.

    :return: latest DevEndpoint name.
    """
    dev_endpoint_tags = sagemaker_client.list_tags(
        ResourceArn=notebook_arn).get('Tags')
    dev_endpoint_names = list(
        filter(lambda x: x['Key'] == 'aws-glue-dev-endpoint',
               dev_endpoint_tags))
    if dev_endpoint_names:
        dev_endpoint_name = dev_endpoint_names[0]['Value']
        return dev_endpoint_name
    raise ValueError("Unable to get latest DevEndpoint from notebook tag")


def dev_endpoint_heartbeat(dev_endpoint_name, last_checked_time):
    """Heartbeat DevEndpoint and get latest time.

    :param dev_endpoint_name: DevEndpoint name.
    :param last_checked_time: Last DevEndpoint heartbeat time.
    :return: latest DevEndpoint heartbeat time.
    """
    current_time = time.time()
    if ((current_time - last_checked_time) >
            DEV_ENDPOINT_HEARTBEAT_INTERVAL_IN_SEC):
        glue_client.get_dev_endpoint(EndpointName=dev_endpoint_name)
        return current_time
    return last_checked_time


def get_glue_client(endpoint_url):
    """Get glue client.

    :param endpoint_url: Glue Endpoint URL.
    :return: glue client.
    """
    if endpoint_url:
        result = boto3.client('glue', endpoint_url=endpoint_url,
                              config=retry_config)
    else:
        result = boto3.client('glue', config=retry_config)
    return result


notebook_arn = get_notebook_arn()
notebook_name = get_notebook_name()
glue_endpoint = get_glue_endpoint()
sagemaker_client = boto3.client('sagemaker', config=retry_config)
glue_client = get_glue_client(glue_endpoint)


def install_dependencies():
    """Install dependencies, only install when notebook starts."""
    try:
        from pip import main as pipmain
    # TODO refactor later
    except Exception:
        from pip._internal import main as pipmain
    pipmain(['install',
             "/home/ec2-user/glue/idna-2.7-py2.py3-none-any.whl"])
    pipmain(['install',
             "/home/ec2-user/glue/chardet-3.0.4-py2.py3-none-any.whl"])
    pipmain(['install',
             "/home/ec2-user/glue/certifi-2018.8.24-py2.py3-none-any.whl"])
    pipmain(['install',
             "/home/ec2-user/glue/requests-2.19.1-py2.py3-none-any.whl"])
    pipmain(['install',
             "/home/ec2-user/glue/botocore-1.12.10-py2.py3-none-any.whl"])
    pipmain(['install',
             "/home/ec2-user/glue/boto3-1.9.10-py2.py3-none-any.whl"])
    pipmain(['install',
             "/home/ec2-user/glue/urllib3-1.23-py2.py3-none-any.whl"])


def start_autossh():
    """Start autossh."""
    autossh_host = get_autossh_host()
    logger.info(f'Starting autossh tunnel to Livy {autossh_host}')
    subprocess.call(['/usr/bin/sudo', '/sbin/initctl', 'reload-configuration'])
    subprocess.call(['/usr/bin/sudo', '/sbin/initctl', 'start', 'autossh'])
    logger.info(f'Started autossh tunnel to Livy {autossh_host}')


def stop_autossh():
    """Stop autossh."""
    autossh_host = get_autossh_host()
    logger.info(f'Stopping autossh tunnel from Livy {autossh_host}')
    subprocess.call(['/usr/bin/sudo', '/sbin/initctl', 'stop', 'autossh'])
    logger.info(f'Stopped autossh tunnel from Livy {autossh_host}')


def ping_livy():
    """Ping livy server to check service is up."""
    logger.info("Pinging Livy...")
    requests.get(url=LIVY_SERVER_URL, timeout=LIVY_SERVER_TIMEOUT_IN_SEC)
    logger.info("Pinged Livy")


def generate_ssh_keypair():
    """Generate SSH KEYPAIR, if it exists, regenerate a new one."""
    logger.info(f"Generating SSH keypair at {SSH_KEY_PRIVATE_PATH}")
    if os.path.exists(SSH_KEY_DIR):
        if os.path.exists(SSH_KEY_PRIVATE_PATH):
            public_key = get_public_key()
            logger.warning(f"Removing current SSH keypair {public_key}")
            os.remove(SSH_KEY_PRIVATE_PATH)
            logger.warning(f"Removed current SSH keypair {public_key}")
    else:
        logger.info(f"Creating directory at {SSH_KEY_DIR}")
        pathlib.Path(SSH_KEY_DIR).mkdir(parents=True)
        logger.info(f"Created directory at {SSH_KEY_DIR}")
    logger.info(subprocess.check_output(
        ['/usr/bin/ssh-keygen', '-f', SSH_KEY_PRIVATE_PATH, '-C',
         notebook_name, '-N', '']))
    os.chmod(SSH_KEY_PRIVATE_PATH, 0o0400)
    public_key = get_public_key()
    logger.info(f"Generated SSH keypair {public_key}")


def add_public_key(dev_endpoint_name):
    """Add Public Key to DevEndpoint.

    :param dev_endpoint_name: DevEndpoint name.
    """
    public_key = get_public_key()
    wait_dev_endpoint_ready(dev_endpoint_name)
    logger.info(f"Adding public_key={public_key} to "
                f"dev_endpoint={dev_endpoint_name}")
    glue_client.update_dev_endpoint(EndpointName=dev_endpoint_name,
                                    AddPublicKeys=[public_key])
    wait_dev_endpoint_ready(dev_endpoint_name)
    logger.info(f"Added public_key={public_key} to "
                f"dev_endpoint={dev_endpoint_name}")
    dev_endpoint = glue_client.get_dev_endpoint(
        EndpointName=dev_endpoint_name)[DEV_ENDPOINT]
    logger.info(f"Dev endpoint details are {dev_endpoint}")
    if PRIVATE_ADDRESS in dev_endpoint:
        dev_endpoint_type = PRIVATE_ADDRESS
        dev_endpoint_address = dev_endpoint[PRIVATE_ADDRESS]
    else:
        dev_endpoint_type = PUBLIC_ADDRESS
        dev_endpoint_address = dev_endpoint[PUBLIC_ADDRESS]
    logger.info(f"Saving dev_endpoint={dev_endpoint_name} {dev_endpoint_type} "
                f"{dev_endpoint_address} to {AUTO_SSH_HOST_PATH}")
    with open(AUTO_SSH_HOST_PATH, 'w+') as file:
        file.write(dev_endpoint_address)
    logger.info(f"Saved dev_endpoint={dev_endpoint_name} {dev_endpoint_type} "
                f"{dev_endpoint_address} to {AUTO_SSH_HOST_PATH}")


def delete_public_keys_if_has(dev_endpoint_name):
    """Delete Public Keys if in DevEndpoint.

    :param dev_endpoint_name: DevEndpoint name.
    """
    try:
        dev_endpoint = glue_client.get_dev_endpoint(
            EndpointName=dev_endpoint_name)[DEV_ENDPOINT]
        public_keys_to_delete = list()
        if PUBLIC_KEY in dev_endpoint:
            public_keys_to_delete.append(dev_endpoint[PUBLIC_KEY])
        if PUBLIC_KEYS in dev_endpoint:
            for public_key in dev_endpoint[PUBLIC_KEYS]:
                # TODO bug accidentally delete other keys
                if notebook_name in public_key:
                    public_keys_to_delete.append(public_key)
        delete_public_keys(dev_endpoint_name, public_keys_to_delete)
    # if old DevEndpoint is deleted or having issues, ignore
    except Exception:
        logger.error("Failed to delete Public Keys from "
                     f"dev_endpoint={dev_endpoint_name}", exc_info=True)


def delete_public_keys(dev_endpoint_name, public_keys_to_delete):
    """Delete Public Keys from the DevEndpoint.

    :param dev_endpoint_name: DevEndpoint name.
    :param public_keys_to_delete: Public Keys to be deleted.
    """
    wait_dev_endpoint_ready(dev_endpoint_name)
    if public_keys_to_delete:
        logger.info(f"Deleting public_keys={public_keys_to_delete} "
                    f"from dev_endpoint={dev_endpoint_name}")
        glue_client.update_dev_endpoint(EndpointName=dev_endpoint_name,
                                        DeletePublicKeys=public_keys_to_delete)
        wait_dev_endpoint_ready(dev_endpoint_name)
        logger.info(f"Deleted public_keys={public_keys_to_delete} "
                    f"from dev_endpoint={dev_endpoint_name}")
    else:
        logger.info("No Public Keys to delete from "
                    f"dev_endpoint={dev_endpoint_name}")


def has_public_key(dev_endpoint):
    """Check if DevEndpoint has current notebook's PublicKey.

    :param dev_endpoint: DevEndpoint Object.
    :return: is public key in DevEndpoint.
    """
    current_public_key = get_public_key()
    if (PUBLIC_KEY in dev_endpoint and
            current_public_key in dev_endpoint[PUBLIC_KEY]):
        return True
    if PUBLIC_KEYS in dev_endpoint:
        for public_key in dev_endpoint[PUBLIC_KEYS]:
            if current_public_key in public_key:
                return True
    return False


def wait_dev_endpoint_ready(dev_endpoint_name):
    """Wait for DevEndpoint to be ready.

    As dev endpoint doesn't allow concurrent update, wait it ready.

    :param dev_endpoint_name: DevEndpoint name.
    """
    start = time.time()
    while (time.time() - start) < UPDATE_DEV_ENDPOINT_TIMEOUT_IN_SEC:
        logger.info(f'Waiting dev_endpoint={dev_endpoint_name} ready')
        time.sleep(WAIT_DEV_ENDPOINT_READY_INTERVAL_IN_SEC)
        dev_endpoint = glue_client.get_dev_endpoint(
            EndpointName=dev_endpoint_name)[DEV_ENDPOINT]
        if LAST_UPDATE_STATUS not in dev_endpoint:
            break
        if dev_endpoint[LAST_UPDATE_STATUS] == COMPLETED:
            logger.info(f'dev_endpoint={dev_endpoint_name} ready')
            break
        if dev_endpoint[LAST_UPDATE_STATUS] == FAILED:
            error_msg = ("LastUpdateStatus is FAILED, "
                         f"dev_endpoint={dev_endpoint_name}")
            raise ValueError(error_msg)
    else:
        logger.error(f"Wait dev_endpoint={dev_endpoint_name} ready timeout")


def is_dev_endpoint_connected():
    """Is current notebook connected to current_dev_endpoint.

    Checking if Livy is up.

    :return: is DevEndpoint connected.
    """
    try:
        requests.get(url=LIVY_SERVER_URL, timeout=LIVY_PING_TIMEOUT_IN_SEC)
        return True
    except requests.exceptions.ConnectionError:
        return False


def is_dev_endpoint_updating(dev_endpoint):
    """Is DevEndpoint is updating something else.

    :param dev_endpoint: DevEndpoint Object.
    :return: is DevEndpoint updating.
    """
    return (LAST_UPDATE_STATUS in dev_endpoint and
            dev_endpoint[LAST_UPDATE_STATUS] != COMPLETED and
            dev_endpoint[LAST_UPDATE_STATUS] != FAILED)


def update_connection_tag(tag_value="ready"):
    """Update SageMaker notebook tag to show its status.

    SageMaker notebook ARN should contain **sagemaker:AddTags**
    permission to make successful calls.
    Available tag values are [ready, disconnected, switching].

    :param tag_value: notebook status tag
    """
    try:
        sagemaker_client.add_tags(
            ResourceArn=notebook_arn,
            Tags=[
                {
                    "Key": "aws-glue-dev-endpoint-connection",
                    "Value": tag_value
                }
            ]
        )
    # Tags exception should not affect reconnect or switch function
    except Exception:
        logger.error(f"Failed to update connection tag to {tag_value}",
                     exc_info=True)


def connect_dev_endpoint(dev_endpoint_name):
    """Connect current notebook to DevEndpoint.

    Clean up all public keys generated by current notebook even
    and notebooks with same name, then connect to DevEndpoint.

    :param dev_endpoint_name: DevEndpoint name.
    """
    logger.info(f"Connecting to dev_endpoint={dev_endpoint_name}")
    delete_public_keys_if_has(dev_endpoint_name)
    generate_ssh_keypair()
    add_public_key(dev_endpoint_name)
    start_autossh()
    logger.info(f"Waiting {LIVY_PING_TIMEOUT_IN_SEC} seconds for tunnel ready")
    time.sleep(LIVY_PING_TIMEOUT_IN_SEC)
    ping_livy()
    save_current_dev_endpoint(dev_endpoint_name)
    update_connection_tag()
    logger.info(f"Connected to dev_endpoint={dev_endpoint_name}")


def disconnect_dev_endpoint(dev_endpoint_name):
    """Disconnect current notebook from DevEndpoint.

    Stop autossh, delete Public Key and update the notebook tag.

    :param dev_endpoint_name: DevEndpoint name.
    """
    logger.info(f"Disconnecting from dev_endpoint={dev_endpoint_name}")
    delete_public_keys_if_has(dev_endpoint_name)
    stop_autossh()
    update_connection_tag(tag_value="disconnected")
    logger.info(f"Disconnected from dev_endpoint={dev_endpoint_name}")


def reconnect_dev_endpoint(dev_endpoint_name):
    """Reconnect DevEndpoint if disconnected.

    Follow below steps to reconnect:
      1. If Livy is up, DevEndpoint is assumed connected.
      2. If DevEndpoint is deleted, throwing exception all the way up
         and failed_count will be incremented.
      3. If DevEndpoint is updating, re-check in next round.
      4. If DevEndpoint has notebook's public_key, restart autossh.
      5. If Livy is down after restarting autossh, reconnect to
         DevEndpoint.
      5. If DevEndpoint doesn't have notebook's public_key, reconnect
         to DevEndpoint.

    :param dev_endpoint_name: DevEndpoint name.
    """
    if not dev_endpoint_name:
        logger.warning("current_dev_endpoint absent")
        return
    # Skip if DevEndpoint is connected
    if not is_dev_endpoint_connected():
        logger.warning(f"dev_endpoint={dev_endpoint_name} disconnected, "
                       "trying to reconnect...")
    else:
        logger.info(f"dev_endpoint={dev_endpoint_name} is connected")
        return
    # Skip if DevEndpoint is updating
    dev_endpoint = glue_client.get_dev_endpoint(
        EndpointName=dev_endpoint_name)[DEV_ENDPOINT]
    if is_dev_endpoint_updating(dev_endpoint):
        logger.warning(f"dev_endpoint={dev_endpoint_name} is updating, "
                       "re-check in next round")
        return
    # Restart autossh if DevEndpoint has notebook's public_key
    public_key_present = has_public_key(dev_endpoint)
    if public_key_present:
        logger.info(f"Public Key is in dev_endpoint={dev_endpoint_name}, "
                    "restarting autossh...")
        stop_autossh()
        start_autossh()
        if is_dev_endpoint_connected():
            logger.info(f"dev_endpoint={dev_endpoint_name} reconnected now")
            return
        logger.warning(f"dev_endpoint={dev_endpoint_name} still disconnected "
                       "after restarting autossh, reconnecting...")
    # Reconnect if public_key absent in DevEndpoint
    if not public_key_present:
        logger.info(f"Public Key is not in dev_endpoint={dev_endpoint_name}, "
                    "reconnecting...")
    disconnect_dev_endpoint(dev_endpoint_name)
    connect_dev_endpoint(dev_endpoint_name)
    logger.info(f"dev_endpoint={dev_endpoint_name} reconnected now")


def reconnect_daemon():
    """Daemon for reconnecting DevEndpoint.

    Periodically checks if DevEndpoint is disconnected and
    reconnect.
    """
    logger.info("reconnect_daemon started")
    failed_count = 0
    while failed_count < RECONNECT_MAX_FAIL_COUNT:
        logger.info("reconnect_daemon checking")
        try:
            current_dev_endpoint = get_current_dev_endpoint()
            reconnect_dev_endpoint(current_dev_endpoint)
            failed_count = 0
        # catch all exceptions until keeps failing and stop
        except Exception:
            failed_count += 1
            logger.error(f"reconnect_daemon failed_count={failed_count}",
                         exc_info=True)
        # notebook restart expects to execute immediately
        time.sleep(RECONNECT_INTERVAL_IN_SEC)
    logger.error(f"reconnect_daemon stopped, failed_count={failed_count}")


def switch_daemon():
    """Daemon for switching DevEndpoint.

    Periodically checks if DevEndpoint is switched.
    It compares the latest notebook tag and current_dev_endpoint from
    disk, if there is delta, DevEndpoint is assumed switched, it will
    disconnect current_dev_endpoint and connect to new DevEndpoint.

    Note it also does initialization of the notebook.
    """
    logger.info("switch_daemon started")
    failed_count = 0
    while failed_count < SWITCH_MAX_FAIL_COUNT:
        logger.info("switch_daemon checking")
        try:
            current_dev_endpoint = get_current_dev_endpoint()
            latest_dev_endpoint = get_latest_dev_endpoint()
            is_changed = (current_dev_endpoint != latest_dev_endpoint)
            if is_changed:
                logger.info("dev_endpoint changing from "
                            f"{current_dev_endpoint} to {latest_dev_endpoint}")
                if current_dev_endpoint:
                    remove_dev_endpoint(current_dev_endpoint)
                    disconnect_dev_endpoint(current_dev_endpoint)
                if latest_dev_endpoint:
                    connect_dev_endpoint(latest_dev_endpoint)
                logger.info("dev_endpoint changed from "
                            f"{current_dev_endpoint} to {latest_dev_endpoint}")
            else:
                logger.info(f"dev_endpoint={latest_dev_endpoint} not changed")
            failed_count = 0
        # catch all exceptions until keeps failing and stop
        except Exception:
            failed_count += 1
            logger.error(f"switch_daemon failed_count={failed_count}",
                         exc_info=True)
        time.sleep(SWITCH_INTERVAL_IN_SEC)
    logger.error(f"switch_daemon stopped, failed_count={failed_count}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--devendpointname',
                        help='Name of dev endpoint to connect to',
                        required=True)
    parser.add_argument('--notebookname', help='Notebook name',
                        required=True)
    parser.add_argument('--endpoint',
                        help='Endpoint address of AWS Glue to use')
    args = parser.parse_args()
    if args.notebookname:
        notebook_name = args.notebookname
    if args.endpoint:
        glue_endpoint = args.endpoint
    install_dependencies()
    connect_dev_endpoint(args.devendpointname)
