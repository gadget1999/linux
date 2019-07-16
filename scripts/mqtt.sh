#!/bin/bash

CMD_PATH=$(dirname "$0")
source $CMD_PATH/common.sh

##########################
# MQTT Shell Listener

# Agent is a listener entity, multiple agents can co-exist with each using own topic
MQTT_AGENT=""
MQTT_TOPIC=""

function mqtt_set_agent() {
 MQTT_AGENT=$1
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
}

function mqtt_event_handler()    {
 local cmd=${1##*/}  # get leaf name
 local arg=${2//\"/}  # trim quotation marks

 # this run_cmd function is implemented by listener instance
 run_cmd $cmd $arg
}

mqtt_listen() {
 /usr/bin/mosquitto_sub -v -h $MQTT_SERVER -p $MQTT_PORT \
  -u $MQTT_USER -P $MQTT_PASSWORD \
  -t "$MQTT_TOPIC/#" | \
 while read -r line ; do
  mqtt_event_handler $line
 done
}
