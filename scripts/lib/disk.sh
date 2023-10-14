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
 elif [ "$mountpoint" != "" ]; then
  debug "Unmount /dev/$partition ($mountpoint)..."
  sudo umount /dev/$partition
 fi

 local backup_file="$backup_folder/$TODAY-$partition.$partition_type.img"
 log "Backup partition /dev/$partition (type:$partition_type) to: $backup_file"
 sudo $backup_cmd -s /dev/$partition -O $backup_file

 if [ "$mountpoint" == "/boot" ]; then
  debug "Re-mount /dev/$partition to /boot"
  sudo mount /dev/$partition /boot
 fi

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

function remove_mount_point() {
 local mount_point=$1

 # need to use sudo test otherwise some folders cannot be detected
 sudo test ! -d $mount_point && return
 sleep 2

 debug "Unmounting [$mount_point]..."
 sudo umount $mount_point
 debug "Deleting [$mount_point]..."
 sudo rmdir $mount_point
}

############# BitLocker #############

function mount_bitlocker() {
 check_packages "dislocker"
 local partition=$1
 local mount_point=$2
 local mount_mode=$3
 local unlock_area=/tmp/bitlocker

 debug "Creating mount points..."
 mkdir -p $unlock_area
 mkdir -p $mount_point

 local password
 read -s -p "Password:" password

 debug "Unlocking [$partition]..."
 sudo dislocker -V $partition -u$password -- $unlock_area

 if [ "$mount_mode" = "RW" ]; then
  debug "Mounting partition to [$mount_point]... (Read-Write)"
  sudo mount -o loop $unlock_area/dislocker-file $mount_point
 else
  debug "Mounting partition to [$mount_point]... (Read-Only)"
  sudo mount -o ro,loop $unlock_area/dislocker-file $mount_point
 fi
}

function unmount_bitlocker() {
 local mount_point=$1
 local unlock_area=/tmp/bitlocker

 remove_mount_point $mount_point
 remove_mount_point $unlock_area
}

############# VHD #############
# more info: https://gist.github.com/allenyllee/0a4c02952bf695470860b27369bbb60d
# install: qemu-utils nbd-client

NBD_DEV=nbd0
function mount_bitlocker_vhd() {
 check_packages "qemu-nbd"
 local vhd_file=$1
 local vhd_dev=/dev/$NBD_DEV
 local vhd_partition="$vhd_dev""p$2"
 local mount_point=$3
 local mount_mode=$4

 if [ ! -f "$vhd_file" ]; then
  log_error "Invalid VHD file: $vhd_file"
  return
 fi

 if [ "$(lsmod | grep nbd)" == "" ]; then
  debug "Load nbd kernel module"
  sudo modprobe nbd
 fi

 debug "Mount VHD to virtual block device"
 sudo qemu-nbd -c "$vhd_dev" "$vhd_file"

 debug "Reload partition table"
 sudo partprobe "$vhd_dev"

 mount_bitlocker "$vhd_partition" "$mount_point" $mount_mode
}

function unmount_bitlocker_vhd() {
 local mount_point=$1
 local vhd_dev=/dev/$NBD_DEV
 local unlock_area=/tmp/bitlocker

 remove_mount_point $mount_point
 remove_mount_point $unlock_area

 if [ "$(lsblk -o kname | grep $NBD_DEV)" != "" ]; then
  debug "Removing virtual block device: $vhd_dev"
  sudo qemu-nbd -d "$vhd_dev"
 fi
}
