#!/usr/bin/env python3
"""Build and exercise the bounded POWER9 optical-bootstrap experiment."""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

FIXED_KERNEL_ARGS = "console=hvc0 rd.neednet=0 ip=off iso_chain_stage=optical"
SAFE_ARG = re.compile(r"^[A-Za-z0-9_./:=,@+-]+$")
BOOT_ID = re.compile(r"boot_id=([0-9A-Fa-f-]{36})")
MAX_LOG_BYTES = 16 * 1024 * 1024
PASS_LINES = ("optical-boot: passed", "network: passed", "kexec: passed")


class ValidationError(ValueError):
    pass


def _path(value: Path, label: str, kind: str) -> Path:
    try:
        path = Path(value).resolve(strict=True)
    except OSError as error:
        raise ValidationError(f"{label} does not exist: {value}") from error
    valid = path.is_file() if kind == "file" else path.is_dir()
    if not valid:
        raise ValidationError(f"{label} is not a {kind}: {value}")
    return path


def _kernel_args(value: str) -> str:
    if any(character in value for character in "\r\n\0"):
        raise ValidationError("kernel arguments must be one line")
    tokens = value.split()
    for token in tokens:
        if not SAFE_ARG.fullmatch(token):
            raise ValidationError(f"unsafe kernel argument: {token!r}")
        if token.startswith(("ip=", "rd.neednet=")):
            raise ValidationError(f"kernel argument conflicts with network isolation: {token}")
    return " ".join(tokens)


def build_iso(args: argparse.Namespace) -> None:
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
    extra_args = _kernel_args(args.kernel_args)

    with tempfile.TemporaryDirectory(prefix=".iso-chain-", dir=parent) as temporary:
        workspace = Path(temporary)
        stage = workspace / "stage"
        grub = stage / "boot/grub"
        grub.mkdir(parents=True)
        shutil.copyfile(kernel, stage / "boot/vmlinuz")
        shutil.copyfile(initramfs, stage / "boot/initramfs.img")
        command_line = " ".join(part for part in (FIXED_KERNEL_ARGS, extra_args) if part)
        (grub / "grub.cfg").write_text(
            "set timeout=0\n"
            "menuentry 'ISO chain experiment' {\n"
            "    echo 'ISO_CHAIN: GRUB optical handoff'\n"
            f"    linux /boot/vmlinuz {command_line}\n"
            "    initrd /boot/initramfs.img\n"
            "}\n"
        )
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
            raise ValidationError(f"output appeared during build: {output}") from error


def qemu_command(iso: Path, disk: Path) -> list[str]:
    fixed = (
        "qemu-system-ppc64 -machine pseries,accel=tcg -cpu power9 -m 4G -smp 2 "
        "-nographic -nic none -snapshot -boot d -device virtio-scsi-pci"
    )
    disk_value, iso_value = (str(path).replace(",", ",,") for path in (disk, iso))
    return fixed.split() + [
        "-drive",
        f"file={disk_value},format=qcow2,if=virtio",
        "-drive",
        f"file={iso_value},format=raw,media=cdrom,readonly=on,if=none,id=cdrom",
        "-device",
        "scsi-cd,drive=cdrom,bootindex=1",
    ]


def smoke(args: argparse.Namespace) -> None:
    iso = _path(args.iso, "ISO", "file")
    disk = _path(args.disk, "disk", "file")
    command = qemu_command(iso, disk)
    os.execvp(command[0], command)


def _ordered_position(content: str, marker: str, start: int) -> int:
    position = content.find(marker, start)
    if position < 0:
        raise ValidationError(f"missing or reordered evidence marker: {marker}")
    return position + len(marker)


def verify_log(path: Path) -> tuple[str, str, str]:
    log = _path(path, "console log", "file")
    if log.stat().st_size > MAX_LOG_BYTES:
        raise ValidationError("console log exceeds 16 MiB evidence limit")
    content = log.read_text(errors="replace")
    if "/l-lan@" in content or "DHCPACK" in content or "DHCP lease acquired" in content:
        raise ValidationError("console log contains forbidden network evidence")
    for match in re.finditer(
        r"ISO_CHAIN_EVIDENCE: network-disabled interfaces=([^\r\n]+)", content
    ):
        if match.group(1) != "lo":
            raise ValidationError("console log reports a non-loopback interface")

    position = 0
    for marker in (
        "Successfully loaded",
        "ISO_CHAIN: GRUB optical handoff",
        "Kernel command line:",
        "iso_chain_stage=optical",
        "ISO_CHAIN_EVIDENCE: first-kernel boot_id=",
    ):
        position = _ordered_position(content, marker, position)
    first_match = BOOT_ID.search(content, position - len("boot_id="))
    if not first_match:
        raise ValidationError("first-kernel evidence has a malformed boot ID")
    position = first_match.end()
    for marker in (
        "ISO_CHAIN_EVIDENCE: network-disabled interfaces=lo",
        "kexec_core: Starting new kernel",
        "Linux version",
        "Kernel command line:",
        "iso_chain_stage=kexec",
    ):
        position = _ordered_position(content, marker, position)
    second_prefix = "ISO_CHAIN_EVIDENCE: second-kernel boot_id="
    try:
        position = _ordered_position(content, second_prefix, position)
    except ValidationError as error:
        raise ValidationError(
            "second kernel reached; evidence service marker is missing"
        ) from error
    second_match = BOOT_ID.search(content, position - len("boot_id="))
    if not second_match:
        raise ValidationError("second-kernel evidence has a malformed boot ID")
    try:
        first_id = uuid.UUID(first_match.group(1))
        second_id = uuid.UUID(second_match.group(1))
    except ValueError as error:
        raise ValidationError("kernel evidence has a malformed boot ID") from error
    if first_id == second_id:
        raise ValidationError("first and second kernel boot IDs are identical")
    _ordered_position(content, "cmdline=iso_chain_stage=kexec", second_match.end())
    return PASS_LINES


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    commands = result.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    for name in ("grub-modules", "kernel", "initramfs", "output"):
        build.add_argument(f"--{name}", required=True, type=Path)
    build.add_argument("--kernel-args", required=True)
    smoke_parser = commands.add_parser("smoke")
    for name in ("iso", "disk"):
        smoke_parser.add_argument(f"--{name}", required=True, type=Path)
    verify = commands.add_parser("verify-log")
    verify.add_argument("log", type=Path)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "build":
            build_iso(args)
        elif args.command == "smoke":
            smoke(args)
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
