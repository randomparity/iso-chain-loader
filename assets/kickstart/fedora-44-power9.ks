text
eula --agreed
lang en_US.UTF-8
keyboard us
timezone UTC --utc
rootpw --lock
firstboot --disable
selinux --enforcing
firewall --enabled
ignoredisk --only-use=vda
zerombr
clearpart --all --initlabel --drives=vda
bootloader --location=mbr --append="console=hvc0"
part prepboot --fstype=prepboot --size=4 --ondisk=vda
part /boot --fstype=xfs --size=1024 --ondisk=vda
part pv.01 --grow --size=1 --ondisk=vda
volgroup fedora pv.01
logvol / --fstype=xfs --grow --size=8192 --name=root --vgname=fedora

%packages --excludedocs
@^minimal-environment
%end

%post --erroronfail
install -d -m 0700 /var/lib/iso-chain
install -d -m 0755 /usr/local/sbin
cat >/usr/local/sbin/iso-chain-installed <<'SCRIPT'
#!/bin/sh
set -eu
test -f /var/lib/iso-chain/install-complete
boot_id=$(cat /proc/sys/kernel/random/boot_id)
printf 'installed-boot: passed boot_id=%s\n' "$boot_id" >/dev/hvc0
systemctl poweroff
SCRIPT
chmod 0755 /usr/local/sbin/iso-chain-installed
cat >/etc/systemd/system/iso-chain-installed.service <<'UNIT'
[Unit]
Description=Report iso-chain installed-system boot
After=multi-user.target

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/iso-chain-installed

[Install]
WantedBy=multi-user.target
UNIT
systemctl enable iso-chain-installed.service
touch /var/lib/iso-chain/install-complete
chmod 0600 /var/lib/iso-chain/install-complete
%end

poweroff
