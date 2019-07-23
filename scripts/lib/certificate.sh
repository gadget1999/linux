#!/bin/bash

CMD_PATH=$(dirname "$0")
source $CMD_PATH/lib/common.sh

##############################################################
# Acme.sh based wrapper to handle certificate issue and renew
##############################################################

function check_cert_env() {
 check_env "MAIN_USER CERT_ROOT CERT_LOCAL_PORT DDNS_DOMAIN"

 CERT_CMD=/home/$MAIN_USER/.acme.sh/acme.sh

 CERT_FOLDER=$DDNS_DOMAIN
 if [ "$CERT_TYPE" == "ecc" ]; then
  CERT_FOLDER="$CERT_FOLDER"_ecc
 fi

 CERT_FULLCHAIN="$CERT_FOLDER/fullchain.cer"
 CERT_KEY="$CERT_FOLDER/$DDNS_DOMAIN.key"

 CERT_TRANSPORT="--httpport $CERT_LOCAL_PORT"
 if [ "$CERT_METHOD" == "tls" ]; then
  CERT_TRANSPORT="--alpn --tlsport $CERT_LOCAL_PORT"
 fi
}

function issue_certificate()  {
 local cmd="$SUDO $CERT_CMD --issue -d $DDNS_DOMAIN --standalone $CERT_TRANSPORT"
 
 if [ "$CERT_TYPE" == "ecc" ]; then
  cmd="$cmd --keylength ec-384"
 fi
 
 debug "CMD: $cmd"
 local output="$($cmd)"
 debug "Result: $output"
 
 if [[ $output != *"Your cert key"* ]]; then
  return 0
 else
  return 1
 fi
}

function renew_certificate()  {
 local force=$1
 local cmd="$SUDO $CERT_CMD --renew $force -d $DDNS_DOMAIN --standalone $CERT_TRANSPORT"
 
 if [ "$CERT_TYPE" == "ecc" ]; then
  cmd="$cmd --ecc"
 fi
 
 debug "CMD: $cmd"
 local output="$($cmd)"
 debug "Result: $output"
 
 if [[ $output != *"Your cert key"* ]]; then
  return 0
 else
  return 1
 fi
}
