#!/bin/sh
set -eu

sys_class_net=${ISO_CHAIN_SYS_CLASS_NET:-/sys/class/net}
resolv_conf=${ISO_CHAIN_RESOLV_CONF:-/etc/resolv.conf}
cmdline=${ISO_CHAIN_CMDLINE:-$(cat /proc/cmdline)}
meminfo=${ISO_CHAIN_MEMINFO:-/proc/meminfo}
run_dir=${ISO_CHAIN_RUN_DIR:-/run}
workspace=
resolver_temporary=

fail() {
    printf '%s\n' "$1" >&2
    exit 1
}

cleanup() {
    [ -z "$workspace" ] || rm -rf "$workspace"
    [ -z "$resolver_temporary" ] || rm -f "$resolver_temporary"
}
trap cleanup EXIT HUP INT TERM

valid_octet() {
    case "$1" in
    [0-9] | [1-9][0-9] | 1[0-9][0-9] | 2[0-4][0-9] | 25[0-5]) return 0 ;;
    esac
    return 1
}

valid_ipv4() {
    case "$1" in .* | *. | *..*) return 1 ;; esac
    old_ifs=$IFS
    IFS=.
    set -f
    # shellcheck disable=SC2086 # Deliberate IPv4 splitting after metacharacter rejection.
    set -- $1
    set +f
    IFS=$old_ifs
    [ "$#" -eq 4 ] || return 1
    valid_octet "$1" && valid_octet "$2" && valid_octet "$3" && valid_octet "$4"
}

valid_ipv4_cidr() {
    address_part=${1%/*}
    prefix=${1#*/}
    [ "$address_part/$prefix" = "$1" ] && valid_ipv4 "$address_part" || return 1
    case "$prefix" in 0 | [1-9] | [12][0-9] | 3[0-2]) return 0 ;; esac
    return 1
}

valid_ipv4_network() {
    valid_ipv4_cidr "$1" || return 1
    network_address=${1%/*}
    network_prefix=${1#*/}
    old_ifs=$IFS
    IFS=.
    set -f
    # shellcheck disable=SC2086 # Address passed strict IPv4 validation above.
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
    # shellcheck disable=SC2086 # Both values passed strict IPv4 validation.
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
    0) [ $(( $1 & mask )) -eq $(( $5 & mask )) ] ;;
    1) [ $(( $2 & mask )) -eq $(( $6 & mask )) ] ;;
    2) [ $(( $3 & mask )) -eq $(( $7 & mask )) ] ;;
    3) [ $(( $4 & mask )) -eq $(( $8 & mask )) ] ;;
    esac
}

valid_sha256() {
    [ "${#1}" -eq 64 ] || return 1
    case "$1" in *[!0-9a-f]*) return 1 ;; esac
}

valid_identifier() {
    [ "${#1}" -le 32 ] || return 1
    case "$1" in [a-z]*) ;; *) return 1 ;; esac
    case "$1" in *[!a-z0-9-]*) return 1 ;; esac
}

valid_size() {
    case "$1" in '' | *[!0-9]* | 0 | 0[0-9]*) return 1 ;; esac
    [ "$1" -le 2147483648 ]
}

valid_path() {
    case "$1" in /*) ;; *) return 1 ;; esac
    case "$1" in / | */) return 1 ;; esac
    case "$1" in *[!A-Za-z0-9./_~-]* | *//* | */./* | */../* | */. | */..) return 1 ;; esac
}

valid_dns_label() {
    [ -n "$1" ] && [ "${#1}" -le 63 ] || return 1
    case "$1" in [!A-Za-z0-9]* | *[!A-Za-z0-9-]* | *[!A-Za-z0-9]) return 1 ;; esac
}

valid_source_host() {
    [ -n "$1" ] && [ "${#1}" -le 253 ] || return 1
    valid_ipv4 "$1" && return 0
    case "$1" in .* | *.) return 1 ;; esac
    old_ifs=$IFS
    IFS=.
    set -f
    # shellcheck disable=SC2086 # Deliberate DNS-label splitting after validation.
    set -- $1
    set +f
    IFS=$old_ifs
    for label in "$@"; do valid_dns_label "$label" || return 1; done
}

valid_port() {
    case "$1" in '' | *[!0-9]* | 0 | 0[0-9]*) return 1 ;; esac
    [ "$1" -le 65535 ]
}

valid_source() {
    case "$source" in
    http://*) authority=${source#http://} ;;
    https://*) authority=${source#https://} ;;
    *) return 1 ;;
    esac
    case "$authority" in
    */*)
        host_authority=${authority%%/*}
        source_path=/${authority#*/}
        valid_path "$source_path" || return 1
        ;;
    *)
        host_authority=$authority
        source_path=
        ;;
    esac
    case "$host_authority" in '' | *[!A-Za-z0-9.:-]* | *:*:*) return 1 ;; esac
    host=${host_authority%%:*}
    [ "$host" = "$host_authority" ] || valid_port "${host_authority#*:}" || return 1
    valid_source_host "$host"
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

one_default_route() {
    count=0
    old_ifs=$IFS
    IFS='
'
    for route in $routes; do
        [ "${route%%,*}" != 0.0.0.0/0 ] || count=$((count + 1))
    done
    IFS=$old_ifs
    [ "$count" -eq 1 ]
}

parse_arguments() {
    lpar=''
    mac=''
    address=''
    dns=''
    source=''
    profile=''
    distribution=''
    release=''
    config_digest=''
    kernel_path=''
    kernel_size=''
    kernel_digest=''
    initramfs_path=''
    initramfs_size=''
    initramfs_digest=''
    repository_path=''
    treeinfo_size=''
    treeinfo_digest=''
    repomd_size=''
    repomd_digest=''
    kickstart_path=''
    kickstart_size=''
    kickstart_digest=''
    minimum_memory=''
    routes=
    set -f
    # shellcheck disable=SC2086 # Kernel command line is deliberately tokenized.
    set -- $cmdline
    set +f
    for argument in "$@"; do
        case "$argument" in
        iso_chain.lpar=*)
            [ -z "$lpar" ] || return 1
            lpar=${argument#*=}
            ;;
        iso_chain.mac=*)
            [ -z "$mac" ] || return 1
            mac=${argument#*=}
            ;;
        iso_chain.address=*)
            [ -z "$address" ] || return 1
            address=${argument#*=}
            ;;
        iso_chain.route=*) routes="$routes${argument#*=}
" ;;
        iso_chain.dns=*)
            [ -z "$dns" ] || return 1
            dns=${argument#*=}
            ;;
        iso_chain.source=*)
            [ -z "$source" ] || return 1
            source=${argument#*=}
            ;;
        iso_chain.profile=*)
            [ -z "$profile" ] || return 1
            profile=${argument#*=}
            ;;
        iso_chain.profile_distribution=*)
            [ -z "$distribution" ] || return 1
            distribution=${argument#*=}
            ;;
        iso_chain.profile_release=*)
            [ -z "$release" ] || return 1
            release=${argument#*=}
            ;;
        iso_chain.profile_kernel_path=*)
            [ -z "$kernel_path" ] || return 1
            kernel_path=${argument#*=}
            ;;
        iso_chain.profile_kernel_size=*)
            [ -z "$kernel_size" ] || return 1
            kernel_size=${argument#*=}
            ;;
        iso_chain.profile_kernel_sha256=*)
            [ -z "$kernel_digest" ] || return 1
            kernel_digest=${argument#*=}
            ;;
        iso_chain.profile_initramfs_path=*)
            [ -z "$initramfs_path" ] || return 1
            initramfs_path=${argument#*=}
            ;;
        iso_chain.profile_initramfs_size=*)
            [ -z "$initramfs_size" ] || return 1
            initramfs_size=${argument#*=}
            ;;
        iso_chain.profile_initramfs_sha256=*)
            [ -z "$initramfs_digest" ] || return 1
            initramfs_digest=${argument#*=}
            ;;
        iso_chain.profile_repository_path=*)
            [ -z "$repository_path" ] || return 1
            repository_path=${argument#*=}
            ;;
        iso_chain.profile_treeinfo_size=*)
            [ -z "$treeinfo_size" ] || return 1
            treeinfo_size=${argument#*=}
            ;;
        iso_chain.profile_treeinfo_sha256=*)
            [ -z "$treeinfo_digest" ] || return 1
            treeinfo_digest=${argument#*=}
            ;;
        iso_chain.profile_repomd_size=*)
            [ -z "$repomd_size" ] || return 1
            repomd_size=${argument#*=}
            ;;
        iso_chain.profile_repomd_sha256=*)
            [ -z "$repomd_digest" ] || return 1
            repomd_digest=${argument#*=}
            ;;
        iso_chain.profile_kickstart_path=*)
            [ -z "$kickstart_path" ] || return 1
            kickstart_path=${argument#*=}
            ;;
        iso_chain.profile_kickstart_size=*)
            [ -z "$kickstart_size" ] || return 1
            kickstart_size=${argument#*=}
            ;;
        iso_chain.profile_kickstart_sha256=*)
            [ -z "$kickstart_digest" ] || return 1
            kickstart_digest=${argument#*=}
            ;;
        iso_chain.profile_minimum_memory_mib=*)
            [ -z "$minimum_memory" ] || return 1
            minimum_memory=${argument#*=}
            ;;
        iso_chain.config_sha256=*)
            [ -z "$config_digest" ] || return 1
            config_digest=${argument#*=}
            ;;
        esac
    done
    valid_identifier "$lpar" && valid_identifier "$profile" || return 1
    [ "$distribution" = fedora ] && [ "$release" = 44 ] || return 1
    valid_ipv4_cidr "$address" && valid_source && valid_routes && one_default_route || return 1
    valid_path "$kernel_path" && valid_size "$kernel_size" || return 1
    valid_sha256 "$kernel_digest" || return 1
    valid_path "$initramfs_path" && valid_size "$initramfs_size" || return 1
    valid_sha256 "$initramfs_digest" && valid_path "$repository_path" || return 1
    valid_size "$treeinfo_size" && valid_sha256 "$treeinfo_digest" || return 1
    valid_size "$repomd_size" && valid_sha256 "$repomd_digest" || return 1
    valid_path "$kickstart_path" && valid_size "$kickstart_size" || return 1
    [ "$kickstart_size" -le 1048576 ] && valid_sha256 "$kickstart_digest" || return 1
    valid_size "$minimum_memory" && [ "$minimum_memory" -le 65536 ] || return 1
    valid_sha256 "$config_digest" && valid_mac || return 1
    dns_count=0
    [ -z "$dns" ] || printf '%s\n' "$dns" | tr ',' '\n' | while IFS= read -r server; do
        dns_count=$((dns_count + 1))
        [ "$dns_count" -le 3 ] && valid_ipv4 "$server" || exit 1
    done
}

valid_mac() {
    old_ifs=$IFS
    IFS=:
    set -f
    # shellcheck disable=SC2086 # Deliberate MAC splitting with pathname expansion off.
    set -- $mac
    set +f
    IFS=$old_ifs
    [ "$#" -eq 6 ] || return 1
    for octet in "$@"; do case "$octet" in [0-9a-f][0-9a-f]) ;; *) return 1 ;; esac done
    case "${1#?}" in 1 | 3 | 5 | 7 | 9 | b | d | f) return 1 ;; esac
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
        found=$(tr 'A-F' 'a-f' <"$path/address" | tr -d '\n')
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
    resolver_temporary="$resolv_conf.iso-chain.$$"
    umask 077
    : >"$resolver_temporary" || return 1
    old_ifs=$IFS
    IFS=,
    for server in $dns; do
        printf 'nameserver %s\n' "$server" >>"$resolver_temporary" || return 1
    done
    IFS=$old_ifs
    mv -f "$resolver_temporary" "$resolv_conf" || return 1
    resolver_temporary=
}

memory_value() {
    field=$1
    while read -r name value unit; do
        [ "$name" = "$field:" ] || continue
        case "$value" in '' | *[!0-9]*) return 1 ;; esac
        [ "$unit" = kB ] || return 1
        printf '%s\n' "$((value / 1024))"
        return 0
    done <"$meminfo"
    return 1
}

stage_failure() {
    printf '%s: failed\n' "$1" >&2
}

check_capacity() {
    total_mib=$(memory_value MemTotal) || { stage_failure memory-read; return 1; }
    available_mib=$(memory_value MemAvailable) || { stage_failure memory-read; return 1; }
    [ "$total_mib" -ge "$minimum_memory" ] || { stage_failure profile-memory; return 1; }
    executable_bytes=$((kernel_size + initramfs_size))
    download_bytes=$((executable_bytes + treeinfo_size + repomd_size + kickstart_size))
    required_mib=$(((executable_bytes + 1073741824 + 1048575) / 1048576))
    [ "$available_mib" -ge "$required_mib" ] || { stage_failure available-memory; return 1; }
    filesystem=$(stat -f -c '%a:%S' "$run_dir") || { stage_failure run-space-check; return 1; }
    blocks=${filesystem%:*}
    block_size=${filesystem#*:}
    case "$blocks:$block_size" in
    *[!0-9:]* | :* | *:) stage_failure run-space-check; return 1 ;;
    esac
    run_available_bytes=$((blocks * block_size))
    [ "$run_available_bytes" -ge $((download_bytes + 1073741824)) ] || {
        stage_failure run-space
        return 1
    }
}

download_artifact() {
    label=$1
    artifact_path=$2
    size=$3
    expected=$4
    partial="$workspace/$label.partial"
    destination="$workspace/$label"
    curl --disable --ipv4 --fail --no-location --connect-timeout 30 --max-time 1200 \
        --max-filesize "$size" --output "$partial" "$source$artifact_path" || {
        stage_failure "$label-http"
        return 1
    }
    [ -f "$partial" ] && [ ! -L "$partial" ] || { stage_failure "$label-file"; return 1; }
    [ "$(stat -c '%s' "$partial")" = "$size" ] || { stage_failure "$label-size"; return 1; }
    actual=$(sha256sum "$partial") || { stage_failure "$label-digest-read"; return 1; }
    [ "${actual%% *}" = "$expected" ] || { stage_failure "$label-digest"; return 1; }
    mv "$partial" "$destination" || { stage_failure "$label-publish"; return 1; }
}

mask_octet() {
    case "$1" in 0) echo 0 ;; 1) echo 128 ;; 2) echo 192 ;; 3) echo 224 ;;
    4) echo 240 ;; 5) echo 248 ;; 6) echo 252 ;; 7) echo 254 ;; *) echo 255 ;; esac
}

netmask() {
    remaining=${address#*/}
    result=
    for _ in 1 2 3 4; do
        bits=$remaining
        [ "$bits" -le 8 ] || bits=8
        octet=$(mask_octet "$bits")
        result=${result:+$result.}$octet
        remaining=$((remaining - bits))
    done
    printf '%s\n' "$result"
}

fedora_command_line() {
    gateway=
    route_arguments=
    old_ifs=$IFS
    IFS='
'
    for route in $routes; do
        destination=${route%%,*}
        route_gateway=${route#*,}
        [ "$destination" != 0.0.0.0/0 ] || {
            [ -z "$gateway" ] || return 1
            gateway=$route_gateway
        }
        route_arguments="$route_arguments rd.route=$destination:$route_gateway:iso0"
    done
    IFS=$old_ifs
    [ -n "$gateway" ] || return 1
    resolver_arguments=
    old_ifs=$IFS
    IFS=,
    for server in $dns; do resolver_arguments="$resolver_arguments nameserver=$server"; done
    IFS=$old_ifs
    client=${address%/*}
    mask=$(netmask)
    arguments="inst.text rd.neednet=1 ifname=iso0:$mac"
    arguments="$arguments ip=$client::$gateway:$mask:$lpar:iso0:none$route_arguments"
    arguments="$arguments$resolver_arguments inst.ks=file:/iso-chain/ks.cfg"
    arguments="$arguments inst.repo=$source$repository_path"
    printf '%s\n' "$arguments console=hvc0 ipv6.disable=1"
}

launch_fedora() {
    umask 077
    workspace=$(mktemp -d "$run_dir/iso-chain.XXXXXX") || return 1
    download_artifact kernel "$kernel_path" "$kernel_size" "$kernel_digest" || return 1
    download_artifact initramfs \
        "$initramfs_path" "$initramfs_size" "$initramfs_digest" || return 1
    download_artifact treeinfo \
        "$repository_path/.treeinfo" "$treeinfo_size" "$treeinfo_digest" || return 1
    download_artifact repomd \
        "$repository_path/repodata/repomd.xml" "$repomd_size" "$repomd_digest" || return 1
    download_artifact kickstart \
        "$kickstart_path" "$kickstart_size" "$kickstart_digest" || return 1
    printf '%s\n' 'artifacts: passed'
    arguments=$(fedora_command_line) || return 1
    kexec -l "$workspace/kernel" --initrd="$workspace/initramfs" --command-line="$arguments" ||
        fail 'kexec-load: failed'
    printf '%s\n' 'kexec-load: passed'
    sync
    printf '%s\n' 'kexec-exec: started'
    if kexec -e; then execute_status=returned; else execute_status=failed; fi
    printf '%s\n' "kexec-exec: $execute_status" >&2
    if ! kexec -u; then printf '%s\n' 'kexec-unload: failed' >&2; fi
    return 1
}

main() {
    parse_arguments || fail 'configuration: failed'
    printf '%s\n' 'ISO_CHAIN: configuration passed'
    find_adapter || fail 'adapter-match: failed'
    printf '%s\n' 'adapter-match: passed'
    if ! configure_network || ! write_resolver; then
        fail 'network: failed'
    fi
    printf '%s\n' 'profile: passed'
    check_capacity || fail 'memory: failed'
    printf 'memory: passed memtotal_mib=%s memavailable_mib=%s run_available_bytes=%s\n' \
        "$total_mib" "$available_mib" "$run_available_bytes"
    launch_fedora || fail 'launcher: failed'
}

main "$@"
