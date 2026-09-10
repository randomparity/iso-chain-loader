#!/bin/sh
set -eu

# shellcheck source=/dev/null
. /usr/lib/anaconda-lib.sh

fail_stage2() {
    warn "iso-chain: embedded Fedora runtime unavailable"
    emergency_shell
    exit 1
}

[ -f /iso-chain/install.img ] && [ ! -L /iso-chain/install.img ] || fail_stage2
anaconda_mount_sysroot /iso-chain/install.img
[ -b /dev/mapper/live-rw ] || fail_stage2
