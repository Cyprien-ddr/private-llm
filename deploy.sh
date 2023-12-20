#!/bin/bash
### OPTIONS ###
deploy_api=1
deploy_front=1
while getopts af opt; do
  case "$opt" in
  a) deploy_api=1; deploy_front=0 ;; 
  f) deploy_front=1; deploy_api=0 ;; 
  \?) exit 1 ;; esac
done
shift $(($OPTIND - 1))
### OPTIONS ###

if (($deploy_api)); then

  rsync -rvp --exclude=".git" --exclude=".venv" api/ cdiederichs@34.253.93.55:/home/cdiederichs/production/insignai-private-llm/
  ssh -t ec2-user@34.253.93.55 "sudo service gunicorn-private-llm-ai restart"
#   ssh cdiederichs@34.253.93.55  <<EOF
# cd production/insignai-private-llm/; 
# EOF

fi

if (($deploy_front)); then

  rsync -rvp --rsync-path="sudo rsync" --exclude=".git" --exclude="client_credentials.json" --exclude="env.php" --exclude="api_token.txt" front/ ec2-user@34.253.93.55:/var/www/insignai-private-llm/production/
  ssh -t ec2-user@34.253.93.55 "sudo chown -R apache: /var/www/insignai-private-llm/production/"

fi
