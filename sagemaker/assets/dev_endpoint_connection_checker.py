"""Check if DevEndpoint and notebook are connected.

It's a blocking call to avoid notebook to start if initialization
not done. It's called from SageMaker LCC script.

To debug the notebook failure reason, this call can be removed from
SageMaker LCC to access the logs.

@author: zhenpenz
@version: v1.0
"""
import time
import requests

# wait livy connection timeout, 30 min in case of region slow
LIVY_SERVER_TIMEOUT_IN_SEC = 1800
LIVY_SERVER_URL = "http://localhost:8998"
LIVY_PING_TIMEOUT_IN_SEC = 5


# Sagemaker notebook lifecycle configuration timeout is 5 minutes.
def wait_for_livy_connection():
    """Wait Livy server up."""
    print('Waiting for livy connection')
    start = time.time()
    while (time.time() - start) < LIVY_SERVER_TIMEOUT_IN_SEC:
        try:
            requests.get(url=LIVY_SERVER_URL, timeout=LIVY_PING_TIMEOUT_IN_SEC)
            print('Livy connection OK')
            return
        except requests.exceptions.ConnectionError:
            print('Livy connection failed, sleeping for '
                  f'{LIVY_PING_TIMEOUT_IN_SEC} seconds.')
            time.sleep(LIVY_PING_TIMEOUT_IN_SEC)

    error_msg = ("Livy connection timeout after "
                 f"{LIVY_SERVER_TIMEOUT_IN_SEC} seconds")
    debug_msg = """
    Please follow below approaches to debug failure reason:
    
    1. Check DevEndpoint existing.
    2. DevEndpoint contains notebook's public key at 
       /home/ec2-user/glue/ssh/glue_key.pub
    3. Check Glue UpdateDevEndpoint, GetDevEndpoint and 
       SageMaker ListTags API not throttled.
    4. Check log in /var/log/sagemaker-bootstrap.log for details.
    
    You should be able to start the notebook by removing the
    LCC OnStart script.
    """
    print(error_msg)
    print(debug_msg)
    raise ValueError(error_msg)


if __name__ == '__main__':
    wait_for_livy_connection()
