#!/usr/bin/env bash

CMD_PATH=$(dirname "$0")
source $CMD_PATH/lib/common.sh

function check_email_env {
 check_env "EMAIL_SENDER EMAIL_API_KEY"
 check_packages "curl"
}

FROM_NAME="Server-$(hostname)"

function send_email_sendgrid() {
 local mailto=$1
 local subject=$2
 local body=$3

 [ -z "$SENDGRID_API_KEY" ] && fatal_error "SENDGRID_API_KEY must be set."

 local maildata="{ \
  \"personalizations\": \
    [{\"to\":[{\"email\":\"$mailto\"}]}], \
    \"from\":{\"email\":\"$EMAIL_SENDER\",\"name\":\"$FROM_NAME\"}, \
    \"subject\":\"$subject\", \
    \"content\":[{\"type\":\"text/html\",\"value\":\"$body\"}]}"

 /usr/bin/curl --request POST \
  --url https://api.sendgrid.com/v3/mail/send \
  --header "Authorization: Bearer $SENDGRID_API_KEY" \
  --header 'Content-Type: application/json' \
  --data "$maildata"
}

function send_email_brevo() {
  local mailto=$1
  local subject=$2
  local body=$3

  [ -z "$BREVO_API_KEY" ] && fatal_error "BREVO_API_KEY must be set."

  local maildata="{\
    \"sender\":{\"email\":\"$EMAIL_SENDER\",\"name\":\"$FROM_NAME\"},\
    \"to\":[{\"email\":\"$mailto\"}],\
    \"subject\":\"$subject\",\
    \"htmlContent\":\"$body\"\
  }"

  /usr/bin/curl --request POST \
    --url https://api.brevo.com/v3/smtp/email \
    --header "api-key: $BREVO_API_KEY" \
    --header 'Content-Type: application/json' \
    --data "$maildata"
}

function send_email_mailersend() {
  local mailto=$1
  local subject=$2
  local body=$3

  [ -z "$MAILERSEND_API_KEY" ] && fatal_error "MAILERSEND_API_KEY must be set."

  local maildata="{\
    \"from\":{\"email\":\"$EMAIL_SENDER\",\"name\":\"$FROM_NAME\"},\
    \"to\":[{\"email\":\"$mailto\"}],\
    \"subject\":\"$subject\",\
    \"html\":\"$body\"\
  }"

  /usr/bin/curl --request POST \
    --url https://api.mailersend.com/v1/email \
    --header "Authorization: Bearer $MAILERSEND_API_KEY" \
    --header 'Content-Type: application/json' \
    --data "$maildata"
}

function send_email_mailjet() {
  local mailto=$1
  local subject=$2
  local body=$3

  [ -z "$MAILJET_API_KEY" ] && fatal_error "MAILJET_API_KEY must be set."

  local maildata="{\
    \"Messages\":[{\
      \"From\":{\"Email\":\"$EMAIL_SENDER\",\"Name\":\"$FROM_NAME\"},\
      \"To\":[{\"Email\":\"$mailto\"}],\
      \"Subject\":\"$subject\",\
      \"HTMLPart\":\"$body\"\
    }]\
  }"

  /usr/bin/curl --request POST \
    --url https://api.mailjet.com/v3.1/send \
    --user "$MAILJET_API_KEY" \
    --header 'Content-Type: application/json' \
    --data "$maildata"
}
