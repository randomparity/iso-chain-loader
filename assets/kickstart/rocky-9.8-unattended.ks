# Rocky Linux 9.8 unattended installation (ADR 0019). build renders the host name, login user,
# keys, and network before this template; it names no disk, address, user, or key itself.
text
lang en_US.UTF-8
keyboard us
timezone UTC --utc
rootpw --lock
firstboot --disable
selinux --enforcing
firewall --enabled --service=ssh
%include /tmp/iso-chain-disk.ks

%packages --excludedocs
@^minimal-environment
%end

%pre --erroronfail --interpreter=/bin/sh
# ADR 0018's guard, repeated in the installer: exactly one non-optical disk, zero in its first and
# last MiB. It only reads the disk, and it partitions only the disk it counted.
set -eu
zero=30e14955ebf1352266dc2ff8067e68104607e750abb9d3b36582b8af909fcb58
count=0
for entry in /sys/block/*; do
    [ -e "$entry/device" ] || continue
    case "${entry##*/}" in sr*) continue ;; esac
    count=$((count + 1))
    disk=${entry##*/}
done
[ "$count" -eq 1 ] || { echo "iso-chain-disk: failed count=$count" >&2; exit 1; }
sectors=$(cat "/sys/block/$disk/size")
case "$sectors" in '' | *[!0-9]*) echo 'iso-chain-disk: failed blank' >&2; exit 1 ;; esac
for skip in 0 $((sectors - 2048)); do
    found=$(dd if="/dev/$disk" bs=512 skip="$skip" count=2048 2>/dev/null | sha256sum)
    [ "${found%% *}" = "$zero" ] || { echo 'iso-chain-disk: failed blank' >&2; exit 1; }
done
cat >/tmp/iso-chain-disk.ks <<EOF
ignoredisk --only-use=$disk
zerombr
clearpart --all --initlabel --drives=$disk
bootloader --location=mbr --boot-drive=$disk --leavebootorder --append="console=hvc0 ipv6.disable=1"
part prepboot --fstype=prepboot --size=4 --ondisk=$disk
part /boot --fstype=xfs --size=1024 --ondisk=$disk
part pv.01 --grow --size=1 --ondisk=$disk
volgroup rocky pv.01
logvol / --fstype=xfs --grow --size=4096 --name=root --vgname=rocky
EOF
%end

reboot
