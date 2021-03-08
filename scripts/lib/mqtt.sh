#!/usr/bin/env bash

CMD_PATH=$(dirname "$0")
source $CMD_PATH/lib/common.sh

function check_mqtt_env {
 check_env "MQTT_SERVER MQTT_PORT MQTT_USER MQTT_PASSWORD MQTT_CMD_BASE MQTT_AGENT"
 check_packages "mosquitto_pub mosquitto_sub"
 MQTT_TOPIC="$MQTT_CMD_BASE/$MQTT_AGENT"
}

function mqtt_send() {
 local topic=$1
 local msg=$2
 local retain=$3

 debug "Sending MQTT message: $topic $msg $retain"
 mosquitto_pub -h $MQTT_SERVER -p $MQTT_PORT \
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

 [ "$combine_topics" == "" ] && combine_topics="-t #"
}

function mqtt_event_handler()    {
 local cmd=${1##*/}  # get leaf name
 local arg=${2//\"/}  # trim quotation marks

 # this callback function is implemented by listener instance
 mqtt_callback $cmd $arg
}

function mqtt_listen() {
 local topics=" -t $MQTT_TOPIC/# "
 if [[ $# > 0 ]]; then
  combine_topics "$@"
  topics="$topics $combine_topics"
 fi
 debug "Listen to topics: $topics"
 mosquitto_sub -v -h $MQTT_SERVER -p $MQTT_PORT \
  -u $MQTT_USER -P $MQTT_PASSWORD \
  $topics | \
 while read -r line ; do
  mqtt_event_handler $line
 done
}

function start_mqtt_agent {
 # sometimes mqtt connection may drop, due to network conditions
 while true; do
  mqtt_listen "$@"

  log "restarting mqtt listener..."
  sleep 10
 done
}

function start_mqtt_monitoring() {
 local topics=$1
 
 mosquitto_sub -v -h $MQTT_SERVER -p $MQTT_PORT \
  -u $MQTT_USER -P $MQTT_PASSWORD \
  $topics | \
   xargs -d$'\n' -L1 sh -c 'date "+%Y.%m.%d-%H:%M:%S $0"'
}

function start_mqtt_logging() {
 local topics=$1
 
 mosquitto_sub -v -h $MQTT_SERVER -p $MQTT_PORT \
  -u $MQTT_USER -P $MQTT_PASSWORD \
  $topics | \
   xargs -d$'\n' -L1 sh -c 'date "+%Y.%m.%d-%H:%M:%S $0"' \
   >> $LOG
}
