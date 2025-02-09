#!/usr/bin/env bash

CMD_PATH=$(dirname "$0")

# Common variables
NOW=$(date +"%Y_%m_%d-%H_%M_%S")
TODAY=$(date +%y%m%d)
EPOCH=$(date +%s)
PROGRAM="${0##*/}"
LOG=/tmp/$PROGRAM.log
ENABLE_LOGGING=1
DEBUG=1

############# Env Checking #############

function load_env() {
 # ENV variables are not available in cron jobs
 local current_user=$(whoami)
 local home_dir=/home/$current_user
 [ "$current_user" == "root" ] && home_dir=/root

 ENV_FILE=$home_dir/.env.conf
 if [ -e $ENV_FILE ]; then
  source $ENV_FILE
 else
  log_error "ENV file not found: $ENV_FILE"
 fi
}

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
   fatal_error "Invalid ENV variables found: $VAR"
  fi
  # debug "$VAR=${!VAR}"
 done
}

function print_env() {
 local VARS=$1
 for VAR in ${VARS[*]}; do
  debug "$VAR=${!VAR}"
 done
}

function check_packages() {
 local PACKAGES=$1
 for PACKAGE in ${PACKAGES[*]}; do
  if [ ! -x "$(command -v $PACKAGE)" ]; then
   fatal_error "Required package not found: $PACKAGE"
  fi
  # debug "$VAR=${!VAR}"
 done
}

function assert_success() {
 local msg=$1

 [ "$?" != "0" ] && fatal_error "$msg failed ($?)."
}

function check_root() {
 [ "$REQUIRES_ROOT" == "" ] && return
 [ "$(id -u)" == "0" ] && return

 fatal_error "This command requires root privilege."
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

LOCKFILE=/tmp/$PROGRAM.$(id -u).lock

function cleanup() {
  if [ "$LOCKFILE" != "" ]; then
    debug "Releasing lock: $LOCKFILE ..."
    rm -r $LOCKFILE
    exit 2
  fi
}

function kill_process_tree() {
 check_packages "pgrep"

 local pid=$1
 log "Kill process tree: PID=$pid"
 kill $(pgrep -P $pid)
 kill $pid
}

function lock() {
 trap cleanup EXIT
 [ "$1" != "" ] && local expiration=$(($(date +%s) + $1))

 if [ -e $LOCKFILE ]; then
  local firstline=$(head -n 1 $LOCKFILE)
  local pid=$(echo $firstline | cut -f1 -d-)
  local expires=$(echo $firstline | cut -f2 -d-)
  if [ "$expires" == "" ] || [ $(date +%s) -lt $expires ]; then
   debug "$PROGRAM is already running (lock expires: $expires)"
   LOCKFILE="" # avoid clean-up function deleting lock file
   exit 1
  else
   log_error "$PROGRAM lock expired ($expires). Clean up and exit."
   kill_process_tree $pid
   exit 2
  fi
 else
  debug "Process [$PROGRAM] started. (PID:$$, lock expires: $expiration)"
  touch $LOCKFILE
  echo "$$-$expiration" > $LOCKFILE
 fi
}

function named_lock() {
 local lock_name=$1
 [ "$lock_name" == "" ] && fatal_error "Lock name is empty."
 LOCKFILE=/tmp/$PROGRAM-$lock_name.lock
 trap cleanup EXIT
 [ "$2" != "" ] && local expiration=$(($(date +%s) + $1))

 if [ -e $LOCKFILE ]; then
  local firstline=$(head -n 1 $LOCKFILE)
  local pid=$(echo $firstline | cut -f1 -d-)
  local expires=$(echo $firstline | cut -f2 -d-)
  if [ "$expires" == "" ] || [ $(date +%s) -lt $expires ]; then
   debug "$PROGRAM-$lock_name is already running (lock expires: $expires)"
   LOCKFILE="" # avoid clean-up function deleting lock file
   exit 1
  else
   log_error "$PROGRAM-$lock_name lock expired ($expires). Clean up and exit."
   kill_process_tree $pid
   exit 2
  fi
 else
  debug "Process [$PROGRAM-$lock_name] started. (PID:$$, lock expires: $expiration)"
  touch $LOCKFILE
  echo "$$-$expiration" > $LOCKFILE
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

###### Cron (track run time for schedules not supported by cron ######

function days_since_lastrun()   {
 local track_file=/home/share/.$PROGRAM.lastrun
 local lastrun_time=0
 local now=$(date +%s)
 [ -s $track_file ] && read -r lastrun_time < $track_file
 days_since_lastrun=$(((now-lastrun_time)/86400))
}

function set_lastrun()   {
 local track_file=/home/share/.$PROGRAM.lastrun
 local now=$(date +%s)
 log "Setting lastrun timestamp: $now"
 echo $now > $track_file
 [ "$?" != "0" ] && log_error "Failed to set timestamp."
}

############# CIFS #############

function mount_cifs_share() {
 local profile=$1
 local profile_path="/home/$MAIN_USER/.smbprofiles/$profile"
 # profile should have definitions for: SMB_VER CIFS_SERVER CIFS_NAME CIFS_USER CIFS_PWD
 source $profile_path
 check_env "SMB_VER CIFS_SERVER CIFS_NAME CIFS_USER CIFS_PWD"
 local mount_point=/mnt/$profile
 local unc=//$CIFS_SERVER/$CIFS_NAME

 if [ "$(df | grep ""$mount_point"")" ]; then
  debug "Share [$mount_point] already mounted."
  mount_cifs_share=0
  return
 fi

 if [ ! -d $mount_point ] ; then
  debug "Creating mount point: $mount_point"
  sudo mkdir -p $mount_point
 fi

 sudo /bin/mount -t cifs \
  -o vers=$SMB_VER,username=$CIFS_USER,password=$CIFS_PWD,rw,iocharset=utf8,file_mode=0777,dir_mode=0777 \
  $unc $mount_point
 if [ "$(df | grep ""$mount_point"")" ]; then
  log "[$mount_point] mounted: $unc"
  mount_cifs_share=2
  return  
 else
  log_error "Failed to mount [$unc] as [$mount_point]."
  mount_cifs_share=1
  return
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
 if sudo test ! -f $source ; then
  debug "$source is not a regular file"
  return 1
 fi

 # copy if target does not exist
 if sudo test ! -f $target ; then
  log "Copying $target"
  $SUDO cp $source $target
  return 1
 fi

 # ask for confirmation if files are different
 local md5source=( $(sudo md5sum "$source") )
 local md5target=( $(sudo md5sum "$target") )
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

function move_files() {
 local source_folder=$1
 local target_folder=$2
 local patterns=$3

 for pattern in ${patterns[*]}; do
  # use IFS to avoid space-in-file-name issue
  # NOTE: unset ASAP as it will break command line with arguments
  IFS=$'\n'
  local files=$source_folder/$pattern
  for filepath in $files; do
   unset IFS
   [ ! -e "$filepath" ] && continue
   local filename=$(basename "$filepath")
   local target=$target_folder/$filename
   log "Moving file [$filepath] to [$target]..."
   mv "$filepath" "$target"
  done
 done
}

function conditional_copy() {
 local condition="$1"
 local src_folder=$2
 local dst_folder=$3

 # condition is to test if the command exists
 [ ! -x "$(command -v $condition)" ] && return

 #debug "Found command: $condition. Will copy related files to $dst_folder."
 [ ! -d $dst_folder ] && $SUDO mkdir -p $dst_folder
 copy_files "$src_folder/*" $dst_folder
}

function move_to_tmpfs() {
  local filepath=$1
  local bakfile="$filepath.sav"
  local filename=${1##*/}  # get leaf name
  local tmpfolder=/tmp/moved-tmpfs
  local tmpfile=$tmpfolder/$filename

  if [[ ! -d "$tmpfolder" ]]; then
    debug "Creating temp folder..."
    sudo mkdir -p $tmpfolder
    sudo chmod 777 $tmpfolder
  fi  

  debug "Checking $filepath link status"
  if sudo test -L $filepath ; then
    if sudo test -e $filepath ; then
      debug "Good link"
      return 0
    else
      debug "Broken link"
      if sudo test -e $bakfile ; then
        log "Copying $bakfile to $tmpfile"
        sudo cp -p $bakfile $tmpfile
        return 0
      fi
      return 3
    fi
  elif sudo test -e $filepath ; then
    debug "Not a link"
  else
    debug "Missing file"
    return 2
  fi

  # up to this point, converting regular file to link
  debug "Copying $filepath to $tmpfile"
  sudo cp -p $filepath $tmpfile
  if sudo test -e $bakfile ; then
   debug "Backup file exists, deleting file to be linked"
   sudo rm $filepath
  else
   log "Backing up file to $bakfile"
   sudo mv -n $filepath $bakfile
  fi

  log "Linking $filepath to $tmpfile"
  sudo ln -s $tmpfile $filepath

  sudo ls -l $filepath
}

function move_locked_file() {
 local file=$1
 local service=$2

 [ -L ${file} ] && [ -e ${file} ] &&
  debug "Skipping good link: $file" && return

 debug "Shutdown service: $service"
 sudo systemctl stop $service

 move_to_tmpfs $file

 debug "Start service: $service"
 sudo systemctl start $service
}

function update_file_from_dropbox() {
 check_packages "dropbox"
 
 local remote_file=$1
 local local_file=$2

 # download from dropbox
 local tmp_file=/tmp/$NOW.tmp
 debug "Downloading $remote_file from DropBox..."
 dropbox download $remote_file $tmp_file
 if [ ! -s $tmp_file ]; then
  log_error "Failed to download file: $remote_file."
  return
 fi

 copy_file $tmp_file $local_file "overwrite"
 rm $tmp_file
}

function update_file_from_box() {
 check_packages "box"

 local remote_file_id=$1
 local remote_file_name=$2
 local local_file=$3

 # download from box
 local tmp_folder=/tmp/$NOW.tmp
 debug "Downloading $remote_file_name from Box ..."
 mkdir -p $tmp_folder
 box files:download $remote_file_id --destination $tmp_folder
 local tmp_file=$tmp_folder/$remote_file_name
 if [ ! -s $tmp_file ]; then
  log_error "Failed to download file: $remote_file_name"
  return
 fi

 copy_file $tmp_file $local_file "overwrite"
 rm -R $tmp_folder
}

function download_file() {
 local remote_file_url=$1
 local remote_file_name=$2
 local local_file=$3

 # download from url
 local tmp_file=/tmp/$NOW.tmp
 debug "Downloading $remote_file_name from internet ..."
 wget -q $remote_file_url -O $tmp_file
 if [ ! -s $tmp_file ]; then
  log_error "Failed to download file: $remote_file_name"
  return
 fi

 copy_file $tmp_file $local_file "overwrite"
 rm -R $tmp_file
}

function update_file_from_box_link() {
 local remote_file_id=$1
 local remote_file_url="https://app.box.com/shared/static/$remote_file_id"
 local remote_file_name=$2
 local local_file=$3

 download_file "$remote_file_url" "$remote_file_name" "$local_file"
}

function is_file_modified_recently() {
 local file_path=$1
 local seconds=$2

 $SUDO [ ! -e "$file_path" ] && \
  log_error "File $file_path doesn't exist." && \
  return 2
 $SUDO [ ! -f "$file_path" ] && \
  log_error "File $file_path is not a regular file." && \
  return 3

 local modified=$($SUDO date -r "$file_path" +%s)
 local diff_time=$((EPOCH - modified))

 if [ "$diff_time" -le $seconds ]; then
  return 0
 else
  log_error "File $file_path is not recently updated: delta=$diff_time"
  return 1
 fi
}

####################
# Bootstraping
####################
load_env
