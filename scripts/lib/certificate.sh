#!/bin/bash

CMD_PATH=$(dirname "$0")
source $CMD_PATH/lib/common.sh

##############################################################
# Acme.sh based wrapper to handle certificate issue and renew
##############################################################

function check_cert_env() {
 check_env "MAIN_USER CERT_ROOT CERT_LOCAL_PORT DDNS_DOMAIN"

 CERT_ROOT_FOLDER=/home/$MAIN_USER/.acme.sh
 CERT_CMD=$CERT_ROOT_FOLDER/acme.sh
 CERT_FOLDER=$DDNS_DOMAIN
 [ "$CERT_TYPE" == "ecc" ] && CERT_FOLDER="$CERT_FOLDER"_ecc
 CERT_FULLCHAIN="$CERT_FOLDER/fullchain.cer"
 CERT_KEY="$CERT_FOLDER/$DDNS_DOMAIN.key"
 CERT_TRANSPORT="--httpport $CERT_LOCAL_PORT"
 [ "$CERT_METHOD" == "tls" ] && CERT_TRANSPORT="--alpn --tlsport $CERT_LOCAL_PORT"
}

function issue_certificate()  {
 local cmd="$SUDO $CERT_CMD --issue -d $DDNS_DOMAIN --standalone $CERT_TRANSPORT"
 
 [ "$CERT_TYPE" == "ecc" ] && cmd="$cmd --keylength ec-384"
 
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
 
 [ "$CERT_TYPE" == "ecc" ] && cmd="$cmd --ecc"
  
 debug "CMD: $cmd"
 local output="$($cmd)"
 debug "Result: $output"
 
 if [[ $output != *"Your cert key"* ]]; then
  return 0
 else
  return 1
 fi
}
