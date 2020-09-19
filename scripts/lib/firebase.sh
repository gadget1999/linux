#!/usr/bin/env bash

CMD_PATH=$(dirname "$0")
source $CMD_PATH/lib/common.sh

function check_firebase_env {
 check_env "FB_BASE_URL FB_KEY"
 check_packages "curl jq"
 FIREBASE_API_ENDPOINT=$FB_BASE_URL
 FIREBASE_API_KEY=$FB_KEY
}

function firebase_setup() {
 FIREBASE_API_ENDPOINT=$1
 FIREBASE_API_KEY=$2
}

function firebase_response() {
 check_env "FB_ENDPOINT FB_AGENT"

 local timestamp=$(date +"%H:%M:%S")
 local path=$1
 local state=$2
 local msg='{"status":"'"$state $NOW"'"}'
 local url="$FIREBASE_API_ENDPOINT/$FB_ENDPOINT/response/$FB_AGENT/$path.json?auth=$FIREBASE_API_KEY"
 local fullpath="/$path"
 
 debug "Sending firebase message to [$url]: $msg"
 curl -X PATCH -d "$msg" "$url"
}

function firebase_send() {
 local path=$1
 local msg=$2
 local url="$FIREBASE_API_ENDPOINT/$path.json?auth=$FIREBASE_API_KEY"

 debug "Sending firebase message to [$url]: $msg"
 curl -X PUT -d "$msg" "$url"
}

function firebase_get_json() {
 local path=$1
 local url="$FIREBASE_API_ENDPOINT/$path.json?auth=$FIREBASE_API_KEY"
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
 check_env "FB_ENDPOINT FB_AGENT"

 FB_REQUEST_URL="$FIREBASE_API_ENDPOINT/$FB_ENDPOINT/request.json?auth=$FIREBASE_API_KEY"
 curl -s -N --http2 -H "Accept:text/event-stream" $FB_REQUEST_URL | \
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

####################
# Bootstraping
####################
check_firebase_env
