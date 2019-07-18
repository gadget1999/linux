#!/bin/bash

CMD_PATH=$(dirname "$0")
source $CMD_PATH/common.sh

function check_firebase_env {
 check_env "FB_BASE_URL FB_KEY FB_AGENT"
}

function firebase_response() {
 local timestamp=$(date +"%H:%M:%S")
 local path=$1
 local state=$2
 local msg='{"status":"'"$state $NOW"'"}'
 local fullpath="response/$FB_AGENT/$path"
 
 firebase_send "$fullpath" "$msg"
}

function firebase_send() {
 local path=$1
 local msg=$2
 local url="$FB_BASE_URL/$path.json?auth=$FB_KEY"

 debug "Sending firebase message to [$url]: $msg"
 /usr/bin/curl -X PATCH -d "$msg" "$url"
}

function trim_str() {
 local str=${1//\"/}
 str=${str//\\/}
 echo "$str"
}

# it seems most of time the format is as Google documented:
# data: {"path":"/host/disable-pihole","data":"4m"}
# however, when using curl to update firebase, sometimes data is like:
# data: {"path":"/host","data":{"disable-pihole":"8m"}}
function event_handler() {
 local json=$2
 local path=$(echo $json | jq '.path')
 local data=$(echo $json | jq '.data')

 path=$(trim_str $path)
 path=${path#*/}       # remove leading /
 cmd=${path##*/}       # get leaf name
 arg=$(trim_str $data)

 if [ "x$path" = "x" ]; then
  return 1
 fi

 # callback function needs to be implemented to handle events
 firebase_callback $cmd $arg $path
}

function firebase_listen() {
 local endpoint=$1
 # httpie is used to handle streaming events from Firebase
 FB_REQUEST_URL="$FB_BASE_URL/$endpoint.json?auth=$FB_KEY"
 /usr/bin/http --stream "$FB_REQUEST_URL" Accept:'text/event-stream' | \
 while read -r line ; do
  echo "$line" | grep "data: {"
  if [ $? = 0 ]; then
   event_handler $line
  fi
 done
}

function start_firebase_agent {
 local endpoint=$1
 # sometimes firebase connection may drop, due to network conditions
 while true; do
  firebase_listen "$endpoint"

  log "restarting firebase agent..."
  sleep 2
 done
}
