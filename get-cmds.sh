#!/bin/bash

[ -f /usr/local/bin/update-cmds ] && exit 0

cd /tmp
wget https://github.com/gadget1999/linux/archive/master.zip
unzip master.zip
sudo cp /tmp/linux-master/scripts/* /usr/local/bin/
sudo chmod +x /usr/local/bin/*
ls -l /usr/local/bin
rm -R /tmp/linux-master
rm /tmp/master.zip
