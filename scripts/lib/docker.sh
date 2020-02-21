#!/usr/bin/env bash

CMD_PATH=$(dirname "$0")
source $CMD_PATH/lib/common.sh

#####################################
## Docker helper functions
#####################################

function setup_container_user() {
 check_env "CONTAINER_USER CONTAINER_UID"
 [ "$(id -u $CONTAINER_USER)" != "" ] && return

 debug "Creating user [$CONTAINER_USER]"
 sudo useradd -M -u $CONTAINER_UID $CONTAINER_USER --shell=/bin/false --home-dir=/non-exist
}

function grant_container_access() {
 setup_container_user

 for volume in "$@"; do
  if [[ $volume = /* ]]; then
   local uid=$(stat -c '%u' $volume)
   [ "$uid" == "$CONTAINER_UID" ] && continue

   debug "Changing permission for $volume..."
   sudo chown $CONTAINER_USER -R $volume
   sudo chgrp $CONTAINER_USER -R $volume 
  fi
 done 
}

# need to match pattern of end-of-line 'pattern$'
function container_exists() {
  sudo docker ps -a | grep " $1$" &> /dev/null
  if [ $? == 0 ]; then
    echo "true"
  else
    echo "false"
  fi
}

function is_container_running() {
  sudo docker ps | grep " $1$" &> /dev/null
  if [ $? == 0 ]; then
    echo "true"
  else
    echo "false"
  fi
}

function delete_container() {
 local container_name=$1

 stop_container $container_name
 [ $(container_exists $container_name) != "true" ] && return

 debug "Deleting container: $container_name"
 sudo docker rm $container_name
}

function stop_container() {
 local container_name=$1
 [ $(is_container_running $container_name) != "true" ] && return

 debug "Stopping container: $container_name"
 sudo docker stop $container_name
}

function start_container() {
 local container_name=$1
 [ $(is_container_running $container_name) == "true" ] && return

 if [ $(container_exists $container_name) != "true" ]; then
  color_echo red "Container does not exist: $container_name"
  return
 fi

 debug "Starting container: $container_name"
 sudo docker start $container_name
 sleep 3
}

function restart_container() {
 local container_name=$1
 local threshold=$2

 [ $(is_container_running $container_name) != "true" ] && return

 local usage=$(docker stats --no-stream --format "{{.Name}} {{.MemPerc}}" | grep "$container_name" | awk '{print substr($2,0,length($2)-1)}')

 # bash does not support comparing float numbers, need to convert to integer first
 usage=${usage%.*}
 threshold=${threshold%.*}

 # comparing strings directly could give wrong results, for example 8 > 10, need to use -gt
 if [[ "$usage" -gt "$threshold" ]]; then
  log "Container [$container_name] memory usage ($usage%) over threshold ($threshold%). Restarting..."
  stop_container $container_name
  start_container $container_name
 fi
}

# enter an existing container
function enter_container() {
 local container_name=$1

 start_container $container_name
 if [ $(is_container_running $container_name) != "true" ]; then
  color_echo red "Container is not running: $container_name"
  return
 fi

 #color_echo red ">>> Now in container: $container_name"
 sudo docker exec -it $container_name sh
 #debug ">>> Now back to host"
}

#####################################
## Creating containers
#####################################

DEBUG_DOCKER=0

function new_container() {
 [ $# != 6 ] && fatal_error "Invalid number of arguments used: $#"

 local container_name=$1
 local image_name=$2
 local stateless=$3
 local background=$4
 local -n extra_options=$5 # use an array to avoid space/quote issues
 local -n entrypoint_options=$6

 # override to foreground if in DEBUG mode
 [ "$DEBUG_DOCKER" != "0" ] && background="foreground"

 # if need to restart, set to stateful (docker run --restart conflicts with --rm)
 case "${extra_args[@]}" in  *"--restart"*) stateless="stateful" ;; esac

 local container_host="$container_name"
 [ "$stateless" == "stateless" ] && extra_options=(--rm "${extra_options[@]}")

 if [ "$background" == "background" ]; then
  extra_options=(-d "${extra_options[@]}")
 else
  extra_options=(-it "${extra_options[@]}")
 fi

 if [ "$(container_exists $container_name)" == "true" ]; then
  # for non-stateless containers, stop if already exists
  if [ "$stateless" != "stateless" ]; then
   color_echo red "Container already exists: $container_name"
   return
  fi
  # for stateless containers, stop first
  stop_container $container_name
 fi

 debug "Update image: $image_name"
 sudo docker pull $image_name

 local docker_options=(
  run --init
  -v /etc/localtime:/etc/localtime:ro
  --tmpfs /run
  --tmpfs /tmp
  --name $container_name
  -h $container_host
  "${extra_options[@]}"
  $image_name
  "${entrypoint_options[@]}"
  )

 [ "$DEBUG_DOCKER" != "0" ] && test-args "${docker_options[@]}"

 debug "Start container (at $background): $container_name"
 sudo docker "${docker_options[@]}"

 # check if the container is started if on background
 if [ "$background" == "background" ]; then
  sleep 3
  if [ $(is_container_running $container_name) != "true" ]; then
   color_echo red "The container may not be capable of running at background."
   return
  fi
 fi
}

function new_container_service() {
 local container_name=$1
 local image_name=$2
 local -n extra_args=$3 # use an array to avoid space/quote issues
 local -n entrypoint_args=$4

 # by default, services are backgroun stateless containers
 local stateless="stateless"
 local background="background"

 if [ "$DEBUG_DOCKER" != "0" ]; then
  # override to foreground if in DEBUG mode
  background="foreground"
 else
  # if it's service, best to restart until stopped
  extra_args=("${extra_args[@]}" --restart unless-stopped)
  # docker run --restart conflicts with --rm, so set to stateful
  stateless="stateful"
 fi

 # delete existing container (assuming service containers do not need to persist)
 delete_container $container_name

 # container services are background stateless containers
 new_container $container_name $image_name $stateless $background extra_args entrypoint_args
}

function new_container_vm() {
 local container_name=$1
 local image_name=$2
 local -n extra_args=$3 # use an array to avoid space/quote issues
 local -n entrypoint_args=$4

 # container vm should be backgroun and stateful
 local stateless="stateful"
 local background="background"

 if [ "$DEBUG_DOCKER" != "0" ]; then
  # override to foreground if in DEBUG mode
  background="foreground"
 else
  # if it's service, best to restart until stopped
  extra_args=("${extra_args[@]}" --restart unless-stopped)
  # docker run --restart conflicts with --rm, so set to stateful
  stateless="stateful"
 fi

 # do not delete existing container vm (vm needs to persist its state)
 #delete_container $container_name

 # container services are background stateless containers
 new_container $container_name $image_name $stateless $background extra_args entrypoint_args
}

function container_cli() {
 local container_name=$1
 local image_name=$2
 local -n extra_args=$3 # use an array to avoid space/quote issues
 local -n entrypoint_args=$4

 # container cli is just CLI in a container, should be foreground and stateless
 local stateless="stateless"
 local background="foreground"

 # container services are background stateless containers
 new_container $container_name $image_name $stateless $background extra_args entrypoint_args
}

function backup_container()    {
  local container=$1
  local filename="$2-container-$container.tar"

  log "Exporting docker container [$container] to: $filename..."
  sudo docker export -o $filename $container

  # verify if the docker image backup is valid
  if ! tar tf $filename &> /dev/null; then
    log "Container backup failed."
  else
    log "Container backup succeeded."
  fi
}

function backup_volume()    {
  local volume=$1
  local filename="$2-vol-$volume.tar"

  debug "Exporting docker volume [$volume] to: $filename..."
  sudo docker run -d --rm -v $volume:/backup --name "backup-$volume" alpine sh
  sudo docker cp backup-$volume:/backup /tmp/backup-$volume
  tar -C /tmp/backup-$volume -cvf $filename .
  sudo docker stop backup-$volume
  sudo rm -rf /tmp/backup-$volume

  # verify if the docker image backup is valid
  if ! tar tf $filename &> /dev/null; then
    debug "Volume backup failed."
  else
    debug "Volume backup succeeded: $filename"
  fi
}

function restore_volume()    {
  local volume=$2
  local filename=$1

  debug "Create docker volume [$volume]"
  sudo docker volume create $volume

  debug "Extracting backup content..."
  mkdir /tmp/restore-$volume
  cp $filename /tmp/restore-$volume/restore-$volume.tar
  cd /tmp/restore-$volume
  tar -xvf restore-$volume.tar
  rm  restore-$volume.tar

  debug "Restoring volume content..."
  sudo docker run -d --rm -v $volume:/restore --name "restore-$volume" alpine
  sudo docker cp /tmp/restore-$volume/. restore-$volume:/restore
  sudo docker rm restore-$volume

  debug "List restored content"
  sudo docker run -it --rm -v $volume:/restore alpine ls -alR /restore

  debug "Clean up resources"
  sudo rm -rf /tmp/restore-$volume
}

function check_volume()    {
  local volume=$1

  debug "Mounting volume to a temporary container..."
  sudo docker run -it --rm -v $volume:/vol alpine sh
}

function squash_image()    {
  local image=$1

  log "Create a temp container for [$image]"
  sudo docker run -d --name squash $image

  log "Export container"
  sudo docker export -o /tmp/squash.tar squash
  sudo docker stop squash
  sudo docker rm squash

  log "Import squashed image"
  sudo docker rmi $image
  sudo docker import /tmp/squash.tar $image
  sudo rm /tmp/squash.tar
}

function delete_orphan_images()    {
  sudo docker images --quiet --filter=dangling=true | \
    xargs --no-run-if-empty docker rmi
}

function delete_orphan_volumes()    {
  sudo docker volume list --quiet --filter=dangling=true | \
    xargs --no-run-if-empty docker rmi
}

####################
# Bootstraping
####################

check_packages "docker"
check_root
