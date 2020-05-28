#!/usr/bin/env bash

CMD_PATH=$(dirname "$0")
source $CMD_PATH/lib/common.sh

##############################################################
# Github related function, install/update tools from source
##############################################################

check_packages "git"

function install_from_source()  {
 local repo_name=$1
 local github_url="https://github.com/drwetter/$repo_name.git"
 local local_path="$CMD_PATH/src/$repo_name"
 
 if [ -d $local_path ]; then
  debug "Updating $local_path from Github"
  sudo git -C $local_path fetch
 else
  debug "Install $repo_name to $local_path"
  sudo git clone --depth 1 $github_url $local_path
 fi
}

function create_command_link()  {
 local repo_cmd=$1
 local cmd_name="$CMD_PATH/$2"
 local repo_cmd_path="$CMD_PATH/src/$repo_cmd"

 sudo ln -s $repo_cmd_path $cmd_name
}
