#!/usr/bin/env python3
"""Build and exercise the bounded POWER9 optical-bootstrap experiment."""

import argparse
import configparser
import ctypes
import errno
import functools
import hashlib
import http.server
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
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import unquote_to_bytes, urlsplit

ANSI_ESCAPE = re.compile(r"\x1b\].*?(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]")
SERVICE_PREFIX = re.compile(r"^\[\s*\d+(?:\.\d+)?\]\s+[\w.-]+\[\d+\]:\s+")
BOOT_ID = r"([0-9A-Fa-f-]{36})"
MAX_LOG_BYTES = 16 * 1024 * 1024
MAX_MANIFEST_BYTES = 64 * 1024
MAX_COMMAND_LINE_BYTES = 2048
MAX_TREEINFO_BYTES = 64 * 1024
MAX_KICKSTART_BYTES = 1024 * 1024
MAX_INSTALL_CAPTURE_BYTES = 8 * 1024 * 1024 * 1024
FEDORA_ISO_SIZE = 3013869568
PASS_LINES = ("optical-boot: passed", "network: passed", "kexec: passed")
IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
MAC = re.compile(r"^[0-9a-f]{2}(?::[0-9a-f]{2}){5}$")
DNS_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
URI_PATH = re.compile(r"^/(?:[A-Za-z0-9._~-]+)(?:/[A-Za-z0-9._~-]+)*$")
MEMORY_EVIDENCE = re.compile(
    r"memory: passed memtotal_mib=([0-9]+) memavailable_mib=([0-9]+) "
    r"run_available_bytes=([0-9]+)"
)
DRACUT_ASSETS = Path(__file__).resolve().parent.parent / "assets/dracut"
KERNEL_MODULES = Path("/usr/lib/modules")
DRACUT_FLAGS = ("--no-hostonly", "--reproducible", "--include", "--install", "--force-drivers")
DRACUT_DRIVERS = "virtio_net virtio_pci virtio_blk virtio_scsi"
DRACUT_TOOLS = (
    "/bin/sh /usr/sbin/ip /usr/bin/curl /usr/bin/systemctl /usr/bin/udevadm "
    "/usr/bin/sha256sum /usr/sbin/kexec /usr/bin/mktemp /usr/bin/stat /usr/bin/sync"
)


class ValidationError(ValueError):
    pass


@dataclass(frozen=True)
class NetworkConfig:
    mac: str
    address: str
    routes: tuple[tuple[str, str], ...]
    dns: tuple[str, ...]


@dataclass(frozen=True)
class Artifact:
    path: str
    size: int
    sha256: str


@dataclass(frozen=True)
class Repository:
    path: str
    treeinfo: Artifact
    repomd: Artifact

    @property
    def treeinfo_path(self) -> str:
        return f"{self.path}/.treeinfo"

    @property
    def repomd_path(self) -> str:
        return f"{self.path}/repodata/repomd.xml"


@dataclass(frozen=True)
class InstallerProfile:
    distribution: str
    release: str
    kernel: Artifact
    initramfs: Artifact
    repository: Repository
    kickstart: Artifact
    minimum_memory_mib: int


@dataclass(frozen=True)
class Manifest:
    version: int
    lpar: str
    network: NetworkConfig
    source: str
    profiles: tuple[tuple[str, InstallerProfile], ...]
    selected_profile: str

    def profile(self, name: str) -> InstallerProfile:
        for candidate, profile in self.profiles:
            if candidate == name:
                return profile
        raise ValidationError("profile is not allowed")


def _path(value: Path, label: str, kind: str) -> Path:
    try:
        path = Path(value).resolve(strict=True)
    except OSError as error:
        raise ValidationError(f"{label}: unavailable") from error
    valid = path.is_file() if kind == "file" else path.is_dir()
    if not valid:
        raise ValidationError(f"{label}: must be a {kind}")
    return path


def _regular_file(value: Path, label: str) -> Path:
    path = Path(value)
    try:
        mode = path.lstat().st_mode
    except OSError as error:
        raise ValidationError(f"{label}: unavailable") from error
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise ValidationError(f"{label}: must be a regular file")
    return path


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _copy_with_sha256(source: Path, destination: Path, expected_size: int) -> str:
    digest = hashlib.sha256()
    copied = 0
    with source.open("rb") as source_stream:
        if not stat.S_ISREG(os.fstat(source_stream.fileno()).st_mode):
            raise ValidationError("Fedora ISO: must be a regular file")
        with destination.open("xb") as destination_stream:
            while block := source_stream.read(1024 * 1024):
                copied += len(block)
                if copied > expected_size:
                    raise ValidationError("Fedora ISO: size does not match")
                destination_stream.write(block)
                digest.update(block)
    if copied != expected_size:
        raise ValidationError("Fedora ISO: size does not match")
    return digest.hexdigest()


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


def _integer(value: object, field: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _manifest_error(field, f"must be an integer from {minimum} through {maximum}")
    return value


def _sha256(value: object, field: str) -> str:
    digest = _string(value, field)
    if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        _manifest_error(field, "must be a lower-case SHA-256 digest")
    return digest


def _url_path(value: object, field: str) -> str:
    path = _string(value, field)
    if URI_PATH.fullmatch(path) is None or any(part in (".", "..") for part in path.split("/")):
        _manifest_error(field, "must be a canonical absolute URL path")
    return path


def _artifact(value: object, field: str, maximum: int, path: str | None = None) -> Artifact:
    fields = {"size", "sha256"} if path is not None else {"path", "size", "sha256"}
    data = _manifest_object(value, fields, field)
    return Artifact(
        path=path if path is not None else _url_path(data["path"], f"{field}.path"),
        size=_integer(data["size"], f"{field}.size", 1, maximum),
        sha256=_sha256(data["sha256"], f"{field}.sha256"),
    )


def _installer_profile(value: object, field: str) -> InstallerProfile:
    data = _manifest_object(
        value,
        {
            "distribution",
            "release",
            "kernel",
            "initramfs",
            "repository",
            "kickstart",
            "minimum_memory_mib",
        },
        field,
    )
    distribution = _string(data["distribution"], f"{field}.distribution")
    release = _string(data["release"], f"{field}.release")
    if (distribution, release) != ("fedora", "44"):
        _manifest_error(f"{field}.distribution/release", "must be fedora/44")
    repository_data = _manifest_object(
        data["repository"], {"path", "treeinfo", "repomd"}, f"{field}.repository"
    )
    repository_path = _url_path(repository_data["path"], f"{field}.repository.path")
    repository = Repository(
        path=repository_path,
        treeinfo=_artifact(
            repository_data["treeinfo"],
            f"{field}.repository.treeinfo",
            1024 * 1024,
            f"{repository_path}/.treeinfo",
        ),
        repomd=_artifact(
            repository_data["repomd"],
            f"{field}.repository.repomd",
            1024 * 1024,
            f"{repository_path}/repodata/repomd.xml",
        ),
    )
    return InstallerProfile(
        distribution=distribution,
        release=release,
        kernel=_artifact(data["kernel"], f"{field}.kernel", 2 * 1024 * 1024 * 1024),
        initramfs=_artifact(data["initramfs"], f"{field}.initramfs", 2 * 1024 * 1024 * 1024),
        repository=repository,
        kickstart=_artifact(data["kickstart"], f"{field}.kickstart", MAX_KICKSTART_BYTES),
        minimum_memory_mib=_integer(
            data["minimum_memory_mib"], f"{field}.minimum_memory_mib", 1, 65536
        ),
    )


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
        or port is not None
        and parsed.netloc.rpartition(":")[2] != str(port)
        or parsed.path != ""
        or re.fullmatch(r"[A-Za-z0-9.-]+(?::[0-9]+)?", parsed.netloc) is None
    ):
        _manifest_error("source", "must be a canonical HTTP origin")
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
    if "0.0.0.0/0" not in destinations:
        _manifest_error("network.routes", "must contain one default route")
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
    if type(root["version"]) is not int or root["version"] != 3:
        _manifest_error("version", "must be exactly 3")
    profiles_value = root["profiles"]
    if type(profiles_value) is not dict or not 1 <= len(profiles_value) <= 16:
        _manifest_error("profiles", "must contain 1 to 16 profile objects")
    profiles = tuple(
        (
            _identifier(name, "profiles name"),
            _installer_profile(profile, f"profiles.{name}"),
        )
        for name, profile in profiles_value.items()
    )
    selected_profile = _identifier(root["selected_profile"], "selected_profile")
    if selected_profile not in dict(profiles):
        _manifest_error("selected_profile", "must be listed in profiles")
    manifest = Manifest(
        version=3,
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


def _manifest_data(manifest: Manifest) -> dict[str, object]:
    def artifact(value: Artifact, include_path: bool = True) -> dict[str, object]:
        result: dict[str, object] = {"size": value.size, "sha256": value.sha256}
        if include_path:
            result["path"] = value.path
        return result

    profiles = {}
    for name, profile in manifest.profiles:
        profiles[name] = {
            "distribution": profile.distribution,
            "release": profile.release,
            "kernel": artifact(profile.kernel),
            "initramfs": artifact(profile.initramfs),
            "repository": {
                "path": profile.repository.path,
                "treeinfo": artifact(profile.repository.treeinfo, include_path=False),
                "repomd": artifact(profile.repository.repomd, include_path=False),
            },
            "kickstart": artifact(profile.kickstart),
            "minimum_memory_mib": profile.minimum_memory_mib,
        }
    return {
        "version": manifest.version,
        "lpar": manifest.lpar,
        "network": {
            "mac": manifest.network.mac,
            "address": manifest.network.address,
            "routes": [
                {"destination": destination, "gateway": gateway}
                for destination, gateway in manifest.network.routes
            ],
            "dns": list(manifest.network.dns),
        },
        "source": manifest.source,
        "profiles": profiles,
        "selected_profile": manifest.selected_profile,
    }


def _kernel_arguments(manifest: Manifest, digest: str, profile: str) -> list[str]:
    selected = manifest.profile(profile)
    args = [
        f"iso_chain.lpar={manifest.lpar}",
        f"iso_chain.mac={manifest.network.mac}",
        f"iso_chain.address={manifest.network.address}",
        *(
            f"iso_chain.route={destination},{gateway}"
            for destination, gateway in manifest.network.routes
        ),
        f"iso_chain.dns={','.join(manifest.network.dns)}",
        f"iso_chain.source={manifest.source}",
        f"iso_chain.profile={profile}",
        f"iso_chain.profile_distribution={selected.distribution}",
        f"iso_chain.profile_release={selected.release}",
        f"iso_chain.profile_kernel_path={selected.kernel.path}",
        f"iso_chain.profile_kernel_size={selected.kernel.size}",
        f"iso_chain.profile_kernel_sha256={selected.kernel.sha256}",
        f"iso_chain.profile_initramfs_path={selected.initramfs.path}",
        f"iso_chain.profile_initramfs_size={selected.initramfs.size}",
        f"iso_chain.profile_initramfs_sha256={selected.initramfs.sha256}",
        f"iso_chain.profile_repository_path={selected.repository.path}",
        f"iso_chain.profile_treeinfo_size={selected.repository.treeinfo.size}",
        f"iso_chain.profile_treeinfo_sha256={selected.repository.treeinfo.sha256}",
        f"iso_chain.profile_repomd_size={selected.repository.repomd.size}",
        f"iso_chain.profile_repomd_sha256={selected.repository.repomd.sha256}",
        f"iso_chain.profile_kickstart_path={selected.kickstart.path}",
        f"iso_chain.profile_kickstart_size={selected.kickstart.size}",
        f"iso_chain.profile_kickstart_sha256={selected.kickstart.sha256}",
        f"iso_chain.profile_minimum_memory_mib={selected.minimum_memory_mib}",
        f"iso_chain.config_sha256={digest}",
        "ipv6.disable=1",
        "rd.systemd.unit=iso-chain.target",
    ]
    if len(" ".join(args).encode("utf-8")) + 1 > MAX_COMMAND_LINE_BYTES:
        raise ValidationError("kernel command line exceeds the 2,048-byte PowerPC limit")
    return args


def _grub_config(manifest: Manifest, digest: str) -> str:
    entries = []
    for profile, _ in manifest.profiles:
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


def _bounded_file(path: Path, label: str, maximum: int) -> bytes:
    regular = _regular_file(path, label)
    with regular.open("rb") as stream:
        content = stream.read(maximum + 1)
    if len(content) > maximum:
        raise ValidationError(f"{label}: exceeds {maximum // 1024} KiB")
    return content


def _treeinfo_paths(repository: Path) -> tuple[Path, Path, Path]:
    encoded = _bounded_file(repository / ".treeinfo", "Fedora treeinfo", MAX_TREEINFO_BYTES)
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(encoded.decode("utf-8"))
        identity = tuple(
            parser["general"][name] for name in ("family", "version", "arch", "variant")
        )
        values = (
            parser["images-ppc64le"]["kernel"],
            parser["images-ppc64le"]["initrd"],
            parser["stage2"]["mainimage"],
        )
    except (UnicodeDecodeError, configparser.Error, KeyError) as error:
        raise ValidationError("Fedora treeinfo: missing or malformed metadata") from error
    if identity != ("Fedora", "44", "ppc64le", "Server"):
        raise ValidationError("Fedora treeinfo: expected Fedora Server 44 ppc64le")
    paths = []
    for value in values:
        if URI_PATH.fullmatch("/" + value) is None or any(
            part in ("", ".", "..") for part in value.split("/")
        ):
            raise ValidationError("Fedora treeinfo: contains a noncanonical path")
        paths.append(_regular_file(repository / value, "Fedora treeinfo artifact"))
    return paths[0], paths[1], paths[2]


def _append_stage2_bundle(
    initramfs: Path, runtime: Path, kickstart: bytes, output: Path, workspace: Path
) -> None:
    source_initramfs = _regular_file(initramfs, "Fedora initramfs")
    if not 6 <= source_initramfs.stat().st_size <= 2 * 1024 * 1024 * 1024:
        raise ValidationError("Fedora initramfs: invalid size")
    with source_initramfs.open("rb") as stream:
        magic = stream.read(6)
    if magic != b"\xfd7zXZ\x00":
        raise ValidationError("Fedora initramfs: unsupported compression")
    hook = _dracut_asset("iso-chain-fedora-stage2.sh")
    overlay = workspace / "stage2-overlay"
    runtime_target = overlay / "iso-chain/install.img"
    kickstart_target = overlay / "iso-chain/ks.cfg"
    hook_target = overlay / "usr/lib/dracut/hooks/initqueue/settled/90-iso-chain-stage2.sh"
    runtime_target.parent.mkdir(parents=True)
    hook_target.parent.mkdir(parents=True)
    os.link(runtime, runtime_target)
    kickstart_target.write_bytes(kickstart)
    kickstart_target.chmod(0o600)
    shutil.copyfile(hook, hook_target)
    hook_target.chmod(0o755)
    archive = workspace / "stage2.cpio"
    names = (
        b"./iso-chain\n./iso-chain/install.img\n./iso-chain/ks.cfg\n"
        b"./usr/lib/dracut/hooks/initqueue/settled/90-iso-chain-stage2.sh\n"
    )
    with archive.open("wb") as stream:
        subprocess.run(
            ["cpio", "--create", "--format=newc", "--owner=0:0", "--quiet"],
            cwd=overlay,
            input=names,
            stdout=stream,
            check=True,
        )
    compressed = workspace / "stage2.cpio.xz"
    with compressed.open("wb") as stream:
        subprocess.run(
            ["xz", "--check=crc32", "--threads=1", "--stdout", str(archive)],
            stdout=stream,
            check=True,
        )
    with output.open("wb") as destination:
        with initramfs.open("rb") as source:
            shutil.copyfileobj(source, destination)
        with compressed.open("rb") as source:
            shutil.copyfileobj(source, destination)


def _artifact_data(path: Path, url_path: str | None, maximum: int) -> dict[str, object]:
    regular = _regular_file(path, "prepared Fedora artifact")
    size = regular.stat().st_size
    if not 1 <= size <= maximum:
        raise ValidationError("prepared Fedora artifact: invalid size")
    result: dict[str, object] = {"size": size, "sha256": _file_sha256(regular)}
    if url_path is not None:
        result["path"] = url_path
    return result


def _publish_directory(source: Path, destination: Path) -> None:
    library = ctypes.CDLL(None, use_errno=True)
    try:
        renameat2 = library.renameat2
    except AttributeError as error:
        raise ValidationError("no-replace directory publication is unsupported") from error
    renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    if renameat2(-100, os.fsencode(source), -100, os.fsencode(destination), 1) == 0:
        return
    failure = ctypes.get_errno()
    if failure == errno.EEXIST:
        raise ValidationError("output appeared during Fedora source preparation")
    if failure in (errno.ENOSYS, errno.EINVAL):
        raise ValidationError("no-replace directory publication is unsupported")
    raise OSError(failure, os.strerror(failure), destination)


def prepare_fedora_source(args: argparse.Namespace) -> None:
    iso = _regular_file(Path(args.iso).absolute(), "Fedora ISO")
    kickstart = _bounded_file(Path(args.kickstart).absolute(), "Kickstart", MAX_KICKSTART_BYTES)
    if not kickstart:
        raise ValidationError("Kickstart: must not be empty")
    expected_digest = _sha256(args.iso_sha256, "ISO digest")
    memory = _integer(args.minimum_memory_mib, "minimum memory", 1, 65536)
    output = Path(args.output).absolute()
    parent = _path(output.parent, "output parent", "directory")
    if os.path.lexists(output):
        raise ValidationError("Fedora source output already exists")
    with tempfile.TemporaryDirectory(prefix=".iso-chain-fedora-", dir=parent) as temporary:
        verified_iso = Path(temporary) / "source.iso"
        if _copy_with_sha256(iso, verified_iso, FEDORA_ISO_SIZE) != expected_digest:
            raise ValidationError("Fedora ISO digest does not match")
        tree = Path(temporary) / "tree"
        repository = tree / "repository"
        repository.mkdir(parents=True)
        subprocess.run(
            [
                "xorriso",
                "-osirrox",
                "on",
                "-indev",
                str(verified_iso),
                "-extract",
                "/",
                str(repository),
            ],
            check=True,
        )
        kernel, initramfs, runtime = _treeinfo_paths(repository)
        repomd = _regular_file(repository / "repodata/repomd.xml", "Fedora repository metadata")
        profile_root = tree / "profiles/fedora-44"
        profile_root.mkdir(parents=True)
        prepared_kernel = profile_root / "vmlinuz"
        prepared_initramfs = profile_root / "initramfs.img"
        prepared_kickstart = profile_root / "ks.cfg"
        shutil.copyfile(kernel, prepared_kernel)
        prepared_kickstart.write_bytes(kickstart)
        prepared_kickstart.chmod(0o600)
        _append_stage2_bundle(
            initramfs, runtime, kickstart, prepared_initramfs, Path(temporary) / "bundle"
        )
        profile = {
            "distribution": "fedora",
            "release": "44",
            "kernel": _artifact_data(prepared_kernel, "/profiles/fedora-44/vmlinuz", 2**31),
            "initramfs": _artifact_data(
                prepared_initramfs, "/profiles/fedora-44/initramfs.img", 2**31
            ),
            "repository": {
                "path": "/repository",
                "treeinfo": _artifact_data(repository / ".treeinfo", None, 2**20),
                "repomd": _artifact_data(repomd, None, 2**20),
            },
            "kickstart": _artifact_data(
                prepared_kickstart, "/profiles/fedora-44/ks.cfg", MAX_KICKSTART_BYTES
            ),
            "minimum_memory_mib": memory,
        }
        _installer_profile(profile, "profile")
        (tree / "profile.json").write_bytes(
            json.dumps(profile, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        )
        _publish_directory(tree, output)


class FedoraRequestHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass

    def _decoded_path(self) -> str | None:
        parsed = urlsplit(self.path)
        if parsed.query or parsed.fragment or not parsed.path.startswith("/"):
            return None
        try:
            decoded = unquote_to_bytes(parsed.path).decode("utf-8")
        except UnicodeDecodeError:
            return None
        if any(ord(character) < 32 or ord(character) == 127 for character in decoded):
            return None
        parts = PurePosixPath(decoded).parts
        if any(part in (".", "..") for part in parts):
            return None
        return decoded

    def send_head(self):
        decoded = self._decoded_path()
        if decoded is None:
            self.send_error(400)
            return None
        root = Path(self.directory)
        candidate = root.joinpath(*PurePosixPath(decoded).parts[1:])
        current = root
        try:
            for part in PurePosixPath(decoded).parts[1:]:
                current /= part
                if current.is_symlink():
                    raise OSError
            descriptor = os.open(candidate, os.O_RDONLY | os.O_NOFOLLOW)
            stream = os.fdopen(descriptor, "rb")
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                stream.close()
                raise OSError
            size = metadata.st_size
        except OSError:
            self.send_error(404)
            return None
        self.send_response(200)
        self.send_header("Content-Type", self.guess_type(str(candidate)))
        self.send_header("Content-Length", str(size))
        self.end_headers()
        return stream

    def log_request(self, code="-", size="-") -> None:
        self._response_status = int(code)

    def send_header(self, keyword: str, value: str) -> None:
        if keyword.lower() == "content-length":
            self._response_bytes = 0 if self.command == "HEAD" else int(value)
        super().send_header(keyword, value)

    def _write_record(self) -> None:
        decoded = self._decoded_path() or "/<invalid>"
        response_bytes = getattr(self, "_response_bytes", 0)
        server = self.server
        server.request_index += 1
        record = {
            "method": self.command,
            "path": decoded,
            "status": self._response_status,
            "bytes": response_bytes,
            "index": server.request_index,
        }
        encoded = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
        server.access_stream.write(encoded)
        server.access_stream.flush()

    def do_GET(self) -> None:
        self._response_bytes = 0
        super().do_GET()
        self._write_record()

    def do_HEAD(self) -> None:
        self._response_bytes = 0
        super().do_HEAD()
        self._write_record()


class FedoraHTTPServer(http.server.HTTPServer):
    def server_close(self) -> None:
        if hasattr(self, "access_stream") and not self.access_stream.closed:
            self.access_stream.close()
        super().server_close()


def _fedora_server(
    directory: Path, bind: str, port: int, access_log: Path
) -> http.server.HTTPServer:
    root = _path(directory, "Fedora source tree", "directory")
    _ipv4_address(bind, "server bind address")
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValidationError("server port must be from 0 through 65535")
    log = Path(access_log).absolute()
    _path(log.parent, "access log parent", "directory")
    if os.path.lexists(log):
        raise ValidationError("access log already exists")
    handler = functools.partial(FedoraRequestHandler, directory=str(root))
    server = FedoraHTTPServer((bind, port), handler)
    try:
        descriptor = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError:
        server.server_close()
        raise ValidationError("access log could not be created without replacement") from None
    server.access_stream = os.fdopen(descriptor, "w", encoding="utf-8")
    server.request_index = 0
    return server


def serve_fedora_source(args: argparse.Namespace) -> None:
    if not 1 <= args.port <= 65535:
        raise ValidationError("server port must be from 1 through 65535")
    server = _fedora_server(args.directory, args.bind, args.port, args.access_log)
    try:
        server.serve_forever()
    finally:
        server.access_stream.close()
        server.server_close()


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
        DRACUT_TOOLS,
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
    iso: Path,
    disk: Path,
    manifest: Manifest,
    capture_prefix: Path,
    adapter_state: str,
    memory_mib: int = 4096,
) -> list[str]:
    if adapter_state not in ("matched", "missing", "duplicate"):
        raise ValidationError("adapter state must be matched, missing, or duplicate")
    if type(memory_mib) is not int or not 1024 <= memory_mib <= 65536:
        raise ValidationError("QEMU memory must be from 1024 through 65536 MiB")
    fixed = (
        "qemu-system-ppc64 -machine pseries,accel=tcg -cpu power9 -smp 2 "
        "-nographic -nic none -snapshot -boot d -device virtio-scsi-pci"
    )
    disk_value, iso_value = (str(path).replace(",", ",,") for path in (disk, iso))
    command = fixed.split() + [
        "-m",
        f"{memory_mib}M",
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
    command = qemu_command(
        iso, disk, manifest, args.capture_prefix, args.adapter_state, args.memory_mib
    )
    os.execvp(command[0], command)


def _qemu_network(manifest: Manifest, capture_fifo: Path) -> list[str]:
    capture = str(capture_fifo).replace(",", ",,")
    return [
        "-nic",
        "none",
        "-netdev",
        "user,id=installnet,ipv6=off",
        "-device",
        f"virtio-net-pci,netdev=installnet,mac={manifest.network.mac}",
        "-object",
        f"filter-dump,id=installdump,netdev=installnet,file={capture}",
    ]


def install_qemu_commands(
    iso: Path,
    disk: Path,
    manifest: Manifest,
    capture_fifo: Path,
    memory_mib: int,
) -> tuple[list[str], list[str]]:
    memory = _integer(memory_mib, "QEMU memory", 1024, 65536)
    disk_value = str(disk).replace(",", ",,")
    iso_value = str(iso).replace(",", ",,")
    common = [
        "qemu-system-ppc64",
        "-machine",
        "pseries,accel=tcg",
        "-cpu",
        "power9",
        "-smp",
        "2",
        "-m",
        f"{memory}M",
        "-display",
        "none",
        "-serial",
        "stdio",
        "-monitor",
        "none",
        "-device",
        "virtio-scsi-pci",
    ]
    disk_drive = f"file={disk_value},format=qcow2,if=virtio"
    install = common + [
        "-boot",
        "d",
        "-drive",
        disk_drive,
        "-drive",
        f"file={iso_value},format=raw,media=cdrom,readonly=on,if=none,id=cdrom",
        "-device",
        "scsi-cd,drive=cdrom,bootindex=1",
        *_qemu_network(manifest, capture_fifo),
    ]
    boot = common + ["-boot", "c", "-drive", disk_drive, "-nic", "none"]
    return install, boot


def _installed_boot_id(encoded: bytes) -> str:
    marker = re.compile(rb"installed-boot: passed boot_id=(" + BOOT_ID.encode() + rb")")
    matches = [match for line in encoded.splitlines() if (match := marker.fullmatch(line.strip()))]
    if len(matches) != 1:
        raise ValidationError("boot console requires one canonical installed-boot marker")
    boot_id = matches[0].group(1).decode("ascii").lower()
    try:
        if str(uuid.UUID(boot_id)) != boot_id:
            raise ValueError
    except ValueError as error:
        raise ValidationError("boot console contains a malformed boot ID") from error
    return boot_id


def _copy_bounded_stream(source, destination: Path, maximum: int, label: str) -> None:
    copied = 0
    with destination.open("xb") as output:
        destination.chmod(0o600)
        while block := source.read(64 * 1024):
            remaining = maximum - copied
            output.write(block[:remaining])
            copied += min(len(block), remaining)
            if len(block) > remaining:
                raise ValidationError(f"{label} exceeds its byte limit")


def _run_qemu_phase(
    command: list[str],
    log: Path,
    timeout: int,
    capture_fifo: Path | None = None,
    capture: Path | None = None,
) -> int:
    if (capture_fifo is None) != (capture is None):
        raise ValidationError("capture paths must be supplied together")
    errors: list[Exception] = []
    process_box: list[subprocess.Popen] = []
    threads: list[threading.Thread] = []

    def copy(source, destination: Path, maximum: int, label: str) -> None:
        try:
            with source:
                _copy_bounded_stream(source, destination, maximum, label)
        except (OSError, ValidationError) as error:
            errors.append(error)
            if process_box:
                process_box[0].terminate()

    if capture_fifo is not None:
        try:
            os.mkfifo(capture_fifo, 0o600)
        except OSError as error:
            raise ValidationError("capture FIFO creation failed") from error

        def copy_capture() -> None:
            try:
                with capture_fifo.open("rb", buffering=0) as source:
                    copy(source, capture, MAX_INSTALL_CAPTURE_BYTES, "install capture")
            except OSError as error:
                errors.append(error)
                if process_box:
                    process_box[0].terminate()

        capture_thread = threading.Thread(target=copy_capture, daemon=True)
        capture_thread.start()
        threads.append(capture_thread)

    try:
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
        except OSError as error:
            if capture_fifo is not None:
                with capture_fifo.open("wb", buffering=0):
                    pass
            raise ValidationError("QEMU could not start") from error
        process_box.append(process)
        if process.stdout is None:
            process.terminate()
            raise ValidationError("QEMU output pipe is unavailable")
        console_thread = threading.Thread(
            target=copy,
            args=(process.stdout, log, MAX_LOG_BYTES, "console log"),
            daemon=True,
        )
        console_thread.start()
        threads.append(console_thread)
        timed_out = False
        try:
            status = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.terminate()
            try:
                status = process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                status = process.wait()
        for thread in threads:
            thread.join(timeout=10)
        if any(thread.is_alive() for thread in threads):
            raise ValidationError("QEMU output reader did not finish")
        if timed_out:
            raise ValidationError("QEMU phase timed out")
        if errors:
            error = errors[0]
            if isinstance(error, ValidationError):
                raise error
            raise ValidationError("QEMU output capture failed") from error
        if status != 0:
            raise ValidationError("QEMU phase failed")
        return status
    finally:
        if capture_fifo is not None:
            capture_fifo.unlink(missing_ok=True)


def install_fedora(args: argparse.Namespace) -> None:
    iso = _regular_file(Path(args.iso).absolute(), "launcher ISO")
    manifest, _, _ = load_manifest(args.config)
    output = Path(args.output).absolute()
    parent = _path(output.parent, "output parent", "directory")
    if os.path.lexists(output):
        raise ValidationError("installation output already exists")
    disk_size = _integer(args.disk_size_gib, "disk size", 8, 256)
    memory = _integer(args.memory_mib, "QEMU memory", 1024, 65536)
    install_timeout = _integer(args.install_timeout_seconds, "install timeout", 1, 86400)
    boot_timeout = _integer(args.boot_timeout_seconds, "boot timeout", 1, 86400)
    if shutil.disk_usage(parent).free < MAX_INSTALL_CAPTURE_BYTES:
        raise ValidationError("output parent lacks install capture capacity")

    with tempfile.TemporaryDirectory(prefix=".iso-chain-install-", dir=parent) as temporary:
        root = Path(temporary)
        root.chmod(0o700)
        staged = root / "result"
        staged.mkdir(mode=0o700)
        disk = staged / "disk.qcow2"
        try:
            subprocess.run(
                ["qemu-img", "create", "-f", "qcow2", str(disk), f"{disk_size}G"],
                check=True,
                capture_output=True,
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise ValidationError("standalone disk creation failed") from error
        disk.chmod(0o600)
        before = _file_sha256(disk)
        install_log = staged / "install-console.log"
        boot_log = staged / "boot-console.log"
        capture = staged / "install.pcap"
        capture_fifo = root / "install-capture.pipe"
        install_command, boot_command = install_qemu_commands(
            iso, disk, manifest, capture_fifo, memory
        )
        install_status = _run_qemu_phase(
            install_command, install_log, install_timeout, capture_fifo, capture
        )
        boot_status = _run_qemu_phase(boot_command, boot_log, boot_timeout)
        _installed_boot_id(_bounded_file(boot_log, "boot console", MAX_LOG_BYTES))
        after = _file_sha256(disk)
        if disk.stat().st_size == 0 or before == after:
            raise ValidationError("standalone disk did not record installation changes")
        result = {
            "version": 1,
            "qemu_memory_mib": memory,
            "disk_size_gib": disk_size,
            "install_timeout_seconds": install_timeout,
            "boot_timeout_seconds": boot_timeout,
            "install_exit_status": install_status,
            "boot_exit_status": boot_status,
            "disk_sha256_before": before,
            "disk_sha256_after": after,
        }
        result_path = staged / "result.json"
        result_path.write_bytes(
            json.dumps(result, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        )
        result_path.chmod(0o600)
        _publish_directory(staged, output)


def _launcher_command_line(lines: list[str], end: int) -> tuple[int, list[str]]:
    fragments = [
        (index, match.group(1).split())
        for index, line in enumerate(lines[:end])
        if (match := re.fullmatch(r"\[\s*\d+\.\d+\] Kernel command line: (.*)", line))
        and any(
            argument.startswith(("iso_chain.", "ipv6.", "rd.systemd.unit="))
            for argument in match.group(1).split()
        )
    ]
    if not fragments or any(
        fragments[index][0] != fragments[index - 1][0] + 1 for index in range(1, len(fragments))
    ):
        raise ValidationError("console log requires one contiguous launcher kernel command line")
    arguments = []
    for index, (_, fragment) in enumerate(fragments):
        continued = index < len(fragments) - 1
        if continued and fragment and fragment[-1] == "\\":
            fragment = fragment[:-1]
        elif continued or fragment and fragment[-1] == "\\":
            message = "malformed" if continued else "incomplete"
            raise ValidationError(f"wrapped launcher kernel command line is {message}")
        arguments.extend(fragment)
    return fragments[0][0], arguments


def _launcher_marker(lines: list[str], marker: str, after: int) -> int:
    if lines.count(marker) != 1 or lines.index(marker) <= after:
        raise ValidationError("missing, repeated, or reordered launcher evidence")
    return lines.index(marker)


def verify_launcher_log(log: Path, manifest: Manifest, expected_profile: str) -> tuple[str, ...]:
    manifest.profile(expected_profile)
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
    launcher_end = next(
        (i + 1 for i, line in enumerate(visible[start:], start) if line == "kexec-exec: started"),
        len(visible),
    )
    if any(
        line
        in (
            "configuration: failed",
            "adapter-match: failed",
            "launcher: failed",
            "kexec-exec: returned",
            "kexec-exec: failed",
            "kexec-unload: failed",
        )
        or ("iso-chain" in line and "failed" in line.lower())
        for line in visible
    ) or any(
        "failed" in line.lower() or "emergency" in line.lower()
        for line in lines[start:launcher_end]
    ):
        raise ValidationError("console log contains failure evidence")
    position, arguments = _launcher_command_line(lines, start)
    canonical = (
        json.dumps(_manifest_data(manifest), sort_keys=True, separators=(",", ":")).encode() + b"\n"
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
    for marker in ("ISO_CHAIN: configuration passed", "adapter-match: passed", "profile: passed"):
        position = _launcher_marker(visible, marker, position)
    memory_lines = [
        (index, match)
        for index, line in enumerate(visible)
        if (match := MEMORY_EVIDENCE.fullmatch(line))
    ]
    if len(memory_lines) != 1 or memory_lines[0][0] <= position:
        raise ValidationError("missing, repeated, or reordered memory evidence")
    position = memory_lines[0][0]
    for marker in ("artifacts: passed", "kexec-load: passed", "kexec-exec: started"):
        position = _launcher_marker(visible, marker, position)
    return (
        "configuration: passed",
        "adapter-match: passed",
        "profile: passed",
        "memory: passed",
        "artifacts: passed",
        "kexec-load: passed",
        "kexec-exec: started",
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
    return "dhcp-ipv6-filter: absent"


def _read_evidence_file(path: Path, label: str, maximum: int) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as error:
        raise ValidationError(f"{label} must be an available regular file") from error
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValidationError(f"{label} must be a regular file")
        encoded = stream.read(maximum + 1)
    if not encoded or len(encoded) > maximum:
        raise ValidationError(f"{label} is empty or exceeds its evidence limit")
    return encoded


def _evidence_json(encoded: bytes, fields: set[str], label: str) -> dict[str, object]:
    try:
        value = json.loads(encoded.decode("utf-8"), object_pairs_hook=_object_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValidationError(f"{label}: invalid JSON") from error
    data = _manifest_object(value, fields, label)
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    if encoded != canonical:
        raise ValidationError(f"{label}: must be canonical JSON")
    return data


def _evidence_integer(value: object, field: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValidationError(f"evidence {field}: invalid integer")
    return value


def _access_records(encoded: bytes) -> list[dict[str, object]]:
    records = []
    fields = {"method", "path", "status", "bytes", "index"}
    for expected_index, line in enumerate(encoded.splitlines(keepends=True), 1):
        record = _evidence_json(line, fields, "access log record")
        if record["method"] != "GET":
            raise ValidationError("access log method is invalid")
        path = record["path"]
        if type(path) is not str:
            raise ValidationError("access log path is invalid")
        _url_path(path, "access log path")
        status = _evidence_integer(record["status"], "status", 100, 599)
        _evidence_integer(record["bytes"], "bytes", 0, 2 * 1024 * 1024 * 1024)
        if record["bytes"] == 0:
            raise ValidationError("access log contains an empty response")
        index = _evidence_integer(record["index"], "index", 1, 2**31 - 1)
        if index != expected_index or status != 200:
            raise ValidationError("access log contains failed or reordered requests")
        records.append(record)
    return records


def _disk_digest(encoded: bytes) -> str:
    try:
        value = encoded.decode("ascii")
    except UnicodeDecodeError as error:
        raise ValidationError("disk hash has invalid grammar") from error
    if re.fullmatch(r"[0-9a-f]{64}\n", value) is None:
        raise ValidationError("disk hash has invalid grammar")
    return value.rstrip("\n")


def _verify_record_identity(
    record: dict[str, object], manifest: Manifest, manifest_digest: str
) -> InstallerProfile:
    version = record["version"]
    recorded_digest = record["manifest_sha256"]
    if (
        type(version) is not int
        or version != 1
        or type(recorded_digest) is not str
        or recorded_digest != manifest_digest
    ):
        raise ValidationError("evidence record identity does not match manifest")
    profile_name = record["profile"]
    if type(profile_name) is not str:
        raise ValidationError("evidence profile is invalid")
    profile = manifest.profile(profile_name)
    configured = _evidence_integer(record["qemu_memory_mib"], "QEMU memory", 1, 65536)
    total = _evidence_integer(record["guest_memtotal_mib"], "MemTotal", 1, 65536)
    available = _evidence_integer(record["guest_memavailable_mib"], "MemAvailable", 1, 65536)
    required = (profile.kernel.size + profile.initramfs.size + 1073741824 + 1048575) // 1048576
    if (
        total > configured
        or total < profile.minimum_memory_mib
        or available > total
        or available < required
    ):
        raise ValidationError("evidence memory does not satisfy the selected profile")
    label = record["disk_label"]
    if type(label) is not str or re.fullmatch(r"[A-Za-z0-9._-]{1,64}", label) is None:
        raise ValidationError("evidence disk label is invalid")
    return profile


def _verify_input_digests(record: dict[str, object], inputs: dict[str, bytes]) -> None:
    expected = record["evidence_sha256"]
    if type(expected) is not dict or set(expected) != set(inputs):
        raise ValidationError("evidence digest map has missing or unknown inputs")
    for name, encoded in inputs.items():
        digest = expected[name]
        if type(digest) is not str or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValidationError("evidence digest map contains an invalid digest")
        if hashlib.sha256(encoded).hexdigest() != digest:
            raise ValidationError("evidence input was replaced after review")


def _verify_http_requests(records: list[dict[str, object]], profile: InstallerProfile) -> None:
    launcher_artifacts = (
        (profile.kernel.path, profile.kernel.size),
        (profile.initramfs.path, profile.initramfs.size),
        (profile.repository.treeinfo_path, profile.repository.treeinfo.size),
        (profile.repository.repomd_path, profile.repository.repomd.size),
    )
    sizes = dict(launcher_artifacts)
    paths = [record["path"] for record in records if record["method"] == "GET"]
    if paths[: len(launcher_artifacts)] != [path for path, _ in launcher_artifacts]:
        raise ValidationError("HTTP evidence has invalid launcher request order")
    for path, size in sizes.items():
        if (
            paths.count(path) < 1
            or path in (profile.kernel.path, profile.initramfs.path)
            and paths.count(path) != 1
        ):
            raise ValidationError("HTTP evidence is missing a required artifact request")
        if any(record["bytes"] != size for record in records if record["path"] == path):
            raise ValidationError("HTTP evidence has an artifact size mismatch")
    repository_prefix = profile.repository.path + "/"
    if any(path not in sizes and not path.startswith(repository_prefix) for path in paths):
        raise ValidationError("HTTP evidence contains a path outside the selected profile")
    if not any(path.startswith(repository_prefix) and path not in sizes for path in paths):
        raise ValidationError("HTTP evidence lacks post-kexec repository corroboration")


def _verify_console_memory(
    encoded: bytes, record: dict[str, object], profile: InstallerProfile
) -> None:
    visible = [
        SERVICE_PREFIX.sub("", ANSI_ESCAPE.sub("", line).strip(), count=1)
        for line in encoded.decode(errors="replace").splitlines()
    ]
    matches = [match for line in visible if (match := MEMORY_EVIDENCE.fullmatch(line))]
    if len(matches) != 1:
        raise ValidationError("console memory evidence is missing or repeated")
    total, available, run_bytes = (int(value) for value in matches[0].groups())
    if total != record["guest_memtotal_mib"] or available != record["guest_memavailable_mib"]:
        raise ValidationError("console memory evidence does not match the record")
    required_bytes = profile.kernel.size + profile.initramfs.size + 1073741824
    if run_bytes < required_bytes:
        raise ValidationError("console run-space evidence is insufficient")


def verify_fedora_evidence(args: argparse.Namespace) -> tuple[str, ...]:
    record_bytes = _read_evidence_file(args.record, "evidence record", 64 * 1024)
    manifest_bytes = _read_evidence_file(args.config, "manifest", 64 * 1024)
    console_bytes = _read_evidence_file(args.console_log, "console", MAX_LOG_BYTES)
    access_bytes = _read_evidence_file(args.access_log, "access log", MAX_LOG_BYTES)
    pcap_bytes = _read_evidence_file(args.pcap, "packet capture", 64 * 1024 * 1024)
    before_bytes = _read_evidence_file(args.disk_hash_before, "disk hash", 256)
    after_bytes = _read_evidence_file(args.disk_hash_after, "disk hash", 256)
    record_fields = {
        "version",
        "manifest_sha256",
        "profile",
        "qemu_memory_mib",
        "guest_memtotal_mib",
        "guest_memavailable_mib",
        "disk_label",
        "evidence_sha256",
        "same_run_collection",
        "installer_ready",
        "intended_disk_visible",
        "intended_source_confirmed",
    }
    record = _evidence_json(record_bytes, record_fields, "evidence record")
    manifest, canonical, manifest_digest = load_manifest_bytes(manifest_bytes)
    if manifest_bytes != canonical:
        raise ValidationError("manifest evidence must be canonical JSON")
    profile = _verify_record_identity(record, manifest, manifest_digest)
    inputs = {
        "manifest": manifest_bytes,
        "console": console_bytes,
        "access_log": access_bytes,
        "pcap": pcap_bytes,
        "disk_before": before_bytes,
        "disk_after": after_bytes,
    }
    _verify_input_digests(record, inputs)
    with tempfile.TemporaryDirectory(prefix="iso-chain-evidence-") as temporary:
        verified_console = Path(temporary) / "console.log"
        verified_pcap = Path(temporary) / "capture.pcap"
        verified_console.write_bytes(console_bytes)
        verified_pcap.write_bytes(pcap_bytes)
        verify_launcher_log(verified_console, manifest, record["profile"])
        network_result = verify_pcap(verified_pcap)
    _verify_console_memory(console_bytes, record, profile)
    _verify_http_requests(_access_records(access_bytes), profile)
    if _disk_digest(before_bytes) != _disk_digest(after_bytes):
        raise ValidationError("disk hash changed during the installer proof")
    flags = (
        "same_run_collection",
        "installer_ready",
        "intended_disk_visible",
        "intended_source_confirmed",
    )
    if any(record[field] is not True for field in flags):
        raise ValidationError("all operator-reviewed observations must be true")
    return (
        "manifest: passed",
        "memory: passed",
        "http-evidence: passed",
        "disk-unchanged: passed",
        network_result,
        "capture-provenance: operator-reviewed",
        "same-run: operator-reviewed",
        "installer-readiness: operator-reviewed",
        "storage-visibility: operator-reviewed",
        "intended-source: operator-reviewed",
    )


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
    fedora = commands.add_parser("prepare-fedora-source")
    fedora.add_argument("--iso", required=True, type=Path)
    fedora.add_argument("--iso-sha256", required=True)
    fedora.add_argument("--minimum-memory-mib", required=True, type=int)
    fedora.add_argument("--kickstart", required=True, type=Path)
    fedora.add_argument("--output", required=True, type=Path)
    server = commands.add_parser("serve-fedora-source")
    server.add_argument("--directory", required=True, type=Path)
    server.add_argument("--bind", required=True)
    server.add_argument("--port", required=True, type=int)
    server.add_argument("--access-log", required=True, type=Path)
    smoke_parser = commands.add_parser("smoke")
    for name in ("iso", "disk", "config", "capture-prefix"):
        smoke_parser.add_argument(f"--{name}", required=True, type=Path)
    smoke_parser.add_argument(
        "--adapter-state", choices=("matched", "missing", "duplicate"), default="matched"
    )
    smoke_parser.add_argument("--memory-mib", type=int, default=4096)
    install = commands.add_parser("install-fedora")
    for name in ("iso", "config", "output"):
        install.add_argument(f"--{name}", required=True, type=Path)
    install.add_argument("--disk-size-gib", type=int, default=20)
    install.add_argument("--memory-mib", type=int, default=4096)
    install.add_argument("--install-timeout-seconds", type=int, default=7200)
    install.add_argument("--boot-timeout-seconds", type=int, default=600)
    verify = commands.add_parser("verify-log")
    verify.add_argument("log", type=Path)
    launcher = commands.add_parser("verify-launcher-log")
    launcher.add_argument("log", type=Path)
    launcher.add_argument("--config", type=Path, required=True)
    launcher.add_argument("--expected-profile", required=True)
    pcap = commands.add_parser("verify-pcap")
    pcap.add_argument("pcap", type=Path)
    fedora_evidence = commands.add_parser("verify-fedora-evidence")
    for name in (
        "record",
        "config",
        "console-log",
        "access-log",
        "pcap",
        "disk-hash-before",
        "disk-hash-after",
    ):
        fedora_evidence.add_argument(f"--{name}", required=True, type=Path)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "build":
            build_iso(args)
        elif args.command == "smoke":
            smoke(args)
        elif args.command == "install-fedora":
            install_fedora(args)
        elif args.command == "inspect":
            sys.stdout.buffer.write(inspect_iso(args.iso))
        elif args.command == "prepare-initramfs":
            prepare_initramfs(args)
        elif args.command == "prepare-fedora-source":
            prepare_fedora_source(args)
        elif args.command == "serve-fedora-source":
            serve_fedora_source(args)
        elif args.command == "verify-launcher-log":
            manifest, _, _ = load_manifest(args.config)
            print(*verify_launcher_log(args.log, manifest, args.expected_profile), sep="\n")
        elif args.command == "verify-pcap":
            print(verify_pcap(args.pcap))
        elif args.command == "verify-fedora-evidence":
            print(*verify_fedora_evidence(args), sep="\n")
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
