#!/usr/bin/env bash

CMD_PATH=$(dirname "$0")
source $CMD_PATH/lib/common.sh

function check_email_env {
 check_env "SENDGRID_FROM SENDGRID_API_KEY"
 check_packages "curl"
}

FROM_NAME="Server-$(hostname)"

function send_email() {
 local mailto=$1
 local subject=$2
 local body=$3

 local maildata="{ \
  \"personalizations\": \
    [{\"to\":[{\"email\":\"$mailto\"}]}], \
    \"from\":{\"email\":\"$SENDGRID_FROM\",\"name\":\"$FROM_NAME\"}, \
    \"subject\":\"$subject\", \
    \"content\":[{\"type\":\"text/html\",\"value\":\"$body\"}]}"

 /usr/bin/curl --request POST \
  --url https://api.sendgrid.com/v3/mail/send \
  --header "Authorization: Bearer $SENDGRID_API_KEY" \
  --header 'Content-Type: application/json' \
  --data "$maildata"
}
