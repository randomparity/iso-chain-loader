#!/bin/sh
set -eu

sys_class_net=${ISO_CHAIN_SYS_CLASS_NET:-/sys/class/net}
resolv_conf=${ISO_CHAIN_RESOLV_CONF:-/etc/resolv.conf}
cmdline=${ISO_CHAIN_CMDLINE:-$(cat /proc/cmdline)}

fail() {
    printf '%s\n' "$1" >&2
    exit 1
}

valid_value() {
    case "$1" in
        ''|*[!A-Za-z0-9./,:_-]*) return 1 ;;
    esac
    return 0
}

valid_mac() {
    old_ifs=$IFS
    IFS=:
    set -f
    # shellcheck disable=SC2086 # Deliberate MAC-octet splitting with pathname expansion off.
    set -- $mac
    set +f
    IFS=$old_ifs
    [ "$#" -eq 6 ] || return 1
    for octet in "$@"; do
        case "$octet" in [0-9a-f][0-9a-f]) ;; *) return 1 ;; esac
    done
    case "${1#?}" in 1|3|5|7|9|b|d|f) return 1 ;; esac
}

valid_octet() {
    case "$1" in
        [0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5]) ;;
        *) return 1 ;;
    esac
}

valid_ipv4() {
    old_ifs=$IFS
    IFS=.
    set -f
    # shellcheck disable=SC2086 # Deliberate IPv4-octet splitting with pathname expansion off.
    set -- $1
    set +f
    IFS=$old_ifs
    [ "$#" -eq 4 ] || return 1
    valid_octet "$1" && valid_octet "$2" && valid_octet "$3" && valid_octet "$4"
}

valid_ipv4_cidr() {
    address_part=${1%/*}
    prefix=${1#*/}
    [ "$address_part/$prefix" = "$1" ] || return 1
    valid_ipv4 "$address_part" || return 1
    case "$prefix" in 0|[1-9]|[12][0-9]|3[0-2]) return 0 ;; esac
    return 1
}

valid_ipv4_network() {
    valid_ipv4_cidr "$1" || return 1
    network_address=${1%/*}
    network_prefix=${1#*/}
    old_ifs=$IFS
    IFS=.
    set -f
    # shellcheck disable=SC2086 # The address passed valid_ipv4_cidr above.
    set -- $network_address
    set +f
    IFS=$old_ifs
    network_number=$(((($1 * 256 + $2) * 256 + $3) * 256 + $4))
    host_bits=$((32 - network_prefix))
    [ "$host_bits" -eq 0 ] && return 0
    host_mask=$(((1 << host_bits) - 1))
    [ $((network_number & host_mask)) -eq 0 ]
}

gateway_in_address_subnet() {
    configured_address=${address%/*}
    prefix_length=${address#*/}

    old_ifs=$IFS
    IFS=.
    set -f
    # shellcheck disable=SC2086 # Both values passed valid_ipv4 before this comparison.
    set -- $configured_address $1
    set +f
    IFS=$old_ifs

    full_octets=$((prefix_length / 8))
    partial_bits=$((prefix_length % 8))
    case "$full_octets" in
        0) ;;
        1) [ "$1" -eq "$5" ] || return 1 ;;
        2) [ "$1" -eq "$5" ] && [ "$2" -eq "$6" ] || return 1 ;;
        3) [ "$1" -eq "$5" ] && [ "$2" -eq "$6" ] && [ "$3" -eq "$7" ] || return 1 ;;
        4) [ "$1" -eq "$5" ] && [ "$2" -eq "$6" ] && [ "$3" -eq "$7" ] &&
            [ "$4" -eq "$8" ] || return 1 ;;
    esac
    [ "$partial_bits" -eq 0 ] && return 0

    mask=$((256 - (1 << (8 - partial_bits))))
    case "$full_octets" in
        0) [ $((1 & mask)) -eq $((5 & mask)) ] ;;
        1) [ $((2 & mask)) -eq $((6 & mask)) ] ;;
        2) [ $((3 & mask)) -eq $((7 & mask)) ] ;;
        3) [ $((4 & mask)) -eq $((8 & mask)) ] ;;
    esac
}

valid_digest() {
    [ "${#digest}" -eq 64 ] || return 1
    case "$digest" in *[!0-9a-f]*) return 1 ;; esac
    return 0
}

valid_profile() {
    [ "${#profile}" -le 32 ] || return 1
    case "$profile" in [a-z]*) ;; *) return 1 ;; esac
    case "$profile" in *[!a-z0-9-]*) return 1 ;; esac
}

valid_dns_label() {
    [ -n "$1" ] && [ "${#1}" -le 63 ] || return 1
    case "$1" in
        [!A-Za-z0-9]*|*[!A-Za-z0-9-]*|*[!A-Za-z0-9]) return 1 ;;
    esac
}

valid_source_host() {
    [ -n "$1" ] && [ "${#1}" -le 253 ] || return 1
    valid_ipv4 "$1" && return 0
    case "$1" in .*|*.) return 1 ;; esac
    old_ifs=$IFS
    IFS=.
    set -f
    # shellcheck disable=SC2086 # Deliberate DNS-label splitting with pathname expansion off.
    set -- $1
    set +f
    IFS=$old_ifs
    for label in "$@"; do
        valid_dns_label "$label" || return 1
    done
}

valid_port() {
    case "$1" in *[!0-9]*|'') return 1 ;; esac
    port_number=$1
    while [ "${port_number#0}" != "$port_number" ]; do
        port_number=${port_number#0}
    done
    case "$port_number" in
        [1-9]|[1-9][0-9]|[1-9][0-9][0-9]|[1-9][0-9][0-9][0-9]|\
        [1-5][0-9][0-9][0-9][0-9]|6[0-4][0-9][0-9][0-9]|65[0-4][0-9][0-9]|\
        655[0-2][0-9]|6553[0-5]) return 0 ;;
    esac
    return 1
}

valid_source() {
    case "$source" in http://*) ;; *) return 1 ;; esac
    authority_and_path=${source#http://}
    case "$authority_and_path" in */*) ;; *) return 1 ;; esac
    authority=${authority_and_path%%/*}
    path=/${authority_and_path#*/}
    case "$authority" in ''|*[!A-Za-z0-9.:-]*|*:*:*) return 1 ;; esac
    host=${authority%%:*}
    if [ "$host" != "$authority" ]; then
        valid_port "${authority#*:}" || return 1
    fi
    valid_source_host "$host" || return 1
    case "$path" in *[!A-Za-z0-9./_~%_-]*) return 1 ;; esac
    escaped_path=$path
    while :; do
        case "$escaped_path" in
            *%*)
                escaped_path=${escaped_path#*%}
                case "$escaped_path" in [0-9A-Fa-f][0-9A-Fa-f]*) ;; *) return 1 ;; esac
                escaped_path=${escaped_path#??}
                ;;
            *) return 0 ;;
        esac
    done
}

valid_routes() {
    route_count=0
    route_destinations='|'
    printf '%s' "$routes" | while IFS=, read -r destination gateway; do
        [ -n "$destination" ] && [ -n "$gateway" ] || exit 1
        valid_ipv4_network "$destination" && valid_ipv4 "$gateway" || exit 1
        gateway_in_address_subnet "$gateway" || exit 1
        case "$route_destinations" in *"|$destination|"*) exit 1 ;; esac
        route_destinations="$route_destinations$destination|"
        route_count=$((route_count + 1))
        [ "$route_count" -le 16 ] || exit 1
    done
}

parse_arguments() {
    mac=''
    address=''
    dns=''
    source=''
    profile=''
    digest=''
    routes=''
    set -f
    # shellcheck disable=SC2086 # The kernel command line is deliberately split into tokens.
    set -- $cmdline
    set +f
    for argument in "$@"; do
        case "$argument" in
            iso_chain.mac=*) [ -z "$mac" ] || return 1; mac=${argument#*=} ;;
            iso_chain.address=*) [ -z "$address" ] || return 1; address=${argument#*=} ;;
            iso_chain.route=*) routes="$routes${argument#*=}
" ;;
            iso_chain.dns=*) [ -z "$dns" ] || return 1; dns=${argument#*=} ;;
            iso_chain.source=*) [ -z "$source" ] || return 1; source=${argument#*=} ;;
            iso_chain.profile=*) [ -z "$profile" ] || return 1; profile=${argument#*=} ;;
            iso_chain.config_sha256=*) [ -z "$digest" ] || return 1; digest=${argument#*=} ;;
        esac
    done
    [ -n "$mac" ] && [ -n "$address" ] && [ -n "$routes" ] && [ -n "$source" ] || return 1
    [ -n "$profile" ] && [ -n "$digest" ] || return 1
    valid_mac && valid_ipv4_cidr "$address" && valid_source || return 1
    valid_profile && valid_digest && valid_routes || return 1
    dns_count=0
    [ -z "$dns" ] || printf '%s\n' "$dns" | tr ',' '\n' | while IFS= read -r server; do
        dns_count=$((dns_count + 1))
        [ "$dns_count" -le 3 ] && valid_ipv4 "$server" || exit 1
    done
}

find_adapter() {
    matches=0
    adapter=
    wanted=$(printf '%s' "$mac" | tr 'A-F' 'a-f')
    for path in "$sys_class_net"/*; do
        [ -d "$path" ] || continue
        name=${path##*/}
        [ "$name" = lo ] && continue
        [ -r "$path/address" ] || continue
        found=$(tr 'A-F' 'a-f' < "$path/address" | tr -d '\n')
        [ "$found" = "$wanted" ] || continue
        matches=$((matches + 1))
        adapter=$name
    done
    [ "$matches" -eq 1 ]
}

configure_network() {
    ip address replace "$address" dev "$adapter" || return 1
    ip link set dev "$adapter" up || return 1
    printf '%s' "$routes" | while IFS=, read -r destination gateway; do
        [ -n "$destination" ] && [ -n "$gateway" ] || exit 1
        ip route replace "$destination" via "$gateway" dev "$adapter" || exit 1
    done
}

write_resolver() {
    [ -n "$dns" ] || return 0
    temporary="$resolv_conf.iso-chain.$$"
    umask 077
    trap 'rm -f "$temporary"' EXIT HUP INT TERM
    : > "$temporary" || return 1
    old_ifs=$IFS
    IFS=,
    for server in $dns; do
        valid_value "$server" || return 1
        printf 'nameserver %s\n' "$server" >> "$temporary" || return 1
    done
    IFS=$old_ifs
    mv -f "$temporary" "$resolv_conf" || return 1
    trap - EXIT HUP INT TERM
}

probe_http() {
    status=$(curl --ipv4 --fail --no-location --max-time 30 --max-filesize 1 --range 0-0 \
        --output /dev/null --write-out '%{http_code}' "$source") || return 1
    [ "$status" = 200 ] || [ "$status" = 206 ]
}

main() {
    parse_arguments || fail 'configuration: failed'
    printf '%s\n' 'ISO_CHAIN: configuration passed'
    find_adapter || fail 'adapter-match: failed'
    printf '%s\n' 'adapter-match: passed'
    if ! configure_network || ! write_resolver || ! probe_http; then
        fail 'launcher: failed'
    fi
    printf '%s\n' 'profile: passed'
    printf '%s\n' 'http-probe: passed'
}

main "$@"
