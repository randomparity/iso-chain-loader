#!/bin/sh
set -eu

sys_class_net=${ISO_CHAIN_SYS_CLASS_NET:-/sys/class/net}
resolv_conf=${ISO_CHAIN_RESOLV_CONF:-/etc/resolv.conf}
cmdline=${ISO_CHAIN_CMDLINE:-$(cat /proc/cmdline)}
meminfo=${ISO_CHAIN_MEMINFO:-/proc/meminfo}
run_dir=${ISO_CHAIN_RUN_DIR:-/run}
media_devices=${ISO_CHAIN_MEDIA_DEVICES:-/dev/sr*}
sys_block=${ISO_CHAIN_SYS_BLOCK:-/sys/block}
dev_dir=${ISO_CHAIN_DEV_DIR:-/dev}
zero_mib_sha256=30e14955ebf1352266dc2ff8067e68104607e750abb9d3b36582b8af909fcb58
workspace=
media_dir=
media_mounted=
resolver_temporary=

fail() {
    printf '%s\n' "$1" >&2
    exit 1
}

cleanup() {
    # The exit path has already reported its failure; a failed unmount must not replace it.
    [ -z "$media_mounted" ] || umount "$media_dir" || true
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

valid_fedora_arguments() {
    [ -z "$live_iso_path" ] && valid_path "$repository_path" || return 1
    valid_size "$treeinfo_size" && valid_sha256 "$treeinfo_digest" || return 1
    valid_size "$repomd_size" && valid_sha256 "$repomd_digest" || return 1
    valid_path "$kickstart_path" && valid_size "$kickstart_size" || return 1
    [ "$kickstart_size" -le 1048576 ] && valid_sha256 "$kickstart_digest"
}

valid_rocky_arguments() {
    [ -z "$live_iso_path" ] && valid_path "$repository_path" || return 1
    # An unattended Rocky profile carries a build-derived Kickstart (ADR 0019); keyless has none.
    if [ -n "$kickstart_path$kickstart_size$kickstart_digest" ]; then
        valid_path "$kickstart_path" && valid_size "$kickstart_size" || return 1
        [ "$kickstart_size" -le 1048576 ] && valid_sha256 "$kickstart_digest" || return 1
    fi
    # The AppStream sibling that Anaconda adds hangs off the BaseOS tree (ADR 0013).
    case "$repository_path" in */BaseOS/ppc64le/os) ;; *) return 1 ;; esac
    valid_size "$treeinfo_size" && valid_sha256 "$treeinfo_digest" || return 1
    valid_size "$repomd_size" && valid_sha256 "$repomd_digest"
}

valid_ubuntu_arguments() {
    [ -z "$repository_path$treeinfo_size$treeinfo_digest$repomd_size$repomd_digest" ] ||
        return 1
    [ -z "$kickstart_path$kickstart_size$kickstart_digest" ] || return 1
    valid_path "$live_iso_path" || return 1
    case "$live_iso_path" in *.iso) ;; *) return 1 ;; esac
    # casper's ip= carries one gateway and at most two DNS servers (ADR 0012). Each route line
    # ends in a newline, so a second newline means a second route.
    case "$routes" in *"
"*"
"*) return 1 ;; esac
    case "$dns" in *,*,*) return 1 ;; esac
}

valid_opensuse_arguments() {
    [ -z "$live_iso_path$treeinfo_size$treeinfo_digest$repomd_size$repomd_digest" ] || return 1
    [ -z "$kickstart_path$kickstart_size$kickstart_digest" ] || return 1
    valid_path "$repository_path" || return 1
    # linuxrc's ifcfg= carries one gateway and one DNS server (ADR 0014). Each route line ends
    # in a newline, so a second newline means a second route.
    case "$routes" in *"
"*"
"*) return 1 ;; esac
    case "$dns" in *,*) return 1 ;; esac
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
    live_iso_path=''
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
        iso_chain.profile_live_iso_path=*)
            [ -z "$live_iso_path" ] || return 1
            live_iso_path=${argument#*=}
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
    valid_ipv4_cidr "$address" && valid_source && valid_routes && one_default_route || return 1
    valid_path "$kernel_path" && valid_size "$kernel_size" || return 1
    valid_sha256 "$kernel_digest" || return 1
    valid_path "$initramfs_path" && valid_size "$initramfs_size" || return 1
    valid_sha256 "$initramfs_digest" || return 1
    case "$distribution:$release" in
    fedora:44) valid_fedora_arguments || return 1 ;;
    rocky:9.8) valid_rocky_arguments || return 1 ;;
    ubuntu:26.04.1) valid_ubuntu_arguments || return 1 ;;
    opensuse:15.6) valid_opensuse_arguments || return 1 ;;
    *) return 1 ;;
    esac
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
    fedora_bytes=$((${treeinfo_size:-0} + ${repomd_size:-0} + ${kickstart_size:-0}))
    download_bytes=$((executable_bytes + fedora_bytes))
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

zero_mib() {
    # A failed read or digest yields a different value, so the check refuses rather than passes.
    found=$(dd if="$dev_dir/$1" bs=512 skip="$2" count=2048 2>/dev/null | sha256sum)
    [ "${found%% *}" = "$zero_mib_sha256" ]
}

check_disk() {
    # ADR 0018: exactly one non-optical disk, zero in its first and last MiB; read only.
    udevadm settle --timeout=60 || { stage_failure disk-settle; return 1; }
    disk_count=0
    for entry in "$sys_block"/*; do
        [ -e "$entry/device" ] || continue
        case "${entry##*/}" in sr*) continue ;; esac
        disk_count=$((disk_count + 1))
        disk=${entry##*/}
    done
    [ "$disk_count" -eq 1 ] || {
        printf 'disk-count: failed count=%s\n' "$disk_count" >&2
        return 1
    }
    sectors=$(cat "$sys_block/$disk/size") || sectors=
    case "$sectors" in '' | *[!0-9]*) stage_failure disk-blank; return 1 ;; esac
    # A disk under 2,048 sectors reads short, so its digest cannot match either.
    zero_mib "$disk" 0 && zero_mib "$disk" $((sectors - 2048)) || {
        stage_failure disk-blank
        return 1
    }
}

publish_artifact() {
    label=$1
    size=$2
    expected=$3
    partial="$workspace/$label.partial"
    [ -f "$partial" ] && [ ! -L "$partial" ] || { stage_failure "$label-file"; return 1; }
    [ "$(stat -c '%s' "$partial")" = "$size" ] || { stage_failure "$label-size"; return 1; }
    actual=$(sha256sum "$partial") || { stage_failure "$label-digest-read"; return 1; }
    [ "${actual%% *}" = "$expected" ] || { stage_failure "$label-digest"; return 1; }
    mv "$partial" "$workspace/$label" || { stage_failure "$label-publish"; return 1; }
}

download_artifact() {
    curl --disable --ipv4 --fail --no-location --cacert /etc/ssl/certs/ca-certificates.crt \
        --connect-timeout 30 --max-time 1200 \
        --max-filesize "$3" --output "$workspace/$1.partial" "$source$2" || {
        stage_failure "$1-http"
        return 1
    }
    publish_artifact "$1" "$3" "$4"
}

copy_media_artifact() {
    cat "$media_dir$2" >"$workspace/$1.partial" || { stage_failure "$1-media"; return 1; }
    publish_artifact "$1" "$3" "$4"
}

media_label() {
    # The build labels the ISO from the config digest; see _volume_id in scripts/iso_chain.py.
    printf 'ISO_CHAIN_%s\n' "$(printf '%s' "${config_digest%"${config_digest#????????????????}"}" |
        tr 'a-f' 'A-F')"
}

find_media() {
    udevadm settle --timeout=60 || return 1
    media_dir="$workspace/media"
    mkdir "$media_dir" || return 1
    matches=0
    media_device=
    for device in $media_devices; do
        [ -e "$device" ] || continue
        # Discovery probes every optical device; a non-iso9660 one is not a match.
        mount -t iso9660 -o ro,nodev,nosuid,noexec "$device" "$media_dir" 2>/dev/null ||
            continue
        found=$(sha256sum "$media_dir/iso-chain/config.json" 2>/dev/null) || found=
        umount "$media_dir" || return 1
        [ "${found%% *}" = "$config_digest" ] || continue
        matches=$((matches + 1))
        media_device=$device
    done
    [ "$matches" -eq 1 ] || return 1
    # Anaconda resolves inst.ks by label, so no other block device may carry this one.
    labelled=$(blkid -c /dev/null -t "LABEL=$(media_label)" -o device) || return 1
    [ "$labelled" = "$media_device" ] || return 1
    mount -t iso9660 -o ro,nodev,nosuid,noexec "$media_device" "$media_dir" || return 1
    media_mounted=1
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

anaconda_command_line() {
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
    arguments="$arguments$resolver_arguments"
    [ -z "$kickstart_path" ] ||
        arguments="$arguments inst.ks=cdrom:LABEL=$(media_label):$kickstart_path"
    arguments="$arguments inst.repo=$source$repository_path"
    printf '%s\n' "$arguments console=hvc0 ipv6.disable=1"
}

launch_anaconda() {
    umask 077
    workspace=$(mktemp -d "$run_dir/iso-chain.XXXXXX") || return 1
    # Only a Kickstart lives on the launcher media; keyless Rocky has none (ADR 0013, ADR 0019).
    if [ -n "$kickstart_path" ]; then
        find_media || { stage_failure media; return 1; }
        printf '%s\n' 'media: passed'
        copy_media_artifact kickstart \
            "$kickstart_path" "$kickstart_size" "$kickstart_digest" || return 1
        umount "$media_dir" || { stage_failure media-unmount; return 1; }
        media_mounted=
    fi
    download_artifact kernel "$kernel_path" "$kernel_size" "$kernel_digest" || return 1
    download_artifact initramfs \
        "$initramfs_path" "$initramfs_size" "$initramfs_digest" || return 1
    download_artifact treeinfo \
        "$repository_path/.treeinfo" "$treeinfo_size" "$treeinfo_digest" || return 1
    download_artifact repomd \
        "$repository_path/repodata/repomd.xml" "$repomd_size" "$repomd_digest" || return 1
    printf '%s\n' 'artifacts: passed'
    arguments=$(anaconda_command_line) || return 1
    execute_kexec "$arguments"
}

ubuntu_command_line() {
    route=${routes%"
"}
    dns_fields=
    [ -z "$dns" ] || dns_fields=:$(printf '%s' "$dns" | tr ',' ':')
    bootif=01-$(printf '%s' "$mac" | tr ':' '-')
    arguments="ip=${address%/*}::${route#*,}:$(netmask):$lpar::off$dns_fields"
    # casper also reads url=, but cloud-init would then fetch the ISO as a cloud-config URL.
    arguments="$arguments BOOTIF=$bootif iso-url=$source$live_iso_path"
    printf '%s\n' "$arguments console=hvc0 ipv6.disable=1"
}

launch_ubuntu() {
    umask 077
    workspace=$(mktemp -d "$run_dir/iso-chain.XXXXXX") || return 1
    download_artifact kernel "$kernel_path" "$kernel_size" "$kernel_digest" || return 1
    download_artifact initramfs \
        "$initramfs_path" "$initramfs_size" "$initramfs_digest" || return 1
    printf '%s\n' 'artifacts: passed'
    execute_kexec "$(ubuntu_command_line)"
}

opensuse_command_line() {
    route=${routes%"
"}
    arguments="ifcfg=$mac=$address,${route#*,}${dns:+,$dns} hostname=$lpar"
    arguments="$arguments install=$source$repository_path textmode=1 self_update=0"
    printf '%s\n' "$arguments console=hvc0 ipv6.disable=1"
}

launch_opensuse() {
    umask 077
    workspace=$(mktemp -d "$run_dir/iso-chain.XXXXXX") || return 1
    download_artifact kernel "$kernel_path" "$kernel_size" "$kernel_digest" || return 1
    download_artifact initramfs \
        "$initramfs_path" "$initramfs_size" "$initramfs_digest" || return 1
    printf '%s\n' 'artifacts: passed'
    execute_kexec "$(opensuse_command_line)"
}

execute_kexec() {
    kexec -l "$workspace/kernel" --initrd="$workspace/initramfs" --command-line="$1" ||
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
    check_disk || fail 'disk: failed'
    printf '%s\n' 'disk: passed'
    case "$distribution" in
    ubuntu) launch_ubuntu ;;
    opensuse) launch_opensuse ;;
    *) launch_anaconda ;;
    esac || fail 'launcher: failed'
}

main "$@"
