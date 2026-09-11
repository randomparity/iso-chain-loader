#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
launcher="$root/assets/dracut/iso-chain-launch.sh"
stage2_hook="$root/assets/dracut/iso-chain-fedora-stage2.sh"
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
    */vmlinuz) content=kernel ;;
    */initramfs.img) content=initramfs ;;
    */.treeinfo) content=treeinfo ;;
    */repodata/repomd.xml) content=metadata ;;
    *) exit 22 ;;
esac
[ "${ISO_CHAIN_FAULT:-}" != digest ] || content=tamper
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
if [ "${ISO_CHAIN_FAULT:-}" = space ] && [ "$1" = -f ]; then
    printf '1:1\n'
else
    /usr/bin/stat "$@"
fi
EOF
    chmod +x "$workspace/bin/ip" "$workspace/bin/curl" "$workspace/bin/kexec" \
        "$workspace/bin/sync" "$workspace/bin/stat"
}

command_line() {
    printf '%s' 'iso_chain.lpar=sys-r1 iso_chain.mac=52:54:00:ab:cd:ef iso_chain.address=10.0.2.15/24 '
    printf '%s' 'iso_chain.route=0.0.0.0/0,10.0.2.2 iso_chain.dns=10.0.2.3,10.0.2.4 '
    printf '%s' 'iso_chain.source=http://192.0.2.2 iso_chain.profile=fedora '
    printf '%s' 'iso_chain.profile_distribution=fedora iso_chain.profile_release=44 '
    printf '%s' 'iso_chain.profile_kernel_path=/profiles/fedora-44/vmlinuz iso_chain.profile_kernel_size=6 '
    printf '%s' 'iso_chain.profile_kernel_sha256=6923dd1bc0460082c5d55a831908c24a282860b7f1cd6c2b79cf1bc8857c639c '
    printf '%s' 'iso_chain.profile_initramfs_path=/profiles/fedora-44/initramfs.img iso_chain.profile_initramfs_size=9 '
    printf '%s' 'iso_chain.profile_initramfs_sha256=9752c38a9065f7646ffaac3621d1fa2f7dbe726c7e12e511eac7fdb14d4e2a24 '
    printf '%s' 'iso_chain.profile_repository_path=/repository iso_chain.profile_treeinfo_size=8 '
    printf '%s' 'iso_chain.profile_treeinfo_sha256=103c1f80d3ca13d76a1eff05f141c5924f3c5e006b27e0755242e804b141f564 '
    printf '%s' 'iso_chain.profile_repomd_size=8 '
    printf '%s' 'iso_chain.profile_repomd_sha256=45447b7afbd5e544f7d0f1df0fccd26014d9850130abd3f020b89ff96b82079f '
    printf '%s' 'iso_chain.profile_minimum_memory_mib=4096 '
    printf '%s' 'iso_chain.config_sha256=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
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
    rm -rf "$net" "$resolv" "$calls" "$output" "$run_dir"
    mkdir -p "$net" "$run_dir"
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
        "$launcher" >"$output" 2>&1
    RUN_STATUS=$?
    set -e
    RUN_CALLS=$calls
    RUN_OUTPUT=$output
    RUN_RESV=$resolv
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
test -x "$launcher" || fail "launcher runtime is absent"
test -x "$stage2_hook" || fail "Fedora stage2 hook is absent"
grep -Fqx '. /usr/lib/anaconda-lib.sh' "$stage2_hook" || fail "stage2 library is not fixed"
grep -Fq '[ -f /iso-chain/install.img ]' "$stage2_hook" || fail "runtime is not regular-only"
grep -Fqx 'anaconda_mount_sysroot /iso-chain/install.img' "$stage2_hook" ||
    fail "stage2 runtime is not mounted exactly once"
test "$(grep -Fc 'anaconda_mount_sysroot ' "$stage2_hook")" -eq 1 ||
    fail "stage2 runtime mount is repeated"
grep -Fqx '[ -d /run/rootfsbase ] || [ -b /dev/mapper/live-rw ] || fail_stage2' "$stage2_hook" ||
    fail "flattened and nested live roots are not accepted"

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

invalid_cmdline=$(command_line)
trailing_dot_dns='iso_chain.dns=10.0.2.3.,10.0.2.4'
invalid_cmdline=${invalid_cmdline/$valid_dns/$trailing_dot_dns}
assert_configuration_rejected "trailing-dot DNS address" "$invalid_cmdline"

invalid_cmdline=$(command_line)
invalid_cmdline=${invalid_cmdline/iso_chain.source=http:\/\/192.0.2.2/iso_chain.source=HTTP:\/\/192.0.2.2}
assert_configuration_rejected "non-canonical HTTP scheme" "$invalid_cmdline"

for source_path in 'repository/' 'repository?query=value'; do
    source_cmdline=$(command_line)
    source_cmdline=${source_cmdline/iso_chain.source=http:\/\/192.0.2.2/iso_chain.source=http:\/\/192.0.2.2\/$source_path}
    run_launcher "eth0" "" 206 "$source_cmdline"
    test "$RUN_STATUS" -ne 0 || fail "source path unexpectedly succeeded: $source_path"
    grep -qx 'configuration: failed' "$RUN_OUTPUT" || fail "source path missed fixed marker"
    assert_no_network_calls
done

run_launcher "eth0"
test "$RUN_STATUS" -ne 0 || fail "returned kexec unexpectedly succeeded"
grep -qx 'ISO_CHAIN: configuration passed' "$RUN_OUTPUT" || fail "missing configuration marker"
grep -qx 'adapter-match: passed' "$RUN_OUTPUT" || fail "missing adapter marker"
grep -qx 'profile: passed' "$RUN_OUTPUT" || fail "missing profile marker"
grep -Eq '^memory: passed memtotal_mib=8192 memavailable_mib=6144 run_available_bytes=[0-9]+$' \
    "$RUN_OUTPUT" || fail "missing memory evidence"
grep -qx 'artifacts: passed' "$RUN_OUTPUT" || fail "missing artifact marker"
grep -qx 'kexec-load: passed' "$RUN_OUTPUT" || fail "missing load marker"
grep -qx 'kexec-exec: started' "$RUN_OUTPUT" || fail "missing execute marker"
grep -qx 'kexec-exec: returned' "$RUN_OUTPUT" || fail "returned execute was hidden"
test "$(cat "$RUN_RESV")" = $'nameserver 10.0.2.3\nnameserver 10.0.2.4' || fail "resolver is wrong"
test "$(grep -c '^curl ' "$RUN_CALLS")" -eq 4 || fail "artifact request count is wrong"
grep -Fq 'http://192.0.2.2/repository/.treeinfo' "$RUN_CALLS" || fail "treeinfo was not fetched"
grep -Fq 'http://192.0.2.2/repository/repodata/repomd.xml' "$RUN_CALLS" || fail "repomd was not fetched"
expected_fedora_args='--command-line=rd.neednet=1 ifname=iso0:52:54:00:ab:cd:ef'
expected_fedora_args="$expected_fedora_args ip=10.0.2.15::10.0.2.2:255.255.255.0:sys-r1:iso0:none"
grep -Fq -- "$expected_fedora_args" "$RUN_CALLS" || fail "Fedora arguments are wrong"
if grep -Fq 'root=/dev/mapper/live-rw' "$RUN_CALLS"; then fail "flattened runtime waits on legacy root"; fi
test "$(grep -c '^kexec -u$' "$RUN_CALLS")" -eq 1 || fail "returned execute was not unloaded once"
test -z "$(find "$workspace/run" -mindepth 1 -print -quit)" || fail "workspace was not cleaned"
if grep -Eqi 'dhcp|ipv6[^.]|--location' "$RUN_CALLS"; then fail "fallback networking was requested"; fi

run_launcher "eth0" threshold
grep -qx 'artifacts: passed' "$RUN_OUTPUT" || fail "exact memory threshold was rejected"

run_launcher "eth0 eth1"
test "$RUN_STATUS" -ne 0 || fail "duplicate adapters unexpectedly succeeded"
grep -qx 'adapter-match: failed' "$RUN_OUTPUT" || fail "duplicate adapters missed fixed marker"
assert_no_network_calls

for fault in ip curl digest memory availability space load execute unload; do
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
    esac
done

printf 'launcher shell tests: passed\n'
