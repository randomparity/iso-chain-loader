#!/usr/bin/env python3
"""Build and exercise the bounded POWER9 optical-bootstrap experiment."""

import argparse
import configparser
import ctypes
import errno
import functools
import hashlib
import http.client
import http.server
import ipaddress
import json
import os
import platform
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import unquote_to_bytes, urlsplit

ANSI_ESCAPE = re.compile(r"\x1b\].*?(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]")
SERVICE_PREFIX = re.compile(r"^\[\s*\d+(?:\.\d+)?\]\s+[\w.-]+\[\d+\]:\s+")
BOOT_ID = r"([0-9A-Fa-f-]{36})"
MAX_LOG_BYTES = 16 * 1024 * 1024
# Sixteen 8,192-character keys written with \u escapes reach 1.5 MiB (ADR 0017).
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_COMMAND_LINE_BYTES = 2048
MAX_TREEINFO_BYTES = 64 * 1024
MAX_KICKSTART_BYTES = 1024 * 1024
MAX_USER_DATA_BYTES = 1024 * 1024
MAX_INSTALL_CAPTURE_BYTES = 8 * 1024 * 1024 * 1024
MAX_INSTALLER_ISO_BYTES = 4 * 1024 * 1024 * 1024
MAX_DISK_INFO_BYTES = 4096
FEDORA_VARIANTS = ("Everything", "Server")
PROFILE_RELEASES = {"fedora": "44", "opensuse": "15.6", "rocky": "9.8", "ubuntu": "26.04.1"}
ROCKY_REPOSITORY_SUFFIX = "/BaseOS/ppc64le/os"
# linuxrc and YaST probe for these optional files below the repository; each may 404 once.
OPENSUSE_PROBES = (
    "content",
    "boot/ppc64le/yast2-trans-en_US.rpm",
    "license.tar.gz",
    "media.1/info.txt",
    "part.info",
    "README.BETA",
    "autoinst.xml",
    "driverupdate",
    "add_on_products.xml",
    "add_on_products",
)
OPENSUSE_PRODUCTS = b"/ openSUSE-Leap 15.6-1\n"
OPENSUSE_ENTRIES = ("boot/ppc64le/linux", "boot/ppc64le/initrd", "media.1/products")
UBUNTU_ISO_NAME = "ubuntu-26.04.1-live-server-ppc64el.iso"
PASS_LINES = ("optical-boot: passed", "network: passed", "kexec: passed")
IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
TARGET_FORMAT = "iso-chain-target-v1"
MEDIA_FORMAT = "iso-chain-media-v1"
MAX_RESULT_BYTES = 64 * 1024
OPERATION_BINDING = re.compile(r"^[0-9a-f]{32}$")
# hmcpctl's built-mode bounds (hmc-mcp src/hmcpctl/operations/lpar/plan.py, ADR 0017).
LOGIN_USER = re.compile(r"[a-z_][a-z0-9_-]{0,31}")
MAX_KEYS = 16
MAX_KEY_LENGTH = 8192
OPTIONAL_ROOT_FIELDS = frozenset({"operation_binding", "ssh_authorized_keys", "login_user"})
MAC = re.compile(r"^[0-9a-f]{2}(?::[0-9a-f]{2}){5}$")
DNS_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
URI_PATH = re.compile(r"^/(?:[A-Za-z0-9._~+^-]+)(?:/[A-Za-z0-9._~+^-]+)*$")
MEDIA_PATH = re.compile(r"^/profiles/[A-Za-z0-9._~-]+/[A-Za-z0-9._~-]+$")
MEMORY_EVIDENCE = re.compile(
    r"memory: passed memtotal_mib=([0-9]+) memavailable_mib=([0-9]+) "
    r"run_available_bytes=([0-9]+)"
)
DRACUT_ASSETS = Path(__file__).resolve().parent.parent / "assets/dracut"
KERNEL_MODULES = Path("/usr/lib/modules")
DRACUT_FLAGS = ("--no-hostonly", "--reproducible", "--include", "--install", "--force-drivers")
# The disk guard counts only disks these drivers expose: virtio, vSCSI, NPIV, and NVMe (ADR 0018).
DRACUT_DRIVERS = (
    "virtio_net virtio_pci virtio_blk virtio_scsi ibmveth ibmvscsi ibmvfc nvme sr_mod isofs"
)
DRACUT_TOOLS = (
    "/bin/sh /usr/sbin/ip /usr/bin/curl /usr/bin/systemctl /usr/bin/udevadm "
    "/usr/bin/sha256sum /usr/sbin/kexec /usr/bin/mktemp /usr/bin/stat /usr/bin/sync "
    "/usr/bin/mount /usr/bin/umount /usr/bin/cat /usr/sbin/blkid /usr/bin/dd"
)
CA_BUNDLE_CANDIDATES = (
    Path("/etc/pki/tls/certs/ca-bundle.crt"),
    Path("/etc/ssl/certs/ca-certificates.crt"),
    Path("/etc/ssl/cert.pem"),
)
AT_FDCWD = -100
RENAME_NOREPLACE = 1
RENAME_EXCL = 0x4
CONTAINER_ENGINES = ("podman", "docker")
CONTAINER_IMAGE = "iso-chain-builder:44"
CONTAINER_MODULE_DIRECTORY = "/usr/lib/grub/powerpc-ieee1275"
CONTAINER_PYTHON = "python3"
CONTAINER_INITRAMFS_IMAGE = "iso-chain-initramfs:44"
CONTAINER_INITRAMFS_SCRIPT = (
    "repository=$1\noutput=$2\nset -- /usr/lib/modules/*\n"
    '[ "$#" -eq 1 ] && [ -f "$1/vmlinuz" ] || '
    '{ echo "error: expected exactly one installed kernel" >&2; exit 2; }\n'
    "version=${1##*/}\n"
    f'{CONTAINER_PYTHON} "$repository/scripts/iso_chain.py" prepare-initramfs '
    '--kernel-version "$version" --output "$output/initramfs.img"\n'
    '[ ! -e "$output/vmlinuz" ] || { echo "error: output already exists" >&2; exit 2; }\n'
    'cp "/usr/lib/modules/$version/vmlinuz" "$output/vmlinuz"\n'
)
REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
ROCKY_KICKSTART = REPOSITORY_ROOT / "assets/kickstart/rocky-9.8-unattended.ks"
UBUNTU_AUTOINSTALL = REPOSITORY_ROOT / "assets/autoinstall/ubuntu-26.04.1.json"


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
    treeinfo: Artifact | None
    repomd: Artifact | None


@dataclass(frozen=True)
class InstallerProfile:
    distribution: str
    release: str
    kernel: Artifact
    initramfs: Artifact
    repository: Repository | None
    kickstart: Artifact | None
    live_iso: Artifact | None
    minimum_memory_mib: int


@dataclass(frozen=True)
class Manifest:
    version: int
    lpar: str
    network: NetworkConfig
    source: str
    profiles: tuple[tuple[str, InstallerProfile], ...]
    selected_profile: str
    operation_binding: str | None = None
    ssh_authorized_keys: tuple[str, ...] = ()
    login_user: str | None = None

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


def _copy_with_sha256(
    source: Path, destination: Path, size: int, label: str, *, exact: bool = True
) -> str:
    """Copy and hash ``source``; ``size`` is the exact size, or the maximum when not ``exact``."""
    digest = hashlib.sha256()
    copied = 0
    with source.open("rb") as source_stream:
        if not stat.S_ISREG(os.fstat(source_stream.fileno()).st_mode):
            raise ValidationError(f"{label}: must be a regular file")
        with destination.open("xb") as destination_stream:
            while block := source_stream.read(1024 * 1024):
                copied += len(block)
                if copied > size:
                    raise ValidationError(f"{label}: size does not match")
                destination_stream.write(block)
                digest.update(block)
    if exact and copied != size:
        raise ValidationError(f"{label}: size does not match")
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


def _manifest_object(
    value: object, fields: set[str], field: str, optional: frozenset[str] = frozenset()
) -> dict[str, object]:
    if type(value) is not dict:
        _manifest_error(field, "must be an object")
    missing = fields - value.keys()
    if missing:
        _manifest_error(field, "missing required field")
    if value.keys() - fields - optional:
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


def _media_artifact(value: object, field: str, maximum: int) -> Artifact:
    artifact = _artifact(value, field, maximum)
    if MEDIA_PATH.fullmatch(artifact.path) is None or any(
        part in (".", "..") for part in artifact.path.split("/")
    ):
        _manifest_error(f"{field}.path", "must be a media path /profiles/<directory>/<file>")
    return artifact


def _installer_profile(value: object, field: str) -> InstallerProfile:
    distribution_value = value.get("distribution") if type(value) is dict else None
    ubuntu = distribution_value == "ubuntu"
    rocky = distribution_value == "rocky"
    opensuse = distribution_value == "opensuse"
    common = {"distribution", "release", "kernel", "initramfs", "minimum_memory_mib"}
    if ubuntu:
        specific = {"live_iso"}
    elif rocky or opensuse:
        specific = {"repository"}
    else:
        specific = {"repository", "kickstart"}
    data = _manifest_object(value, common | specific, field)
    distribution = _string(data["distribution"], f"{field}.distribution")
    release = _string(data["release"], f"{field}.release")
    if PROFILE_RELEASES.get(distribution) != release:
        _manifest_error(
            f"{field}.distribution/release",
            "must be fedora/44, opensuse/15.6, rocky/9.8, or ubuntu/26.04.1",
        )
    kernel = _artifact(data["kernel"], f"{field}.kernel", 2 * 1024 * 1024 * 1024)
    initramfs = _artifact(data["initramfs"], f"{field}.initramfs", 2 * 1024 * 1024 * 1024)
    memory = _integer(data["minimum_memory_mib"], f"{field}.minimum_memory_mib", 1, 65536)
    if ubuntu:
        live_iso = _artifact(data["live_iso"], f"{field}.live_iso", MAX_INSTALLER_ISO_BYTES)
        # casper only treats iso-url= as a live ISO when it ends in .iso.
        if not live_iso.path.endswith(".iso"):
            _manifest_error(f"{field}.live_iso.path", "must end in .iso")
        return InstallerProfile(
            distribution, release, kernel, initramfs, None, None, live_iso, memory
        )
    if opensuse:
        repository_data = _manifest_object(data["repository"], {"path"}, f"{field}.repository")
        repository = Repository(
            _url_path(repository_data["path"], f"{field}.repository.path"), None, None
        )
        return InstallerProfile(
            distribution, release, kernel, initramfs, repository, None, None, memory
        )
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
    if rocky:
        # The AppStream sibling that Anaconda adds is derived from this suffix (ADR 0013).
        if not repository_path.endswith(ROCKY_REPOSITORY_SUFFIX):
            _manifest_error(f"{field}.repository.path", f"must end in {ROCKY_REPOSITORY_SUFFIX}")
        return InstallerProfile(
            distribution, release, kernel, initramfs, repository, None, None, memory
        )
    kickstart = _media_artifact(data["kickstart"], f"{field}.kickstart", MAX_KICKSTART_BYTES)
    return InstallerProfile(
        distribution, release, kernel, initramfs, repository, kickstart, None, memory
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


def _validate_source(value: object, field: str = "source") -> str:
    source = _string(value, field)
    if not source.startswith(("http://", "https://")):
        _manifest_error(field, "must use the canonical lower-case http:// or https:// scheme")
    if any(char.isspace() or char in "\\\"'?#" for char in source):
        _manifest_error(field, "contains forbidden characters")
    try:
        parsed = urlsplit(source)
        port = parsed.port
    except ValueError as error:
        _manifest_error(field, "has an invalid port")
        raise AssertionError from error
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        _manifest_error(field, "must be a credential-free HTTP(S) URL without query or fragment")
    if (
        not parsed.hostname
        or port == 0
        or port is not None
        and parsed.netloc.rpartition(":")[2] != str(port)
        or parsed.path != ""
        and URI_PATH.fullmatch(parsed.path) is None
        or re.fullmatch(r"[A-Za-z0-9.-]+(?::[0-9]+)?", parsed.netloc) is None
    ):
        _manifest_error(field, "must be a canonical HTTP(S) origin or base path")
    _validate_source_host(parsed.hostname, field)
    return source


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file, code, msg, headers, new_url):
        return None


def _external_artifacts(profile: InstallerProfile) -> tuple[Artifact, ...]:
    if profile.live_iso is not None:
        return (profile.kernel, profile.initramfs, profile.live_iso)
    if profile.repository.treeinfo is None:
        return (profile.kernel, profile.initramfs)
    return (
        profile.kernel,
        profile.initramfs,
        profile.repository.treeinfo,
        profile.repository.repomd,
    )


def _set_response_timeout(response: object, remaining: float) -> None:
    socket = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
    if socket is not None:
        socket.settimeout(remaining)


def validate_external_source(
    manifest: Manifest, profile_name: str, timeout_seconds: int
) -> list[dict[str, object]]:
    if not 1 <= timeout_seconds <= 300:
        raise ValidationError("external source timeout must be from 1 through 300 seconds")
    profile = manifest.profile(profile_name)
    opener = urllib.request.build_opener(_NoRedirectHandler)
    results = []
    for artifact in _external_artifacts(profile):
        request = urllib.request.Request(
            manifest.source + artifact.path,
            headers={"Accept": "application/octet-stream"},
        )
        digest = hashlib.sha256()
        size = 0
        deadline = time.monotonic() + timeout_seconds
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                if response.status != 200:
                    raise ValidationError("external source returned a non-200 response")
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ValidationError("external source request timed out")
                    _set_response_timeout(response, remaining)
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > artifact.size:
                        raise ValidationError("external source response exceeds the manifest size")
                    digest.update(chunk)
        except (
            http.client.HTTPException,
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
        ) as error:
            raise ValidationError("external source request failed") from error
        if size != artifact.size or digest.hexdigest() != artifact.sha256:
            raise ValidationError("external source artifact does not match the manifest")
        results.append({"path": artifact.path, "size": size, "sha256": digest.hexdigest()})
    return results


def _validate_source_host(host: str, field: str) -> None:
    try:
        host.encode("ascii")
        ipaddress.IPv4Address(host)
        return
    except UnicodeEncodeError, ipaddress.AddressValueError:
        pass
    if len(host) > 253 or any(DNS_LABEL.fullmatch(label) is None for label in host.split(".")):
        _manifest_error(field, "host must be an ASCII IPv4 address or DNS name")


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


def _read_manifest_bytes(path: Path, label: str = "manifest") -> bytes:
    try:
        with Path(path).open("rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValidationError(f"{label} file: must be a regular file")
            encoded = stream.read(MAX_MANIFEST_BYTES + 1)
    except OSError as error:
        raise ValidationError(f"{label} file: unavailable") from error
    if len(encoded) > MAX_MANIFEST_BYTES:
        raise ValidationError(f"{label} file: exceeds 2 MiB")
    return encoded


def _json_document(path: Path, label: str) -> object:
    encoded = _read_manifest_bytes(path, label)
    try:
        return json.loads(encoded.decode("utf-8"), object_pairs_hook=_object_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValidationError(f"{label} JSON: invalid UTF-8 JSON") from error


def compose_target_manifest(target: Path, base: Path) -> bytes:
    """Return manifest v4 JSON binding one base profile to a target request (ADR 0015)."""
    request = _manifest_object(
        _json_document(target, "target"),
        {"format", "profile", "lpar", "mac", "network"},
        "target",
        optional=OPTIONAL_ROOT_FIELDS,
    )
    if request["format"] != TARGET_FORMAT:
        _manifest_error("target.format", f"must be {TARGET_FORMAT}")
    network = _manifest_object(request["network"], {"address", "routes", "dns"}, "network")
    data = _manifest_object(
        _json_document(base, "base manifest"), {"version", "source", "profiles"}, "base"
    )
    profiles = data["profiles"]
    if type(profiles) is not dict or not 1 <= len(profiles) <= 16:
        _manifest_error("base.profiles", "must contain 1 to 16 profile objects")
    profile = _string(request["profile"], "target.profile")
    matches = [
        key
        for key, value in profiles.items()
        if type(value) is dict and f"{value.get('distribution')}-{value.get('release')}" == profile
    ]
    if len(matches) != 1:
        _manifest_error("target.profile", "must match exactly one base profile")
    composed = {
        "version": data["version"],
        "lpar": request["lpar"],
        "network": {"mac": request["mac"], **network},
        "source": data["source"],
        "profiles": {matches[0]: profiles[matches[0]]},
        "selected_profile": matches[0],
    }
    composed.update((key, request[key]) for key in sorted(OPTIONAL_ROOT_FIELDS & request.keys()))
    return json.dumps(composed).encode()


def _login(root: dict[str, object]) -> tuple[tuple[str, ...], str | None]:
    """Return the validated SSH keys and login user, or no keys and None (ADR 0017)."""
    if ("ssh_authorized_keys" in root) != ("login_user" in root):
        _manifest_error("ssh_authorized_keys/login_user", "must appear together")
    if "login_user" not in root:
        return (), None
    keys = root["ssh_authorized_keys"]
    if type(keys) is not list or not 1 <= len(keys) <= MAX_KEYS:
        _manifest_error("ssh_authorized_keys", f"must hold 1 to {MAX_KEYS} keys")
    for index, key in enumerate(keys):
        # isprintable() rejects every line break, including U+2028 and NEL, and every control.
        if type(key) is not str or not 1 <= len(key) <= MAX_KEY_LENGTH or not key.isprintable():
            _manifest_error(
                f"ssh_authorized_keys[{index}]",
                f"must be one line of 1 to {MAX_KEY_LENGTH} printable characters",
            )
    user = root["login_user"]
    if type(user) is not str or LOGIN_USER.fullmatch(user) is None:
        _manifest_error("login_user", "must match [a-z_][a-z0-9_-]{0,31}")
    return tuple(keys), user


def _canonical_bytes(data: object) -> bytes:
    return (
        json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        + b"\n"
    )


def load_manifest_bytes(encoded: bytes) -> tuple[Manifest, bytes, str]:
    try:
        data = json.loads(encoded.decode("utf-8"), object_pairs_hook=_object_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValidationError("manifest JSON: invalid UTF-8 JSON") from error
    root = _manifest_object(
        data,
        {"version", "lpar", "network", "source", "profiles", "selected_profile"},
        "root",
        optional=OPTIONAL_ROOT_FIELDS,
    )
    version = root["version"]
    if type(version) is int and version == 3:
        _manifest_error(
            "version", "3 is no longer supported; regenerate the profile with prepare-fedora-source"
        )
    if type(version) is not int or version != 4:
        _manifest_error("version", "must be exactly 4")
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
    media: dict[str, Artifact] = {}
    for name, profile in profiles:
        if profile.kickstart is None:
            continue
        if media.setdefault(profile.kickstart.path, profile.kickstart) != profile.kickstart:
            _manifest_error(
                f"profiles.{name}", "reuses a media path with a different size or digest"
            )
    selected_profile = _identifier(root["selected_profile"], "selected_profile")
    if selected_profile not in dict(profiles):
        _manifest_error("selected_profile", "must be listed in profiles")
    binding = root.get("operation_binding")
    if "operation_binding" in root and (
        type(binding) is not str or OPERATION_BINDING.fullmatch(binding) is None
    ):
        _manifest_error("operation_binding", "must be 32 lower-case hex digits")
    keys, user = _login(root)
    network = _validate_network(root["network"])
    for name, profile in profiles:
        # casper's ip= carries one gateway and at most two DNS servers (ADR 0012).
        if profile.distribution == "ubuntu" and (
            [destination for destination, _ in network.routes] != ["0.0.0.0/0"]
            or len(network.dns) > 2
        ):
            _manifest_error(
                f"profiles.{name}",
                "ubuntu handoff supports only the default route and at most two DNS servers",
            )
        # linuxrc's ifcfg= carries one gateway and a space-separated DNS field (ADR 0014).
        if profile.distribution == "opensuse" and (
            [destination for destination, _ in network.routes] != ["0.0.0.0/0"]
            or len(network.dns) > 1
        ):
            _manifest_error(
                f"profiles.{name}",
                "opensuse handoff supports only the default route and at most one DNS server",
            )
    manifest = Manifest(
        version=4,
        lpar=_identifier(root["lpar"], "lpar"),
        network=network,
        source=_validate_source(root["source"]),
        profiles=profiles,
        selected_profile=selected_profile,
        operation_binding=binding,
        ssh_authorized_keys=keys,
        login_user=user,
    )
    canonical = _canonical_bytes(data)
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
        data: dict[str, object] = {
            "distribution": profile.distribution,
            "release": profile.release,
            "kernel": artifact(profile.kernel),
            "initramfs": artifact(profile.initramfs),
            "minimum_memory_mib": profile.minimum_memory_mib,
        }
        if profile.live_iso is not None:
            data["live_iso"] = artifact(profile.live_iso)
        elif profile.repository.treeinfo is None:
            data["repository"] = {"path": profile.repository.path}
        else:
            data["repository"] = {
                "path": profile.repository.path,
                "treeinfo": artifact(profile.repository.treeinfo, include_path=False),
                "repomd": artifact(profile.repository.repomd, include_path=False),
            }
            if profile.kickstart is not None:
                data["kickstart"] = artifact(profile.kickstart)
        profiles[name] = data
    result: dict[str, object] = {
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
    if manifest.operation_binding is not None:
        result["operation_binding"] = manifest.operation_binding
    if manifest.login_user is not None:
        result["ssh_authorized_keys"] = list(manifest.ssh_authorized_keys)
        result["login_user"] = manifest.login_user
    return result


def _rocky_kickstart(manifest: Manifest) -> bytes:
    """Render the unattended Rocky Kickstart from the manifest's login values (ADR 0019)."""
    for index, key in enumerate(manifest.ssh_authorized_keys):
        # pykickstart hands shlex's tokens to argparse, which reads a leading - as an option.
        if key.startswith("-"):
            _manifest_error(f"ssh_authorized_keys[{index}]", "must not start with -")
    # Anaconda rejects a host name label that ends in -.
    if manifest.lpar.endswith("-"):
        _manifest_error("lpar", "must not end in - for an unattended rocky install")
    network = manifest.network
    user = shlex.quote(manifest.login_user)
    gateway = dict(network.routes)["0.0.0.0/0"]
    other_routes = [route for route in network.routes if route[0] != "0.0.0.0/0"]
    routes = [
        f"route{index}={destination},{via}"
        for index, (destination, via) in enumerate(other_routes, 1)
    ]
    dns = ["dns=" + "".join(f"{server};" for server in network.dns)] if network.dns else []
    keyfile = "/etc/NetworkManager/system-connections/iso-chain.nmconnection"
    lines = [
        f"network --hostname={manifest.lpar}",
        f"user --name={user}",
        *(f"sshkey --username={user} {shlex.quote(key)}" for key in manifest.ssh_authorized_keys),
        "%post --erroronfail --interpreter=/bin/sh",
        "set -eu",
        "rm -f /etc/NetworkManager/system-connections/* /etc/sysconfig/network-scripts/ifcfg-*",
        "umask 077",
        f"cat >{keyfile} <<'ISO_CHAIN_KEYFILE'",
        "[connection]",
        "id=iso-chain",
        "type=ethernet",
        "autoconnect=true",
        "",
        "[ethernet]",
        f"mac-address={network.mac}",
        "",
        "[ipv4]",
        "method=manual",
        f"address1={network.address}",
        f"gateway={gateway}",
        *routes,
        *dns,
        "",
        "[ipv6]",
        "method=disabled",
        "ISO_CHAIN_KEYFILE",
        f"restorecon {keyfile}",
        "%end",
        "",
    ]
    rendered = "\n".join(lines).encode() + ROCKY_KICKSTART.read_bytes()
    if len(rendered) > MAX_KICKSTART_BYTES:
        raise ValidationError("rendered Kickstart exceeds 1 MiB")
    return rendered


def _profile_kickstart(manifest: Manifest, name: str) -> tuple[Artifact, bytes | None] | None:
    """Return a profile's media Kickstart and, when build derives it, its bytes (ADR 0019)."""
    profile = manifest.profile(name)
    if profile.kickstart is not None:
        return profile.kickstart, None
    if profile.distribution != "rocky" or manifest.login_user is None:
        return None
    rendered = _rocky_kickstart(manifest)
    path = f"/profiles/{name}/ks.cfg"
    return Artifact(path, len(rendered), hashlib.sha256(rendered).hexdigest()), rendered


def _ubuntu_user_data(manifest: Manifest) -> bytes:
    """Render cloud-init user data holding the unattended autoinstall (ADR 0020)."""
    # cloud-init sets the host name from user data; a label ending in - is not a valid one.
    if manifest.lpar.endswith("-"):
        _manifest_error("lpar", "must not end in - for an unattended ubuntu install")
    network = manifest.network
    ethernet: dict[str, object] = {
        "match": {"macaddress": network.mac},
        "addresses": [network.address],
        "routes": [{"to": "default", "via": dict(network.routes)["0.0.0.0/0"]}],
        "dhcp4": False,
        "dhcp6": False,
        "accept-ra": False,
        "link-local": [],
    }
    if network.dns:
        ethernet["nameservers"] = {"addresses": list(network.dns)}
    autoinstall = json.loads(UBUNTU_AUTOINSTALL.read_text())
    autoinstall["network"] = {"version": 2, "ethernets": {"iso0": ethernet}}
    autoinstall["user-data"] = {
        "hostname": manifest.lpar,
        "disable_root": True,
        "users": [
            {
                "name": manifest.login_user,
                "lock_passwd": True,
                "shell": "/bin/bash",
                "ssh_authorized_keys": list(manifest.ssh_authorized_keys),
            }
        ],
    }
    # JSON is YAML flow syntax, and json.dumps writes each value as one double-quoted scalar.
    document = json.dumps(
        {"autoinstall": autoinstall}, ensure_ascii=False, indent=2, sort_keys=True
    )
    rendered = f"#cloud-config\n{document}\n".encode()
    if len(rendered) > MAX_USER_DATA_BYTES:
        raise ValidationError("rendered user data exceeds 1 MiB")
    return rendered


def _profile_user_data(manifest: Manifest, name: str) -> bytes | None:
    """Return an unattended Ubuntu profile's ISO-root user data, else None (ADR 0020)."""
    if manifest.profile(name).distribution != "ubuntu" or manifest.login_user is None:
        return None
    return _ubuntu_user_data(manifest)


def _profile_source_arguments(
    profile: InstallerProfile, kickstart: Artifact | None, user_data: bytes | None
) -> list[str]:
    if profile.live_iso is not None:
        arguments = [f"iso_chain.profile_live_iso_path={profile.live_iso.path}"]
        if user_data is None:
            return arguments
        return [
            *arguments,
            f"iso_chain.profile_user_data_size={len(user_data)}",
            f"iso_chain.profile_user_data_sha256={hashlib.sha256(user_data).hexdigest()}",
        ]
    if profile.repository.treeinfo is None:
        return [f"iso_chain.profile_repository_path={profile.repository.path}"]
    arguments = [
        f"iso_chain.profile_repository_path={profile.repository.path}",
        f"iso_chain.profile_treeinfo_size={profile.repository.treeinfo.size}",
        f"iso_chain.profile_treeinfo_sha256={profile.repository.treeinfo.sha256}",
        f"iso_chain.profile_repomd_size={profile.repository.repomd.size}",
        f"iso_chain.profile_repomd_sha256={profile.repository.repomd.sha256}",
    ]
    if kickstart is None:
        return arguments
    return [
        *arguments,
        f"iso_chain.profile_kickstart_path={kickstart.path}",
        f"iso_chain.profile_kickstart_size={kickstart.size}",
        f"iso_chain.profile_kickstart_sha256={kickstart.sha256}",
    ]


def _kernel_arguments(manifest: Manifest, digest: str, profile: str) -> list[str]:
    selected = manifest.profile(profile)
    derived = _profile_kickstart(manifest, profile)
    kickstart = derived[0] if derived is not None else None
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
        *_profile_source_arguments(selected, kickstart, _profile_user_data(manifest, profile)),
        f"iso_chain.profile_minimum_memory_mib={selected.minimum_memory_mib}",
        f"iso_chain.config_sha256={digest}",
        "ipv6.disable=1",
        "rd.systemd.unit=iso-chain.target",
    ]
    if len(" ".join(args).encode("utf-8")) + 1 > MAX_COMMAND_LINE_BYTES:
        raise ValidationError("kernel command line exceeds the 2,048-byte PowerPC limit")
    return args


def _ubuntu_handoff(manifest: Manifest, profile: InstallerProfile, label: str | None) -> list[str]:
    """Return the casper command line that iso-chain-launch.sh ubuntu_command_line emits.

    With the launcher ISO's label, it adds the unattended tokens of ADR 0020.
    """
    interface = ipaddress.IPv4Interface(manifest.network.address)
    fields = [
        str(interface.ip),
        "",
        manifest.network.routes[0][1],
        str(interface.netmask),
        manifest.lpar,
        "",
        "off",
        *manifest.network.dns,
    ]
    arguments = [
        "ip=" + ":".join(fields),
        "BOOTIF=01-" + manifest.network.mac.replace(":", "-"),
        f"iso-url={manifest.source}{profile.live_iso.path}",
    ]
    if label is None:
        return [*arguments, "console=hvc0", "ipv6.disable=1"]
    # cc: is cloud-init's command-line configuration; it points NoCloud at the launcher ISO.
    cloud_config = f"cc:datasource:%20{{NoCloud:%20{{fs_label:%20{label}}}}}%20end_cc"
    # curtin copies the arguments after --- into the installed system's command line.
    return [
        *arguments,
        "autoinstall",
        "ds=nocloud",
        cloud_config,
        "console=hvc0",
        "---",
        "ipv6.disable=1",
    ]


def _opensuse_handoff(manifest: Manifest, profile: InstallerProfile) -> list[str]:
    """Return the linuxrc arguments that iso-chain-launch.sh opensuse_command_line emits."""
    network = manifest.network
    ifcfg = ",".join((f"{network.mac}={network.address}", network.routes[0][1], *network.dns))
    return [
        f"ifcfg={ifcfg}",
        f"hostname={manifest.lpar}",
        f"install={manifest.source}{profile.repository.path}",
        "textmode=1",
        "self_update=0",
        "console=hvc0",
        "ipv6.disable=1",
    ]


def _volume_id(digest: str) -> str:
    # Anaconda's bare inst.ks=cdrom:<path> takes the first optical drive holding <path>; the
    # launcher names this label instead. Among built ISOs, equal labels imply equal configs.
    return "ISO_CHAIN_" + digest[:16].upper()


# powerpc-ieee1275 GRUB has no chainloader, so an installed disk boots through its own grub.cfg.
# grubenv marks an installed GRUB directory; the launcher ISO carries none (ADR 0018).
INSTALLED_DISK_MENU = """\
for iso_chain_directory in /grub2 /boot/grub2 /grub /boot/grub; do
    if [ -z "$iso_chain_disk" ]; then
        if search --no-floppy --file --set=iso_chain_disk $iso_chain_directory/grubenv; then
            set iso_chain_config=$iso_chain_directory/grub.cfg
        fi
    fi
done
if [ -n "$iso_chain_disk" ]; then
    set default=installed_disk
    menuentry 'installed disk' --id installed_disk {
        echo 'ISO_CHAIN: GRUB installed-disk handoff'
        configfile ($iso_chain_disk)$iso_chain_config
    }
fi
"""


# An unattended Ubuntu install creates grubenv before its user exists; the template's late command
# then sets this marker, so an interrupted install never becomes the default (ADR 0020).
UBUNTU_COMPLETION_MENU = INSTALLED_DISK_MENU.replace(
    "            set iso_chain_config=$iso_chain_directory/grub.cfg\n",
    "            set iso_chain_config=$iso_chain_directory/grub.cfg\n"
    "            set iso_chain_env=$iso_chain_directory/grubenv\n",
).replace(
    "done\n",
    "done\n"
    'if [ -n "$iso_chain_disk" ]; then\n'
    "    load_env --file ($iso_chain_disk)$iso_chain_env iso_chain_installed\n"
    '    if [ "$iso_chain_installed" != 1 ]; then\n'
    "        unset iso_chain_disk\n"
    "    fi\n"
    "fi\n",
)


def _grub_config(manifest: Manifest, digest: str) -> str:
    # After a PowerVM CAS reboot, Fedora's GRUB replays the last entry's source from a
    # 1,024-byte buffer and double-frees anything longer, so the arguments live outside it.
    variables = []
    entries = []
    for index, (profile, _) in enumerate(manifest.profiles):
        arguments = " ".join(_kernel_arguments(manifest, digest, profile))
        variables.append(f"set iso_chain_args_{index}='{arguments}'\n")
        entries.append(
            f"menuentry '{profile}' --id '{profile}' {{\n"
            "    echo 'ISO_CHAIN: GRUB optical handoff'\n"
            f"    linux /boot/vmlinuz $iso_chain_args_{index}\n"
            "    initrd /boot/initramfs.img\n"
            "}\n"
        )
    header = f'set timeout=5\nset default="{manifest.selected_profile}"\n'
    menu = INSTALLED_DISK_MENU
    if _profile_user_data(manifest, manifest.selected_profile) is not None:
        menu = UBUNTU_COMPLETION_MENU
    return header + "".join(variables) + menu + "".join(entries)


def _stage_profile_artifacts(manifest: Manifest, profiles: Path, stage: Path) -> None:
    root = _path(profiles, "profile artifact directory", "directory")
    # cloud-init's NoCloud reads user-data and meta-data from the volume root (ADR 0020).
    user_data = _profile_user_data(manifest, manifest.selected_profile)
    if user_data is not None:
        (stage / "user-data").write_bytes(user_data)
        (stage / "meta-data").write_bytes(b"")
    for name, _ in manifest.profiles:
        kickstart = _profile_kickstart(manifest, name)
        if kickstart is None:
            continue
        artifact, rendered = kickstart
        target = stage / artifact.path.lstrip("/")
        if target.exists():
            continue
        if rendered is not None:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(rendered)
            continue
        source = _regular_file(root / artifact.path.lstrip("/"), "profile Kickstart")
        target.parent.mkdir(parents=True, exist_ok=True)
        if _copy_with_sha256(source, target, artifact.size, "profile Kickstart") != artifact.sha256:
            raise ValidationError("profile Kickstart does not match the manifest")


def media_result(
    manifest: Manifest, manifest_sha256: str, iso_sha256: str, iso_size: int, url: str | None
) -> bytes:
    """Return the canonical iso-chain-media-v1 producer result line (ADR 0015)."""
    # The result names one profile, so the menu must offer no other.
    if len(manifest.profiles) != 1:
        _manifest_error("profiles", "a producer result needs exactly one profile")
    profile = manifest.profile(manifest.selected_profile)
    network = _manifest_data(manifest)["network"]
    del network["mac"]
    result: dict[str, object] = {
        "format": MEDIA_FORMAT,
        "iso_sha256": iso_sha256,
        "iso_size": iso_size,
        "manifest_sha256": manifest_sha256,
        "distribution": profile.distribution,
        "release": profile.release,
        "architecture": "ppc64le",
        "mac": manifest.network.mac,
        "network": network,
    }
    if manifest.operation_binding is not None:
        result["operation_binding"] = manifest.operation_binding
    if url is not None:
        result["url"] = url
    encoded = json.dumps(result, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    if len(encoded) > MAX_RESULT_BYTES:
        raise ValidationError("producer result exceeds 64 KiB")
    return encoded


def _build_manifest(args: argparse.Namespace) -> tuple[Manifest, bytes, str]:
    if (args.config is None) == (args.target is None) or (args.target is None) != (
        args.base_config is None
    ):
        raise ValidationError("give either --config or both --target and --base-config")
    if (args.output is None) == (args.publish_dir is None) or (args.publish_dir is None) != (
        args.publish_url is None
    ):
        raise ValidationError("give either --output or both --publish-dir and --publish-url")
    if args.config is not None:
        loaded = load_manifest(Path(args.config))
    else:
        loaded = load_manifest_bytes(
            compose_target_manifest(Path(args.target), Path(args.base_config))
        )
    # Only the Rocky Kickstart and the Ubuntu user data render the values; others would silently
    # omit them (ADR 0017). One menu serves every profile, and the Ubuntu completion marker
    # governs it, so the two cannot share an ISO (ADR 0020).
    distributions = {profile.distribution for _, profile in loaded[0].profiles}
    if loaded[0].login_user is not None and distributions not in ({"rocky"}, {"ubuntu"}):
        raise ValidationError(
            "login_user and ssh_authorized_keys: every profile must be rocky, or every profile "
            "ubuntu (ADR 0017, ADR 0019, ADR 0020)"
        )
    # Render now so container-build refuses an unrenderable value before the engine runs.
    if loaded[0].login_user is not None:
        (_rocky_kickstart if distributions == {"rocky"} else _ubuntu_user_data)(loaded[0])
    # Built media is bound and published; prepared media is neither (hmc-mcp ADR 0191).
    if (loaded[0].operation_binding is None) != (args.publish_dir is None):
        raise ValidationError(
            "operation_binding requires --publish-dir, and a published ISO requires "
            "operation_binding"
        )
    if args.publish_dir is not None and len(loaded[0].profiles) != 1:
        raise ValidationError("a published ISO must carry exactly one profile")
    return loaded


def build_iso(args: argparse.Namespace) -> bytes:
    manifest, canonical, digest = _build_manifest(args)
    if args.publish_dir is None:
        url_base = None
        output = Path(args.output).absolute()
        parent = _path(output.parent, "output parent", "directory")
        if output.exists():
            raise ValidationError(f"output already exists: {output}")
    else:
        url_base = _validate_source(args.publish_url, "publish_url")
        parent = _path(args.publish_dir, "publish directory", "directory")

    modules = _path(args.grub_modules, "GRUB module path", "directory")
    kernel = _path(args.kernel, "kernel", "file")
    initramfs = _path(args.initramfs, "initramfs", "file")
    profiles = _path(Path(args.profiles), "profile artifact directory", "directory")
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
        _stage_profile_artifacts(manifest, profiles, stage)
        temporary_iso = workspace / "experiment.iso"
        subprocess.run(
            [
                "grub2-mkrescue",
                "-d",
                str(modules),
                "-o",
                str(temporary_iso),
                str(stage),
                "--",
                "-volid",
                _volume_id(digest),
            ],
            check=True,
            stdout=sys.stderr,
        )
        if not temporary_iso.is_file():
            raise ValidationError("grub2-mkrescue did not create an ISO")
        iso_sha256 = _file_sha256(temporary_iso)
        iso_size = temporary_iso.stat().st_size
        if url_base is not None:
            output = parent / f"{iso_sha256}.iso"
        try:
            os.link(temporary_iso, output)
        except FileExistsError as error:
            raise ValidationError("output appeared during build") from error
    if len(manifest.profiles) != 1:
        return b""
    url = None if url_base is None else f"{url_base}/{output.name}"
    return media_result(manifest, digest, iso_sha256, iso_size, url)


def _container_engine(requested: str | None) -> str:
    considered = CONTAINER_ENGINES if requested is None else (requested,)
    for name in considered:
        resolved = shutil.which(name)
        if resolved is not None:
            return resolved
    raise ValidationError(
        "container engine is unavailable: "
        + ("install podman or docker" if requested is None else requested)
    )


def container_build_command(args: argparse.Namespace, engine: str) -> list[str]:
    _build_manifest(args)
    repository = _path(REPOSITORY_ROOT, "repository root", "directory")
    if args.config is not None:
        inputs = [("--config", _path(Path(args.config), "manifest", "file"))]
    else:
        inputs = [
            ("--target", _path(Path(args.target), "target request", "file")),
            ("--base-config", _path(Path(args.base_config), "base manifest", "file")),
        ]
    kernel = _path(Path(args.kernel), "kernel", "file")
    initramfs = _path(Path(args.initramfs), "Fedora initramfs", "file")
    profiles = _path(Path(args.profiles), "profile artifact directory", "directory")
    if args.publish_dir is None:
        output = Path(args.output)
        parent = _path(output.parent, "output parent", "directory")
        output = parent / output.name
        if output.exists():
            raise ValidationError(f"output already exists: {output}")
        outputs = [("--output", str(output))]
    else:
        _validate_source(args.publish_url, "publish_url")
        parent = _path(Path(args.publish_dir), "publish directory", "directory")
        outputs = [("--publish-dir", str(parent)), ("--publish-url", args.publish_url)]
    if parent == Path("/"):
        raise ValidationError("container mount source must not be the filesystem root")
    if parent == repository:
        raise ValidationError(
            f"output directory must not be the repository root, whose mount would then be "
            f"writable: {parent}"
        )
    sources = [
        (repository, False),
        *((path.parent, False) for _, path in inputs),
        (kernel.parent, False),
        (initramfs.parent, False),
        (parent, True),
        (profiles, False),
    ]
    if args.grub_modules is not None:
        modules = _path(args.grub_modules, "GRUB module path", "directory")
        sources.append((modules, False))
        module_argument = str(modules)
    else:
        module_argument = CONTAINER_MODULE_DIRECTORY
    directories: dict[Path, bool] = {}
    for source, writable in sources:
        if source == Path("/"):
            raise ValidationError("container mount source must not be the filesystem root")
        if "," in str(source):
            raise ValidationError("container mount source cannot contain a comma")
        directories[source] = directories.get(source, False) or writable
    command = [engine, "run", "--rm"]
    for source, writable in directories.items():
        options = f"type=bind,source={source},target={source}"
        if not writable:
            options += ",readonly"
        command.extend(["--mount", options])
    command.extend(
        [
            args.image,
            CONTAINER_PYTHON,
            str(repository / "scripts/iso_chain.py"),
            "build",
            "--grub-modules",
            module_argument,
            "--kernel",
            str(kernel),
            "--initramfs",
            str(initramfs),
            "--profiles",
            str(profiles),
            *(token for flag, path in inputs for token in (flag, str(path))),
            *(token for pair in outputs for token in pair),
        ]
    )
    return command


def _require_container_image(
    engine: str, image: str, containerfile: str, platform_name: str | None
) -> None:
    inspected = subprocess.run(
        [engine, "image", "inspect", image], check=False, capture_output=True
    )
    if inspected.returncode != 0:
        lines = [
            line.strip()
            for line in inspected.stderr.decode(errors="replace").splitlines()
            if line.strip()
        ]
        detail = f": {lines[-1]}" if lines else ""
        platform_option = f"--platform {platform_name} " if platform_name else ""
        raise ValidationError(
            f"container image {image} is unavailable{detail}; build it with: {engine} build "
            f"{platform_option}--file {containerfile} --tag {image} ."
        )


def container_build(args: argparse.Namespace) -> None:
    engine = _container_engine(args.engine)
    command = container_build_command(args, engine)
    _require_container_image(engine, args.image, "Containerfile", None)
    os.execvp(engine, command)


def container_prepare_initramfs_command(args: argparse.Namespace, engine: str) -> list[str]:
    repository = _path(REPOSITORY_ROOT, "repository root", "directory")
    output = _path(Path(args.output_dir).absolute(), "output directory", "directory")
    if output == repository:
        raise ValidationError("output directory must not be the repository root")
    for source in (repository, output):
        if source == Path("/") or "," in str(source):
            raise ValidationError(f"container mount source is not supported: {source}")
    for name in ("vmlinuz", "initramfs.img"):
        if os.path.lexists(output / name):
            raise ValidationError(f"output already exists: {output / name}")
    return [
        engine,
        "run",
        "--rm",
        "--platform",
        "linux/ppc64le",
        "--mount",
        f"type=bind,source={repository},target={repository},readonly",
        "--mount",
        f"type=bind,source={output},target={output}",
        args.image,
        "/bin/sh",
        "-euc",
        CONTAINER_INITRAMFS_SCRIPT,
        "iso-chain",
        str(repository),
        str(output),
    ]


def container_prepare_initramfs(args: argparse.Namespace) -> None:
    engine = _container_engine(args.engine)
    command = container_prepare_initramfs_command(args, engine)
    _require_container_image(engine, args.image, "Containerfile.initramfs", "linux/ppc64le")
    os.execvp(engine, command)


def _embedded_manifest(path: Path) -> tuple[Path, tuple[Manifest, bytes, str]]:
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
        return iso, load_manifest(extracted)


def inspect_iso(path: Path) -> bytes:
    _, (_, canonical, _) = _embedded_manifest(path)
    return canonical


def inspect_result(path: Path) -> bytes:
    """Return the prepared-mode producer result for an existing ISO (ADR 0015)."""
    iso, (manifest, _, digest) = _embedded_manifest(path)
    if manifest.operation_binding is not None:
        _manifest_error("operation_binding", "is bound; inspect reports prepared media only")
    return media_result(manifest, digest, _file_sha256(iso), iso.stat().st_size, None)


def _bounded_file(path: Path, label: str, maximum: int) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    except OSError as error:
        if error.errno == errno.ELOOP:
            raise ValidationError(f"{label}: must be a regular file") from error
        raise ValidationError(f"{label}: unavailable") from error
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValidationError(f"{label}: must be a regular file")
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            descriptor = -1
            content = stream.read(maximum + 1)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(content) > maximum:
        raise ValidationError(f"{label}: exceeds {maximum // 1024} KiB")
    return content


def _treeinfo_images(
    tree: Path,
    iso_digest: str,
    label: str,
    identity: tuple[str, str, str],
    variants: tuple[str, ...],
    appstream: str | None = None,
) -> tuple[tuple[str, str], ...]:
    """Return each (ISO path, SHA-256) the tree's .treeinfo binds to the boot ISO."""
    encoded = _bounded_file(tree / ".treeinfo", label, MAX_TREEINFO_BYTES)
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str  # checksum keys are case-sensitive paths
    try:
        parser.read_string(encoded.decode("utf-8"))
        found = tuple(parser["general"][name] for name in ("family", "version", "arch"))
        variant = parser["general"]["variant"]
        values = (parser["images-ppc64le"]["kernel"], parser["images-ppc64le"]["initrd"])
        checksums = [parser["checksums"][value] for value in ("images/boot.iso", *values)]
    except (UnicodeDecodeError, configparser.Error, KeyError) as error:
        raise ValidationError(f"{label}: missing or malformed metadata") from error
    if found != identity or variant not in variants:
        expected = " ".join(identity) + " " + " or ".join(variants)
        raise ValidationError(f"{label}: expected {expected}")
    # Anaconda adds the AppStream variant from this relative path (ADR 0013).
    found_appstream = parser.get("variant-AppStream", "repository", fallback=None)
    if appstream is not None and found_appstream not in (appstream, appstream + "/"):
        raise ValidationError(f"{label}: AppStream is not the sibling repository")
    digests = []
    for checksum in checksums:
        kind, _, digest = checksum.partition(":")
        if kind != "sha256" or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ValidationError(f"{label}: checksum entries must be SHA-256")
        digests.append(digest)
    if digests[0] != iso_digest:
        raise ValidationError(f"{label}: images/boot.iso does not match the netinst ISO")
    for value in values:
        if URI_PATH.fullmatch("/" + value) is None or any(
            part in ("", ".", "..") for part in value.split("/")
        ):
            raise ValidationError(f"{label}: contains a noncanonical path")
    return tuple(zip(values, digests[1:], strict=True))


def _artifact_data(path: Path, url_path: str | None, maximum: int) -> dict[str, object]:
    regular = _regular_file(path, "prepared artifact")
    size = regular.stat().st_size
    if not 1 <= size <= maximum:
        raise ValidationError("prepared artifact: invalid size")
    result: dict[str, object] = {"size": size, "sha256": _file_sha256(regular)}
    if url_path is not None:
        result["path"] = url_path
    return result


def _publish_directory(source: Path, destination: Path) -> None:
    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        publish = getattr(library, "renamex_np", None)
        arguments: tuple[object, ...] = (
            os.fsencode(source),
            os.fsencode(destination),
            RENAME_EXCL,
        )
        argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
    else:
        publish = getattr(library, "renameat2", None)
        arguments = (
            AT_FDCWD,
            os.fsencode(source),
            AT_FDCWD,
            os.fsencode(destination),
            RENAME_NOREPLACE,
        )
        argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
    if publish is None:
        raise ValidationError("no-replace directory publication is unsupported")
    publish.argtypes = argtypes
    publish.restype = ctypes.c_int
    if publish(*arguments) == 0:
        return
    failure = ctypes.get_errno()
    if failure == errno.EEXIST:
        raise ValidationError("output appeared during source preparation")
    if failure in (errno.ENOSYS, errno.EINVAL, errno.ENOTSUP):
        raise ValidationError("no-replace directory publication is unsupported")
    raise OSError(failure, os.strerror(failure), destination)


def _extract_treeinfo_images(
    iso: Path,
    expected_digest: str,
    images: tuple[tuple[str, str], ...],
    repository_path: str,
    work: Path,
    label: str,
) -> list[dict[str, object]]:
    """Copy the boot ISO, check its digest, and pin each image it holds against .treeinfo."""
    verified_iso = work / "source.iso"
    copied = _copy_with_sha256(
        iso, verified_iso, MAX_INSTALLER_ISO_BYTES, f"{label} ISO", exact=False
    )
    if copied != expected_digest:
        raise ValidationError(f"{label} ISO digest does not match")
    extracted = []
    for index, (iso_path, digest) in enumerate(images):
        target = work / f"image-{index}"
        subprocess.run(
            [
                "xorriso",
                "-osirrox",
                "on",
                "-indev",
                str(verified_iso),
                "-extract",
                "/" + iso_path,
                str(target),
            ],
            check=True,
        )
        if _file_sha256(_regular_file(target, f"extracted {label} image")) != digest:
            raise ValidationError(f"extracted {label} image does not match .treeinfo")
        extracted.append(_artifact_data(target, f"{repository_path}/{iso_path}", 2**31))
    return extracted


def prepare_fedora_source(args: argparse.Namespace) -> None:
    iso = _regular_file(Path(args.iso).absolute(), "Fedora ISO")
    tree = _path(Path(args.tree).absolute(), "Fedora tree", "directory")
    kickstart = _bounded_file(Path(args.kickstart).absolute(), "Kickstart", MAX_KICKSTART_BYTES)
    if not kickstart:
        raise ValidationError("Kickstart: must not be empty")
    expected_digest = _sha256(args.iso_sha256, "ISO digest")
    repository_path = _url_path(args.repository_path, "repository path")
    memory = _integer(args.minimum_memory_mib, "minimum memory", 1, 65536)
    images = _treeinfo_images(
        tree, expected_digest, "Fedora treeinfo", ("Fedora", "44", "ppc64le"), FEDORA_VARIANTS
    )
    repomd = _regular_file(tree / "repodata/repomd.xml", "Fedora repository metadata")
    output = Path(args.output).absolute()
    parent = _path(output.parent, "output parent", "directory")
    if os.path.lexists(output):
        raise ValidationError("Fedora source output already exists")
    with tempfile.TemporaryDirectory(prefix=".iso-chain-fedora-", dir=parent) as temporary:
        work = Path(temporary)
        kernel, initramfs = _extract_treeinfo_images(
            iso, expected_digest, images, repository_path, work, "Fedora"
        )
        published = work / "tree"
        profile_root = published / "profiles/fedora-44"
        profile_root.mkdir(parents=True)
        prepared_kickstart = profile_root / "ks.cfg"
        prepared_kickstart.write_bytes(kickstart)
        prepared_kickstart.chmod(0o600)
        profile = {
            "distribution": "fedora",
            "release": "44",
            "kernel": kernel,
            "initramfs": initramfs,
            "repository": {
                "path": repository_path,
                "treeinfo": _artifact_data(tree / ".treeinfo", None, 2**20),
                "repomd": _artifact_data(repomd, None, 2**20),
            },
            "kickstart": _artifact_data(
                prepared_kickstart, "/profiles/fedora-44/ks.cfg", MAX_KICKSTART_BYTES
            ),
            "minimum_memory_mib": memory,
        }
        _installer_profile(profile, "profile")
        (published / "profile.json").write_bytes(
            json.dumps(profile, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        )
        _publish_directory(published, output)


def prepare_rocky_source(args: argparse.Namespace) -> None:
    iso = _regular_file(Path(args.iso).absolute(), "Rocky ISO")
    tree = _path(Path(args.tree).absolute(), "Rocky tree", "directory")
    expected_digest = _sha256(args.iso_sha256, "ISO digest")
    repository_path = _url_path(args.repository_path, "repository path")
    if not repository_path.endswith(ROCKY_REPOSITORY_SUFFIX):
        raise ValidationError(f"repository path: must end in {ROCKY_REPOSITORY_SUFFIX}")
    memory = _integer(args.minimum_memory_mib, "minimum memory", 1, 65536)
    images = _treeinfo_images(
        tree,
        expected_digest,
        "Rocky treeinfo",
        ("Rocky Linux", "9.8", "ppc64le"),
        ("BaseOS",),
        appstream="../../../AppStream/ppc64le/os",
    )
    repomd = _regular_file(tree / "repodata/repomd.xml", "Rocky repository metadata")
    output = Path(args.output).absolute()
    parent = _path(output.parent, "output parent", "directory")
    if os.path.lexists(output):
        raise ValidationError("Rocky source output already exists")
    with tempfile.TemporaryDirectory(prefix=".iso-chain-rocky-", dir=parent) as temporary:
        work = Path(temporary)
        kernel, initramfs = _extract_treeinfo_images(
            iso, expected_digest, images, repository_path, work, "Rocky"
        )
        published = work / "tree"
        published.mkdir()
        profile = {
            "distribution": "rocky",
            "release": "9.8",
            "kernel": kernel,
            "initramfs": initramfs,
            "repository": {
                "path": repository_path,
                "treeinfo": _artifact_data(tree / ".treeinfo", None, 2**20),
                "repomd": _artifact_data(repomd, None, 2**20),
            },
            "minimum_memory_mib": memory,
        }
        _installer_profile(profile, "profile")
        (published / "profile.json").write_bytes(
            json.dumps(profile, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        )
        _publish_directory(published, output)


def _opensuse_checksums(path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    text = _bounded_file(path, "openSUSE CHECKSUMS", 2**20).decode("utf-8", errors="replace")
    for line in text.splitlines():
        if not line:
            continue
        match = re.fullmatch(r"([0-9a-f]{64})  (\S+)", line)
        if match is None or match[2] in entries:
            raise ValidationError("openSUSE CHECKSUMS: malformed or repeated entry")
        entries[match[2]] = match[1]
    if not all(relative in entries for relative in OPENSUSE_ENTRIES):
        raise ValidationError("openSUSE CHECKSUMS: missing a boot or product entry")
    return entries


def prepare_opensuse_source(args: argparse.Namespace) -> None:
    checksums = _regular_file(Path(args.checksums).absolute(), "openSUSE CHECKSUMS")
    tree = _path(Path(args.tree).absolute(), "openSUSE tree", "directory")
    repository_path = _url_path(args.repository_path, "repository path")
    memory = _integer(args.minimum_memory_mib, "minimum memory", 1, 65536)
    output = Path(args.output).absolute()
    parent = _path(output.parent, "output parent", "directory")
    if os.path.lexists(output):
        raise ValidationError("openSUSE source output already exists")
    entries = _opensuse_checksums(checksums)
    products = _bounded_file(tree / "media.1/products", "openSUSE tree media.1/products", 4096)
    if (
        hashlib.sha256(products).hexdigest() != entries["media.1/products"]
        or products != OPENSUSE_PRODUCTS
    ):
        raise ValidationError("openSUSE tree: not the Leap 15.6 repository")
    artifacts = {}
    for name, relative in (("kernel", OPENSUSE_ENTRIES[0]), ("initramfs", OPENSUSE_ENTRIES[1])):
        path = _regular_file(tree / relative, f"openSUSE tree {relative}")
        artifact = _artifact_data(path, f"{repository_path}/{relative}", 2**31)
        if artifact["sha256"] != entries[relative]:
            raise ValidationError(f"openSUSE tree: {relative} does not match CHECKSUMS")
        artifacts[name] = artifact
    profile = {
        "distribution": "opensuse",
        "release": "15.6",
        **artifacts,
        "repository": {"path": repository_path},
        "minimum_memory_mib": memory,
    }
    _installer_profile(profile, "profile")
    with tempfile.TemporaryDirectory(prefix=".iso-chain-opensuse-", dir=parent) as temporary:
        published = Path(temporary) / "tree"
        published.mkdir()
        (published / "profile.json").write_bytes(
            json.dumps(profile, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        )
        _publish_directory(published, output)


def prepare_ubuntu_source(args: argparse.Namespace) -> None:
    iso = _regular_file(Path(args.iso).absolute(), "Ubuntu ISO")
    expected_digest = _sha256(args.iso_sha256, "ISO digest")
    release_path = _url_path(args.release_path, "release path")
    memory = _integer(args.minimum_memory_mib, "minimum memory", 1, 65536)
    output = Path(args.output).absolute()
    parent = _path(output.parent, "output parent", "directory")
    if os.path.lexists(output):
        raise ValidationError("Ubuntu source output already exists")
    with tempfile.TemporaryDirectory(prefix=".iso-chain-ubuntu-", dir=parent) as temporary:
        work = Path(temporary)
        verified_iso = work / "source.iso"
        copied = _copy_with_sha256(
            iso, verified_iso, MAX_INSTALLER_ISO_BYTES, "Ubuntu ISO", exact=False
        )
        if copied != expected_digest:
            raise ValidationError("Ubuntu ISO digest does not match")
        members = (
            ("/.disk/info", "info"),
            ("/casper/vmlinux", "kernel"),
            ("/casper/initrd", "initramfs"),
        )
        for member, name in members:
            subprocess.run(
                [
                    "xorriso",
                    "-osirrox",
                    "on",
                    "-indev",
                    str(verified_iso),
                    "-extract",
                    member,
                    str(work / name),
                ],
                check=True,
            )
        info = _bounded_file(work / "info", "Ubuntu .disk/info", MAX_DISK_INFO_BYTES)
        text = info.decode("utf-8", errors="replace")
        if not text.startswith("Ubuntu-Server 26.04.1 LTS ") or " - Release ppc64el " not in text:
            raise ValidationError("Ubuntu ISO is not the 26.04.1 ppc64el live server")
        netboot = f"{release_path}/netboot/ppc64el"
        profile = {
            "distribution": "ubuntu",
            "release": "26.04.1",
            "kernel": _artifact_data(work / "kernel", f"{netboot}/linux", 2**31),
            "initramfs": _artifact_data(work / "initramfs", f"{netboot}/initrd", 2**31),
            "live_iso": {
                "path": f"{release_path}/{UBUNTU_ISO_NAME}",
                "size": verified_iso.stat().st_size,
                "sha256": expected_digest,
            },
            "minimum_memory_mib": memory,
        }
        _installer_profile(profile, "profile")
        published = work / "tree"
        (published / "netboot/ppc64el").mkdir(parents=True)
        os.link(work / "kernel", published / "netboot/ppc64el/linux")
        os.link(work / "initramfs", published / "netboot/ppc64el/initrd")
        (published / "profile.json").write_bytes(
            json.dumps(profile, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        )
        _publish_directory(published, output)


class SourceRequestHandler(http.server.SimpleHTTPRequestHandler):
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


class SourceHTTPServer(http.server.HTTPServer):
    def server_close(self) -> None:
        if hasattr(self, "access_stream") and not self.access_stream.closed:
            self.access_stream.close()
        super().server_close()


def _source_server(
    directory: Path, bind: str, port: int, access_log: Path
) -> http.server.HTTPServer:
    root = _path(directory, "source tree", "directory")
    _ipv4_address(bind, "server bind address")
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValidationError("server port must be from 0 through 65535")
    log = Path(access_log).absolute()
    _path(log.parent, "access log parent", "directory")
    if os.path.lexists(log):
        raise ValidationError("access log already exists")
    handler = functools.partial(SourceRequestHandler, directory=str(root))
    server = SourceHTTPServer((bind, port), handler)
    try:
        descriptor = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError:
        server.server_close()
        raise ValidationError("access log could not be created without replacement") from None
    server.access_stream = os.fdopen(descriptor, "w", encoding="utf-8")
    server.request_index = 0
    return server


def serve_source(args: argparse.Namespace) -> None:
    if not 1 <= args.port <= 65535:
        raise ValidationError("server port must be from 1 through 65535")
    server = _source_server(args.directory, args.bind, args.port, args.access_log)
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
    result = [
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
    for bundle in CA_BUNDLE_CANDIDATES:
        if bundle.is_file():
            result[result.index("--force-drivers") : result.index("--force-drivers")] = [
                "--include",
                str(bundle),
                "/etc/ssl/certs/ca-certificates.crt",
            ]
            break
    return result


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
    if not any(bundle.is_file() for bundle in CA_BUNDLE_CANDIDATES):
        raise ValidationError("a system CA bundle is required for HTTPS sources")
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
        "-nographic",
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
    marker = re.compile(r"installed-boot: passed boot_id=" + BOOT_ID)
    visible = [
        SERVICE_PREFIX.sub("", ANSI_ESCAPE.sub("", line).strip(), count=1)
        for line in encoded.decode(errors="replace").splitlines()
    ]
    matches = [match for line in visible if (match := marker.fullmatch(line))]
    if len(matches) != 1:
        raise ValidationError("boot console requires one canonical installed-boot marker")
    boot_id = matches[0].group(1).lower()
    try:
        if str(uuid.UUID(boot_id)) != boot_id:
            raise ValueError
    except ValueError as error:
        raise ValidationError("boot console contains a malformed boot ID") from error
    return boot_id


def _copy_bounded_stream(
    source,
    destination: Path,
    maximum: int,
    label: str,
    until: bytes | None = None,
    seen: threading.Event | None = None,
) -> None:
    """Copy at most ``maximum`` bytes; set ``seen`` once ``until`` has been copied."""
    copied = 0
    window = b""
    read_available = getattr(source, "read1", source.read)
    with destination.open("xb", buffering=0) as output:
        destination.chmod(0o600)
        while block := read_available(64 * 1024):
            remaining = maximum - copied
            output.write(block[:remaining])
            copied += min(len(block), remaining)
            if len(block) > remaining:
                raise ValidationError(f"{label} exceeds its byte limit")
            if until is not None and seen is not None:
                window = window[-len(until) :] + block
                if until in window:
                    seen.set()


def _wait_or_stop(process: subprocess.Popen, timeout: int, seen: threading.Event) -> int | None:
    """Return QEMU's exit status, or None once ``seen`` is set; raise at ``timeout``."""
    deadline = time.monotonic() + timeout
    while not seen.is_set():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(process.args, timeout)
        try:
            return process.wait(timeout=min(remaining, 1))
        except subprocess.TimeoutExpired:
            continue
    return None


def _run_qemu_phase(
    command: list[str],
    log: Path,
    timeout: int,
    capture_fifo: Path | None = None,
    capture: Path | None = None,
    until: bytes | None = None,
) -> int:
    """Run one QEMU phase; with ``until``, stop QEMU once the console shows it and return 0."""
    if (capture_fifo is None) != (capture is None):
        raise ValidationError("capture paths must be supplied together")
    errors: list[Exception] = []
    seen = threading.Event()
    process_box: list[subprocess.Popen] = []
    threads: list[threading.Thread] = []

    def copy(source, destination: Path, maximum: int, label: str, *marker) -> None:
        try:
            with source:
                _copy_bounded_stream(source, destination, maximum, label, *marker)
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
            args=(process.stdout, log, MAX_LOG_BYTES, "console log", until, seen),
            daemon=True,
        )
        console_thread.start()
        threads.append(console_thread)
        timed_out = False
        try:
            if until is None:
                status = process.wait(timeout=timeout)
            else:
                status = _wait_or_stop(process, timeout, seen)
        except subprocess.TimeoutExpired:
            timed_out = True
            status = None
        stopped = status is None and not timed_out
        if status is None:
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
        if stopped:
            return 0
        if status != 0:
            raise ValidationError("QEMU phase failed")
        if until is not None:
            raise ValidationError("QEMU phase ended before its console marker")
        return status
    finally:
        if capture_fifo is not None:
            capture_fifo.unlink(missing_ok=True)


@dataclass(frozen=True)
class InstallRun:
    iso: Path
    output: Path
    parent: Path
    disk_size: int
    memory: int
    install_timeout: int
    boot_timeout: int


def _install_run(args: argparse.Namespace, captures: int) -> InstallRun:
    """Validate an install harness's inputs before any external command runs."""
    iso = _regular_file(Path(args.iso).absolute(), "launcher ISO")
    output = Path(args.output).absolute()
    parent = _path(output.parent, "output parent", "directory")
    if os.path.lexists(output):
        raise ValidationError("installation output already exists")
    run = InstallRun(
        iso,
        output,
        parent,
        _integer(args.disk_size_gib, "disk size", 8, 256),
        _integer(args.memory_mib, "QEMU memory", 1024, 65536),
        _integer(args.install_timeout_seconds, "install timeout", 1, 86400),
        _integer(args.boot_timeout_seconds, "boot timeout", 1, 86400),
    )
    if shutil.disk_usage(parent).free < captures * MAX_INSTALL_CAPTURE_BYTES:
        raise ValidationError("output parent lacks install capture capacity")
    return run


def _fresh_disk(disk: Path, size_gib: int) -> str:
    """Create a standalone qcow2 disk and return its SHA-256."""
    try:
        subprocess.run(
            ["qemu-img", "create", "-f", "qcow2", str(disk), f"{size_gib}G"],
            check=True,
            capture_output=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ValidationError("standalone disk creation failed") from error
    disk.chmod(0o600)
    return _file_sha256(disk)


def _publish_install(staged: Path, output: Path, result: dict[str, object]) -> None:
    result_path = staged / "result.json"
    result_path.write_bytes(
        json.dumps(result, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    )
    result_path.chmod(0o600)
    _publish_directory(staged, output)


def install_fedora(args: argparse.Namespace) -> None:
    manifest = load_manifest(args.config)[0]
    if manifest.profile(manifest.selected_profile).distribution != "fedora":
        raise ValidationError("install-fedora requires a selected Fedora profile")
    run = _install_run(args, 1)
    with tempfile.TemporaryDirectory(prefix=".iso-chain-install-", dir=run.parent) as temporary:
        root = Path(temporary)
        root.chmod(0o700)
        staged = root / "result"
        staged.mkdir(mode=0o700)
        disk = staged / "disk.qcow2"
        before = _fresh_disk(disk, run.disk_size)
        install_log = staged / "install-console.log"
        boot_log = staged / "boot-console.log"
        capture = staged / "install.pcap"
        capture_fifo = root / "install-capture.pipe"
        install_command, boot_command = install_qemu_commands(
            run.iso, disk, manifest, capture_fifo, run.memory
        )
        install_status = _run_qemu_phase(
            install_command, install_log, run.install_timeout, capture_fifo, capture
        )
        boot_status = _run_qemu_phase(boot_command, boot_log, run.boot_timeout)
        _installed_boot_id(_bounded_file(boot_log, "boot console", MAX_LOG_BYTES))
        after = _file_sha256(disk)
        if disk.stat().st_size == 0 or before == after:
            raise ValidationError("standalone disk did not record installation changes")
        result = {
            "version": 1,
            "qemu_memory_mib": run.memory,
            "disk_size_gib": run.disk_size,
            "install_timeout_seconds": run.install_timeout,
            "boot_timeout_seconds": run.boot_timeout,
            "install_exit_status": install_status,
            "boot_exit_status": boot_status,
            "disk_sha256_before": before,
            "disk_sha256_after": after,
            "disk_bytes_after": disk.stat().st_size,
        }
        _publish_install(staged, run.output, result)


def install_rocky(args: argparse.Namespace) -> None:
    """Install unattended Rocky in QEMU, then boot the disk with the ISO attached (ADR 0019)."""
    _install_unattended(args, "rocky")


def install_ubuntu(args: argparse.Namespace) -> None:
    """Install unattended Ubuntu in QEMU, then boot the disk with the ISO attached (ADR 0020)."""
    _install_unattended(args, "ubuntu")


def _install_unattended(args: argparse.Namespace, distribution: str) -> None:
    manifest = load_manifest(args.config)[0]
    if (
        manifest.profile(manifest.selected_profile).distribution != distribution
        or manifest.login_user is None
    ):
        name = {"rocky": "Rocky", "ubuntu": "Ubuntu"}[distribution]
        raise ValidationError(
            f"install-{distribution} requires a selected {name} profile with login values"
        )
    run = _install_run(args, 2)
    with tempfile.TemporaryDirectory(prefix=".iso-chain-install-", dir=run.parent) as temporary:
        root = Path(temporary)
        root.chmod(0o700)
        staged = root / "result"
        staged.mkdir(mode=0o700)
        disk = staged / "disk.qcow2"
        before = _fresh_disk(disk, run.disk_size)
        phases = {}
        for phase in ("install", "boot"):
            fifo = root / f"{phase}-capture.pipe"
            command = install_qemu_commands(run.iso, disk, manifest, fifo, run.memory)[0]
            # -no-reboot turns the installer's reboot into QEMU's exit; the boot phase restarts
            # with the same ISO, disk, and NIC, as firmware would after a reset.
            phases[phase] = (command + ["-no-reboot"], staged / f"{phase}-console.log", fifo)
        command, log, fifo = phases["install"]
        install_status = _run_qemu_phase(
            command, log, run.install_timeout, fifo, staged / "install.pcap"
        )
        after, after_bytes = _file_sha256(disk), disk.stat().st_size
        if before == after:
            raise ValidationError("standalone disk did not record installation changes")
        command, log, fifo = phases["boot"]
        _run_qemu_phase(
            command,
            log,
            run.boot_timeout,
            fifo,
            staged / "boot.pcap",
            until=f"{manifest.lpar} login:".encode(),
        )
        result = {
            "version": 1,
            "qemu_memory_mib": run.memory,
            "disk_size_gib": run.disk_size,
            "install_timeout_seconds": run.install_timeout,
            "boot_timeout_seconds": run.boot_timeout,
            "install_exit_status": install_status,
            "boot_stop": "login-prompt",
            # The disk as the installer left it; the boot phase then writes its own state.
            "disk_sha256_before": before,
            "disk_sha256_after": after,
            "disk_bytes_after": after_bytes,
        }
        _publish_install(staged, run.output, result)


def _kernel_command_line(
    lines: list[str],
    first: int,
    end: int,
    prefixes: tuple[str, ...] | None,
    subject: str,
    caller_field: bool = False,
) -> tuple[int, list[str]]:
    # The openSUSE kernel prints a [ T<n>] or [ C<n>] caller field after the timestamp.
    caller = r"(?:\[\s*[TC]\d+\])?" if caller_field else ""
    pattern = re.compile(rf"\[\s*\d+\.\d+\]{caller} Kernel command line: (.*)")
    fragments = [
        (index, match.group(1).split())
        for index in range(first, end)
        if (match := pattern.fullmatch(lines[index]))
        and (
            prefixes is None
            or any(argument.startswith(prefixes) for argument in match.group(1).split())
        )
    ]
    if not fragments or any(
        fragments[index][0] != fragments[index - 1][0] + 1 for index in range(1, len(fragments))
    ):
        raise ValidationError(f"console log requires one contiguous {subject} kernel command line")
    arguments = []
    for index, (_, fragment) in enumerate(fragments):
        continued = index < len(fragments) - 1
        if continued and fragment and fragment[-1] == "\\":
            fragment = fragment[:-1]
        elif continued or fragment and fragment[-1] == "\\":
            message = "malformed" if continued else "incomplete"
            raise ValidationError(f"wrapped {subject} kernel command line is {message}")
        arguments.extend(fragment)
    return fragments[0][0], arguments


def _launcher_marker(lines: list[str], marker: str, after: int) -> int:
    if lines.count(marker) != 1 or lines.index(marker) <= after:
        raise ValidationError("missing, repeated, or reordered launcher evidence")
    return lines.index(marker)


def verify_launcher_log(log: Path, manifest: Manifest, expected_profile: str) -> tuple[str, ...]:
    profile = manifest.profile(expected_profile)
    # Only a Kickstart or user-data handoff reads the launcher media (ADR 0011, 0019, 0020).
    kickstart = _profile_kickstart(manifest, expected_profile)
    user_data = _profile_user_data(manifest, expected_profile)
    media = ("media: passed",) if kickstart is not None or user_data is not None else ()
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
            "media: failed",
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
    position, arguments = _kernel_command_line(
        lines, 0, start, ("iso_chain.", "ipv6.", "rd.systemd.unit="), "launcher"
    )
    digest = hashlib.sha256(_canonical_bytes(_manifest_data(manifest))).hexdigest()
    expected = _kernel_arguments(manifest, digest, expected_profile)
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
    for marker in (
        "disk: passed",
        *media,
        "artifacts: passed",
        "kexec-load: passed",
        "kexec-exec: started",
    ):
        position = _launcher_marker(visible, marker, position)
    opensuse = profile.distribution == "opensuse"
    _, installer = _kernel_command_line(
        lines, launcher_end, len(lines), None, "installer", caller_field=opensuse
    )
    if opensuse:
        _verify_opensuse_handoff(lines[launcher_end:], installer, manifest, profile)
        return _launcher_results(media)
    if profile.live_iso is not None:
        # The launcher emits the whole casper line, so an added url=, cloud-config-url=, or ds=
        # that would make cloud-init fetch or select a configuration differs from it.
        label = None if user_data is None else _volume_id(digest)
        handoff = [argument.replace('"', "") for argument in installer]
        if handoff != _ubuntu_handoff(manifest, profile, label):
            raise ValidationError("installer handoff evidence is missing, repeated, or different")
        return _launcher_results(media)
    # The kernel accepts a double-quoted parameter, so quotes cannot hide a key.
    keys = [argument.replace('"', "").split("=", 1)[0] for argument in installer]
    kickstarts = [arg for arg, key in zip(installer, keys, strict=True) if key in ("inst.ks", "ks")]
    if kickstart is not None:
        label = _volume_id(digest)
        expected_kickstarts = [f"inst.ks=cdrom:LABEL={label}:{kickstart[0].path}"]
    else:
        expected_kickstarts = []
    if kickstarts != expected_kickstarts:
        raise ValidationError("installer Kickstart evidence is missing, repeated, or different")
    # The Rocky Kickstart names no repository, so inst.repo alone decides the install source.
    if profile.distribution == "rocky":
        repositories = [arg for arg, key in zip(installer, keys, strict=True) if key == "inst.repo"]
        if repositories != [f"inst.repo={manifest.source}{profile.repository.path}"]:
            raise ValidationError(
                "installer repository evidence is missing, repeated, or different"
            )
    return _launcher_results(media)


def _verify_opensuse_handoff(
    lines: list[str], installer: list[str], manifest: Manifest, profile: InstallerProfile
) -> None:
    # linuxrc folds option case, ignores -, _, and . in keys, and has aliases such as repo and
    # insecure, so only a whole-line comparison keeps an added option from going unseen.
    if [argument.replace('"', "") for argument in installer] != _opensuse_handoff(
        manifest, profile
    ):
        raise ValidationError("installer handoff evidence is missing, repeated, or different")
    addresses = [index for index, line in enumerate(lines) if line == "IP addresses:"]
    address = str(ipaddress.IPv4Interface(manifest.network.address).ip)
    if len(addresses) != 1 or lines[addresses[0] + 1 : addresses[0] + 2] != [address]:
        raise ValidationError("installer network evidence is missing or different")


def _launcher_results(media: tuple[str, ...]) -> tuple[str, ...]:
    return (
        "configuration: passed",
        "adapter-match: passed",
        "profile: passed",
        "memory: passed",
        "disk: passed",
        *media,
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


def _access_records(encoded: bytes, allow_head: bool = False) -> list[dict[str, object]]:
    records = []
    fields = {"method", "path", "status", "bytes", "index"}
    methods = ("GET", "HEAD") if allow_head else ("GET",)
    for expected_index, line in enumerate(encoded.splitlines(keepends=True), 1):
        record = _evidence_json(line, fields, "access log record")
        if record["method"] not in methods:
            raise ValidationError("access log method is invalid")
        path = record["path"]
        if type(path) is not str:
            raise ValidationError("access log path is invalid")
        _url_path(path, "access log path")
        status = _evidence_integer(record["status"], "status", 100, 599)
        _evidence_integer(record["bytes"], "bytes", 0, MAX_INSTALLER_ISO_BYTES)
        if record["method"] == "HEAD":
            if status != 200 or record["bytes"] != 0:
                raise ValidationError("access log contains an invalid HEAD response")
        elif record["bytes"] == 0:
            raise ValidationError("access log contains an empty response")
        index = _evidence_integer(record["index"], "index", 1, 2**31 - 1)
        if index != expected_index or status not in (200, 404):
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


def _reject_failed_requests(records: list[dict[str, object]], allowed: tuple[str, ...]) -> None:
    failed = [record["path"] for record in records if record["status"] != 200]
    if any(path not in allowed or failed.count(path) != 1 for path in failed):
        raise ValidationError("access log contains failed or reordered requests")


def _verify_http_requests(records: list[dict[str, object]], profile: InstallerProfile) -> None:
    launcher_artifacts = tuple(
        (artifact.path, artifact.size) for artifact in _external_artifacts(profile)
    )
    rocky = profile.distribution == "rocky"
    opensuse = profile.distribution == "opensuse"
    base = profile.repository.path if profile.repository is not None else ""
    probes = ()
    if rocky:
        probes = _rocky_probes(base)
    elif opensuse:
        probes = tuple(f"{base}/{path}" for path in OPENSUSE_PROBES)
    _reject_failed_requests(records, probes)
    if opensuse:
        _verify_opensuse_requests(records, profile, probes)
        return
    records = [record for record in records if record["status"] == 200]
    if profile.live_iso is not None:
        if tuple((record["path"], record["bytes"]) for record in records) != launcher_artifacts:
            raise ValidationError(
                "HTTP evidence must be exactly the kernel, initramfs, and live ISO requests"
            )
        return
    sizes = dict(launcher_artifacts)
    paths = [record["path"] for record in records if record["method"] == "GET"]
    if paths[: len(launcher_artifacts)] != [path for path, _ in launcher_artifacts]:
        raise ValidationError("HTTP evidence has invalid launcher request order")
    once = (profile.kernel.path, profile.initramfs.path)
    for path, size in sizes.items():
        if paths.count(path) < 1 or path in once and paths.count(path) != 1:
            raise ValidationError("HTTP evidence is missing a required artifact request")
        if any(record["bytes"] != size for record in records if record["path"] == path):
            raise ValidationError("HTTP evidence has an artifact size mismatch")
    prefixes = _repository_prefixes(profile)
    if any(path not in sizes and not path.startswith(prefixes) for path in paths):
        raise ValidationError("HTTP evidence contains a path outside the selected profile")
    if not any(path.startswith(prefixes) and path not in sizes for path in paths):
        raise ValidationError("HTTP evidence lacks post-kexec repository corroboration")


def _verify_opensuse_requests(
    records: list[dict[str, object]], profile: InstallerProfile, probes: tuple[str, ...]
) -> None:
    pins = (profile.kernel, profile.initramfs)
    launcher = [("GET", 200, pin.path, pin.size) for pin in pins]
    if [
        (record["method"], record["status"], record["path"], record["bytes"])
        for record in records[:2]
    ] != launcher:
        raise ValidationError("HTTP evidence has invalid launcher request order")
    later = records[2:]
    if any(record["path"] in (pin.path for pin in pins) for record in later):
        raise ValidationError("HTTP evidence repeats a launcher artifact request")
    if any(record["status"] == 200 and record["path"] in probes for record in later):
        raise ValidationError("HTTP evidence serves an installer probe")
    if any(not record["path"].startswith(profile.repository.path + "/") for record in later):
        raise ValidationError("HTTP evidence contains a path outside the selected profile")
    if not any(record["method"] == "GET" and record["status"] == 200 for record in later):
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


def verify_installer_evidence(args: argparse.Namespace) -> tuple[str, ...]:
    record_bytes = _read_evidence_file(args.record, "evidence record", 64 * 1024)
    manifest_bytes = _read_evidence_file(args.config, "manifest", MAX_MANIFEST_BYTES)
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
    _verify_http_requests(
        _access_records(access_bytes, allow_head=profile.distribution == "opensuse"), profile
    )
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
        # Ubuntu's flag records the installer's static network screen (spec: Evidence).
        "installer-network: operator-reviewed"
        if profile.distribution == "ubuntu"
        else "intended-source: operator-reviewed",
    )


def _rocky_probes(base: str) -> tuple[str, ...]:
    # Anaconda's stage1 probes for these optional images; Rocky publishes neither (ADR 0013).
    return (f"{base}/images/updates.img", f"{base}/images/product.img")


def _repository_prefixes(profile: InstallerProfile) -> tuple[str, ...]:
    base = profile.repository.path
    if profile.distribution != "rocky":
        return (base + "/",)
    # Anaconda adds the AppStream sibling the BaseOS .treeinfo names (ADR 0013).
    return (base + "/", base.removesuffix(ROCKY_REPOSITORY_SUFFIX) + "/AppStream/ppc64le/os/")


def _verify_install_http_requests(
    records: list[dict[str, object]], profile: InstallerProfile
) -> None:
    # casper fetches only the live ISO after kexec; every package comes from it (ADR 0020).
    if profile.live_iso is not None:
        _verify_http_requests(records, profile)
        return
    rocky = profile.distribution == "rocky"
    _reject_failed_requests(records, _rocky_probes(profile.repository.path) if rocky else ())
    launcher_artifacts = tuple(
        (artifact.path, artifact.size) for artifact in _external_artifacts(profile)
    )
    if len(records) <= len(launcher_artifacts):
        raise ValidationError("HTTP evidence lacks post-kexec repository traffic")
    for record, (path, size) in zip(
        records[: len(launcher_artifacts)], launcher_artifacts, strict=True
    ):
        if record["path"] != path or record["bytes"] != size:
            raise ValidationError("HTTP evidence has invalid launcher request order or size")
    paths = [record["path"] for record in records]
    if any(paths.count(path) != 1 for path in (profile.kernel.path, profile.initramfs.path)):
        raise ValidationError("HTTP evidence requires exactly one kernel and initramfs request")
    prefixes = _repository_prefixes(profile)
    if any(not path.startswith(prefixes) for path in paths[len(launcher_artifacts) :]):
        raise ValidationError("HTTP evidence contains post-kexec traffic outside the repository")


def _verify_install_result(
    encoded: bytes, record: dict[str, object], before: str, after: str, unattended: bool = False
) -> None:
    # An unattended harness stops its boot phase at the login prompt, so it has no exit status.
    boot_field, boot_value = (
        ("boot_stop", "login-prompt") if unattended else ("boot_exit_status", 0)
    )
    fields = {
        "version",
        "qemu_memory_mib",
        "disk_size_gib",
        "install_timeout_seconds",
        "boot_timeout_seconds",
        "install_exit_status",
        boot_field,
        "disk_sha256_before",
        "disk_sha256_after",
        "disk_bytes_after",
    }
    result = _evidence_json(encoded, fields, "process result")
    values = (
        type(result["version"]) is int and result["version"] == 1,
        type(result["qemu_memory_mib"]) is int
        and result["qemu_memory_mib"] == record["qemu_memory_mib"],
        type(result["disk_size_gib"]) is int and 8 <= result["disk_size_gib"] <= 256,
        type(result["install_timeout_seconds"]) is int
        and 1 <= result["install_timeout_seconds"] <= 86400,
        type(result["boot_timeout_seconds"]) is int
        and 1 <= result["boot_timeout_seconds"] <= 86400,
        type(result["install_exit_status"]) is int and result["install_exit_status"] == 0,
        type(result[boot_field]) is type(boot_value) and result[boot_field] == boot_value,
        result["disk_sha256_before"] == before,
        result["disk_sha256_after"] == after,
        type(result["disk_bytes_after"]) is int and result["disk_bytes_after"] > 0,
    )
    if not all(values):
        raise ValidationError("process result does not prove a successful bounded installation")


def _install_evidence(
    bounds: dict[str, tuple[Path, str, int]], distribution: str
) -> tuple[dict[str, object], dict[str, bytes], Manifest, InstallerProfile]:
    """Read bounded install evidence and check its record against the manifest and digests."""
    encoded = {
        name: _read_evidence_file(path, label, maximum)
        for name, (path, label, maximum) in bounds.items()
    }
    record = _evidence_json(
        encoded.pop("record"),
        {
            "version",
            "manifest_sha256",
            "profile",
            "qemu_memory_mib",
            "disk_label",
            "evidence_sha256",
            "same_run_collection",
        },
        "installation evidence record",
    )
    manifest, canonical, manifest_digest = load_manifest_bytes(encoded["manifest"])
    if encoded["manifest"] != canonical:
        raise ValidationError("manifest evidence must be canonical JSON")
    if (
        type(record["version"]) is not int
        or record["version"] != 1
        or record["manifest_sha256"] != manifest_digest
    ):
        raise ValidationError("installation evidence identity does not match manifest")
    if type(record["profile"]) is not str:
        raise ValidationError("installation evidence profile is invalid")
    profile = manifest.profile(record["profile"])
    if profile.distribution != distribution or (
        distribution != "fedora" and manifest.login_user is None
    ):
        name = {
            "fedora": "a Fedora",
            "rocky": "an unattended Rocky",
            "ubuntu": "an unattended Ubuntu",
        }[distribution]
        raise ValidationError(f"installation evidence requires {name} profile")
    record["qemu_memory_mib"] = _evidence_integer(
        record["qemu_memory_mib"], "QEMU memory", 1024, 65536
    )
    label = record["disk_label"]
    if type(label) is not str or re.fullmatch(r"[A-Za-z0-9._-]{1,64}", label) is None:
        raise ValidationError("installation evidence disk label is invalid")
    if record["same_run_collection"] is not True:
        raise ValidationError("installation evidence same-run assertion must be true")
    _verify_input_digests(record, encoded)
    return record, encoded, manifest, profile


def _install_bounds(args: argparse.Namespace) -> dict[str, tuple[Path, str, int]]:
    return {
        "record": (args.record, "installation evidence record", 64 * 1024),
        "manifest": (args.config, "manifest", MAX_MANIFEST_BYTES),
        "install_console": (args.install_console_log, "install console", MAX_LOG_BYTES),
        "boot_console": (args.boot_console_log, "boot console", MAX_LOG_BYTES),
        "access_log": (args.access_log, "access log", MAX_LOG_BYTES),
        "result": (args.result, "process result", 64 * 1024),
        "install_pcap": (args.install_pcap, "install packet capture", 64 * 1024 * 1024),
        "disk_before": (args.disk_hash_before, "disk hash", 65),
        "disk_after": (args.disk_hash_after, "disk hash", 65),
    }


def _verify_install_disk_and_traffic(
    record: dict[str, object],
    encoded: dict[str, bytes],
    manifest: Manifest,
    profile: InstallerProfile,
) -> str:
    """Check the disk change, process result, HTTP log, launcher log, and install capture."""
    before = _disk_digest(encoded["disk_before"])
    after = _disk_digest(encoded["disk_after"])
    if before == after:
        raise ValidationError("disk evidence does not show installation mutation")
    unattended = profile.distribution != "fedora"
    _verify_install_result(encoded["result"], record, before, after, unattended)
    _verify_install_http_requests(_access_records(encoded["access_log"]), profile)
    with tempfile.TemporaryDirectory(prefix="iso-chain-install-evidence-") as temporary:
        install_log = Path(temporary) / "install.log"
        install_log.write_bytes(encoded["install_console"])
        verify_launcher_log(install_log, manifest, record["profile"])
        return _verify_capture(encoded["install_pcap"])


def _verify_capture(encoded: bytes) -> str:
    with tempfile.TemporaryDirectory(prefix="iso-chain-capture-") as temporary:
        capture = Path(temporary) / "capture.pcap"
        capture.write_bytes(encoded)
        return verify_pcap(capture)


def verify_fedora_install_evidence(args: argparse.Namespace) -> tuple[str, ...]:
    bounds = _install_bounds(args)
    bounds["kickstart"] = (args.kickstart, "Kickstart", MAX_KICKSTART_BYTES)
    record, encoded, manifest, profile = _install_evidence(bounds, "fedora")
    kickstart = encoded["kickstart"]
    if (
        len(kickstart) != profile.kickstart.size
        or hashlib.sha256(kickstart).hexdigest() != profile.kickstart.sha256
    ):
        raise ValidationError("Kickstart evidence does not match the selected profile")
    network_result = _verify_install_disk_and_traffic(record, encoded, manifest, profile)
    _installed_boot_id(encoded["boot_console"])
    return (
        "manifest: passed",
        "kickstart: passed",
        "network-config: passed",
        "http-evidence: passed",
        "installation: passed",
        "disk-mutation: passed",
        "disk-only-boot: passed",
        network_result,
        "same-run: operator-reviewed",
    )


def _visible_lines(encoded: bytes) -> list[str]:
    return [
        SERVICE_PREFIX.sub("", ANSI_ESCAPE.sub("", line).strip(), count=1)
        for line in encoded.decode(errors="replace").splitlines()
    ]


def _verify_installer_reboot(encoded: bytes) -> None:
    # The kernel names how the installer ended; a power-off would strand the partition.
    lines = _visible_lines(encoded)
    restart = re.compile(r"\[\s*\d+\.\d+\] reboot: Restarting system")
    power_down = re.compile(r"\[\s*\d+\.\d+\] reboot: Power down")
    if sum(bool(restart.fullmatch(line)) for line in lines) != 1 or any(
        power_down.fullmatch(line) for line in lines
    ):
        raise ValidationError("install console must end the installation with one reboot")


def _verify_installed_disk_login(encoded: bytes, lpar: str) -> None:
    lines = _visible_lines(encoded)
    handoff = "ISO_CHAIN: GRUB installed-disk handoff"
    if (
        lines.count(handoff) != 1
        or "ISO_CHAIN: GRUB optical handoff" in lines
        or "ISO_CHAIN: configuration passed" in lines
    ):
        raise ValidationError("boot console must show one installed-disk handoff and no launcher")
    # The kernel may print on the prompt's line before the harness stops QEMU.
    prompt = f"{lpar} login:"
    if not any(line.startswith(prompt) for line in lines[lines.index(handoff) + 1 :]):
        raise ValidationError("boot console lacks the installed system's login prompt")


def _verify_autoinstall_marker(encoded: bytes) -> None:
    # Only a run that read the user data prints this; subiquity's echo of the script does not
    # match it, and an interactive fallback prints nothing (ADR 0020).
    lines = _visible_lines(encoded)
    start = lines.index("kexec-exec: started") if "kexec-exec: started" in lines else len(lines)
    marker = re.compile(r"autoinstall-disk: passed [a-z][a-z0-9]*")
    matches = [index for index, line in enumerate(lines) if marker.fullmatch(line)]
    if len(matches) != 1 or matches[0] < start:
        raise ValidationError("install console requires one autoinstall disk marker after kexec")


def verify_rocky_install_evidence(args: argparse.Namespace) -> tuple[str, ...]:
    """Re-derive an install-rocky run from its records (ADR 0019)."""
    return _verify_unattended_install(args, "rocky")


def verify_ubuntu_install_evidence(args: argparse.Namespace) -> tuple[str, ...]:
    """Re-derive an install-ubuntu run from its records (ADR 0020)."""
    return _verify_unattended_install(args, "ubuntu")


def _verify_unattended_install(args: argparse.Namespace, distribution: str) -> tuple[str, ...]:
    bounds = _install_bounds(args)
    bounds["boot_pcap"] = (args.boot_pcap, "boot packet capture", 64 * 1024 * 1024)
    record, encoded, manifest, profile = _install_evidence(bounds, distribution)
    _verify_installer_reboot(encoded["install_console"])
    if distribution == "ubuntu":
        _verify_autoinstall_marker(encoded["install_console"])
    install_network = _verify_install_disk_and_traffic(record, encoded, manifest, profile)
    _verify_installed_disk_login(encoded["boot_console"], manifest.lpar)
    boot_network = _verify_capture(encoded["boot_pcap"])
    return (
        "manifest: passed",
        "user-data: passed" if distribution == "ubuntu" else "kickstart: passed",
        "network-config: passed",
        "http-evidence: passed",
        "installation: passed",
        "reboot: passed",
        "disk-mutation: passed",
        "installed-disk-boot: passed",
        f"install-{install_network}",
        f"boot-{boot_network}",
        "same-run: operator-reviewed",
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
    for name in ("grub-modules", "kernel", "initramfs", "profiles"):
        build.add_argument(f"--{name}", required=True, type=Path)
    container = commands.add_parser("container-build")
    for name in ("kernel", "initramfs", "profiles"):
        container.add_argument(f"--{name}", required=True, type=Path)
    for command in (build, container):
        for name in ("config", "target", "base-config", "output", "publish-dir"):
            command.add_argument(f"--{name}", type=Path)
        command.add_argument("--publish-url")
    container.add_argument("--grub-modules", type=Path)
    container.add_argument("--engine", default=None)
    container.add_argument("--image", default=CONTAINER_IMAGE)
    inspect = commands.add_parser("inspect")
    inspect.add_argument("iso", type=Path)
    inspect.add_argument("--result", action="store_true")
    container_prepare = commands.add_parser("container-prepare-initramfs")
    container_prepare.add_argument("--output-dir", required=True, type=Path)
    container_prepare.add_argument("--engine", default=None)
    container_prepare.add_argument("--image", default=CONTAINER_INITRAMFS_IMAGE)
    prepare = commands.add_parser("prepare-initramfs")
    prepare.add_argument("--kernel-version", required=True)
    prepare.add_argument("--output", required=True, type=Path)
    fedora = commands.add_parser("prepare-fedora-source")
    fedora.add_argument("--iso", required=True, type=Path)
    fedora.add_argument("--iso-sha256", required=True)
    fedora.add_argument("--tree", required=True, type=Path)
    fedora.add_argument("--repository-path", required=True)
    fedora.add_argument("--minimum-memory-mib", required=True, type=int)
    fedora.add_argument("--kickstart", required=True, type=Path)
    fedora.add_argument("--output", required=True, type=Path)
    rocky = commands.add_parser("prepare-rocky-source")
    rocky.add_argument("--iso", required=True, type=Path)
    rocky.add_argument("--iso-sha256", required=True)
    rocky.add_argument("--tree", required=True, type=Path)
    rocky.add_argument("--repository-path", required=True)
    rocky.add_argument("--minimum-memory-mib", required=True, type=int)
    rocky.add_argument("--output", required=True, type=Path)
    opensuse = commands.add_parser("prepare-opensuse-source")
    opensuse.add_argument("--checksums", required=True, type=Path)
    opensuse.add_argument("--tree", required=True, type=Path)
    opensuse.add_argument("--repository-path", required=True)
    opensuse.add_argument("--minimum-memory-mib", required=True, type=int)
    opensuse.add_argument("--output", required=True, type=Path)
    ubuntu = commands.add_parser("prepare-ubuntu-source")
    ubuntu.add_argument("--iso", required=True, type=Path)
    ubuntu.add_argument("--iso-sha256", required=True)
    ubuntu.add_argument("--release-path", required=True)
    ubuntu.add_argument("--minimum-memory-mib", required=True, type=int)
    ubuntu.add_argument("--output", required=True, type=Path)
    server = commands.add_parser("serve-source")
    server.add_argument("--directory", required=True, type=Path)
    server.add_argument("--bind", required=True)
    server.add_argument("--port", required=True, type=int)
    server.add_argument("--access-log", required=True, type=Path)
    external = commands.add_parser("validate-external-source")
    external.add_argument("--config", required=True, type=Path)
    external.add_argument("--profile")
    external.add_argument("--timeout-seconds", type=int, default=30)
    smoke_parser = commands.add_parser("smoke")
    for name in ("iso", "disk", "config", "capture-prefix"):
        smoke_parser.add_argument(f"--{name}", required=True, type=Path)
    smoke_parser.add_argument(
        "--adapter-state", choices=("matched", "missing", "duplicate"), default="matched"
    )
    smoke_parser.add_argument("--memory-mib", type=int, default=4096)
    install = commands.add_parser("install-fedora")
    rocky_install = commands.add_parser("install-rocky")
    ubuntu_install = commands.add_parser("install-ubuntu")
    for command, memory, install_timeout, boot_timeout in (
        (install, 4096, 7200, 600),
        (rocky_install, 8192, 14400, 3600),
        (ubuntu_install, 8192, 14400, 3600),
    ):
        for name in ("iso", "config", "output"):
            command.add_argument(f"--{name}", required=True, type=Path)
        command.add_argument("--disk-size-gib", type=int, default=20)
        command.add_argument("--memory-mib", type=int, default=memory)
        command.add_argument("--install-timeout-seconds", type=int, default=install_timeout)
        command.add_argument("--boot-timeout-seconds", type=int, default=boot_timeout)
    verify = commands.add_parser("verify-log")
    verify.add_argument("log", type=Path)
    launcher = commands.add_parser("verify-launcher-log")
    launcher.add_argument("log", type=Path)
    launcher.add_argument("--config", type=Path, required=True)
    launcher.add_argument("--expected-profile", required=True)
    pcap = commands.add_parser("verify-pcap")
    pcap.add_argument("pcap", type=Path)
    evidence = commands.add_parser("verify-installer-evidence")
    for name in (
        "record",
        "config",
        "console-log",
        "access-log",
        "pcap",
        "disk-hash-before",
        "disk-hash-after",
    ):
        evidence.add_argument(f"--{name}", required=True, type=Path)
    install_evidence = commands.add_parser("verify-fedora-install-evidence")
    rocky_evidence = commands.add_parser("verify-rocky-install-evidence")
    ubuntu_evidence = commands.add_parser("verify-ubuntu-install-evidence")
    for command, extra in (
        (install_evidence, "kickstart"),
        (rocky_evidence, "boot-pcap"),
        (ubuntu_evidence, "boot-pcap"),
    ):
        for name in (
            "record",
            "config",
            extra,
            "install-console-log",
            "boot-console-log",
            "access-log",
            "result",
            "install-pcap",
            "disk-hash-before",
            "disk-hash-after",
        ):
            command.add_argument(f"--{name}", required=True, type=Path)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "build":
            sys.stdout.buffer.write(build_iso(args))
        elif args.command == "container-build":
            container_build(args)
        elif args.command == "container-prepare-initramfs":
            container_prepare_initramfs(args)
        elif args.command == "smoke":
            smoke(args)
        elif args.command == "install-fedora":
            install_fedora(args)
        elif args.command == "install-rocky":
            install_rocky(args)
        elif args.command == "install-ubuntu":
            install_ubuntu(args)
        elif args.command == "inspect":
            report = inspect_result if args.result else inspect_iso
            sys.stdout.buffer.write(report(args.iso))
        elif args.command == "prepare-initramfs":
            prepare_initramfs(args)
        elif args.command == "prepare-fedora-source":
            prepare_fedora_source(args)
        elif args.command == "prepare-rocky-source":
            prepare_rocky_source(args)
        elif args.command == "prepare-opensuse-source":
            prepare_opensuse_source(args)
        elif args.command == "prepare-ubuntu-source":
            prepare_ubuntu_source(args)
        elif args.command == "serve-source":
            serve_source(args)
        elif args.command == "validate-external-source":
            manifest, _, _ = load_manifest(args.config)
            profile = args.profile or manifest.selected_profile
            results = validate_external_source(manifest, profile, args.timeout_seconds)
            print(json.dumps({"profile": profile, "artifacts": results}, sort_keys=True))
        elif args.command == "verify-launcher-log":
            manifest, _, _ = load_manifest(args.config)
            print(*verify_launcher_log(args.log, manifest, args.expected_profile), sep="\n")
        elif args.command == "verify-pcap":
            print(verify_pcap(args.pcap))
        elif args.command == "verify-installer-evidence":
            print(*verify_installer_evidence(args), sep="\n")
        elif args.command == "verify-fedora-install-evidence":
            print(*verify_fedora_install_evidence(args), sep="\n")
        elif args.command == "verify-rocky-install-evidence":
            print(*verify_rocky_install_evidence(args), sep="\n")
        elif args.command == "verify-ubuntu-install-evidence":
            print(*verify_ubuntu_install_evidence(args), sep="\n")
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
