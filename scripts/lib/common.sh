#!/bin/bash

CMD_PATH=$(dirname "$0")
source $CMD_PATH/env.conf

# Common variables
NOW=$(date +"%Y.%m.%d-%H:%M:%S")
TODAY=$(date +%Y_%m_%d)
PROGRAM="${0##*/}"
LOG=/tmp/$PROGRAM.log
DEBUG=1

############# Env Checking #############

function check_os_type() {
 [ "$OS" != "" ] && return
 
 if [ -x "$(command -v /usr/bin/apt-get)" ]; then
  OS="debian"
  return
 elif [ -x "$(command -v /usr/bin/yum)" ]; then
  OS="centos"
  return
 fi
}

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


############# Files #############

DIFF_CMD="/usr/bin/diff --color"
[ -x "$(command -v /usr/bin/colordiff)" ] && DIFF_CMD="/usr/bin/colordiff"

NEED_CONFIRM="yes"
function copy_file() {
 local source=$1
 local target=$2
 local overwrite=$3

 # see if this is a regular file
 [ ! -f $source ] && return 0
 
 # copy if target does not exist
 if [ ! -f $target ]; then
  log "Copying $target"
  $SUDO cp $source $target
  return 1
 fi

 # do not overwrite conf files
 [[ $target == *".conf" ]] && return 0
 
 # ask for confirmation if files are different
 local md5source=( $(md5sum "$source") )
 local md5target=( $(md5sum "$target") )
 [ $md5source == $md5target ] && return 0
 
 # file changed, asking for confirmation
 if [[ "$overwrite" == "overwrite" || "$NEED_CONFIRM" != "yes" ]]; then
  log "Updating $target"
  $SUDO cp $source $target
  return 1
 fi

 echo "================= $target ================="
 #diff --color --side-by-side $target $source
 $DIFF_CMD $target $source
 read -p "Overwrite $target (Yes/[No]/All)?" choice
 case "$choice" in
  y|Y )
   log "Updating $target"
   $SUDO cp $source $target
   return 1
   ;;
  A|a )
   NEED_CONFIRM="no"
   log "Updating $target"
   $SUDO cp $source $target
   return 1
   ;;
  * )
   return 0
   ;;
 esac
}

function copy_files() {
 local files=$1
 local folder=$2

 for filepath in $files; do
  filename=$(basename "$filepath")
  target=$folder/$filename
  copy_file $filepath $target
 done
}

