#!/usr/bin/env bash

CMD_PATH=$(dirname "$0")
source $CMD_PATH/lib/common.sh

function check_firebase_env {
 check_env "FB_BASE_URL FB_KEY FB_ENDPOINT FB_AGENT"
 check_packages "curl jq"
}

function firebase_setup() {
 FB_BASE_URL=$1
 FB_KEY=$2
}

function firebase_response() {
 local timestamp=$(date +"%H:%M:%S")
 local path=$1
 local state=$2
 local msg='{"status":"'"$state $timestamp"'"}'
 local url="$FB_BASE_URL/$FB_ENDPOINT/response/$FB_AGENT/$path.json?auth=$FB_KEY"
 local fullpath="/$path"
 
 debug "Sending firebase message to [$url]: $msg"
 curl -X PATCH -d "$msg" "$url"
}

function firebase_send() {
 local path=$1
 local msg=$2
 local resource_url="$FB_BASE_URL/$path.json"
 local url="$resource_url?auth=$FB_KEY"

 debug "Sending firebase message to [$resource_url]: $msg"
 curl -X PUT -d "$msg" "$url"
}

function firebase_get_json() {
 local path=$1
 local url="$FB_BASE_URL/$path.json?auth=$FB_KEY"
 curl -s "$url"
}

function firebase_get_attr() {
 local path=$1
 local attr=$2
 local msg=$(firebase_get_json $path)
 echo $msg | jq -r ".$attr"
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

 [ "$path" == "" ] && return 1
 
 # callback function needs to be implemented to handle events
 firebase_callback $cmd $arg $path
}

function firebase_listen() {
 FB_REQUEST_URL="$FB_BASE_URL/$FB_ENDPOINT/request.json?auth=$FB_KEY"
 curl -s -N --http2 -H "Accept:text/event-stream" $FB_REQUEST_URL | \
 # httpie is used to handle streaming events from Firebase
# /usr/bin/http --stream "$FB_REQUEST_URL" Accept:'text/event-stream' | \
 while read -r line ; do
  [[ "$line" == *"data: {"* ]] && event_handler $line
 done
}

function start_firebase_agent {
 # sometimes firebase connection may drop, due to network conditions
 while true; do
  firebase_listen

  log "restarting firebase agent..."
  sleep 10
 done
}