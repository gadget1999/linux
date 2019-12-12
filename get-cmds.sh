#!/usr/bin/env bash

[ -f /usr/local/bin/update-cmds ] && exit 0

cd /tmp
wget https://github.com/gadget1999/linux/archive/master.zip
unzip master.zip
sudo cp /tmp/linux-master/scripts/* /usr/local/bin/
sudo chmod +x /usr/local/bin/*
sudo mkdir /usr/local/bin/lib
sudo cp /tmp/linux-master/scripts/lib/* /usr/local/bin/lib/
ls -l /usr/local/bin
rm -R /tmp/linux-master
rm /tmp/master.zip
