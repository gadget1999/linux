#!/bin/bash

CMD_PATH=$(dirname "$0")
source $CMD_PATH/lib/common.sh

function check_mqtt_env {
 check_env "MQTT_SERVER MQTT_PORT MQTT_USER MQTT_PASSWORD MQTT_CMD_BASE MQTT_AGENT"
 MQTT_TOPIC="$MQTT_CMD_BASE/$MQTT_AGENT"
}

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

 [ "$combine_topics" == "" ] && combine_topics="-t #"
}

function mqtt_event_handler()    {
 local cmd=${1##*/}  # get leaf name
 local arg=${2//\"/}  # trim quotation marks

 # this callback function is implemented by listener instance
 mqtt_callback $cmd $arg
}

function mqtt_listen() {
 /usr/bin/mosquitto_sub -v -h $MQTT_SERVER -p $MQTT_PORT \
  -u $MQTT_USER -P $MQTT_PASSWORD \
  -t "$MQTT_TOPIC/#" | \
 while read -r line ; do
  mqtt_event_handler $line
 done
}

function start_mqtt_agent {
 # sometimes mqtt connection may drop, due to network conditions
 while true; do
  mqtt_listen

  log "restarting mqtt listener..."
  sleep 10
 done
}

function start_mqtt_monitoring() {
 local topics=$1
 
 /usr/bin/mosquitto_sub -v -h $MQTT_SERVER -p $MQTT_PORT \
  -u $MQTT_USER -P $MQTT_PASSWORD \
  $topics | \
   xargs -d$'\n' -L1 sh -c 'date "+%Y.%m.%d-%H:%M:%S $0"'
}

function start_mqtt_logging() {
 local topics=$1
 
 /usr/bin/mosquitto_sub -v -h $MQTT_SERVER -p $MQTT_PORT \
  -u $MQTT_USER -P $MQTT_PASSWORD \
  $topics | \
   xargs -d$'\n' -L1 sh -c 'date "+%Y.%m.%d-%H:%M:%S $0"' \
   >> $LOG
}
