#!/usr/bin/env python3
"""Build and exercise the bounded POWER9 optical-bootstrap experiment."""

import argparse
import hashlib
import ipaddress
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

ANSI_ESCAPE = re.compile(r"\x1b\].*?(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]")
SERVICE_PREFIX = re.compile(r"^\[\s*\d+(?:\.\d+)?\]\s+[\w.-]+\[\d+\]:\s+")
BOOT_ID = r"([0-9A-Fa-f-]{36})"
MAX_LOG_BYTES = 16 * 1024 * 1024
MAX_MANIFEST_BYTES = 64 * 1024
MAX_COMMAND_LINE_BYTES = 2048
PASS_LINES = ("optical-boot: passed", "network: passed", "kexec: passed")
IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
MAC = re.compile(r"^[0-9a-f]{2}(?::[0-9a-f]{2}){5}$")
DNS_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
URI_PATH = re.compile(r"^(?:/[A-Za-z0-9._~%-]*)*$")
DRACUT_ASSETS = Path(__file__).resolve().parent.parent / "assets/dracut"
KERNEL_MODULES = Path("/usr/lib/modules")
DRACUT_FLAGS = ("--no-hostonly", "--reproducible", "--include", "--install", "--force-drivers")
DRACUT_DRIVERS = "virtio_net virtio_pci virtio_blk virtio_scsi"


class ValidationError(ValueError):
    pass


@dataclass(frozen=True)
class NetworkConfig:
    mac: str
    address: str
    routes: tuple[tuple[str, str], ...]
    dns: tuple[str, ...]


@dataclass(frozen=True)
class Manifest:
    version: int
    lpar: str
    network: NetworkConfig
    source: str
    profiles: tuple[str, ...]
    selected_profile: str


def _path(value: Path, label: str, kind: str) -> Path:
    try:
        path = Path(value).resolve(strict=True)
    except OSError as error:
        raise ValidationError(f"{label}: unavailable") from error
    valid = path.is_file() if kind == "file" else path.is_dir()
    if not valid:
        raise ValidationError(f"{label}: must be a {kind}")
    return path


def _manifest_error(field: str, rule: str) -> None:
    raise ValidationError(f"manifest {field}: {rule}")


def _object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            _manifest_error("JSON", "duplicate key")
        result[key] = value
    return result


def _manifest_object(value: object, fields: set[str], field: str) -> dict[str, object]:
    if type(value) is not dict:
        _manifest_error(field, "must be an object")
    missing = fields - value.keys()
    if missing:
        _manifest_error(field, "missing required field")
    if value.keys() - fields:
        _manifest_error(field, "unknown field")
    return value


def _string(value: object, field: str) -> str:
    if type(value) is not str:
        _manifest_error(field, "must be a string")
    return value


def _identifier(value: object, field: str) -> str:
    result = _string(value, field)
    if IDENTIFIER.fullmatch(result) is None:
        _manifest_error(field, "must be a lower-case identifier")
    return result


def _ipv4_address(value: object, field: str) -> str:
    text = _string(value, field)
    try:
        address = ipaddress.IPv4Address(text)
    except ipaddress.AddressValueError as error:
        _manifest_error(field, "must be an IPv4 address")
        raise AssertionError from error
    if str(address) != text:
        _manifest_error(field, "must be canonical")
    return text


def _ipv4_interface(value: object) -> tuple[str, ipaddress.IPv4Network]:
    text = _string(value, "network.address")
    try:
        interface = ipaddress.IPv4Interface(text)
    except (ipaddress.AddressValueError, ipaddress.NetmaskValueError, ValueError) as error:
        _manifest_error("network.address", "must be an IPv4 CIDR address")
        raise AssertionError from error
    if str(interface) != text:
        _manifest_error("network.address", "must be canonical")
    return text, interface.network


def _ipv4_network(value: object) -> tuple[str, ipaddress.IPv4Network]:
    text = _string(value, "network.routes.destination")
    try:
        network = ipaddress.IPv4Network(text, strict=True)
    except (ipaddress.AddressValueError, ValueError) as error:
        _manifest_error("network.routes.destination", "must be an IPv4 network")
        raise AssertionError from error
    if str(network) != text:
        _manifest_error("network.routes.destination", "must be canonical")
    return text, network


def _validate_source(value: object) -> str:
    source = _string(value, "source")
    if not source.startswith("http://"):
        _manifest_error("source", "must use the canonical lower-case http:// scheme")
    if any(char.isspace() or char in "\\\"'" for char in source):
        _manifest_error("source", "contains forbidden characters")
    try:
        parsed = urlsplit(source)
        port = parsed.port
    except ValueError as error:
        _manifest_error("source", "has an invalid port")
        raise AssertionError from error
    if (
        parsed.scheme != "http"
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        _manifest_error("source", "must be a credential-free HTTP URL without query or fragment")
    if (
        not parsed.hostname
        or port == 0
        or parsed.path == ""
        or URI_PATH.fullmatch(parsed.path) is None
        or re.fullmatch(r"[A-Za-z0-9.-]+(?::[0-9]+)?", parsed.netloc) is None
    ):
        _manifest_error("source", "has an invalid host, port, or path")
    if "%" in parsed.path and re.search(r"%(?![0-9A-Fa-f]{2})", parsed.path):
        _manifest_error("source", "has an invalid percent escape")
    _validate_source_host(parsed.hostname)
    return source


def _validate_source_host(host: str) -> None:
    try:
        host.encode("ascii")
        ipaddress.IPv4Address(host)
        return
    except UnicodeEncodeError, ipaddress.AddressValueError:
        pass
    if len(host) > 253 or any(DNS_LABEL.fullmatch(label) is None for label in host.split(".")):
        _manifest_error("source", "host must be an ASCII IPv4 address or DNS name")


def _validate_network(value: object) -> NetworkConfig:
    network = _manifest_object(value, {"mac", "address", "routes", "dns"}, "network")
    mac = _string(network["mac"], "network.mac")
    if MAC.fullmatch(mac) is None or int(mac[:2], 16) & 1:
        _manifest_error("network.mac", "must be a lower-case unicast Ethernet MAC")
    address, local_network = _ipv4_interface(network["address"])
    routes = _validate_routes(network["routes"], local_network)
    dns = _validate_dns(network["dns"])
    return NetworkConfig(mac=mac, address=address, routes=routes, dns=dns)


def _validate_routes(
    value: object, local_network: ipaddress.IPv4Network
) -> tuple[tuple[str, str], ...]:
    if type(value) is not list or not 1 <= len(value) <= 16:
        _manifest_error("network.routes", "must contain 1 to 16 routes")
    routes: list[tuple[str, str]] = []
    destinations: set[str] = set()
    for route in value:
        entry = _manifest_object(route, {"destination", "gateway"}, "network.routes")
        destination, _ = _ipv4_network(entry["destination"])
        gateway = _ipv4_address(entry["gateway"], "network.routes.gateway")
        if destination in destinations:
            _manifest_error("network.routes.destination", "must be unique")
        gateway_address = ipaddress.IPv4Address(gateway)
        if gateway_address not in local_network:
            _manifest_error("network.routes.gateway", "must be in the configured interface subnet")
        destinations.add(destination)
        routes.append((destination, gateway))
    return tuple(routes)


def _validate_dns(value: object) -> tuple[str, ...]:
    if type(value) is not list or len(value) > 3:
        _manifest_error("network.dns", "must contain at most 3 addresses")
    return tuple(_ipv4_address(address, "network.dns") for address in value)


def _read_manifest_bytes(path: Path) -> bytes:
    try:
        with Path(path).open("rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                _manifest_error("file", "must be a regular file")
            encoded = stream.read(MAX_MANIFEST_BYTES + 1)
    except OSError as error:
        raise ValidationError("manifest file: unavailable") from error
    if len(encoded) > MAX_MANIFEST_BYTES:
        _manifest_error("file", "exceeds 64 KiB")
    return encoded


def load_manifest_bytes(encoded: bytes) -> tuple[Manifest, bytes, str]:
    try:
        data = json.loads(encoded.decode("utf-8"), object_pairs_hook=_object_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValidationError("manifest JSON: invalid UTF-8 JSON") from error
    root = _manifest_object(
        data,
        {"version", "lpar", "network", "source", "profiles", "selected_profile"},
        "root",
    )
    if type(root["version"]) is not int or root["version"] != 1:
        _manifest_error("version", "must be exactly 1")
    profiles_value = root["profiles"]
    if type(profiles_value) is not list or not 1 <= len(profiles_value) <= 16:
        _manifest_error("profiles", "must contain 1 to 16 identifiers")
    profiles = tuple(_identifier(profile, "profiles") for profile in profiles_value)
    if len(set(profiles)) != len(profiles):
        _manifest_error("profiles", "must be unique")
    selected_profile = _identifier(root["selected_profile"], "selected_profile")
    if selected_profile not in profiles:
        _manifest_error("selected_profile", "must be listed in profiles")
    manifest = Manifest(
        version=1,
        lpar=_identifier(root["lpar"], "lpar"),
        network=_validate_network(root["network"]),
        source=_validate_source(root["source"]),
        profiles=profiles,
        selected_profile=selected_profile,
    )
    canonical = (
        json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        + b"\n"
    )
    return manifest, canonical, hashlib.sha256(canonical).hexdigest()


def load_manifest(path: Path) -> tuple[Manifest, bytes, str]:
    return load_manifest_bytes(_read_manifest_bytes(path))


def _kernel_arguments(manifest: Manifest, digest: str, profile: str) -> list[str]:
    args = [
        f"iso_chain.mac={manifest.network.mac}",
        f"iso_chain.address={manifest.network.address}",
        *(
            f"iso_chain.route={destination},{gateway}"
            for destination, gateway in manifest.network.routes
        ),
        f"iso_chain.dns={','.join(manifest.network.dns)}",
        f"iso_chain.source={manifest.source}",
        f"iso_chain.profile={profile}",
        f"iso_chain.config_sha256={digest}",
        "ipv6.disable=1",
        "rd.systemd.unit=iso-chain.target",
    ]
    if len(" ".join(args).encode("utf-8")) + 1 > MAX_COMMAND_LINE_BYTES:
        raise ValidationError("kernel command line exceeds the 2,048-byte PowerPC limit")
    return args


def _grub_config(manifest: Manifest, digest: str) -> str:
    entries = []
    for profile in manifest.profiles:
        arguments = " ".join(_kernel_arguments(manifest, digest, profile))
        entries.append(
            f"menuentry '{profile}' --id '{profile}' {{\n"
            "    echo 'ISO_CHAIN: GRUB optical handoff'\n"
            f"    linux /boot/vmlinuz {arguments}\n"
            "    initrd /boot/initramfs.img\n"
            "}\n"
        )
    return f'set timeout=5\nset default="{manifest.selected_profile}"\n' + "".join(entries)


def build_iso(args: argparse.Namespace) -> None:
    manifest, canonical, digest = load_manifest(Path(args.config))
    output = Path(args.output).absolute()
    parent = _path(output.parent, "output parent", "directory")
    if output.exists():
        raise ValidationError(f"output already exists: {output}")

    modules = _path(args.grub_modules, "GRUB module path", "directory")
    kernel = _path(args.kernel, "kernel", "file")
    initramfs = _path(args.initramfs, "initramfs", "file")
    modinfo = _path(modules / "modinfo.sh", "GRUB modinfo.sh", "file").read_text()
    if "grub_modinfo_target_cpu=powerpc" not in modinfo or (
        "grub_modinfo_platform=ieee1275" not in modinfo
    ):
        raise ValidationError("GRUB modules are not powerpc-ieee1275")
    grub_config = _grub_config(manifest, digest)

    with tempfile.TemporaryDirectory(prefix=".iso-chain-", dir=parent) as temporary:
        workspace = Path(temporary)
        stage = workspace / "stage"
        grub = stage / "boot/grub"
        grub.mkdir(parents=True)
        config = stage / "iso-chain/config.json"
        config.parent.mkdir()
        config.write_bytes(canonical)
        shutil.copyfile(kernel, stage / "boot/vmlinuz")
        shutil.copyfile(initramfs, stage / "boot/initramfs.img")
        (grub / "grub.cfg").write_text(grub_config)
        temporary_iso = workspace / "experiment.iso"
        subprocess.run(
            ["grub2-mkrescue", "-d", str(modules), "-o", str(temporary_iso), str(stage)],
            check=True,
        )
        if not temporary_iso.is_file():
            raise ValidationError("grub2-mkrescue did not create an ISO")
        try:
            os.link(temporary_iso, output)
        except FileExistsError as error:
            raise ValidationError("output appeared during build") from error


def inspect_iso(path: Path) -> bytes:
    iso = _path(path, "ISO", "file")
    with tempfile.TemporaryDirectory(prefix=".iso-chain-inspect-", dir=iso.parent) as temporary:
        extracted = Path(temporary) / "config.json"
        subprocess.run(
            [
                "xorriso",
                "-osirrox",
                "on",
                "-indev",
                str(iso),
                "-extract",
                "/iso-chain/config.json",
                str(extracted),
            ],
            check=True,
        )
        _, canonical, _ = load_manifest(extracted)
        return canonical


def _dracut_asset(name: str) -> Path:
    return _path(DRACUT_ASSETS / name, f"launcher asset {name}", "file")


def _dracut_supports(command: str) -> None:
    help_text = subprocess.run(
        [command, "--help"], check=True, capture_output=True, text=True
    ).stdout
    if any(flag not in help_text for flag in DRACUT_FLAGS):
        raise ValidationError("dracut lacks required launcher flags")


def _dracut_command(command: str, kernel_version: str, image: Path) -> list[str]:
    launcher = _dracut_asset("iso-chain-launch.sh")
    service = _dracut_asset("iso-chain-launch.service")
    target = _dracut_asset("iso-chain.target")
    return [
        command,
        "--no-hostonly",
        "--reproducible",
        "--add",
        "systemd",
        "--include",
        str(launcher),
        "/usr/libexec/iso-chain-launch.sh",
        "--include",
        str(service),
        "/etc/systemd/system/iso-chain-launch.service",
        "--include",
        str(target),
        "/etc/systemd/system/iso-chain.target",
        "--install",
        "/bin/sh /usr/sbin/ip /usr/bin/curl /usr/bin/systemctl /usr/bin/udevadm",
        "--force-drivers",
        DRACUT_DRIVERS,
        "--kver",
        kernel_version,
        str(image),
    ]


def prepare_initramfs(args: argparse.Namespace) -> None:
    if platform.machine() != "ppc64le":
        raise ValidationError("prepare-initramfs requires a ppc64le host")
    output = Path(args.output).absolute()
    parent = _path(output.parent, "output parent", "directory")
    if output.exists():
        raise ValidationError(f"output already exists: {output}")
    kernel_version = args.kernel_version
    if not re.fullmatch(r"[A-Za-z0-9._+-]+", kernel_version):
        raise ValidationError("kernel version is invalid")
    _path(KERNEL_MODULES / kernel_version, "kernel tree", "directory")
    command = shutil.which("dracut")
    if command is None:
        raise ValidationError("dracut is unavailable")
    for asset in ("iso-chain-launch.sh", "iso-chain-launch.service", "iso-chain.target"):
        _dracut_asset(asset)
    _dracut_supports(command)
    with tempfile.TemporaryDirectory(prefix=".iso-chain-initramfs-", dir=parent) as temporary:
        image = Path(temporary) / "initramfs.img"
        subprocess.run(_dracut_command(command, kernel_version, image), check=True)
        if not image.is_file():
            raise ValidationError("dracut did not create an initramfs")
        try:
            os.link(image, output)
        except FileExistsError as error:
            raise ValidationError("output appeared during preparation") from error


def qemu_command(
    iso: Path, disk: Path, manifest: Manifest, capture_prefix: Path, adapter_state: str
) -> list[str]:
    if adapter_state not in ("matched", "missing", "duplicate"):
        raise ValidationError("adapter state must be matched, missing, or duplicate")
    fixed = (
        "qemu-system-ppc64 -machine pseries,accel=tcg -cpu power9 -m 4G -smp 2 "
        "-nographic -nic none -snapshot -boot d -device virtio-scsi-pci"
    )
    disk_value, iso_value = (str(path).replace(",", ",,") for path in (disk, iso))
    command = fixed.split() + [
        "-drive",
        f"file={disk_value},format=qcow2,if=virtio",
        "-drive",
        f"file={iso_value},format=raw,media=cdrom,readonly=on,if=none,id=cdrom",
        "-device",
        "scsi-cd,drive=cdrom,bootindex=1",
    ]
    mac = manifest.network.mac
    if adapter_state == "missing":
        mac = mac[:-2] + f"{int(mac[-2:], 16) ^ 1:02x}"
    for index in range(2 if adapter_state == "duplicate" else 1):
        capture = Path(f"{capture_prefix}-net{index}.pcap")
        if os.path.lexists(capture):
            raise ValidationError("capture already exists")
        capture_value = str(capture).replace(",", ",,")
        command += [
            "-netdev",
            f"user,id=net{index},ipv6=off",
            "-device",
            f"virtio-net-pci,netdev=net{index},mac={mac}",
            "-object",
            f"filter-dump,id=dump{index},netdev=net{index},file={capture_value}",
        ]
    return command


def smoke(args: argparse.Namespace) -> None:
    iso = _path(args.iso, "ISO", "file")
    disk = _path(args.disk, "disk", "file")
    manifest, _, _ = load_manifest(args.config)
    command = qemu_command(iso, disk, manifest, args.capture_prefix, args.adapter_state)
    os.execvp(command[0], command)


def verify_launcher_log(log: Path, manifest: Manifest, expected_profile: str) -> tuple[str, ...]:
    if expected_profile not in manifest.profiles:
        raise ValidationError("expected profile is not allowed")
    path = _path(log, "console log", "file")
    with path.open("rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValidationError("console log must be a regular file")
        encoded = stream.read(MAX_LOG_BYTES + 1)
    if len(encoded) > MAX_LOG_BYTES:
        raise ValidationError("console log exceeds evidence limit")
    lines = [
        ANSI_ESCAPE.sub("", line).strip() for line in encoded.decode(errors="replace").splitlines()
    ]
    visible = [SERVICE_PREFIX.sub("", line, count=1) for line in lines]
    start = next(
        (i for i, line in enumerate(visible) if line == "ISO_CHAIN: configuration passed"),
        len(visible),
    )
    if any(
        line in ("configuration: failed", "adapter-match: failed", "launcher: failed")
        or ("iso-chain" in line and "failed" in line.lower())
        for line in visible
    ) or any("failed" in line.lower() or "emergency" in line.lower() for line in lines[start:]):
        raise ValidationError("console log contains failure evidence")
    cmdlines = [
        (index, match.group(1).split())
        for index, line in enumerate(lines)
        if (match := re.fullmatch(r"\[\s*\d+\.\d+\] Kernel command line: (.*)", line))
    ]
    if len(cmdlines) != 1:
        raise ValidationError("console log requires exactly one kernel command line")
    position, arguments = cmdlines[0]
    canonical = (
        json.dumps(
            {
                "version": manifest.version,
                "lpar": manifest.lpar,
                "network": {
                    "mac": manifest.network.mac,
                    "address": manifest.network.address,
                    "routes": [
                        {"destination": dest, "gateway": gateway}
                        for dest, gateway in manifest.network.routes
                    ],
                    "dns": manifest.network.dns,
                },
                "source": manifest.source,
                "profiles": manifest.profiles,
                "selected_profile": manifest.selected_profile,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        + b"\n"
    )
    expected = _kernel_arguments(manifest, hashlib.sha256(canonical).hexdigest(), expected_profile)
    actual = [
        arg for arg in arguments if arg.startswith(("iso_chain.", "ipv6.", "rd.systemd.unit="))
    ]
    if actual != expected:
        raise ValidationError("kernel configuration or profile evidence does not match")
    handoff = "ISO_CHAIN: GRUB optical handoff"
    if lines[:position].count(handoff) != 1:
        raise ValidationError("missing optical handoff evidence")
    target = "Reached target iso-chain.target - ISO chain launcher terminal target."
    markers = (
        "ISO_CHAIN: configuration passed",
        "adapter-match: passed",
        "profile: passed",
        "http-probe: passed",
        target if target in visible else "[  OK  ] " + target,
    )
    for marker in markers:
        if visible.count(marker) != 1 or visible.index(marker) <= position:
            raise ValidationError("missing, repeated, or reordered launcher evidence")
        position = visible.index(marker)
    return (
        "configuration: passed",
        "adapter-match: passed",
        "profile: passed",
        "http-probe: passed",
        "launcher-once: passed",
        "terminal-target: passed",
    )


def verify_pcap(path: Path) -> str:
    capture = _path(path, "packet capture", "file")
    if not 0 < capture.stat().st_size <= 64 * 1024 * 1024:
        raise ValidationError("packet capture is empty or exceeds evidence limit")
    try:
        result = subprocess.run(
            [
                "tcpdump",
                "-nn",
                "-r",
                str(capture),
                "-c",
                "1",
                "ip6 or (udp and (port 67 or port 68))",
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
    except (subprocess.SubprocessError, OSError) as error:
        raise ValidationError("packet capture verification failed") from error
    if result.stdout:
        raise ValidationError("packet capture contains DHCP or IPv6")
    return "dhcp-ipv6: absent"


def _ordered_position(content: str, marker: str, start: int) -> int:
    position = content.find(marker, start)
    if position < 0:
        raise ValidationError(f"missing or reordered evidence marker: {marker}")
    return position + len(marker)


def _evidence_lines(content: str) -> list[tuple[int, str]]:
    evidence = []
    offset = 0
    for raw_line in content.splitlines(keepends=True):
        marker = raw_line.find("ISO_CHAIN_EVIDENCE:")
        visible = ANSI_ESCAPE.sub("", raw_line.rstrip("\r\n"))
        visible = SERVICE_PREFIX.sub("", visible, count=1)
        if marker >= 0 and visible.startswith("ISO_CHAIN_EVIDENCE:"):
            evidence.append((offset + marker, visible))
        offset += len(raw_line)
    return evidence


def _evidence_line(evidence: list[tuple[int, str]], prefix: str, start: int) -> tuple[str, int]:
    for position, line in evidence:
        if position >= start and line.startswith(prefix):
            return line, position + len(line)
    raise ValidationError(f"missing or reordered evidence marker: {prefix}")


def _boot_id(
    evidence: list[tuple[int, str]], prefix: str, suffix: str, start: int
) -> tuple[uuid.UUID, int]:
    line, position = _evidence_line(evidence, prefix, start)
    match = re.fullmatch(re.escape(prefix) + BOOT_ID + re.escape(suffix), line)
    if match is None:
        raise ValidationError("kernel evidence has a malformed boot ID")
    try:
        boot_id = uuid.UUID(match.group(1))
    except ValueError as error:
        raise ValidationError("kernel evidence has a malformed boot ID") from error
    if match.group(1).lower() != str(boot_id):
        raise ValidationError("kernel evidence has a malformed boot ID")
    return boot_id, position


def verify_log(path: Path) -> tuple[str, str, str]:
    log = _path(path, "console log", "file")
    with log.open("rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValidationError("console log is not a regular file")
        encoded = stream.read(MAX_LOG_BYTES + 1)
    if len(encoded) > MAX_LOG_BYTES:
        raise ValidationError("console log exceeds 16 MiB evidence limit")
    content = encoded.decode(errors="replace")
    if any(marker in content for marker in ("/l-lan@", "DHCPACK", "DHCP lease acquired")):
        raise ValidationError("console log contains forbidden network evidence")
    evidence = _evidence_lines(content)
    network_prefix = "ISO_CHAIN_EVIDENCE: network-disabled interfaces="
    for _, line in evidence:
        if line.startswith(network_prefix) and line != network_prefix + "lo":
            raise ValidationError("console log reports a non-loopback interface")

    position = 0
    for marker in (
        "Successfully loaded",
        "ISO_CHAIN: GRUB optical handoff",
        "Kernel command line:",
        "iso_chain_stage=optical",
    ):
        position = _ordered_position(content, marker, position)
    first_id, position = _boot_id(
        evidence, "ISO_CHAIN_EVIDENCE: first-kernel boot_id=", "", position
    )
    _, position = _evidence_line(evidence, network_prefix, position)
    for marker in (
        "kexec_core: Starting new kernel",
        "Linux version",
        "Kernel command line:",
        "iso_chain_stage=kexec",
    ):
        position = _ordered_position(content, marker, position)
    second_prefix = "ISO_CHAIN_EVIDENCE: second-kernel boot_id="
    try:
        second_id, position = _boot_id(
            evidence, second_prefix, " cmdline=iso_chain_stage=kexec", position
        )
    except ValidationError as error:
        if second_prefix in content[position:]:
            raise
        raise ValidationError(
            "second kernel reached; evidence service marker is missing"
        ) from error
    if first_id == second_id:
        raise ValidationError("first and second kernel boot IDs are identical")
    return PASS_LINES


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    commands = result.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    for name in ("config", "grub-modules", "kernel", "initramfs", "output"):
        build.add_argument(f"--{name}", required=True, type=Path)
    inspect = commands.add_parser("inspect")
    inspect.add_argument("iso", type=Path)
    prepare = commands.add_parser("prepare-initramfs")
    prepare.add_argument("--kernel-version", required=True)
    prepare.add_argument("--output", required=True, type=Path)
    smoke_parser = commands.add_parser("smoke")
    for name in ("iso", "disk", "config", "capture-prefix"):
        smoke_parser.add_argument(f"--{name}", required=True, type=Path)
    smoke_parser.add_argument(
        "--adapter-state", choices=("matched", "missing", "duplicate"), default="matched"
    )
    verify = commands.add_parser("verify-log")
    verify.add_argument("log", type=Path)
    launcher = commands.add_parser("verify-launcher-log")
    launcher.add_argument("log", type=Path)
    launcher.add_argument("--config", type=Path, required=True)
    launcher.add_argument("--expected-profile", required=True)
    pcap = commands.add_parser("verify-pcap")
    pcap.add_argument("pcap", type=Path)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "build":
            build_iso(args)
        elif args.command == "smoke":
            smoke(args)
        elif args.command == "inspect":
            sys.stdout.buffer.write(inspect_iso(args.iso))
        elif args.command == "prepare-initramfs":
            prepare_initramfs(args)
        elif args.command == "verify-launcher-log":
            manifest, _, _ = load_manifest(args.config)
            print(*verify_launcher_log(args.log, manifest, args.expected_profile), sep="\n")
        elif args.command == "verify-pcap":
            print(verify_pcap(args.pcap))
        else:
            print(*verify_log(args.log), sep="\n")
    except ValidationError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as error:
        return error.returncode or 1
    except OSError as error:
        print(f"error: external operation failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
