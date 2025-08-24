#!/usr/bin/env bash

CMD_PATH=$(dirname "$0")
source $CMD_PATH/lib/common.sh

#####################################
## Docker helper functions
#####################################

#DOCKER_CMD="sudo docker"
#DOCKER_CMD="podman"
[ "$DOCKER_CMD" == "" ] && DOCKER_CMD="sudo -E docker"

DOCKER_LOCAL_REPO_FLAG=/tmp/docker-use-local-repo
function use_local_docker_repo() {
 debug "Use local docker repo"
 touch $DOCKER_LOCAL_REPO_FLAG
}

function setup_container_user() {
 check_env "CONTAINER_USER CONTAINER_UID"
 [ "$(id -u $CONTAINER_USER)" != "" ] && return

 debug "Creating user [$CONTAINER_USER]"
 sudo useradd -M -u $CONTAINER_UID $CONTAINER_USER --shell=/bin/false --home-dir=/non-exist
}

function grant_container_access() {
 setup_container_user

 for volume in "$@"; do
  # avoid changing system patch by mistake (should at least be 3 levels below /)
  var=${volume//[!\/]}
  (( ${#var} < 3 )) && [[ ${volume} != *"/tmp/"* ]] && \
   fatal_error "Blocked risky action: changing permission for $volume"

  if [[ $volume = /* ]]; then
   local uid=$(stat -c '%u' $volume)
   [ "$uid" == "$CONTAINER_UID" ] && continue

   debug "Changing permission for $volume..."
   sudo chown $CONTAINER_USER -R $volume
   sudo chgrp $CONTAINER_USER -R $volume 
  fi
 done 
}

function prepare_container_folders() {
 local container_root=$1
 local -n subfolders=$2 # use an array to avoid space/quote issues  

 if [ ! -d $container_root ]; then
  debug "Creating folder: $container_root"
  sudo mkdir -p $container_root
  grant_container_access $container_root
 fi

 for subfolder in "${subfolders[@]}"; do
  local folder=$container_root/$subfolder
  if [ ! -d $folder ]; then
   debug "Creating folder: $folder"
   sudo mkdir -p $folder
   grant_container_access $folder
  fi
 done 
}

# need to match pattern of end-of-line 'pattern$'
function container_exists() {
  $DOCKER_CMD ps -a | grep " $1$" &> /dev/null
  if [ $? == 0 ]; then
    echo "true"
  else
    echo "false"
  fi
}

function is_container_running() {
  $DOCKER_CMD ps | grep " $1$" &> /dev/null
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
 $DOCKER_CMD rm $container_name
}

function stop_container() {
 local container_name=$1
 [ $(is_container_running $container_name) != "true" ] && return

 debug "Stopping container: $container_name"
 $DOCKER_CMD stop $container_name
}

function start_container() {
 local container_name=$1
 [ $(is_container_running $container_name) == "true" ] && return

 if [ $(container_exists $container_name) != "true" ]; then
  color_echo red "Container does not exist: $container_name"
  return
 fi

 debug "Starting container: $container_name"
 $DOCKER_CMD start $container_name
 sleep 3
}

function restart_container() {
 local container_name=$1
 local threshold=$2

 [ $(is_container_running $container_name) != "true" ] && return

 local usage=$($DOCKER_CMD stats --no-stream --format "{{.Name}} {{.MemPerc}}" | grep "$container_name" | awk '{print substr($2,0,length($2)-1)}')

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
 $DOCKER_CMD exec -it $container_name sh
 #debug ">>> Now back to host"
}

function create_docker_network() {
 local network_driver=$1
 local network_name=$2

 # see if can find the network
 $DOCKER_CMD network ls --format "table {{.Name}}" | \
  grep "$network_name$" &> /dev/null
 if [ $? == 0 ]; then
  debug "Network $network_name already exists."
  return
 fi

 log "Creating docker network: $network_name (type:$network_driver)"
 $DOCKER_CMD network create --driver $network_driver $network_name
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
  # use "-i" instead because otherwise script being called (without TTY) will not work
  #extra_options=(-it "${extra_options[@]}")
  extra_options=(-i "${extra_options[@]}")
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

 if [ ! -f "$DOCKER_LOCAL_REPO_FLAG" ]; then
  debug "Update image: $image_name"
  $DOCKER_CMD pull $image_name
 fi

 local docker_options=(
  run --init
  -v /etc/localtime:/etc/localtime:ro
  --tmpfs /tmp
  --name $container_name
  -h $container_host
  "${extra_options[@]}"
  $image_name
  "${entrypoint_options[@]}"
  )

 [ "$DEBUG_DOCKER" != "0" ] && test-args "${docker_options[@]}"

 debug "Start container (at $background): $container_name"
 $DOCKER_CMD "${docker_options[@]}"

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
  #################### move auto-restart as stateless is easier to maintain
# else
  # if it's service, best to restart until stopped
#  extra_args=("${extra_args[@]}" --restart unless-stopped)
  # docker run --restart conflicts with --rm, so set to stateful
#  stateless="stateful"
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

 [ $(is_container_running $container_name) == "true" ] && return

 if [ "$(container_exists $container_name)" == "true" ]; then
  start_container $container_name
  return
 fi

 # do not delete existing container vm (vm needs to persist its state)
 #delete_container $container_name

 # container services are background stateless containers
 new_container $container_name $image_name $stateless $background extra_args entrypoint_args
}

function container_cli() {
 local image_name=$1
 local -n extra_args=$2 # use an array to avoid space/quote issues
 local -n entrypoint_args=$3

 # container cli is just CLI in a container, should be foreground and stateless
 local stateless="stateless"
 local background="foreground"

 # container services are background stateless containers
 new_container "$PROGRAM" $image_name $stateless $background extra_args entrypoint_args
}

function backup_container()    {
  local container=$1
  local filename="$2-container-$container.tar"

  log "Exporting docker container [$container] to: $filename..."
  $DOCKER_CMD export -o $filename $container

  # verify if the docker image backup is valid
  if ! sudo tar tf $filename &> /dev/null; then
    log "Container backup failed."
  else
    log "Container backup succeeded."
  fi
}

function backup_volume()    {
  local volume=$1
  local filename="$2-vol-$volume.tar"

  debug "Exporting docker volume [$volume] to: $filename..."
  $DOCKER_CMD run -d -v $volume:/backup --name "backup-$volume" alpine sh
  $DOCKER_CMD cp backup-$volume:/backup /tmp/backup-$volume
  sudo tar -C /tmp/backup-$volume -cvf $filename .
  $DOCKER_CMD stop backup-$volume
  $DOCKER_CMD rm backup-$volume
  sudo rm -rf /tmp/backup-$volume

  # verify if the docker image backup is valid
  if ! sudo tar tf $filename &> /dev/null; then
    debug "Volume backup failed."
  else
    debug "Volume backup succeeded: $filename"
  fi
}

function restore_volume()    {
  local volume=$2
  local filename=$1

  debug "Create docker volume [$volume]"
  $DOCKER_CMD volume create $volume

  debug "Extracting backup content..."
  mkdir /tmp/restore-$volume
  cp $filename /tmp/restore-$volume/restore-$volume.tar
  cd /tmp/restore-$volume
  tar -xvf restore-$volume.tar
  rm  restore-$volume.tar

  debug "Restoring volume content..."
  $DOCKER_CMD run -d -v $volume:/restore --name "restore-$volume" alpine sh
  $DOCKER_CMD cp /tmp/restore-$volume/. restore-$volume:/restore
  $DOCKER_CMD rm restore-$volume

  debug "List restored content"
  $DOCKER_CMD run -it --rm -v $volume:/restore alpine ls -alR /restore

  debug "Clean up resources"
  sudo rm -rf /tmp/restore-$volume
}

function check_volume()    {
  local volume=$1

  debug "Mounting volume to a temporary container..."
  $DOCKER_CMD run -it --rm -v $volume:/vol alpine sh
}

function squash_image()    {
  local image=$1

  log "Create a temp container for [$image]"
  $DOCKER_CMD run -d --name squash $image

  log "Export container"
  $DOCKER_CMD export -o /tmp/squash.tar squash
  $DOCKER_CMD stop squash
  $DOCKER_CMD rm squash

  log "Import squashed image"
  $DOCKER_CMD rmi $image
  $DOCKER_CMD import /tmp/squash.tar $image
  sudo rm /tmp/squash.tar
}

function delete_orphan_images()    {
  $DOCKER_CMD images --quiet --filter=dangling=true | \
    xargs --no-run-if-empty $DOCKER_CMD rmi
}

function delete_orphan_volumes()    {
  $DOCKER_CMD volume list --quiet --filter=dangling=true | \
    xargs --no-run-if-empty docker rmi
}

function delete_old_images() {
 local image_name="$1"
 local keep_version="$2"

 if [ -z "$image_name" ]; then
  error "Usage: delete_old_images image_name [version_to_keep]"
  return 1
 fi

 # Find old image IDs
 local old_images=$($DOCKER_CMD images --format "{{.Repository}}:{{.Tag}} {{.ID}}" | \
  grep "^$image_name:" | \
  grep -v ":$keep_version" | \
  awk '{print $2}')

 if [ -n "$old_images" ]; then
  debug "Removing old images for $image_name except version $keep_version:"
  debug "$old_images"
  $DOCKER_CMD rmi $old_images
 else
  debug "No old images to remove for $image_name."
 fi
}

###############################
# Building images from Github
###############################

function build_image_from_github() {
 local github_repo=$1
 local image_prefix=$2
 local container_name=$3
 local target_platform=$4
 local image_name="$image_prefix$container_name"
 local github_path="https://github.com/$github_repo.git#master:$container_name"

 local default_tag=""
 if [[ "$target_platform" == "*"* ]]; then
  target_platform=$(echo "$target_platform" | cut -c2-)
  default_tag="latest"
 fi

 log "Removing previous local copies of [$image_name].."
 $DOCKER_CMD rmi "$image_name:$target_platform"
 [ "$default_tag" != "" ] && \
   $DOCKER_CMD rmi "$image_name:$default_tag"

 log "Building docker image [$image_name:$target_platform] ..."
 $DOCKER_CMD build --force-rm --no-cache \
   --build-arg TARGET_PLATFORM=$target_platform \
   $github_path -t $image_name:$target_platform
 [ "$default_tag" != "" ] && \
   $DOCKER_CMD tag $image_name:$target_platform $image_name:$default_tag

 #log "Squashing the image..."
 #squash_image $IMAGE_NAME

 log "Pushing image to docker hub..."
 $DOCKER_CMD push --all-tags $image_name && {
  log "Removing local image..."
  $DOCKER_CMD rmi "$image_name:$target_platform"
  [ "$default_tag" != "" ] && \
   $DOCKER_CMD rmi "$image_name:$default_tag"
 }
}

# use buildx to build multi-arch images
function buildx_image_from_github() {
 local github_repo=$1
 local image_prefix=$2
 local container_name=$3
 local target_platform=$4
 local docker_hub_user=$5
 local image_name="$docker_hub_user/$image_prefix$container_name"
 local github_path="https://github.com/$github_repo.git#master:$container_name"

 log "Removing previous local copies of [$image_name].."
 $DOCKER_CMD rmi "$image_name:latest"

 log "Building docker image [$image_name @ $target_platform] ..."
 $DOCKER_CMD buildx build --force-rm --no-cache \
   --platform=$target_platform --push \
   $github_path -t $image_name:latest && {
    log "Removing local image..."
    $DOCKER_CMD rmi "$image_name:latest"
   }
}

####################
# Bootstraping
####################

check_packages $DOCKER_CMD
check_root
