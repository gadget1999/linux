#!/bin/bash

CMD_PATH=$(dirname "$0")
source $CMD_PATH/env.conf

RED=`tput setaf 1`
GREEN=`tput setaf 2`
NOCOLOR=`tput sgr0`
function log() {
    local TIMESTAMP=$(date +%Y.%m.%d_%H:%M:%S)

    echo "${GREEN}$TIMESTAMP $1${NOCOLOR}"
    echo "$TIMESTAMP $1" >> $LOG
}

function debug() {
    if [ "$DEBUG" == "1" ]; then
        local TIMESTAMP=$(date +%Y.%m.%d_%H:%M:%S)

        echo "$TIMESTAMP $1"
    fi
}

LOCKFILE=/tmp/$PROGRAM.lock

function cleanup() {
  if [ "$LOCKFILE" != "" ]; then
    log "Process exiting ..."
    rm -r $LOCKFILE
    exit 2
  fi
}

function lock() {
  Lock
}

function Lock() {
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

function mqtt_pub() {
  /home/share/bin/mqtt-pub "$1" "$2" $3
}

function combine_topics
{
  combine_topics=""
  for a in "$@" # Loop over arguments
  do
    combine_topics+=" -t $a/# "
  done
}

function check_env
{
 local VARS=$1
 for VAR in ${VARS[*]}; do
  if [[ ${!VAR} == "" ]]; then
   log "Invalid ENV variables found: $VAR"
   exit
  fi
 done
}
