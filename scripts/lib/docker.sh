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
  if [ $(is_container_running $1) == "true" ]; then
    echo "Stopping container: $1"
    docker stop $1
  fi
}

function enter_container() {
 local container_name=$1
 
 if [ $(is_container_running $container_name) != "true" ]; then
  echo_red "Container is not running: $container_name"
  return
 fi

 echo_red ">>> Now in container: $container_name"
 docker exec -it $container_name \
  bash -c 'cd; bash -l'
 echo_green ">>> Now back to host"
}

function new_container() {
 local container_name=$1
 local imange_name=$2
 local keep=$3
 local container_host="$container_name"

 if [ $(is_container_running $container_name) == "true" ]; then
  enter_container $container_name
  return
 fi

 if [ $(container_exists $container_name) == "true" ]; then
  echo_red "Container (stopped) already exists: $container_name"
  return
 fi

 echo_green "Update image: $imange_name"
 docker pull $imange_name

 local docker_options="--log-driver none
  -v /etc/localtime:/etc/localtime
  -v $container_name-root:/root
  --tmpfs /tmp
  --name $container_name
  -h $container_host
  "

 if [ "$keep" != "keep" ]; then
  # create a one-time use temp container
  echo_red ">>> Now inside of container (one-time use): $container_name"
  docker_options="-it --rm $docker_options"
  docker run $docker_options $imange_name \
   bash -c 'cd; bash -l'
  echo_green ">>> Now back to host"
  return
 fi

 # if need to keep container, need to keep it running at background
 echo_green "Start container (at background): $container_name"
 docker_options="-d $docker_options"
 docker run $docker_options $imange_name
 sleep 3
 if [ $(is_container_running $container_name) != "true" ]; then
  echo_red "The container may not be capable of running at background."
  docker rm $container_name
  return
 fi

 enter_container $container_name
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

