#!/bin/bash

CMD_PATH=$(dirname "$0")
source $CMD_PATH/common.sh

##############################################################
# Acme.sh based wrapper to handle certificate issue and renew
##############################################################

check_env "MAIN_USER CERT_ROOT CERT_TYPE CERT_METHOD CERT_LOCAL_PORT"

CERT_CMD=/home/$MAIN_USER/.acme.sh/acme.sh

CERT_FOLDER=$CERT_ROOT/$DDNS_DOMAIN
if [ "$CERT_TYPE" == "ecc" ]; then
 CERT_FOLDER="$CERT_FOLDER"_ecc
fi

CERT_FULLCHAIN="$CERT_FOLDER/fullchain.cer"
CERT_KEY="$CERT_FOLDER/$DDNS_DOMAIN.key"

case $CERT_METHOD in
 http)
  CERT_TRANSPORT="--httpport $CERT_LOCAL_PORT"
  ;;
 tls)
  CERT_TRANSPORT="--alpn --tlsport $CERT_LOCAL_PORT"
  ;;
 *)
  CERT_TRANSPORT=""
  ;;
esac

function issue_cert()  {
 local cmd="$SUDO $CERT_CMD --issue -d $DDNS_DOMAIN --standalone $CERT_TRANSPORT"
 
 if [ "$CERT_TYPE" == "ecc" ]; then
  cmd="$cmd --keylength ec-384"
 fi
 
 log "Begin to issue certificate: $cmd"
 local output="$($cmd)"
 log "Result: $output"
 
 if [[ $output != *"Your cert key"* ]]; then
  issue_cert="OK"
 fi
}

function renew_cert()  {
 local cmd="$SUDO $CERT_CMD --renew -d $DDNS_DOMAIN --standalone $CERT_TRANSPORT"
 
 if [ "$CERT_TYPE" == "ecc" ]; then
  cmd="$cmd --ecc"
 fi
 
 log "Begin to renew certificate: $cmd"
 local output="$($cmd)"
 log "Result: $output"
 
 if [[ $output != *"Your cert key"* ]]; then
  renew_cert="OK"
 fi
}
