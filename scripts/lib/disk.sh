#!/usr/bin/env bash

CMD_PATH=$(dirname "$0")
source $CMD_PATH/lib/common.sh

function check_disk_env {
 check_env "PARTCLONE_ROOT"
 check_packages "sfdisk tee partclone.ext4 partclone.dd"
}

function backup_partition_table() {
 local disk=$1
 local backup_folder=$2
 [ ! "$backup_folder" ] && backup_folder=$PARTCLONE_ROOT

 local is_disk=$(lsblk -nl -o FSTYPE,KNAME,TYPE /dev/$disk 2> /dev/null | \
                 grep "$name .*disk")
 [ ! "$is_disk" ] && fatal_error "/dev/$disk is not a disk"

 local backup_file="$backup_folder/$TODAY-$disk-sfdisk.txt"
 log "Backup /dev/$disk partition table to: $backup_file"
 sudo sfdisk -d /dev/$disk | sudo tee $backup_file > /dev/null

 [ ! -s $backup_file ] && log_error "Backup partition table failed."
}

function backup_partition() {
 local partition=$1
 local backup_folder=$2
 [ ! "$backup_folder" ] && backup_folder=$PARTCLONE_ROOT

 # get partition type
 local partition_type=$(lsblk -nl -o FSTYPE,KNAME,TYPE /dev/$partition 2> /dev/null | \
                        grep "$name .*part" | cut -d ' ' -f 1)
 if [ ! "$partition_type" ] || [[ ${#partition_type} -gt 8 ]]; then
  fatal_error "Failed to get /dev/$partition file system type."
 fi

 # get partclone variant based on partition type
 local backup_cmd="partclone"
 case $partition_type in
  ext2|ext3|ext4|ntfs|fat32|exfat)
   backup_bin="partclone.$partition_type"
   backup_cmd="$backup_bin -c"
   is_supported=true
   ;;
  *)
   backup_bin="partclone.dd"
   backup_cmd="$backup_bin"
   ;;
 esac
 check_packages "$backup_bin"

 # test if this is the current system partition
 local mountpoint=$(lsblk -o MOUNTPOINT,KNAME,FSTYPE | \
                    grep "$partition " | cut -d ' ' -f 1)
 if [ "$mountpoint" == "/" ]; then
  log_error "/dev/$partition is root partition, skipped."
  return
 elif [ "$mountpoint" != "/boot" ] && [ "$mountpoint" != "" ]; then
  debug "Unmount /dev/$partition..."
  sudo umount /dev/$partition
 fi

 local backup_file="$backup_folder/$TODAY-$partition.$partition_type.img"
 log "Backup partition /dev/$partition (type:$partition_type) to: $backup_file"
 sudo $backup_cmd -s /dev/$partition -O $backup_file

 [ ! -s $backup_file ] && log_error "Backup partition data failed."
}

function backup_disk() {
 local disk=$1
 local backup_folder=$2
 [ ! "$backup_folder" ] && backup_folder=$PARTCLONE_ROOT

 local is_disk=$(lsblk -nl -o FSTYPE,KNAME,TYPE /dev/$disk 2> /dev/null | \
                 grep "$name .*disk")
 [ ! "$is_disk" ] && fatal_error "/dev/$disk is not a disk"

 # backup partition table
 backup_partition_table $disk $backup_folder

 # backup partitions
 lsblk -nl -o KNAME,TYPE /dev/$disk | \
 while read line; do
  local name=$(echo $line | cut -d ' ' -f 1)
  local type=$(echo $line | cut -d ' ' -f 2)
  [ "$type" == "disk" ] && continue
  # backup partition
  backup_partition $name $backup_folder
 done
}

check_disk_env
