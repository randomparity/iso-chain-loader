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
    chmod +x "$workspace/bin/ip" "$workspace/bin/curl" "$workspace/bin/kexec" \
        "$workspace/bin/sync" "$workspace/bin/stat" "$workspace/bin/sha256sum" \
        "$workspace/bin/udevadm" "$workspace/bin/mount" "$workspace/bin/umount"
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
    rm -rf "$net" "$resolv" "$calls" "$output" "$run_dir" "$media"
    mkdir -p "$net" "$run_dir" "$media"
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
    [ "$fault" != media-digest ] || printf 'kickstarX' >"$media/sr0/profiles/fedora-44/ks.cfg"
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
        ISO_CHAIN_MEDIA_DEVICES="$media/sr*" \
        "$launcher" >"$output" 2>&1
    RUN_STATUS=$?
    set -e
    RUN_CALLS=$calls
    RUN_OUTPUT=$output
    RUN_RESV=$resolv
}

make_device() {
    mkdir -p "$1/iso-chain" "$1/profiles/fedora-44"
    printf 'config' >"$1/iso-chain/config.json"
    printf 'kickstart' >"$1/profiles/fedora-44/ks.cfg"
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
if grep -q '^curl .*ks\.cfg' "$RUN_CALLS"; then fail "Kickstart was requested"; fi
grep -Fq 'http://192.0.2.2/repository/.treeinfo' "$RUN_CALLS" || fail "treeinfo was not fetched"
grep -Fq 'http://192.0.2.2/repository/repodata/repomd.xml' "$RUN_CALLS" || fail "repomd was not fetched"
expected_fedora_args='--command-line=inst.text rd.neednet=1 ifname=iso0:52:54:00:ab:cd:ef'
expected_fedora_args="$expected_fedora_args ip=10.0.2.15::10.0.2.2:255.255.255.0:sys-r1:iso0:none"
grep -Fq -- "$expected_fedora_args" "$RUN_CALLS" || fail "Fedora arguments are wrong"
media_label=ISO_CHAIN_$(printf '%s' "$config_digest" | cut -c1-16 | tr 'a-f' 'A-F')
grep -Fq "inst.ks=cdrom:LABEL=$media_label:/profiles/fedora-44/ks.cfg" "$RUN_CALLS" ||
    fail "Kickstart argument is not bound to the verified media"
test "$(grep -c '^kexec -u$' "$RUN_CALLS")" -eq 1 || fail "returned execute was not unloaded once"
test -z "$(find "$workspace/run" -mindepth 1 -print -quit)" || fail "workspace was not cleaned"
if grep -Eqi 'dhcp|ipv6[^.]|--location' "$RUN_CALLS"; then fail "fallback networking was requested"; fi

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
    media-size     media-digest memory availability space load execute unload; do
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
    media-none | media-duplicate | media-foreign | mount) reason='media: failed' ;;
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

printf 'launcher shell tests: passed\n'
