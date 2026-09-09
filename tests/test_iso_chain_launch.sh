#!/usr/bin/env bash
set -euo pipefail

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

write_fake_commands
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

run_launcher "eth0"
test "$RUN_STATUS" -eq 0 || fail "one adapter failed"
grep -qx 'ISO_CHAIN: configuration passed' "$RUN_OUTPUT" || fail "missing configuration marker"
grep -qx 'adapter-match: passed' "$RUN_OUTPUT" || fail "missing adapter marker"
grep -qx 'profile: passed' "$RUN_OUTPUT" || fail "missing profile marker"
grep -qx 'http-probe: passed' "$RUN_OUTPUT" || fail "missing HTTP marker"
test "$(cat "$RUN_RESV")" = $'nameserver 10.0.2.3\nnameserver 10.0.2.4' || fail "resolver is wrong"
expected_calls=$'ip address replace 10.0.2.15/24 dev eth0\nip link set dev eth0 up\nip route replace 0.0.0.0/0 via 10.0.2.2 dev eth0\ncurl --ipv4 --fail --no-location --max-time 30 --max-filesize 1 --range 0-0 --output /dev/null --write-out %{http_code} http://192.0.2.2/probe'
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
