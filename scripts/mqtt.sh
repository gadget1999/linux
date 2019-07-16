#!/bin/bash

CMD_PATH=$(dirname "$0")
source $CMD_PATH/common.sh

##########################
# MQTT Shell Listener

function mqtt_send() {
 local topic=$1
 local msg=$2
 local retain=$3

 log "Sending MQTT message: $topic $msg $retain"
 /usr/bin/mosquitto_pub -h $MQTT_SERVER -p $MQTT_PORT \
  -u $MQTT_USER -P $MQTT_PASSWORD \
  -t "$topic" -m "$msg" $retain
}

function combine_topics
{
 combine_topics=""
 for a in "$@" # Loop over arguments
 do
  combine_topics+=" -t $a/# "
 done
}

function mqtt_event_handler()    {
 local cmd=${1##*/}  # get leaf name
 local arg=${2//\"/}  # trim quotation marks

 # this run_cmd function is implemented by listener instance
 run_cmd $cmd $arg
}

function mqtt_listen() {
 local agent=$1
 local topic="$MQTT_CMD_BASE/$agent"

 /usr/bin/mosquitto_sub -v -h $MQTT_SERVER -p $MQTT_PORT \
  -u $MQTT_USER -P $MQTT_PASSWORD \
  -t "$topic/#" | \
 while read -r line ; do
  mqtt_event_handler $line
 done
}

function start_mqtt_agent {
 local agent=$1

 # sometimes mqtt connection may drop, due to network conditions
 while true; do
  mqtt_listen agent

  log "restarting mqtt listener..."
  sleep 2
 done
}


