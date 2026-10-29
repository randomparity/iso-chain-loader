# Fedora 44 starter Kickstart for operator_kickstart (ADR 0034). Copy it, replace the placeholders
# below and embed the result in the manifest. Build adds a blank-disk guard before this text and a
# completion marker after it; everything else is yours to own and check.
#
# Source: the launcher passes inst.repo=<manifest source><repository path>, so this file names no
# url or repo line. Add none that points anywhere but the manifest source.
text
eula --agreed
lang en_US.UTF-8
keyboard us
timezone UTC --utc
# Placeholder login: replace the user name and the key. No password hash is stored; root is locked.
rootpw --lock
user --name=exampleuser --lock
sshkey --username=exampleuser "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAINdamAGCsQq31Uv+08lkBzoO4XLz2qYjJa8CGmj3B1Ea synthetic-test-key"
firstboot --disable
selinux --enforcing
firewall --enabled --service=ssh
# The guard has already required exactly one non-optical disk, blank at both ends.
zerombr
clearpart --all --initlabel
autopart
# Keep the firmware boot order so the installed disk is reached through the ISO's menu.
bootloader --location=mbr --leavebootorder --append="console=hvc0 ipv6.disable=1"

%packages --excludedocs
@^minimal-environment
%end

reboot
