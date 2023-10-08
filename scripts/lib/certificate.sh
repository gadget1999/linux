#!/usr/bin/env bash

CMD_PATH=$(dirname "$0")
source $CMD_PATH/lib/common.sh
source $CMD_PATH/lib/docker.sh

##############################################################
# Acme.sh docker based wrapper certificate issue and renew
##############################################################

function check_cert_env() {
 check_env "CERT_ROOT CERT_LOCAL_PORT DDNS_DOMAIN"

 CERT_FOLDER="$DDNS_DOMAIN"
 [ "$CERT_TYPE" == "ecc" ] && CERT_FOLDER="$CERT_FOLDER"_ecc
 CERT_FULLCHAIN="$CERT_FOLDER/fullchain.cer"
 CERT_FULLCHAIN_PATH="$CERT_ROOT/$CERT_FULLCHAIN"
 CERT_KEY="$CERT_FOLDER/$DDNS_DOMAIN.key"
}

ACME_IMAGE_NAME="neilpang/acme.sh"
ACME_DOCKER_OPTS=(
 -v $CERT_ROOT:/acme.sh
 --net=host
 )

function issue_certificate_docker()  {
 local force=$1
 local cmd_args=(
  --issue
  --ocsp
  $force
  -d $DDNS_DOMAIN
  --standalone
  --server letsencrypt
  --keylength ec-384
  --debug
  )

 container_cli "$ACME_IMAGE_NAME" ACME_DOCKER_OPTS cmd_args
 if is_file_modified_recently "$CERT_FULLCHAIN_PATH" 120 ; then
  return 0
 else
  return 1
 fi
}

function renew_certificate_docker()  {
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
 if is_file_modified_recently "$CERT_FULLCHAIN_PATH" 120 ; then
  return 0
 else
  return 1
 fi
}
