#!/usr/bin/env bash

CMD_PATH=$(dirname "$0")
source $CMD_PATH/lib/common.sh

#####################################
## Docker helper functions
#####################################

check_packages "docker"

# need to match pattern of end-of-line 'pattern$'
function container_exists() {
  docker ps -a | grep " $1$" &> /dev/null
  if [ $? == 0 ]; then
    echo "true"
  else
    echo "false"
  fi
}

function is_container_running() {
  docker ps | grep " $1$" &> /dev/null
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
 docker rm $container_name
}

function stop_container() {
 local container_name=$1
 [ $(is_container_running $container_name) != "true" ] && return

 debug "Stopping container: $container_name"
 docker stop $container_name
}

function start_container() {
 local container_name=$1
 [ $(is_container_running $container_name) == "true" ] && return

 if [ $(container_exists $container_name) != "true" ]; then
  color_echo red "Container does not exist: $container_name"
  return
 fi

 debug "Starting container: $container_name"
 docker start $container_name
 sleep 3
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
 docker exec -it $container_name sh
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
 docker pull $image_name

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
 docker "${docker_options[@]}"

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

function backup_container()    {
  local container=$1
  local filename="$2-container-$container.tar"

  log "Exporting docker container [$container] to: $filename..."
  docker export -o $filename $container

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
  docker run -d -v $volume:/backup --name "backup-$volume" busybox
  docker cp backup-$volume:/backup /tmp/backup-$volume
  tar -C /tmp/backup-$volume -cvf $filename .
  docker rm backup-$volume
  $SUDO rm -rf /tmp/backup-$volume

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
  docker volume create $volume

  debug "Extracting backup content..."
  mkdir /tmp/restore-$volume
  cp $filename /tmp/restore-$volume/restore-$volume.tar
  cd /tmp/restore-$volume
  tar -xvf restore-$volume.tar
  rm  restore-$volume.tar

  debug "Restoring volume content..."
  docker run -d -v $volume:/restore --name "restore-$volume" busybox
  docker cp /tmp/restore-$volume/. restore-$volume:/restore
  docker rm restore-$volume

  debug "List restored content"
  docker run -it --rm -v $volume:/restore busybox ls -alR /restore

  debug "Clean up resources"
  $SUDO rm -rf /tmp/restore-$volume
}

function check_volume()    {
  local volume=$1

  debug "Listing volume content..."
  docker run -it --rm -v $volume:/vol busybox sh
}

function squash_image()    {
  local image=$1

  log "Create a temp container for [$image]"
  docker run -d --name squash $image

  log "Export container"
  docker export -o /tmp/squash.tar squash
  docker stop squash
  docker rm squash

  log "Import squashed image"
  docker rmi $image
  docker import /tmp/squash.tar $image
  rm /tmp/squash.tar
}

function delete_orphan_images()    {
  docker images --quiet --filter=dangling=true | \
    xargs --no-run-if-empty docker rmi
}

function delete_orphan_volumes()    {
  docker volume list --quiet --filter=dangling=true | \
    xargs --no-run-if-empty docker rmi
}
