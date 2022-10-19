#!/usr/bin/env bash

CMD_PATH=$(dirname "$0")
source $CMD_PATH/lib/common.sh

##############################################################
# Acme.sh based wrapper to handle certificate issue and renew
##############################################################

function check_cert_env() {
 check_env "CERT_ROOT CERT_LOCAL_PORT DDNS_DOMAIN"

 CERT_CMD=$CERT_ROOT/acme.sh
 CERT_FOLDER=$DDNS_DOMAIN
 [ "$CERT_TYPE" == "ecc" ] && CERT_FOLDER="$CERT_FOLDER"_ecc
 CERT_FULLCHAIN="$CERT_FOLDER/fullchain.cer"
 CERT_KEY="$CERT_FOLDER/$DDNS_DOMAIN.key"
 CERT_TRANSPORT="--standalone --httpport $CERT_LOCAL_PORT"
 [ "$CERT_METHOD" == "tls" ] && CERT_TRANSPORT="--alpn --tlsport $CERT_LOCAL_PORT"
}

function issue_certificate()  {
 local cmd="$CERT_CMD --issue --ocsp -d $DDNS_DOMAIN $CERT_TRANSPORT"

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

function issue_certificate_docker()  {
 check_env "$CERT_STORAGE"
 check_packages "docker"
 local CERT_CMD="docker run --rm -it
           -v $CERT_STORAGE:/acme.sh
           -p 443:$CERT_LOCAL_PORT
           neilpang/acme.sh"
 local cmd="$CERT_CMD --issue --ocsp -d $DDNS_DOMAIN $CERT_TRANSPORT
           --server letsencrypt"

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

function issue_certificate_azdns()  {
 local cmd="$CERT_CMD --issue --dns dns_azure -d $AZDNS_DOMAIN -d *.$AZDNS_DOMAIN "

 [ "$CERT_TYPE" == "ecc" ] && cmd="$cmd --keylength ec-384"

 debug "CMD: $cmd"
 $cmd
}

function renew_certificate()  {
 local force=$1
 local cmd="$CERT_CMD --renew $force -d $DDNS_DOMAIN $CERT_TRANSPORT"
 
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
