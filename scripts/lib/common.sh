#!/usr/bin/env bash

CMD_PATH=$(dirname "$0")
source $CMD_PATH/env.conf

# Common variables
NOW=$(date +"%Y_%m_%d-%H_%M_%S")
TODAY=$(date +%Y_%m_%d)
PROGRAM="${0##*/}"
LOG=/tmp/$PROGRAM.log
ENABLE_LOGGING=1
DEBUG=1
MAIN_USER_ID=$(id -u $MAIN_USER)

############# Env Checking #############

function check_os_type() {
 [ "$OS_TYPE" != "" ] && return

 if [ -x "$(command -v /usr/bin/apt-get)" ]; then
  OS_TYPE="debian"
  MAIN_BIN="/usr/bin"
  return
 elif [ -x "$(command -v /usr/bin/yum)" ]; then
  OS_TYPE="centos"
  MAIN_BIN="/usr/bin"
  return
 elif [ -x "$(command -v /opt/bin/opkg)" ]; then
  OS_TYPE="entware"
  MAIN_BIN="/opt/bin"
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

function show_usage() {
 local msg=$1

 color_echo orange "Usage: $PROGRAM $msg"
 exit 1
}

############# Logging #############

NOCOLOR="\e[m"

function color_echo() {
 local color=$1
 local msg=$2

 case $color in
  (red|RED)			color="\e[31m";;
  (green|GREEN)		color="\e[32m";;
  (yellow|YELLOW)	color="\e[33m";;
  (purple|PURPLE)	color="\e[35m";;
  (cyan|CYAN)		color="\e[36m";;
  (orange|ORANGE)	color="\e[91m";;
  (*)				color="$NOCOLOR";;
 esac
 
 echo -e "${color}$msg${NOCOLOR}"
}

function log() {
 local TIMESTAMP=$(date +%Y.%m.%d_%H:%M:%S)
 color_echo green "$TIMESTAMP $1"
 [ "$ENABLE_LOGGING" == "1" ] && echo "$TIMESTAMP $1" >> $LOG
}

function log_error() {
 local TIMESTAMP=$(date +%Y.%m.%d_%H:%M:%S)
 color_echo red "$TIMESTAMP $1"
 [ "$ENABLE_LOGGING" == "1" ] && echo "$TIMESTAMP $1" >> $LOG
}

function debug() {
 [ "$DEBUG" != "1" ] && return

 local TIMESTAMP=$(date +%Y.%m.%d_%H:%M:%S)
 color_echo yellow "$TIMESTAMP $1"
}

function fatal_error() {
 color_echo red "$1"
 exit 1
}

############# Locking (single-run) #############

LOCKFILE=/tmp/$PROGRAM.lock

function cleanup() {
  if [ "$LOCKFILE" != "" ]; then
    log "Process [$PROGRAM] exiting ..."
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
    log "Process [$PROGRAM] started."
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

DIFF_CMD="diff --color"
[ -x "$(command -v colordiff)" ] && DIFF_CMD="colordiff"

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

function conditional_copy() {
 local condition="$1"
 local src_folder=$2
 local dst_folder=$3

 # condition is to test if the command exists
 [ ! -x "$(command -v $condition)" ] && return

 #debug "Found command: $condition. Will copy related files to $dst_folder."
 [ ! -d $dst_folder ] && $SUDO mkdir $dst_folder
 copy_files "$src_folder/*" $dst_folder
}
