#!/usr/bin/env bash

CMD_PATH=$(dirname "$0")
source $CMD_PATH/lib/common.sh
source $CMD_PATH/lib/docker.sh

##############################################################
# Acme.sh docker based wrapper certificate issue and renew
##############################################################

function check_cert_env() {
 check_env "CERT_STORAGE CERT_LOCAL_PORT DDNS_DOMAIN"

 CERT_FOLDER=$CERT_STORAGE/$DDNS_DOMAIN
 [ "$CERT_TYPE" == "ecc" ] && CERT_FOLDER="$CERT_FOLDER"_ecc
 CERT_FULLCHAIN="$CERT_FOLDER/fullchain.cer"
 CERT_KEY="$CERT_FOLDER/$DDNS_DOMAIN.key"
}

ACME_IMAGE_NAME="neilpang/acme.sh"
ACME_DOCKER_OPTS=(
 -v $CERT_STORAGE:/acme.sh
 -p 443:$CERT_LOCAL_PORT
 )

function issue_certificate_docker()  {
 check_env "CERT_STORAGE"

 local force=$1
 local cmd_args=(
  --issue
  --ocsp
  $force
  -d $DDNS_DOMAIN
  --standalone
  --alpn
  --tlsport $CERT_LOCAL_PORT
  --server letsencrypt
  --keylength ec-384
  --debug
  )

 container_cli "$ACME_IMAGE_NAME" ACME_DOCKER_OPTS cmd_args
 if is_file_modified_recently "$CERT_FULLCHAIN" 120 ; then
  return 0
 else
  return 1
 fi
}

function renew_certificate_docker()  {
 check_env "CERT_STORAGE"

 local force=$1
 local cmd_args=(
  --renew
  $force
  -d $DDNS_DOMAIN
  --standalone
  --httpport $CERT_LOCAL_PORT
  --server letsencrypt
  --keylength ec-384
  )

 container_cli "$ACME_IMAGE_NAME" ACME_DOCKER_OPTS cmd_args
 if is_file_modified_recently "$CERT_FULLCHAIN" 120 ; then
  return 0
 else
  return 1
 fi
}
