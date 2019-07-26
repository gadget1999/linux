#!/bin/bash

CMD_PATH=$(dirname "$0")
source $CMD_PATH/env.conf

# Common variables
NOW=$(date +"%Y.%m.%d-%H:%M:%S")
TODAY=$(date +%Y_%m_%d)
PROGRAM="${0##*/}"
LOG=/tmp/$PROGRAM.log
DEBUG=1

############# Env checking #############

function check_env() {
 local VARS=$1
 for VAR in ${VARS[*]}; do
  if [[ ${!VAR} == "" ]]; then
   log_error "Invalid ENV variables found: $VAR"
   exit
  fi
  # debug "$VAR=${!VAR}"
 done
}

function check_packages() {
 local PACKAGES=$1
 for PACKAGE in ${PACKAGES[*]}; do
  if [ ! -x "$(command -v $PACKAGE)" ]; then
   log_error "Required package not found: $PACKAGE"
   exit
  fi
  # debug "$VAR=${!VAR}"
 done
}

############# Logging #############

RED=`tput setaf 1`
GREEN=`tput setaf 2`
NOCOLOR=`tput sgr0`
function log() {
    local TIMESTAMP=$(date +%Y.%m.%d_%H:%M:%S)

    echo "${GREEN}$TIMESTAMP $1${NOCOLOR}"
    echo "$TIMESTAMP $1" >> $LOG
}

function log_error() {
    local TIMESTAMP=$(date +%Y.%m.%d_%H:%M:%S)

    echo "${RED}$TIMESTAMP $1${NOCOLOR}"
    echo "$TIMESTAMP $1" >> $LOG
}

function debug() {
    if [ "$DEBUG" == "1" ]; then
        local TIMESTAMP=$(date +%Y.%m.%d_%H:%M:%S)

        echo "$TIMESTAMP $1"
    fi
}

############# Locking (single-run) #############

LOCKFILE=/tmp/$PROGRAM.lock

function cleanup() {
  if [ "$LOCKFILE" != "" ]; then
    log "Process exiting ..."
    rm -r $LOCKFILE
    exit 2
  fi
}

function lock() {
  trap cleanup EXIT

  if [ -e $LOCKFILE ]; then
    debug "$PROGRAM is already running."
    LOCKFILE=""
    exit 1
  else
    log "Process started."
    touch $LOCKFILE
  fi
}

function should_continue() {
  if [ ! -f $LOCKFILE ]; then
    debug "Stop signal detected. $PROGRAM will exit."
    return 1;
  else
    return 0; # 0 means success (true condition)
  fi
}
