#!/bin/bash
set -ex
# it's required to kill existing daemon before starting
# as stopping crontab job won't kill the daemon
sudo pkill -f bootstrap.switch_daemon
# it's required to go to below path to import libraries successfully
cd /home/ec2-user/glue
python3 -c "import bootstrap; bootstrap.install_dependencies()"
python3 -c "import bootstrap; bootstrap.switch_daemon()"
