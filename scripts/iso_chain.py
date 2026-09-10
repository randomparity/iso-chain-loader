#!/usr/bin/env python3
"""Build and exercise the bounded POWER9 optical-bootstrap experiment."""

import argparse
import configparser
import ctypes
import errno
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
MAX_TREEINFO_BYTES = 64 * 1024
PASS_LINES = ("optical-boot: passed", "network: passed", "kexec: passed")
IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
MAC = re.compile(r"^[0-9a-f]{2}(?::[0-9a-f]{2}){5}$")
DNS_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
URI_PATH = re.compile(r"^/(?:[A-Za-z0-9._~-]+)(?:/[A-Za-z0-9._~-]+)*$")
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
        {"distribution", "release", "kernel", "initramfs", "repository", "minimum_memory_mib"},
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
    if type(root["version"]) is not int or root["version"] != 2:
        _manifest_error("version", "must be exactly 2")
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
        version=2,
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


def _append_stage2_bundle(initramfs: Path, runtime: Path, output: Path, workspace: Path) -> None:
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
    hook_target = overlay / "usr/lib/dracut/hooks/initqueue/settled/90-iso-chain-stage2.sh"
    runtime_target.parent.mkdir(parents=True)
    hook_target.parent.mkdir(parents=True)
    os.link(runtime, runtime_target)
    shutil.copyfile(hook, hook_target)
    hook_target.chmod(0o755)
    archive = workspace / "stage2.cpio"
    names = b"./iso-chain/install.img\n./usr/lib/dracut/hooks/initqueue/settled/90-iso-chain-stage2.sh\n"
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
    expected_digest = _sha256(args.iso_sha256, "ISO digest")
    memory = _integer(args.minimum_memory_mib, "minimum memory", 1, 65536)
    if _file_sha256(iso) != expected_digest:
        raise ValidationError("Fedora ISO digest does not match")
    output = Path(args.output).absolute()
    parent = _path(output.parent, "output parent", "directory")
    if os.path.lexists(output):
        raise ValidationError("Fedora source output already exists")
    with tempfile.TemporaryDirectory(prefix=".iso-chain-fedora-", dir=parent) as temporary:
        tree = Path(temporary) / "tree"
        repository = tree / "repository"
        subprocess.run(
            ["xorriso", "-osirrox", "on", "-indev", str(iso), "-extract", "/", str(repository)],
            check=True,
        )
        kernel, initramfs, runtime = _treeinfo_paths(repository)
        repomd = _regular_file(repository / "repodata/repomd.xml", "Fedora repository metadata")
        profile_root = tree / "profiles/fedora-44"
        profile_root.mkdir(parents=True)
        prepared_kernel = profile_root / "vmlinuz"
        prepared_initramfs = profile_root / "initramfs.img"
        shutil.copyfile(kernel, prepared_kernel)
        _append_stage2_bundle(initramfs, runtime, prepared_initramfs, Path(temporary) / "bundle")
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
            "minimum_memory_mib": memory,
        }
        _installer_profile(profile, "profile")
        (tree / "profile.json").write_bytes(
            json.dumps(profile, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        )
        _publish_directory(tree, output)


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
    fedora = commands.add_parser("prepare-fedora-source")
    fedora.add_argument("--iso", required=True, type=Path)
    fedora.add_argument("--iso-sha256", required=True)
    fedora.add_argument("--minimum-memory-mib", required=True, type=int)
    fedora.add_argument("--output", required=True, type=Path)
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
        elif args.command == "prepare-fedora-source":
            prepare_fedora_source(args)
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
