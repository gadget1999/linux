#!/bin/bash

CMD_PATH=$(dirname "$0")
source $CMD_PATH/lib/common.sh

#####################################
## Docker helper functions
#####################################

check_packages "/usr/bin/docker"

function container_exists() {
  docker ps -a | grep "$1" &> /dev/null
  if [ $? == 0 ]; then
    echo "true"
  else
    echo "false"
  fi
}

function is_container_running() {
  docker ps | grep "$1" &> /dev/null
  if [ $? == 0 ]; then
    echo "true"
  else
    echo "false"
  fi
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
 docker exec -it $container_name \
  bash -c 'cd; bash -l'
 #debug ">>> Now back to host"
}

# create a temp container
function new_tmp_container() {
 local container_name=$1
 local image_name=$2
 local -n extra_options=$3 # use an array to avoid space/quote issues
 local container_cmd=$4
 local container_host="$container_name"

 if [ $(container_exists $container_name) == "true" ]; then
  color_echo red "Container already exists: $container_name"
  return
 fi

 if [ "$container_cmd" == "entrypoint" ]; then
  container_cmd=()
 else
  container_cmd=(bash -c 'cd; bash -l')
 fi

 debug "Update image: $image_name"
 docker pull $image_name

 local docker_options=(
  run -it --rm
  -v /etc/localtime:/etc/localtime
  -v $container_name-root:/root
  --tmpfs /tmp
  --name $container_name
  -h $container_host
  "${extra_options[@]}"
  $image_name
  "${container_cmd[@]}"
  )

 # create a one-time use temp container
 #color_echo red ">>> Now inside of container (one-time use): $container_name"
 #test-args "${docker_options[@]}"
 docker "${docker_options[@]}"
 #debug ">>> Now back to host"
}

# create a long running container
function new_container() {
 local container_name=$1
 local image_name=$2
 local keep=$3
 local -n extra_options=$4 # use an array to avoid space/quote issues
 local container_host="$container_name"

 if [ $(container_exists $container_name) == "true" ]; then
  color_echo red "Container already exists: $container_name"
  return
 fi

 debug "Update image: $image_name"
 docker pull $image_name

 [ "$keep" != "keep" ] && extra_options=(--rm "${extra_options[@]}")

 local docker_options=(
  run -d
  -v /etc/localtime:/etc/localtime
  -v $container_name-root:/root
  --tmpfs /tmp
  --name $container_name
  -h $container_host
  "${extra_options[@]}"
  $image_name
  )

 debug "Start container (at background): $container_name"
 #test-args "${docker_options[@]}"
 docker "${docker_options[@]}"
 sleep 3
 if [ $(is_container_running $container_name) != "true" ]; then
  color_echo red "The container may not be capable of running at background."
  docker rm $container_name
  return
 fi
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

  log "Exporting docker volume [$volume] to: $filename..."
  docker run -d -v $volume:/backup --name "backup-$volume" busybox
  docker cp backup-$volume:/backup /tmp/backup-$volume
  tar -C /tmp/backup-$volume -cvf $filename .
  docker rm backup-$volume
  sudo rm -rf /tmp/backup-$volume

  # verify if the docker image backup is valid
  if ! tar tf $filename &> /dev/null; then
    log "Volume backup failed."
  else
    log "Volume backup succeeded."
  fi
}

function restore_volume()    {
  local volume=$2
  local filename=$1

  log "Create docker volume [$volume]"
  docker volume create $volume

  log "Extracting backup content..."
  mkdir /tmp/restore-$volume
  cp $filename /tmp/restore-$volume/restore-$volume.tar
  cd /tmp/restore-$volume
  tar -xvf restore-$volume.tar
  rm  restore-$volume.tar

  log "Restoring volume content..."
  docker run -d -v $volume:/restore --name "restore-$volume" busybox
  docker cp /tmp/restore-$volume/. restore-$volume:/restore
  docker rm restore-$volume

  log "List restored content"
  docker run -it --rm -v $volume:/restore busybox ls -alR /restore

  log "Clean up resources"
  sudo rm -rf /tmp/restore-$volume
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
