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
    cat > "$workspace/bin/ip" <<'EOF'
#!/usr/bin/env bash
printf 'ip %s\n' "$*" >> "$ISO_CHAIN_CALLS"
test "${ISO_CHAIN_FAULT:-}" != "ip" || exit 9
EOF
    cat > "$workspace/bin/curl" <<'EOF'
#!/usr/bin/env bash
printf 'curl %s\n' "$*" >> "$ISO_CHAIN_CALLS"
test "${ISO_CHAIN_FAULT:-}" != "curl" || exit 9
printf '%s' "${ISO_CHAIN_HTTP_STATUS:-206}"
EOF
    chmod +x "$workspace/bin/ip" "$workspace/bin/curl"
}

command_line() {
    printf '%s' 'iso_chain.mac=52:54:00:ab:cd:ef iso_chain.address=10.0.2.15/24 '
    printf '%s' 'iso_chain.route=0.0.0.0/0,10.0.2.2 iso_chain.dns=10.0.2.3,10.0.2.4 '
    printf '%s' 'iso_chain.source=http://192.0.2.2/probe iso_chain.profile=fedora '
    printf '%s' 'iso_chain.config_sha256=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
}

run_launcher() {
    local adapters=$1
    local fault=${2:-}
    local status=${3:-206}
    local cmdline=${4:-$(command_line)}
    local net="$workspace/net"
    local resolv="$workspace/resolv.conf"
    local calls="$workspace/calls"
    local output="$workspace/output"
    rm -rf "$net" "$resolv" "$calls" "$output"
    mkdir -p "$net"
    for adapter in $adapters; do
        mkdir -p "$net/$adapter"
        printf '%s\n' '52:54:00:AB:CD:EF' > "$net/$adapter/address"
    done
    set +e
    PATH="$workspace/bin:$PATH" ISO_CHAIN_SYS_CLASS_NET="$net" ISO_CHAIN_RESOLV_CONF="$resolv" \
        ISO_CHAIN_CMDLINE="$cmdline" ISO_CHAIN_CALLS="$calls" ISO_CHAIN_FAULT="$fault" \
        ISO_CHAIN_HTTP_STATUS="$status" "$launcher" > "$output" 2>&1
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
grep -Fqx 'anaconda_mount_sysroot /iso-chain/install.img' "$stage2_hook" || \
    fail "stage2 runtime is not mounted exactly once"
test "$(grep -Fc 'anaconda_mount_sysroot ' "$stage2_hook")" -eq 1 || \
    fail "stage2 runtime mount is repeated"
grep -Fq '[ -b /dev/mapper/live-rw ]' "$stage2_hook" || fail "live root is not required"

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
invalid_cmdline=${invalid_cmdline/iso_chain.source=http:\/\/192.0.2.2\/probe/iso_chain.source=HTTP:\/\/192.0.2.2\/probe}
assert_configuration_rejected "non-canonical HTTP scheme" "$invalid_cmdline"

for source_path in '~probe' 'probe%20x'; do
    source_cmdline=$(command_line)
    source_cmdline=${source_cmdline/iso_chain.source=http:\/\/192.0.2.2\/probe/iso_chain.source=http:\/\/192.0.2.2\/$source_path}
    run_launcher "eth0" "" 206 "$source_cmdline"
    test "$RUN_STATUS" -eq 0 || fail "valid source path was rejected: $source_path"
done

for source_path in 'probe%2G' 'probe?query=value'; do
    source_cmdline=$(command_line)
    source_cmdline=${source_cmdline/iso_chain.source=http:\/\/192.0.2.2\/probe/iso_chain.source=http:\/\/192.0.2.2\/$source_path}
    run_launcher "eth0" "" 206 "$source_cmdline"
    test "$RUN_STATUS" -ne 0 || fail "invalid source path unexpectedly succeeded: $source_path"
    grep -qx 'configuration: failed' "$RUN_OUTPUT" || fail "invalid source path missed fixed marker"
    assert_no_network_calls
done

run_launcher "eth0"
test "$RUN_STATUS" -eq 0 || fail "one adapter failed"
grep -qx 'ISO_CHAIN: configuration passed' "$RUN_OUTPUT" || fail "missing configuration marker"
grep -qx 'adapter-match: passed' "$RUN_OUTPUT" || fail "missing adapter marker"
grep -qx 'profile: passed' "$RUN_OUTPUT" || fail "missing profile marker"
grep -qx 'http-probe: passed' "$RUN_OUTPUT" || fail "missing HTTP marker"
test "$(cat "$RUN_RESV")" = $'nameserver 10.0.2.3\nnameserver 10.0.2.4' || fail "resolver is wrong"
expected_calls=$'ip address replace 10.0.2.15/24 dev eth0\nip link set dev eth0 up\nip route replace 0.0.0.0/0 via 10.0.2.2 dev eth0\ncurl --disable --ipv4 --fail --no-location --max-time 30 --max-filesize 1 --range 0-0 --output /dev/null --write-out %{http_code} http://192.0.2.2/probe'
test "$(cat "$RUN_CALLS")" = "$expected_calls" || fail "network operations are unordered"

run_launcher "eth0 eth1"
test "$RUN_STATUS" -ne 0 || fail "duplicate adapters unexpectedly succeeded"
grep -qx 'adapter-match: failed' "$RUN_OUTPUT" || fail "duplicate adapters missed fixed marker"
assert_no_network_calls

for fault in ip curl; do
    run_launcher "eth0" "$fault"
    test "$RUN_STATUS" -ne 0 || fail "$fault failure unexpectedly succeeded"
    grep -qx 'launcher: failed' "$RUN_OUTPUT" || fail "$fault failure missed fixed marker"
    if [ "$fault" = ip ]; then
        test "$(wc -l < "$RUN_CALLS")" -eq 1 || fail "ip fault reached a later operation"
    fi
done

run_launcher "eth0" "" 302
test "$RUN_STATUS" -ne 0 || fail "redirect status unexpectedly succeeded"
grep -qx 'launcher: failed' "$RUN_OUTPUT" || fail "HTTP failure missed fixed marker"

printf 'launcher shell tests: passed\n'
