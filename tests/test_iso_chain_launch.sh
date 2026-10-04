#!/usr/bin/env bash
set -euo pipefail

# The launcher validates hex and identifier grammar with bracket ranges whose matching follows the
# locale, and it runs in the guest's C locale. Pin it so the harness does not follow the host's.
export LC_ALL=C

root=$(cd "$(dirname "$0")/.." && pwd)
launcher="$root/assets/dracut/iso-chain-launch.sh"
workspace=$(mktemp -d)
trap 'rm -rf "$workspace"' EXIT

fail() {
    echo "test failure: $*" >&2
    exit 1
}

write_fake_commands() {
    mkdir -p "$workspace/bin"
    cat >"$workspace/bin/ip" <<'EOF'
#!/usr/bin/env bash
printf 'ip %s\n' "$*" >> "$ISO_CHAIN_CALLS"
test "${ISO_CHAIN_FAULT:-}" != "ip" || exit 9
EOF
    cat >"$workspace/bin/curl" <<'EOF'
#!/usr/bin/env bash
printf 'curl %s\n' "$*" >> "$ISO_CHAIN_CALLS"
test "${ISO_CHAIN_FAULT:-}" != "curl" || exit 9
output=
url=${!#}
while [ "$#" -gt 0 ]; do
    if [ "$1" = --output ]; then output=$2; shift 2; else shift; fi
done
case "$url" in
    */ppc/ppc64/vmlinuz) content=kernel ;;
    */ppc/ppc64/initrd.img) content=initramfs ;;
    */.treeinfo) content=treeinfo ;;
    */repodata/repomd.xml) content=metadata ;;
    */netboot/ppc64el/linux) content=kernel ;;
    */netboot/ppc64el/initrd) content=initramfs ;;
    */oss/boot/ppc64le/linux) content=kernel ;;
    */oss/boot/ppc64le/initrd) content=initramfs ;;
    *) exit 22 ;;
esac
[ "${ISO_CHAIN_FAULT:-}" != digest ] || content=$(printf '%s' "$content" | tr a-z A-Z)
[ "${ISO_CHAIN_FAULT:-}" != size ] || content=x
[ "${ISO_CHAIN_FAULT:-}:$content" != initramfs-digest:initramfs ] || content=initramfX
printf '%s' "$content" > "$output"
EOF
    cat >"$workspace/bin/kexec" <<'EOF'
#!/usr/bin/env bash
printf 'kexec %s\n' "$*" >> "$ISO_CHAIN_CALLS"
case "${ISO_CHAIN_FAULT:-}:$1" in load:-l|execute:-e|unload:-u) exit 9 ;; esac
exit 0
EOF
    cat >"$workspace/bin/sync" <<'EOF'
#!/usr/bin/env bash
printf 'sync\n' >> "$ISO_CHAIN_CALLS"
EOF
    cat >"$workspace/bin/stat" <<'EOF'
#!/usr/bin/env bash
case "${1:-}:${2:-}" in
    -f:-c)
        if [ "${ISO_CHAIN_FAULT:-}" = space ]; then
            printf '1:1\n'
        else
            printf '1048576:4096\n'
        fi
        ;;
    -c:%s)
        set -- $(wc -c <"${3:?}")
        printf '%s\n' "$1"
        ;;
    *) exit 1 ;;
esac
EOF
    cat >"$workspace/bin/sha256sum" <<'EOF'
#!/usr/bin/env bash
for candidate in /usr/bin/sha256sum /sbin/sha256sum; do
    if [ -x "$candidate" ]; then
        exec "$candidate" "$@"
    fi
done
exec /usr/bin/shasum -a 256 "$@"
EOF
    cat >"$workspace/bin/udevadm" <<'EOF'
#!/usr/bin/env bash
printf 'udevadm %s\n' "$*" >> "$ISO_CHAIN_CALLS"
test "${ISO_CHAIN_FAULT:-}" != disk-settle || exit 1
EOF
    cat >"$workspace/bin/mount" <<'EOF'
#!/usr/bin/env bash
printf 'mount %s\n' "$*" >> "$ISO_CHAIN_CALLS"
test "${ISO_CHAIN_FAULT:-}" != mount || { echo 'mount: wrong fs type' >&2; exit 32; }
[ "$1 $2 $3" = "-t iso9660 -o" ] && [ "$4" = ro,nodev,nosuid,noexec ] || exit 32
cp -R "$5/." "$6/"
EOF
    cat >"$workspace/bin/umount" <<'EOF'
#!/usr/bin/env bash
printf 'umount %s\n' "$*" >> "$ISO_CHAIN_CALLS"
find "$1" -mindepth 1 -delete
EOF
    cat >"$workspace/bin/blkid" <<'EOF'
#!/usr/bin/env bash
# Like util-linux blkid -t, answer one tag and exit 2 when no device matches it.
printf 'blkid %s\n' "$*" >> "$ISO_CHAIN_CALLS"
tag=
while [ "$#" -gt 0 ]; do
    if [ "$1" = -t ]; then tag=$2; shift 2; else shift; fi
done
case "${ISO_CHAIN_FAULT:-}:$tag" in
    nocloud-lower:LABEL=iso_chain_* | nocloud-fat:LABEL_FATBOOT=ISO_CHAIN_*)
        printf '/dev/sr1\n'
        exit 0
        ;;
    nocloud-error:LABEL=iso_chain_*) exit 4 ;;
    *:LABEL=ISO_CHAIN_*) ;;
    *) exit 2 ;;
esac
found=
for device in $ISO_CHAIN_MEDIA_DEVICES; do
    [ "$(cat "$device/iso-chain/config.json")" != config ] || { printf '%s\n' "$device"; found=1; }
done
[ "${ISO_CHAIN_FAULT:-}" != media-label ] || { printf '/dev/sda1\n'; found=1; }
[ -n "$found" ] || exit 2
EOF
    chmod +x "$workspace/bin/ip" "$workspace/bin/curl" "$workspace/bin/kexec" \
        "$workspace/bin/sync" "$workspace/bin/stat" "$workspace/bin/sha256sum" \
        "$workspace/bin/udevadm" "$workspace/bin/mount" "$workspace/bin/umount" \
        "$workspace/bin/blkid"
}

command_line() {
    printf '%s' 'iso_chain.lpar=sys-r1 iso_chain.mac=52:54:00:ab:cd:ef iso_chain.address=10.0.2.15/24 '
    printf '%s' 'iso_chain.route=0.0.0.0/0,10.0.2.2 iso_chain.dns=10.0.2.3,10.0.2.4 '
    printf '%s' 'iso_chain.source=http://192.0.2.2 iso_chain.profile=fedora '
    printf '%s' 'iso_chain.profile_distribution=fedora iso_chain.profile_release=44 '
    printf '%s' 'iso_chain.profile_kernel_path=/repository/ppc/ppc64/vmlinuz iso_chain.profile_kernel_size=6 '
    printf '%s' 'iso_chain.profile_kernel_sha256=6923dd1bc0460082c5d55a831908c24a282860b7f1cd6c2b79cf1bc8857c639c '
    printf '%s' 'iso_chain.profile_initramfs_path=/repository/ppc/ppc64/initrd.img iso_chain.profile_initramfs_size=9 '
    printf '%s' 'iso_chain.profile_initramfs_sha256=9752c38a9065f7646ffaac3621d1fa2f7dbe726c7e12e511eac7fdb14d4e2a24 '
    printf '%s' 'iso_chain.profile_repository_path=/repository iso_chain.profile_treeinfo_size=8 '
    printf '%s' 'iso_chain.profile_treeinfo_sha256=103c1f80d3ca13d76a1eff05f141c5924f3c5e006b27e0755242e804b141f564 '
    printf '%s' 'iso_chain.profile_repomd_size=8 '
    printf '%s' 'iso_chain.profile_repomd_sha256=45447b7afbd5e544f7d0f1df0fccd26014d9850130abd3f020b89ff96b82079f '
    printf '%s' 'iso_chain.profile_kickstart_path=/profiles/fedora-44/ks.cfg iso_chain.profile_kickstart_size=9 '
    printf '%s' "iso_chain.profile_kickstart_sha256=$kickstart_digest "
    printf '%s' 'iso_chain.profile_minimum_memory_mib=4096 '
    printf '%s' "iso_chain.config_sha256=$config_digest"
}

ubuntu_command_line() {
    printf '%s' 'iso_chain.lpar=sys-r1 iso_chain.mac=52:54:00:ab:cd:ef iso_chain.address=10.0.2.15/24 '
    printf '%s' 'iso_chain.route=0.0.0.0/0,10.0.2.2 iso_chain.dns=10.0.2.3,10.0.2.4 '
    printf '%s' 'iso_chain.source=http://192.0.2.2 iso_chain.profile=ubuntu '
    printf '%s' 'iso_chain.profile_distribution=ubuntu iso_chain.profile_release=26.04.1 '
    printf '%s' 'iso_chain.profile_kernel_path=/ubuntu/netboot/ppc64el/linux iso_chain.profile_kernel_size=6 '
    printf '%s' 'iso_chain.profile_kernel_sha256=6923dd1bc0460082c5d55a831908c24a282860b7f1cd6c2b79cf1bc8857c639c '
    printf '%s' 'iso_chain.profile_initramfs_path=/ubuntu/netboot/ppc64el/initrd iso_chain.profile_initramfs_size=9 '
    printf '%s' 'iso_chain.profile_initramfs_sha256=9752c38a9065f7646ffaac3621d1fa2f7dbe726c7e12e511eac7fdb14d4e2a24 '
    printf '%s' 'iso_chain.profile_live_iso_path=/ubuntu/ubuntu-26.04.1-live-server-ppc64el.iso '
    printf '%s' 'iso_chain.profile_minimum_memory_mib=4096 '
    printf '%s' "iso_chain.config_sha256=$config_digest"
}

opensuse_command_line() {
    printf '%s' 'iso_chain.lpar=sys-r1 iso_chain.mac=52:54:00:ab:cd:ef iso_chain.address=10.0.2.15/24 '
    printf '%s' 'iso_chain.route=0.0.0.0/0,10.0.2.2 iso_chain.dns=10.0.2.3 '
    printf '%s' 'iso_chain.source=http://192.0.2.2 iso_chain.profile=opensuse '
    printf '%s' 'iso_chain.profile_distribution=opensuse iso_chain.profile_release=15.6 '
    printf '%s' 'iso_chain.profile_kernel_path=/oss/boot/ppc64le/linux iso_chain.profile_kernel_size=6 '
    printf '%s' 'iso_chain.profile_kernel_sha256=6923dd1bc0460082c5d55a831908c24a282860b7f1cd6c2b79cf1bc8857c639c '
    printf '%s' 'iso_chain.profile_initramfs_path=/oss/boot/ppc64le/initrd iso_chain.profile_initramfs_size=9 '
    printf '%s' 'iso_chain.profile_initramfs_sha256=9752c38a9065f7646ffaac3621d1fa2f7dbe726c7e12e511eac7fdb14d4e2a24 '
    printf '%s' 'iso_chain.profile_repository_path=/oss '
    printf '%s' 'iso_chain.profile_minimum_memory_mib=4096 '
    printf '%s' "iso_chain.config_sha256=$config_digest"
}

run_launcher() {
    local adapters=$1
    local fault=${2:-}
    local cmdline=${4:-$(command_line)}
    local net="$workspace/net"
    local resolv="$workspace/resolv.conf"
    local calls="$workspace/calls"
    local output="$workspace/output"
    local meminfo="$workspace/meminfo"
    local run_dir="$workspace/run"
    local media="$workspace/media"
    local block="$workspace/sys/block"
    local devices="$workspace/dev"
    rm -rf "$net" "$resolv" "$calls" "$output" "$run_dir" "$media" "$workspace/sys" "$devices"
    mkdir -p "$net" "$run_dir" "$media" "$block/sr0/device" "$block/loop0" "$devices"
    case "$fault" in
    disk-none) ;;
    disk-two) make_disk vda 8192 && make_disk vdb 8192 ;;
    disk-small) make_disk vda 1024 ;;
    *) make_disk vda 8192 ;;
    esac
    case "$fault" in
    disk-head) write_disk_byte 0 ;;
    disk-middle) write_disk_byte 2097152 ;;
    disk-tail) write_disk_byte $((8192 * 512 - 1)) ;;
    esac
    local bus="$workspace/sys/bus"
    mkdir -p "$bus/pci/devices/0000:00:00.0" "$bus/pci/devices/0000:00:01.0/driver" \
        "$bus/vio/devices/71000001" "$bus/vio/devices/71000002/driver" "$bus/vio/devices/vio"
    printf '0x030000\n' >"$bus/pci/devices/0000:00:00.0/class"
    printf '0x010000\n' >"$bus/pci/devices/0000:00:01.0/class"
    printf 'vio:TnvramSqemu,spapr-nvram\n' >"$bus/vio/devices/71000001/modalias"
    printf 'vio:TvscsiSIBM,v-scsi\n' >"$bus/vio/devices/71000002/modalias"
    case "$fault" in
    controller-pci-storage) make_pci 0000:00:02.0 0x010400 ;;
    controller-pci-fc) make_pci 0000:00:02.0 0x0c0400 ;;
    controller-pci-unreadable) mkdir -p "$bus/pci/devices/0000:00:02.0" ;;
    controller-two) make_pci 0000:00:02.0 0x010400 && make_pci 0000:00:03.0 0x0c0400 ;;
    controller-vio-vscsi) rm -r "$bus/vio/devices/71000002/driver" ;;
    controller-vio-fcp)
        mkdir -p "$bus/vio/devices/30000003"
        printf 'vio:TfcpSIBM,vfc-client\n' >"$bus/vio/devices/30000003/modalias"
        ;;
    controller-bus-empty) rm -r "$bus/pci/devices"/* "$bus/vio" ;;
    esac
    RUN_DISKS_BEFORE=$(find "$devices" -type f -exec cksum {} +)
    case "$fault" in
    media-none) ;;
    media-duplicate) make_device "$media/sr0" && make_device "$media/sr1" ;;
    media-foreign) make_device "$media/sr0" && printf 'other' >"$media/sr0/iso-chain/config.json" ;;
    media-second)
        make_device "$media/sr0" && make_device "$media/sr1"
        printf 'other' >"$media/sr0/iso-chain/config.json"
        printf 'kickstarX' >"$media/sr0/profiles/fedora-44/ks.cfg"
        ;;
    *) make_device "$media/sr0" ;;
    esac
    [ "$fault" != media-size ] || printf 'x' >"$media/sr0/profiles/fedora-44/ks.cfg"
    case "$fault" in
    user-data-digest) printf 'userdatX' >"$media/sr0/user-data" ;;
    meta-data-content) printf 'x' >"$media/sr0/meta-data" ;;
    meta-data-missing) rm "$media/sr0/meta-data" ;;
    meta-data-link) rm "$media/sr0/meta-data" && ln -s user-data "$media/sr0/meta-data" ;;
    esac
    if [ "$fault" = media-digest ]; then
        printf 'kickstarX' >"$media/sr0/profiles/fedora-44/ks.cfg"
        printf 'kickstarX' >"$media/sr0/profiles/rocky/ks.cfg"
    fi
    printf 'MemTotal: 8388608 kB\nMemAvailable: 6291456 kB\n' >"$meminfo"
    if [ "$fault" = threshold ]; then
        printf 'MemTotal: 4194304 kB\nMemAvailable: 2097152 kB\n' >"$meminfo"
    elif [ "$fault" = memory ]; then
        printf 'MemTotal: 4193280 kB\nMemAvailable: 3145728 kB\n' >"$meminfo"
    elif [ "$fault" = availability ]; then
        printf 'MemTotal: 8388608 kB\nMemAvailable: 1048576 kB\n' >"$meminfo"
    fi
    for adapter in $adapters; do
        mkdir -p "$net/$adapter"
        printf '%s\n' '52:54:00:AB:CD:EF' >"$net/$adapter/address"
    done
    set +e
    PATH="$workspace/bin:$PATH" ISO_CHAIN_SYS_CLASS_NET="$net" ISO_CHAIN_RESOLV_CONF="$resolv" \
        ISO_CHAIN_CMDLINE="$cmdline" ISO_CHAIN_CALLS="$calls" ISO_CHAIN_FAULT="$fault" \
        ISO_CHAIN_MEMINFO="$meminfo" ISO_CHAIN_RUN_DIR="$run_dir" \
        ISO_CHAIN_MEDIA_DEVICES="$media/sr*" ISO_CHAIN_SYS_BLOCK="$block" ISO_CHAIN_DEV_DIR="$devices" \
        ISO_CHAIN_SYS_BUS="$bus" \
        "$launcher" >"$output" 2>&1
    RUN_STATUS=$?
    set -e
    RUN_CALLS=$calls
    RUN_OUTPUT=$output
    RUN_RESV=$resolv
    RUN_DISKS_AFTER=$(find "$workspace/dev" -type f -exec cksum {} +)
}

make_disk() {
    mkdir -p "$workspace/sys/block/$1/device"
    printf '%s\n' "$2" >"$workspace/sys/block/$1/size"
    dd if=/dev/zero of="$workspace/dev/$1" bs=512 count=0 seek="$2" 2>/dev/null
}

make_pci() {
    mkdir -p "$workspace/sys/bus/pci/devices/$1"
    printf '%s\n' "$2" >"$workspace/sys/bus/pci/devices/$1/class"
}

write_disk_byte() {
    printf 'x' | dd of="$workspace/dev/vda" bs=1 seek="$1" conv=notrunc 2>/dev/null
}

make_device() {
    mkdir -p "$1/iso-chain" "$1/profiles/fedora-44" "$1/profiles/rocky"
    printf 'config' >"$1/iso-chain/config.json"
    printf 'kickstart' >"$1/profiles/fedora-44/ks.cfg"
    printf 'kickstart' >"$1/profiles/rocky/ks.cfg"
    printf 'userdata' >"$1/user-data"
    : >"$1/meta-data"
}

assert_no_network_calls() {
    test ! -e "$RUN_CALLS" || fail "negative path invoked a network command"
}

assert_configuration_rejected() {
    local label=$1
    local cmdline=$2
    run_launcher "eth0" "" 206 "$cmdline"
    test "$RUN_STATUS" -ne 0 || fail "$label unexpectedly succeeded"
    grep -qx 'configuration: failed' "$RUN_OUTPUT" || fail "$label missed fixed marker"
    assert_no_network_calls
}

write_fake_commands
config_digest=$(printf 'config' | "$workspace/bin/sha256sum" | cut -d' ' -f1)
kickstart_digest=$(printf 'kickstart' | "$workspace/bin/sha256sum" | cut -d' ' -f1)
test -x "$launcher" || fail "launcher runtime is absent"

run_launcher ""
assert_no_network_calls
test "$RUN_STATUS" -ne 0 || fail "zero adapters unexpectedly succeeded"
grep -qx 'adapter-match: failed' "$RUN_OUTPUT" || fail "zero adapters missed fixed marker"

run_launcher "eth0" "" 206 'iso_chain.mac=52:54:00:ab:cd:ef'
test "$RUN_STATUS" -ne 0 || fail "incomplete arguments unexpectedly succeeded"
grep -qx 'configuration: failed' "$RUN_OUTPUT" || fail "missing fixed configuration failure"
assert_no_network_calls

invalid_cmdline=$(command_line)
invalid_cmdline=${invalid_cmdline/iso_chain.mac=52:54:00:ab:cd:ef/iso_chain.mac=bad}
run_launcher "eth0" "" 206 "$invalid_cmdline"
test "$RUN_STATUS" -ne 0 || fail "invalid arguments unexpectedly succeeded"
grep -qx 'configuration: failed' "$RUN_OUTPUT" || fail "invalid arguments missed fixed marker"
assert_no_network_calls

for invalid_dns in 'invalid-dns' '10.0.2.3,invalid-dns' '10.0.2.3,'; do
    invalid_cmdline=$(command_line)
    invalid_cmdline=${invalid_cmdline/iso_chain.dns=10.0.2.3,10.0.2.4/iso_chain.dns=$invalid_dns}
    run_launcher "eth0" "" 206 "$invalid_cmdline"
    test "$RUN_STATUS" -ne 0 || fail "invalid DNS unexpectedly succeeded: $invalid_dns"
    grep -qx 'configuration: failed' "$RUN_OUTPUT" || fail "invalid DNS missed fixed marker"
    assert_no_network_calls
done

invalid_cmdline=$(command_line)
valid_route='iso_chain.route=0.0.0.0/0,10.0.2.2'
invalid_route='iso_chain.route=0.0.0.0/0,192.0.2.1'
invalid_cmdline=${invalid_cmdline/$valid_route/$invalid_route}
run_launcher "eth0" "" 206 "$invalid_cmdline"
test "$RUN_STATUS" -ne 0 || fail "off-subnet gateway unexpectedly succeeded"
grep -qx 'configuration: failed' "$RUN_OUTPUT" || fail "off-subnet gateway missed fixed marker"
assert_no_network_calls

invalid_cmdline=$(command_line)
escaped_route='iso_chain.route=0.0.0.0/0,10.0.2.2\cINVALID'
invalid_cmdline=${invalid_cmdline/$valid_route/$escaped_route}
run_launcher "eth0" "" 206 "$invalid_cmdline"
test "$RUN_STATUS" -ne 0 || fail "escaped route unexpectedly succeeded"
grep -qx 'configuration: failed' "$RUN_OUTPUT" || fail "escaped route missed fixed marker"
assert_no_network_calls

invalid_cmdline=$(command_line)
valid_mac_value='iso_chain.mac=52:54:00:ab:cd:ef'
multicast_mac='iso_chain.mac=53:54:00:ab:cd:ef'
invalid_cmdline=${invalid_cmdline/$valid_mac_value/$multicast_mac}
assert_configuration_rejected "multicast MAC" "$invalid_cmdline"

invalid_cmdline=$(command_line)
host_route='iso_chain.route=192.0.2.1/24,10.0.2.2'
invalid_cmdline=${invalid_cmdline/$valid_route/$host_route}
assert_configuration_rejected "route destination with host bits" "$invalid_cmdline"

invalid_cmdline="$(command_line) $valid_route"
assert_configuration_rejected "duplicate route destination" "$invalid_cmdline"

invalid_cmdline=$(command_line)
invalid_cmdline=${invalid_cmdline/$valid_route/iso_chain.route=192.0.2.0\/24,10.0.2.2}
assert_configuration_rejected "missing default route" "$invalid_cmdline"

invalid_cmdline=$(command_line)
invalid_cmdline=${invalid_cmdline/iso_chain.profile_kickstart_size=9/iso_chain.profile_kickstart_size=1048577}
assert_configuration_rejected "oversized Kickstart" "$invalid_cmdline"

invalid_cmdline="$(command_line) iso_chain.config_sha256=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
assert_configuration_rejected "duplicate configuration digest" "$invalid_cmdline"

invalid_cmdline=$(command_line)
valid_dns='iso_chain.dns=10.0.2.3,10.0.2.4'
too_many_dns='iso_chain.dns=10.0.2.3,10.0.2.4,10.0.2.5,10.0.2.6'
invalid_cmdline=${invalid_cmdline/$valid_dns/$too_many_dns}
assert_configuration_rejected "too many DNS servers" "$invalid_cmdline"

invalid_cmdline=$(command_line)
for third_octet in {3..18}; do
    invalid_cmdline="$invalid_cmdline iso_chain.route=10.0.$third_octet.0/24,10.0.2.2"
done
assert_configuration_rejected "too many routes" "$invalid_cmdline"

for malformed_address in '.10.0.2.15/24' '10..2.15/24' '10.0.2.15./24'; do
    invalid_cmdline=$(command_line)
    valid_address='iso_chain.address=10.0.2.15/24'
    invalid_address="iso_chain.address=$malformed_address"
    invalid_cmdline=${invalid_cmdline/$valid_address/$invalid_address}
    assert_configuration_rejected "malformed interface address" "$invalid_cmdline"
done

invalid_cmdline=$(command_line)
invalid_cmdline=${invalid_cmdline/0.0.0.0\/0,10.0.2.2/0.0.0.0.\/0,10.0.2.2}
assert_configuration_rejected "trailing-dot route destination" "$invalid_cmdline"

invalid_cmdline=$(command_line)
invalid_cmdline=${invalid_cmdline/0.0.0.0\/0,10.0.2.2/0.0.0.0\/0,10.0.2.2.}
assert_configuration_rejected "trailing-dot route gateway" "$invalid_cmdline"

for subnet_case in \
    '10.0.0.1/1 128.0.0.1' \
    '10.0.0.1/9 10.128.0.1' \
    '10.0.0.1/17 10.0.128.1' \
    '10.0.0.1/25 10.0.0.129'; do
    read -r subnet_address subnet_gateway <<<"$subnet_case"
    invalid_cmdline=$(command_line)
    invalid_cmdline=${invalid_cmdline/iso_chain.address=10.0.2.15\/24/iso_chain.address=$subnet_address}
    invalid_cmdline=${invalid_cmdline/$valid_route/iso_chain.route=0.0.0.0\/0,$subnet_gateway}
    assert_configuration_rejected "partial-prefix off-subnet gateway" "$invalid_cmdline"
done

for subnet_case in \
    '10.0.0.1/1 10.0.0.2' \
    '10.0.0.1/9 10.1.0.1' \
    '10.0.0.1/17 10.0.1.1' \
    '10.0.0.1/25 10.0.0.2'; do
    read -r subnet_address subnet_gateway <<<"$subnet_case"
    valid_cmdline=$(command_line)
    valid_cmdline=${valid_cmdline/iso_chain.address=10.0.2.15\/24/iso_chain.address=$subnet_address}
    valid_cmdline=${valid_cmdline/$valid_route/iso_chain.route=0.0.0.0\/0,$subnet_gateway}
    run_launcher "eth0" "" 206 "$valid_cmdline"
    grep -qx 'profile: passed' "$RUN_OUTPUT" || fail "valid partial-prefix gateway was rejected"
done

invalid_cmdline=$(command_line)
trailing_dot_dns='iso_chain.dns=10.0.2.3.,10.0.2.4'
invalid_cmdline=${invalid_cmdline/$valid_dns/$trailing_dot_dns}
assert_configuration_rejected "trailing-dot DNS address" "$invalid_cmdline"

invalid_cmdline=$(command_line)
invalid_cmdline=${invalid_cmdline/iso_chain.source=http:\/\/192.0.2.2/iso_chain.source=HTTP:\/\/192.0.2.2}
assert_configuration_rejected "non-canonical HTTP scheme" "$invalid_cmdline"

https_cmdline=$(command_line)
https_cmdline=${https_cmdline/iso_chain.source=http:\/\/192.0.2.2/iso_chain.source=https:\/\/192.0.2.2}
run_launcher "eth0" "" 206 "$https_cmdline"
grep -qx 'profile: passed' "$RUN_OUTPUT" || fail "HTTPS source was rejected"
grep -Fq 'https://192.0.2.2/repository/.treeinfo' "$RUN_CALLS" ||
    fail "HTTPS artifact request was not preserved"

https_path_cmdline=${https_cmdline/https:\/\/192.0.2.2/https:\/\/192.0.2.2\/fedora\/44}
run_launcher "eth0" "" 206 "$https_path_cmdline"
grep -qx 'profile: passed' "$RUN_OUTPUT" || fail "HTTPS source base path was rejected"
grep -Fq 'https://192.0.2.2/fedora/44/repository/.treeinfo' "$RUN_CALLS" ||
    fail "HTTPS source base path was not preserved"

invalid_cmdline=$(command_line)
invalid_cmdline=${invalid_cmdline/iso_chain.source=http:\/\/192.0.2.2/iso_chain.source=http:\/\/192.0.2.2:080}
assert_configuration_rejected "non-canonical HTTP port" "$invalid_cmdline"

for source_path in 'repository/' 'repository?query=value'; do
    source_cmdline=$(command_line)
    source_cmdline=${source_cmdline/iso_chain.source=http:\/\/192.0.2.2/iso_chain.source=http:\/\/192.0.2.2\/$source_path}
    run_launcher "eth0" "" 206 "$source_cmdline"
    test "$RUN_STATUS" -ne 0 || fail "source path unexpectedly succeeded: $source_path"
    grep -qx 'configuration: failed' "$RUN_OUTPUT" || fail "source path missed fixed marker"
    assert_no_network_calls
done

for profile_path in / /repository/ppc/ppc64/vmlinuz/; do
    invalid_cmdline=$(command_line)
    invalid_cmdline=${invalid_cmdline/iso_chain.profile_kernel_path=\/repository\/ppc\/ppc64\/vmlinuz/iso_chain.profile_kernel_path=$profile_path}
    assert_configuration_rejected "non-canonical profile path" "$invalid_cmdline"
done

for kickstart_path in / /profiles/fedora-44/ks.cfg/; do
    invalid_cmdline=$(command_line)
    invalid_cmdline=${invalid_cmdline/iso_chain.profile_kickstart_path=\/profiles\/fedora-44\/ks.cfg/iso_chain.profile_kickstart_path=$kickstart_path}
    assert_configuration_rejected "non-canonical Kickstart path" "$invalid_cmdline"
done

run_launcher "eth0"
test "$RUN_STATUS" -ne 0 || fail "returned kexec unexpectedly succeeded"
grep -qx 'ISO_CHAIN: configuration passed' "$RUN_OUTPUT" || fail "missing configuration marker"
grep -qx 'adapter-match: passed' "$RUN_OUTPUT" || fail "missing adapter marker"
grep -qx 'profile: passed' "$RUN_OUTPUT" || fail "missing profile marker"
grep -Eq '^memory: passed memtotal_mib=8192 memavailable_mib=6144 run_available_bytes=[0-9]+$' \
    "$RUN_OUTPUT" || fail "missing memory evidence"
grep -qx 'media: passed' "$RUN_OUTPUT" || fail "missing media marker"
test "$(grep -n -x -e 'media: passed' -e 'artifacts: passed' "$RUN_OUTPUT" | cut -d: -f2- | tr '\n' ' ')" = \
    'media: passed artifacts: passed ' || fail "media marker is not before artifacts"
grep -qx 'artifacts: passed' "$RUN_OUTPUT" || fail "missing artifact marker"
grep -qx 'kexec-load: passed' "$RUN_OUTPUT" || fail "missing load marker"
grep -qx 'kexec-exec: started' "$RUN_OUTPUT" || fail "missing execute marker"
grep -qx 'kexec-exec: returned' "$RUN_OUTPUT" || fail "returned execute was hidden"
test "$(cat "$RUN_RESV")" = $'nameserver 10.0.2.3\nnameserver 10.0.2.4' || fail "resolver is wrong"
test "$(grep '^curl ' "$RUN_CALLS" | sed 's/.* //' | tr '\n' ' ')" = \
    'http://192.0.2.2/repository/ppc/ppc64/vmlinuz http://192.0.2.2/repository/ppc/ppc64/initrd.img http://192.0.2.2/repository/.treeinfo http://192.0.2.2/repository/repodata/repomd.xml ' ||
    fail "artifact requests are wrong"
grep -Fq 'mount -t iso9660 -o ro,nodev,nosuid,noexec' "$RUN_CALLS" || fail "media was not mounted"
awk '/^mount / { mounted = 1 } /^umount / { mounted = 0 } /^curl / { exit mounted }' "$RUN_CALLS" ||
    fail "media stayed mounted into artifact traffic"
if grep -q '^curl .*ks\.cfg' "$RUN_CALLS"; then fail "Kickstart was requested"; fi
grep -Fq 'http://192.0.2.2/repository/.treeinfo' "$RUN_CALLS" || fail "treeinfo was not fetched"
grep -Fq 'http://192.0.2.2/repository/repodata/repomd.xml' "$RUN_CALLS" || fail "repomd was not fetched"
expected_fedora_args='--command-line=inst.text rd.neednet=1 ifname=iso0:52:54:00:ab:cd:ef'
expected_fedora_args="$expected_fedora_args ip=10.0.2.15::10.0.2.2:255.255.255.0:sys-r1:iso0:none"
grep -Fq -- "$expected_fedora_args" "$RUN_CALLS" || fail "Fedora arguments are wrong"
media_label=ISO_CHAIN_$(printf '%s' "$config_digest" | cut -c1-16 | tr 'a-f' 'A-F')
grep -Fq "inst.ks=cdrom:LABEL=$media_label:/profiles/fedora-44/ks.cfg" "$RUN_CALLS" ||
    fail "Kickstart argument is not bound to the verified media"
grep -Fqx "blkid -c /dev/null -t LABEL=$media_label -o device" "$RUN_CALLS" ||
    fail "media label uniqueness was not checked"
test "$(grep -c '^kexec -u$' "$RUN_CALLS")" -eq 1 || fail "returned execute was not unloaded once"
test -z "$(find "$workspace/run" -mindepth 1 -print -quit)" || fail "workspace was not cleaned"
if grep -Eqi 'dhcp|ipv6[^.]|--location' "$RUN_CALLS"; then fail "fallback networking was requested"; fi

grep -qx 'disk: passed' "$RUN_OUTPUT" || fail "one blank disk missed disk marker"
test "$(grep -n -E -x -e 'memory: passed .*' -e 'disk: passed' -e 'media: passed' "$RUN_OUTPUT" |
    cut -d: -f2 | tr '\n' ' ')" = 'memory disk media ' || fail "disk marker is out of order"

for fault in disk-settle disk-none disk-two disk-head disk-tail disk-small; do
    run_launcher "eth0" "$fault"
    test "$RUN_STATUS" -ne 0 || fail "$fault unexpectedly succeeded"
    grep -qx 'disk: failed' "$RUN_OUTPUT" || fail "$fault missed fixed marker"
    case "$fault" in
    disk-settle) reason='disk-settle: failed' ;;
    disk-none) reason='disk-count: failed count=0' ;;
    disk-two) reason='disk-count: failed count=2' ;;
    *) reason='disk-blank: failed' ;;
    esac
    grep -qx "$reason" "$RUN_OUTPUT" || fail "$fault missed actionable reason"
    if grep -q -e '^mount ' -e '^curl ' -e '^kexec ' "$RUN_CALLS"; then fail "$fault reached a handoff"; fi
    test "$RUN_DISKS_BEFORE" = "$RUN_DISKS_AFTER" || fail "$fault changed a disk"
done

for fault in controller-pci-storage controller-pci-fc controller-pci-unreadable \
    controller-vio-vscsi controller-vio-fcp controller-two; do
    run_launcher "eth0" "$fault"
    test "$RUN_STATUS" -ne 0 || fail "$fault unexpectedly succeeded"
    grep -qx 'disk: failed' "$RUN_OUTPUT" || fail "$fault missed fixed marker"
    unbound=1
    [ "$fault" != controller-two ] || unbound=2
    grep -qx "disk-controller: failed unbound=$unbound" "$RUN_OUTPUT" ||
        fail "$fault missed actionable reason"
    if grep -q -e '^mount ' -e '^curl ' -e '^kexec ' "$RUN_CALLS"; then fail "$fault reached a handoff"; fi
    test "$RUN_DISKS_BEFORE" = "$RUN_DISKS_AFTER" || fail "$fault changed a disk"
done

run_launcher "eth0" controller-bus-empty
grep -qx 'disk: passed' "$RUN_OUTPUT" || fail "an empty bus tree was refused"

run_launcher "eth0" disk-middle
grep -qx 'disk: passed' "$RUN_OUTPUT" || fail "data between the checked regions was refused"

run_launcher "eth0" threshold
grep -qx 'artifacts: passed' "$RUN_OUTPUT" || fail "exact memory threshold was rejected"

run_launcher "eth0" media-second
grep -qx 'media: passed' "$RUN_OUTPUT" || fail "matching media beside foreign media was not found"
grep -qx 'kexec-load: passed' "$RUN_OUTPUT" || fail "matching media beside foreign media was not used"

run_launcher "eth0 eth1"
test "$RUN_STATUS" -ne 0 || fail "duplicate adapters unexpectedly succeeded"
grep -qx 'adapter-match: failed' "$RUN_OUTPUT" || fail "duplicate adapters missed fixed marker"
assert_no_network_calls

for fault in ip curl size digest initramfs-digest media-none media-duplicate media-foreign mount \
    media-label media-size media-digest memory availability space load execute unload; do
    run_launcher "eth0" "$fault"
    test "$RUN_STATUS" -ne 0 || fail "$fault failure unexpectedly succeeded"
    case "$fault" in
    ip) marker='network: failed' ;;
    memory | availability | space) marker='memory: failed' ;;
    load) marker='kexec-load: failed' ;;
    *) marker='launcher: failed' ;;
    esac
    grep -qx "$marker" "$RUN_OUTPUT" || fail "$fault failure missed fixed marker"
    case "$fault" in
    curl) reason='kernel-http: failed' ;;
    size) reason='kernel-size: failed' ;;
    digest) reason='kernel-digest: failed' ;;
    initramfs-digest) reason='initramfs-digest: failed' ;;
    media-none | media-duplicate | media-foreign | media-label | mount) reason='media: failed' ;;
    media-size) reason='kickstart-size: failed' ;;
    media-digest) reason='kickstart-digest: failed' ;;
    memory) reason='profile-memory: failed' ;;
    availability) reason='available-memory: failed' ;;
    space) reason='run-space: failed' ;;
    *) reason= ;;
    esac
    [ -z "$reason" ] || grep -qx "$reason" "$RUN_OUTPUT" ||
        fail "$fault failure missed actionable reason"
    case "$fault" in
    memory | availability | space)
        if grep -q '^curl ' "$RUN_CALLS" 2>/dev/null; then fail "$fault reached artifact traffic"; fi
        ;;
    execute)
        grep -qx 'kexec-exec: failed' "$RUN_OUTPUT" || fail "execute failure was hidden"
        test "$(grep -c '^kexec -u$' "$RUN_CALLS")" -eq 1 || fail "execute failure did not unload"
        ;;
    unload)
        grep -qx 'kexec-unload: failed' "$RUN_OUTPUT" || fail "unload failure was hidden"
        ;;
    digest)
        test "$(grep -c '^curl ' "$RUN_CALLS")" -eq 1 || fail "bad digest reached later traffic"
        if grep -q '^kexec ' "$RUN_CALLS"; then fail "bad digest reached kexec"; fi
        ;;
    media-*)
        if grep -q -e '^curl ' -e '^kexec ' "$RUN_CALLS"; then fail "$fault reached traffic"; fi
        ;;
    mount)
        if grep -q -e '^curl ' -e '^kexec ' "$RUN_CALLS"; then fail "$fault reached traffic"; fi
        if grep -q 'wrong fs type' "$RUN_OUTPUT"; then fail "probe mount error reached console"; fi
        ;;
    esac
done

run_launcher "eth0" "" 206 "$(ubuntu_command_line)"
test "$RUN_STATUS" -ne 0 || fail "Ubuntu returned kexec unexpectedly succeeded"
for marker in 'ISO_CHAIN: configuration passed' 'adapter-match: passed' 'profile: passed' \
    'artifacts: passed' 'kexec-load: passed' 'kexec-exec: started'; do
    grep -qx "$marker" "$RUN_OUTPUT" || fail "Ubuntu launch missed marker: $marker"
done
if grep -q '^media: ' "$RUN_OUTPUT"; then fail "Ubuntu launch reported media"; fi
if grep -q '^mount ' "$RUN_CALLS"; then fail "Ubuntu launch mounted media"; fi
test "$(grep '^curl ' "$RUN_CALLS" | sed 's/.* //' | tr '\n' ' ')" = \
    'http://192.0.2.2/ubuntu/netboot/ppc64el/linux http://192.0.2.2/ubuntu/netboot/ppc64el/initrd ' ||
    fail "Ubuntu artifact requests are wrong"
expected_ubuntu_args='--command-line=ip=10.0.2.15::10.0.2.2:255.255.255.0:sys-r1::off:10.0.2.3:10.0.2.4'
expected_ubuntu_args="$expected_ubuntu_args BOOTIF=01-52-54-00-ab-cd-ef"
expected_ubuntu_args="$expected_ubuntu_args iso-url=http://192.0.2.2/ubuntu/ubuntu-26.04.1-live-server-ppc64el.iso"
expected_ubuntu_args="$expected_ubuntu_args console=hvc0 ipv6.disable=1"
grep -q -- "$expected_ubuntu_args\$" "$RUN_CALLS" || fail "Ubuntu arguments are wrong"
if grep -Eqi 'dhcp|ipv6[^.]|--location' "$RUN_CALLS"; then fail "Ubuntu requested fallback networking"; fi
test -z "$(find "$workspace/run" -mindepth 1 -print -quit)" || fail "Ubuntu workspace was not cleaned"

ubuntu_cmdline=$(ubuntu_command_line)
run_launcher "eth0" "" 206 "${ubuntu_cmdline/iso_chain.dns=10.0.2.3,10.0.2.4/iso_chain.dns=}"
grep -Fq ':sys-r1::off BOOTIF=01-52-54-00-ab-cd-ef ' "$RUN_CALLS" ||
    fail "Ubuntu arguments without DNS are wrong"

live_iso_argument='iso_chain.profile_live_iso_path=/ubuntu/ubuntu-26.04.1-live-server-ppc64el.iso'
assert_configuration_rejected "Ubuntu without live ISO" "${ubuntu_cmdline/$live_iso_argument/}"
assert_configuration_rejected "Ubuntu non-ISO live path" \
    "${ubuntu_cmdline/$live_iso_argument/iso_chain.profile_live_iso_path=/ubuntu/live.img}"
assert_configuration_rejected "Ubuntu with Kickstart" \
    "$ubuntu_cmdline iso_chain.profile_kickstart_path=/profiles/fedora-44/ks.cfg"
assert_configuration_rejected "Ubuntu with a second route" \
    "$ubuntu_cmdline iso_chain.route=192.0.2.0/24,10.0.2.2"
assert_configuration_rejected "Ubuntu with three DNS servers" \
    "${ubuntu_cmdline/iso_chain.dns=10.0.2.3,10.0.2.4/iso_chain.dns=10.0.2.3,10.0.2.4,10.0.2.5}"
assert_configuration_rejected "Ubuntu with Fedora release" \
    "${ubuntu_cmdline/iso_chain.profile_release=26.04.1/iso_chain.profile_release=44}"
assert_configuration_rejected "Fedora with live ISO" \
    "$(command_line) iso_chain.profile_live_iso_path=/ubuntu/x.iso"

for fault in digest initramfs-digest; do
    run_launcher "eth0" "$fault" 206 "$ubuntu_cmdline"
    test "$RUN_STATUS" -ne 0 || fail "Ubuntu $fault unexpectedly succeeded"
    grep -qx 'launcher: failed' "$RUN_OUTPUT" || fail "Ubuntu $fault missed fixed marker"
    case "$fault" in
    digest) reason='kernel-digest: failed' ;;
    *) reason='initramfs-digest: failed' ;;
    esac
    grep -qx "$reason" "$RUN_OUTPUT" || fail "Ubuntu $fault missed actionable reason"
    if grep -q '^kexec ' "$RUN_CALLS"; then fail "Ubuntu $fault reached kexec"; fi
done

user_data_digest=$(printf 'userdata' | "$workspace/bin/sha256sum" | cut -d' ' -f1)
ubuntu_user_data="iso_chain.profile_user_data_size=8 iso_chain.profile_user_data_sha256=$user_data_digest"
unattended_label=ISO_CHAIN_$(printf '%s' "$config_digest" | cut -c1-16 | tr 'a-f' 'A-F')
run_launcher "eth0" "" 206 "$ubuntu_cmdline $ubuntu_user_data"
test "$RUN_STATUS" -ne 0 || fail "unattended Ubuntu returned kexec unexpectedly succeeded"
for marker in 'ISO_CHAIN: configuration passed' 'disk: passed' 'media: passed' \
    'artifacts: passed' 'kexec-load: passed' 'kexec-exec: started'; do
    grep -qx "$marker" "$RUN_OUTPUT" || fail "unattended Ubuntu missed marker: $marker"
done
expected_unattended_ubuntu="${expected_ubuntu_args% console=hvc0 ipv6.disable=1}"
expected_unattended_ubuntu="$expected_unattended_ubuntu autoinstall ds=nocloud"
expected_unattended_ubuntu="$expected_unattended_ubuntu cc:datasource:%20{NoCloud:%20{fs_label:%20$unattended_label}}%20end_cc"
expected_unattended_ubuntu="$expected_unattended_ubuntu console=hvc0 --- ipv6.disable=1"
expected_unattended_ubuntu="$expected_unattended_ubuntu rd.systemd.mask=systemd-networkd.service"
expected_unattended_ubuntu="$expected_unattended_ubuntu rd.systemd.mask=systemd-networkd.socket"
grep -Fq -- "$expected_unattended_ubuntu" "$RUN_CALLS" || fail "unattended Ubuntu arguments are wrong"
grep -q -- "--command-line=.*systemd-networkd.socket\$" "$RUN_CALLS" || fail "unattended Ubuntu line has a tail"
for tag in "LABEL=$(printf '%s' "$unattended_label" | tr 'A-Z' 'a-z')" "LABEL_FATBOOT=$unattended_label"; do
    grep -Fqx -- "blkid -c /dev/null -t $tag -o device" "$RUN_CALLS" ||
        fail "unattended Ubuntu did not check NoCloud label $tag"
done
test -z "$(find "$workspace/run" -mindepth 1 -print -quit)" || fail "unattended Ubuntu workspace was not cleaned"

for fault in user-data-digest meta-data-content meta-data-missing meta-data-link nocloud-lower \
    nocloud-fat nocloud-error media-none media-duplicate; do
    run_launcher "eth0" "$fault" 206 "$ubuntu_cmdline $ubuntu_user_data"
    test "$RUN_STATUS" -ne 0 || fail "unattended Ubuntu $fault unexpectedly succeeded"
    case "$fault" in
    user-data-digest) reason='user-data-digest: failed' ;;
    meta-data-*) reason='meta-data: failed' ;;
    nocloud-*) reason='media-label: failed' ;;
    *) reason='media: failed' ;;
    esac
    grep -qx "$reason" "$RUN_OUTPUT" || fail "unattended Ubuntu $fault missed actionable reason"
    grep -qx 'launcher: failed' "$RUN_OUTPUT" || fail "unattended Ubuntu $fault missed fixed marker"
    if grep -q '^curl ' "$RUN_CALLS"; then fail "unattended Ubuntu $fault downloaded"; fi
    if grep -q '^kexec ' "$RUN_CALLS"; then fail "unattended Ubuntu $fault reached kexec"; fi
done

assert_configuration_rejected "Ubuntu with user-data size alone" \
    "$ubuntu_cmdline iso_chain.profile_user_data_size=8"
assert_configuration_rejected "Ubuntu with user-data digest alone" \
    "$ubuntu_cmdline iso_chain.profile_user_data_sha256=$user_data_digest"
assert_configuration_rejected "Ubuntu with oversized user data" \
    "$ubuntu_cmdline ${ubuntu_user_data/size=8/size=1048577}"
assert_configuration_rejected "Ubuntu with a non-hex user-data digest" \
    "$ubuntu_cmdline ${ubuntu_user_data/sha256=?/sha256=g}"
assert_configuration_rejected "Ubuntu with repeated user-data size" \
    "$ubuntu_cmdline $ubuntu_user_data iso_chain.profile_user_data_size=8"
assert_configuration_rejected "Fedora with user data" "$(command_line) $ubuntu_user_data"

rocky_command_line() {
    local cmdline
    cmdline=$(command_line)
    cmdline=${cmdline/iso_chain.profile=fedora/iso_chain.profile=rocky}
    cmdline=${cmdline/iso_chain.profile_distribution=fedora/iso_chain.profile_distribution=rocky}
    cmdline=${cmdline/iso_chain.profile_release=44/iso_chain.profile_release=9.8}
    cmdline=${cmdline//=\/repository/=$rocky_repository}
    cmdline=${cmdline/iso_chain.profile_kickstart_path=\/profiles\/fedora-44\/ks.cfg /}
    cmdline=${cmdline/iso_chain.profile_kickstart_size=9 /}
    cmdline=${cmdline/iso_chain.profile_kickstart_sha256=$kickstart_digest /}
    printf '%s' "$cmdline"
}

rocky_repository=/pub/rocky/9.8/BaseOS/ppc64le/os
rocky_cmdline=$(rocky_command_line)
run_launcher "eth0" "" 206 "$rocky_cmdline"
test "$RUN_STATUS" -ne 0 || fail "Rocky returned kexec unexpectedly succeeded"
for marker in 'adapter-match: passed' 'artifacts: passed' 'kexec-load: passed'; do
    grep -qx "$marker" "$RUN_OUTPUT" || fail "Rocky launch missed marker: $marker"
done
if grep -q '^media: ' "$RUN_OUTPUT"; then fail "Rocky launch reported media"; fi
if grep -q -e '^mount ' -e '^blkid ' "$RUN_CALLS"; then fail "Rocky launch probed media"; fi
rocky_url=http://192.0.2.2$rocky_repository
test "$(grep '^curl ' "$RUN_CALLS" | sed 's/.* //' | tr '\n' ' ')" = \
    "$rocky_url/ppc/ppc64/vmlinuz $rocky_url/ppc/ppc64/initrd.img $rocky_url/.treeinfo $rocky_url/repodata/repomd.xml " ||
    fail "Rocky artifact requests are wrong"
expected_rocky_args='--command-line=inst.text rd.neednet=1 ifname=iso0:52:54:00:ab:cd:ef'
expected_rocky_args="$expected_rocky_args ip=10.0.2.15::10.0.2.2:255.255.255.0:sys-r1:iso0:none"
expected_rocky_args="$expected_rocky_args rd.route=0.0.0.0/0:10.0.2.2:iso0"
expected_rocky_args="$expected_rocky_args nameserver=10.0.2.3 nameserver=10.0.2.4"
expected_rocky_args="$expected_rocky_args inst.repo=$rocky_url console=hvc0 ipv6.disable=1"
grep -q -- "$expected_rocky_args\$" "$RUN_CALLS" || fail "Rocky arguments are wrong"
if grep -q 'inst.ks' "$RUN_CALLS"; then fail "Rocky handoff named a Kickstart"; fi

for unknown_argument in iso_chain.future_setting=1 iso_chain.profile_kernel_sha25=abc iso_chain.foo; do
    assert_configuration_rejected "unknown argument $unknown_argument" \
        "$rocky_cmdline $unknown_argument"
done

run_launcher "eth0" "" 206 "$rocky_cmdline rd.shell=0 ipv6.disable=1 quiet"
grep -qx 'kexec-load: passed' "$RUN_OUTPUT" || fail "non-iso_chain arguments were rejected"
if grep -Eqi 'dhcp|ipv6[^.]|--location' "$RUN_CALLS"; then fail "Rocky requested fallback networking"; fi
test -z "$(find "$workspace/run" -mindepth 1 -print -quit)" || fail "Rocky workspace was not cleaned"

rocky_kickstart="iso_chain.profile_kickstart_path=/profiles/rocky/ks.cfg"
rocky_kickstart="$rocky_kickstart iso_chain.profile_kickstart_size=9"
rocky_kickstart="$rocky_kickstart iso_chain.profile_kickstart_sha256=$kickstart_digest"
run_launcher "eth0" "" 206 "$rocky_cmdline $rocky_kickstart"
test "$RUN_STATUS" -ne 0 || fail "unattended Rocky returned kexec unexpectedly succeeded"
for marker in 'disk: passed' 'media: passed' 'artifacts: passed' 'kexec-load: passed'; do
    grep -qx "$marker" "$RUN_OUTPUT" || fail "unattended Rocky launch missed marker: $marker"
done
grep -Fq 'mount -t iso9660 -o ro,nodev,nosuid,noexec' "$RUN_CALLS" ||
    fail "unattended Rocky media was not mounted"
if grep -q '^curl .*ks\.cfg' "$RUN_CALLS"; then fail "unattended Rocky Kickstart was requested"; fi
expected_unattended="${expected_rocky_args% inst.repo=*}"
expected_unattended="$expected_unattended inst.ks=cdrom:LABEL=$media_label:/profiles/rocky/ks.cfg"
expected_unattended="$expected_unattended inst.repo=$rocky_url console=hvc0 ipv6.disable=1"
grep -q -- "$expected_unattended\$" "$RUN_CALLS" || fail "unattended Rocky arguments are wrong"
test -z "$(find "$workspace/run" -mindepth 1 -print -quit)" ||
    fail "unattended Rocky workspace was not cleaned"

run_launcher "eth0" media-digest 206 "$rocky_cmdline $rocky_kickstart"
test "$RUN_STATUS" -ne 0 || fail "unattended Rocky Kickstart digest unexpectedly succeeded"
if grep -q -e '^curl ' -e '^kexec ' "$RUN_CALLS"; then
    fail "unattended Rocky Kickstart mismatch reached a download"
fi

assert_configuration_rejected "Rocky with a partial Kickstart" \
    "$rocky_cmdline iso_chain.profile_kickstart_path=/profiles/rocky/ks.cfg"
assert_configuration_rejected "Rocky with an oversized Kickstart" \
    "$rocky_cmdline ${rocky_kickstart/size=9/size=1048577}"
assert_configuration_rejected "Rocky with live ISO" \
    "$rocky_cmdline iso_chain.profile_live_iso_path=/ubuntu/x.iso"
assert_configuration_rejected "Rocky with a non-BaseOS repository" \
    "${rocky_cmdline//=$rocky_repository/=/repository}"
assert_configuration_rejected "Rocky without repomd" \
    "${rocky_cmdline/iso_chain.profile_repomd_size=8 /}"
assert_configuration_rejected "Rocky with Fedora release" \
    "${rocky_cmdline/iso_chain.profile_release=9.8/iso_chain.profile_release=44}"

run_launcher "eth0" digest 206 "$rocky_cmdline"
test "$RUN_STATUS" -ne 0 || fail "Rocky digest unexpectedly succeeded"
grep -qx 'kernel-digest: failed' "$RUN_OUTPUT" || fail "Rocky digest missed actionable reason"
if grep -q '^kexec ' "$RUN_CALLS"; then fail "Rocky digest reached kexec"; fi

run_launcher "eth0" "" 206 "$(opensuse_command_line)"
test "$RUN_STATUS" -ne 0 || fail "openSUSE returned kexec unexpectedly succeeded"
for marker in 'ISO_CHAIN: configuration passed' 'adapter-match: passed' 'profile: passed' \
    'artifacts: passed' 'kexec-load: passed' 'kexec-exec: started'; do
    grep -qx "$marker" "$RUN_OUTPUT" || fail "openSUSE launch missed marker: $marker"
done
if grep -q '^media: ' "$RUN_OUTPUT"; then fail "openSUSE launch reported media"; fi
if grep -q -e '^mount ' -e '^blkid ' "$RUN_CALLS"; then fail "openSUSE launch probed media"; fi
test "$(grep '^curl ' "$RUN_CALLS" | sed 's/.* //' | tr '\n' ' ')" = \
    'http://192.0.2.2/oss/boot/ppc64le/linux http://192.0.2.2/oss/boot/ppc64le/initrd ' ||
    fail "openSUSE artifact requests are wrong"
expected_opensuse_args='--command-line=ifcfg=52:54:00:ab:cd:ef=10.0.2.15/24,10.0.2.2,10.0.2.3'
expected_opensuse_args="$expected_opensuse_args hostname=sys-r1 install=http://192.0.2.2/oss"
expected_opensuse_args="$expected_opensuse_args textmode=1 self_update=0 console=hvc0 ipv6.disable=1"
grep -q -- "$expected_opensuse_args\$" "$RUN_CALLS" || fail "openSUSE arguments are wrong"
if grep -Eqi 'dhcp|ipv6[^.]|--location' "$RUN_CALLS"; then fail "openSUSE requested fallback networking"; fi
test -z "$(find "$workspace/run" -mindepth 1 -print -quit)" || fail "openSUSE workspace was not cleaned"

opensuse_cmdline=$(opensuse_command_line)
run_launcher "eth0" "" 206 "${opensuse_cmdline/iso_chain.dns=10.0.2.3/iso_chain.dns=}"
grep -q -- '--command-line=ifcfg=52:54:00:ab:cd:ef=10.0.2.15/24,10.0.2.2 hostname=' "$RUN_CALLS" ||
    fail "openSUSE arguments without DNS are wrong"

assert_configuration_rejected "openSUSE with treeinfo" \
    "$opensuse_cmdline iso_chain.profile_treeinfo_size=8"
assert_configuration_rejected "openSUSE with repomd" \
    "$opensuse_cmdline iso_chain.profile_repomd_size=8"
assert_configuration_rejected "openSUSE with a live ISO" \
    "$opensuse_cmdline iso_chain.profile_live_iso_path=/ubuntu/x.iso"
assert_configuration_rejected "openSUSE with Kickstart" \
    "$opensuse_cmdline iso_chain.profile_kickstart_path=/profiles/fedora-44/ks.cfg"
assert_configuration_rejected "openSUSE with user data" "$opensuse_cmdline $ubuntu_user_data"
assert_configuration_rejected "Rocky with user data" "$rocky_cmdline $ubuntu_user_data"
assert_configuration_rejected "openSUSE with a second route" \
    "$opensuse_cmdline iso_chain.route=192.0.2.0/24,10.0.2.2"
assert_configuration_rejected "openSUSE with a second DNS server" \
    "${opensuse_cmdline/iso_chain.dns=10.0.2.3/iso_chain.dns=10.0.2.3,10.0.2.4}"
assert_configuration_rejected "openSUSE without a repository path" \
    "${opensuse_cmdline/iso_chain.profile_repository_path=\/oss /}"
assert_configuration_rejected "openSUSE with Fedora release" \
    "${opensuse_cmdline/iso_chain.profile_release=15.6/iso_chain.profile_release=44}"

run_launcher "eth0" digest 206 "$opensuse_cmdline"
test "$RUN_STATUS" -ne 0 || fail "openSUSE digest unexpectedly succeeded"
grep -qx 'kernel-digest: failed' "$RUN_OUTPUT" || fail "openSUSE digest missed actionable reason"
if grep -q '^kexec ' "$RUN_CALLS"; then fail "openSUSE digest reached kexec"; fi

for guarded_cmdline in "$ubuntu_cmdline" "$rocky_cmdline" "$opensuse_cmdline"; do
    run_launcher "eth0" disk-head 206 "$guarded_cmdline"
    test "$RUN_STATUS" -ne 0 || fail "non-Fedora non-blank disk unexpectedly succeeded"
    grep -qx 'disk-blank: failed' "$RUN_OUTPUT" || fail "non-Fedora disk refusal missed reason"
    if grep -q -e '^curl ' -e '^kexec ' "$RUN_CALLS"; then fail "non-Fedora refusal reached a handoff"; fi
    run_launcher "eth0" controller-pci-storage 206 "$guarded_cmdline"
    test "$RUN_STATUS" -ne 0 || fail "non-Fedora unbound controller unexpectedly succeeded"
    grep -qx 'disk-controller: failed unbound=1' "$RUN_OUTPUT" ||
        fail "non-Fedora controller refusal missed reason"
    if grep -q -e '^curl ' -e '^kexec ' "$RUN_CALLS"; then fail "non-Fedora refusal reached a handoff"; fi
done

printf 'launcher shell tests: passed\n'
