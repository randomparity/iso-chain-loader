import hashlib
import io
import json
import os
import platform
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from scripts import iso_chain

FIRST_ID = "11111111-1111-4111-8111-111111111111"
SECOND_ID = "22222222-2222-4222-8222-222222222222"


def manifest_data(**changes):
    profile = {
        "distribution": "fedora",
        "release": "44",
        "kernel": {"path": "/profiles/fedora-44/vmlinuz", "size": 6, "sha256": "1" * 64},
        "initramfs": {
            "path": "/profiles/fedora-44/initramfs.img",
            "size": 9,
            "sha256": "2" * 64,
        },
        "repository": {
            "path": "/repository",
            "treeinfo": {"size": 10, "sha256": "3" * 64},
            "repomd": {"size": 11, "sha256": "4" * 64},
        },
        "kickstart": {
            "path": "/profiles/fedora-44/ks.cfg",
            "size": 12,
            "sha256": "5" * 64,
        },
        "minimum_memory_mib": 4096,
    }
    data = {
        "version": 3,
        "lpar": "sys-r1",
        "network": {
            "mac": "52:54:00:12:34:56",
            "address": "10.0.2.15/24",
            "routes": [{"destination": "0.0.0.0/0", "gateway": "10.0.2.2"}],
            "dns": ["10.0.2.3"],
        },
        "source": "http://10.0.2.2:8000",
        "profiles": {"fedora": profile, "rescue": profile},
        "selected_profile": "fedora",
    }
    data.update(changes)
    return data


class ManifestV3Tests(unittest.TestCase):
    def setUp(self):
        self.temp = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(self.temp)

    def load(self, data, name="manifest.json"):
        path = self.root / name
        path.write_text(json.dumps(data))
        return iso_chain.load_manifest(path)

    def test_valid_manifest_is_immutable_and_canonical(self):
        manifest, canonical, digest = self.load(manifest_data())
        self.assertEqual(manifest.lpar, "sys-r1")
        self.assertEqual(manifest.network.routes, (("0.0.0.0/0", "10.0.2.2"),))
        self.assertEqual(
            canonical,
            json.dumps(manifest_data(), sort_keys=True, separators=(",", ":")).encode() + b"\n",
        )
        self.assertRegex(digest, r"^[0-9a-f]{64}$")
        with self.assertRaises(AttributeError):
            manifest.lpar = "other"

    def test_equivalent_input_has_the_same_canonical_bytes_and_digest(self):
        first, bytes_one, digest_one = self.load(manifest_data())
        second, bytes_two, digest_two = self.load(
            json.loads(json.dumps(manifest_data(), indent=4)), "spaced.json"
        )
        self.assertEqual(first, second)
        self.assertEqual(bytes_one, bytes_two)
        self.assertEqual(digest_one, digest_two)

    def test_rejects_schema_types_bounds_and_unknown_fields_without_echoing_input(self):
        opaque_value = "untrusted-input"
        cases = (
            (None, "object"),
            (manifest_data(version=2), "version"),
            (manifest_data(lpar="Sys"), "lpar"),
            (manifest_data(network="bad"), "network"),
            (manifest_data(profiles={}), "profiles"),
            (manifest_data(profiles=[]), "profiles"),
            (manifest_data(selected_profile="other"), "selected_profile"),
            (manifest_data(extra=opaque_value), "unknown"),
        )
        for data, field in cases:
            with (
                self.subTest(data=data),
                self.assertRaisesRegex(iso_chain.ValidationError, field) as caught,
            ):
                self.load(data)
            self.assertNotIn(opaque_value, str(caught.exception))

    def test_rejects_network_source_and_route_failures_without_echoing_input(self):
        opaque_value = "http://untrusted.example/value"
        cases = (
            (
                manifest_data(network={**manifest_data()["network"], "mac": "53:54:00:12:34:56"}),
                "mac",
            ),
            (
                manifest_data(network={**manifest_data()["network"], "address": "2001:db8::1/64"}),
                "address",
            ),
            (manifest_data(network={**manifest_data()["network"], "dns": ["10.0.2.3"] * 4}), "dns"),
            (manifest_data(network={**manifest_data()["network"], "routes": []}), "routes"),
            (
                manifest_data(
                    network={
                        **manifest_data()["network"],
                        "routes": [{"destination": "0.0.0.0/0", "gateway": "192.0.2.1"}],
                    }
                ),
                "gateway",
            ),
            (manifest_data(source=f"http://10.0.2.2?{opaque_value}"), "source"),
            (manifest_data(source="HTTP://10.0.2.2"), "source"),
            (manifest_data(source="https://10.0.2.2"), "source"),
            (manifest_data(source="http://10.0.2.2/a"), "source"),
            (manifest_data(source="http://10.0.2.2:080"), "source"),
            (
                manifest_data(
                    network={
                        **manifest_data()["network"],
                        "routes": [{"destination": "192.0.2.0/24", "gateway": "10.0.2.2"}],
                    }
                ),
                "routes",
            ),
        )
        for data, field in cases:
            with (
                self.subTest(data=data),
                self.assertRaisesRegex(iso_chain.ValidationError, field) as caught,
            ):
                self.load(data)
            self.assertNotIn(opaque_value, str(caught.exception))

    def test_rejects_invalid_interface_prefixes_without_echoing_them(self):
        for prefix in ("99", "opaque-prefix"):
            with self.subTest(prefix=prefix):
                data = manifest_data(
                    network={
                        **manifest_data()["network"],
                        "address": f"10.0.2.15/{prefix}",
                    }
                )
                with self.assertRaisesRegex(iso_chain.ValidationError, "network.address") as caught:
                    self.load(data)
                self.assertNotIn(prefix, str(caught.exception))

    def test_requires_route_gateways_to_be_directly_connected_including_default(self):
        directly_connected = manifest_data()
        self.assertEqual(
            self.load(directly_connected)[0].network.routes,
            (("0.0.0.0/0", "10.0.2.2"),),
        )
        indirectly_reachable = manifest_data(
            network={
                **manifest_data()["network"],
                "routes": [
                    {"destination": "192.0.2.0/24", "gateway": "10.0.2.2"},
                    {"destination": "0.0.0.0/0", "gateway": "192.0.2.1"},
                ],
            }
        )
        with self.assertRaisesRegex(iso_chain.ValidationError, "gateway"):
            self.load(indirectly_reachable)

    def test_rejects_manifest_larger_than_64_kib(self):
        path = self.root / "large.json"
        path.write_bytes(b" " * (64 * 1024 + 1))
        with self.assertRaisesRegex(iso_chain.ValidationError, "64 KiB"):
            iso_chain.load_manifest(path)

    def test_profile_contract_and_derived_repository_paths(self):
        manifest, _, _ = self.load(manifest_data())
        profile = manifest.profile("fedora")
        self.assertEqual(profile.distribution, "fedora")
        self.assertEqual(profile.release, "44")
        self.assertEqual(profile.repository.treeinfo_path, "/repository/.treeinfo")
        self.assertEqual(profile.repository.repomd_path, "/repository/repodata/repomd.xml")
        self.assertEqual(profile.kickstart.path, "/profiles/fedora-44/ks.cfg")
        self.assertEqual(profile.minimum_memory_mib, 4096)

    def test_kernel_arguments_bind_the_selected_profile(self):
        manifest, _, digest = self.load(manifest_data())
        arguments = iso_chain._kernel_arguments(manifest, digest, "fedora")
        self.assertIn("iso_chain.lpar=sys-r1", arguments)
        self.assertIn("iso_chain.profile_distribution=fedora", arguments)
        self.assertIn("iso_chain.profile_release=44", arguments)
        self.assertIn("iso_chain.profile_kernel_path=/profiles/fedora-44/vmlinuz", arguments)
        self.assertIn("iso_chain.profile_kernel_size=6", arguments)
        self.assertIn("iso_chain.profile_kernel_sha256=" + "1" * 64, arguments)
        self.assertIn("iso_chain.profile_repository_path=/repository", arguments)
        self.assertIn("iso_chain.profile_treeinfo_sha256=" + "3" * 64, arguments)
        self.assertIn("iso_chain.profile_repomd_sha256=" + "4" * 64, arguments)
        self.assertIn("iso_chain.profile_kickstart_path=/profiles/fedora-44/ks.cfg", arguments)
        self.assertIn("iso_chain.profile_kickstart_size=12", arguments)
        self.assertIn("iso_chain.profile_kickstart_sha256=" + "5" * 64, arguments)
        self.assertIn("iso_chain.profile_minimum_memory_mib=4096", arguments)

    def test_rejects_profile_fields_bounds_and_noncanonical_paths(self):
        base = manifest_data()
        profile = base["profiles"]["fedora"]
        cases = (
            ({**profile, "distribution": "rhel"}, "distribution"),
            ({**profile, "release": "45"}, "release"),
            ({**profile, "minimum_memory_mib": 0}, "memory"),
            ({**profile, "extra": "value"}, "unknown"),
            ({**profile, "kernel": {**profile["kernel"], "size": 0}}, "size"),
            ({**profile, "kernel": {**profile["kernel"], "sha256": "A" * 64}}, "sha256"),
            ({**profile, "kernel": {**profile["kernel"], "path": "/a/../b"}}, "path"),
            ({key: value for key, value in profile.items() if key != "kickstart"}, "missing"),
            ({**profile, "kickstart": {**profile["kickstart"], "size": 0}}, "size"),
            (
                {**profile, "kickstart": {**profile["kickstart"], "size": 1024 * 1024 + 1}},
                "size",
            ),
            ({**profile, "kickstart": {**profile["kickstart"], "sha256": "A" * 64}}, "sha256"),
            ({**profile, "kickstart": {**profile["kickstart"], "path": "/a/../b"}}, "path"),
            (
                {
                    **profile,
                    "repository": {**profile["repository"], "path": "/repository%2fother"},
                },
                "path",
            ),
        )
        for changed, field in cases:
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(iso_chain.ValidationError, field),
            ):
                self.load({**base, "profiles": {"fedora": changed}})


def valid_log(second_id: str = SECOND_ID) -> str:
    lines = [
        "Successfully loaded",
        "ISO_CHAIN: GRUB optical handoff",
        "Kernel command line: root=/dev/vda3 iso_chain_stage=optical",
        f"ISO_CHAIN_EVIDENCE: first-kernel boot_id={FIRST_ID}",
        "ISO_CHAIN_EVIDENCE: network-disabled interfaces=lo",
        "kexec_core: Starting new kernel",
        "Linux version 6.17.1",
        "Kernel command line: root=/dev/vda3 iso_chain_stage=kexec",
        f"ISO_CHAIN_EVIDENCE: second-kernel boot_id={second_id} cmdline=iso_chain_stage=kexec",
    ]
    return "\n".join(lines)


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(self.temp)
        self.modules = self.root / "modules"
        self.modules.mkdir()
        (self.modules / "modinfo.sh").write_text(
            "grub_modinfo_target_cpu=powerpc\ngrub_modinfo_platform=ieee1275\n"
        )
        self.kernel = self.root / "vmlinuz"
        self.kernel.write_bytes(b"kernel")
        self.initramfs = self.root / "initramfs.img"
        self.initramfs.write_bytes(b"initramfs")
        self.output = self.root / "result.iso"
        self.config = self.root / "manifest.json"
        self.config.write_text(json.dumps(manifest_data()))

    def args(self, **changes):
        values = {
            "grub_modules": self.modules,
            "kernel": self.kernel,
            "initramfs": self.initramfs,
            "config": self.config,
            "output": self.output,
        }
        values.update(changes)
        return SimpleNamespace(**values)

    def test_build_stages_manifest_menu_and_publishes_once(self):
        def fake_run(command, check):
            self.assertTrue(check)
            self.assertEqual(command[:3], ["grub2-mkrescue", "-d", str(self.modules.resolve())])
            stage = Path(command[-1])
            config = (stage / "boot/grub/grub.cfg").read_text()
            self.assertIn("ISO_CHAIN: GRUB optical handoff", config)
            self.assertIn("set timeout=5", config)
            self.assertIn('set default="fedora"', config)
            self.assertIn("menuentry 'fedora'", config)
            self.assertIn("menuentry 'rescue'", config)
            self.assertIn("iso_chain.mac=52:54:00:12:34:56", config)
            self.assertIn("iso_chain.address=10.0.2.15/24", config)
            self.assertIn("iso_chain.route=0.0.0.0/0,10.0.2.2", config)
            self.assertIn("iso_chain.dns=10.0.2.3", config)
            self.assertIn("iso_chain.source=http://10.0.2.2:8000", config)
            self.assertIn("iso_chain.profile=fedora", config)
            for command_line in (
                line for line in config.splitlines() if line.startswith("    linux ")
            ):
                self.assertIn("ipv6.disable=1", command_line.split())
            self.assertIn("rd.systemd.unit=iso-chain.target", config)
            self.assertEqual(
                (stage / "iso-chain/config.json").read_bytes(),
                iso_chain.load_manifest(self.config)[1],
            )
            self.assertEqual(
                [(stage / name).read_bytes() for name in ("boot/vmlinuz", "boot/initramfs.img")],
                [b"kernel", b"initramfs"],
            )
            Path(command[-2]).write_bytes(b"iso")

        with mock.patch("scripts.iso_chain.subprocess.run", side_effect=fake_run):
            iso_chain.build_iso(self.args())
        self.assertEqual(self.output.read_bytes(), b"iso")

    def test_build_rejects_bad_inputs_before_running_tool(self):
        for changes in (
            {"kernel": self.root / "missing"},
            {"initramfs": self.modules},
            {"grub_modules": self.kernel},
            {"config": self.root / "missing.json"},
        ):
            with (
                self.subTest(changes=changes),
                mock.patch("scripts.iso_chain.subprocess.run") as run,
            ):
                with self.assertRaises(iso_chain.ValidationError):
                    iso_chain.build_iso(self.args(**changes))
                run.assert_not_called()

    def test_build_rejects_wrong_grub_platform_and_existing_output(self):
        (self.modules / "modinfo.sh").write_text(
            "grub_modinfo_target_cpu=x86_64\ngrub_modinfo_platform=efi\n"
        )
        with self.assertRaisesRegex(iso_chain.ValidationError, "powerpc-ieee1275"):
            iso_chain.build_iso(self.args())
        self.output.write_bytes(b"existing")
        with self.assertRaisesRegex(iso_chain.ValidationError, "already exists"):
            iso_chain.build_iso(self.args(grub_modules=self.root))

    def test_failed_tool_and_publication_race_do_not_overwrite(self):
        with (
            mock.patch(
                "scripts.iso_chain.subprocess.run",
                side_effect=subprocess.CalledProcessError(7, ["grub2-mkrescue"]),
            ),
            self.assertRaises(subprocess.CalledProcessError),
        ):
            iso_chain.build_iso(self.args())
        self.assertFalse(self.output.exists())

        def race(command, check):
            Path(command[-2]).write_bytes(b"generated")
            self.output.write_bytes(b"racer")

        with (
            mock.patch("scripts.iso_chain.subprocess.run", side_effect=race),
            self.assertRaisesRegex(iso_chain.ValidationError, "appeared during build"),
        ):
            iso_chain.build_iso(self.args())
        self.assertEqual(self.output.read_bytes(), b"racer")

    def test_builds_distinct_manifests_and_rejects_too_long_command_before_tool(self):
        other = self.root / "other.json"
        other.write_text(json.dumps(manifest_data(selected_profile="rescue")))
        configs = []

        def fake_run(command, check):
            configs.append((Path(command[-1]) / "boot/grub/grub.cfg").read_text())
            Path(command[-2]).write_bytes(b"iso")

        with mock.patch("scripts.iso_chain.subprocess.run", side_effect=fake_run):
            iso_chain.build_iso(self.args(output=self.root / "first.iso"))
            iso_chain.build_iso(self.args(config=other, output=self.root / "second.iso"))
        self.assertIn('set default="fedora"', configs[0])
        self.assertIn('set default="rescue"', configs[1])
        self.assertNotEqual(configs[0], configs[1])

        huge_profile = "p" + "a" * 2047
        profile = iso_chain.load_manifest_bytes(json.dumps(manifest_data()).encode())[0].profile(
            "fedora"
        )
        huge_manifest = iso_chain.Manifest(
            version=2,
            lpar="sys-r1",
            network=iso_chain.NetworkConfig(
                mac="52:54:00:12:34:56",
                address="10.0.2.15/24",
                routes=(("0.0.0.0/0", "10.0.2.2"),),
                dns=("10.0.2.3",),
            ),
            source="http://10.0.2.2:8000",
            profiles=((huge_profile, profile),),
            selected_profile=huge_profile,
        )
        with (
            mock.patch.object(
                iso_chain, "load_manifest", return_value=(huge_manifest, b"{}\n", "a" * 64)
            ),
            mock.patch("scripts.iso_chain.subprocess.run") as run,
            self.assertRaisesRegex(iso_chain.ValidationError, "2,048"),
        ):
            iso_chain.build_iso(self.args(output=self.root / "long.iso"))
        run.assert_not_called()

    def verify(self, content: str):
        path = self.root / "boot.log"
        path.write_text(content)
        return iso_chain.verify_log(path)

    def test_accepts_ordered_distinct_kernel_evidence(self):
        self.assertEqual(
            self.verify(valid_log()),
            ("optical-boot: passed", "network: passed", "kexec: passed"),
        )

    def test_rejects_missing_reordered_or_replayed_evidence(self):
        for content in (
            valid_log().replace("Successfully loaded\n", ""),
            "\n".join(reversed(valid_log().splitlines())),
            valid_log(FIRST_ID),
            valid_log().replace(SECOND_ID, "not-a-uuid"),
            valid_log().replace("Linux version 6.17.1\n", ""),
        ):
            with self.subTest(content=content), self.assertRaises(iso_chain.ValidationError):
                self.verify(content)

    def test_classifies_second_kernel_without_service_marker(self):
        content = valid_log().rsplit("\n", 1)[0]
        with self.assertRaisesRegex(iso_chain.ValidationError, "evidence service"):
            self.verify(content)

    def test_rejects_network_evidence_without_echoing_log(self):
        for forbidden in (
            "/l-lan@30000002",
            "ISO_CHAIN_EVIDENCE: network-disabled interfaces=eth0,lo",
            "DHCPACK from 10.0.2.2",
        ):
            secret = f"private-{forbidden}"
            with self.subTest(forbidden=forbidden):
                with self.assertRaises(iso_chain.ValidationError) as caught:
                    self.verify(valid_log() + "\n" + forbidden + "\n" + secret)
                self.assertNotIn(secret, str(caught.exception))

    def test_bounds_the_bytes_read_from_a_console_log(self):
        path = self.root / "boot.log"
        path.write_bytes(b"placeholder")
        descriptor = os.open(path, os.O_RDONLY)
        self.addCleanup(os.close, descriptor)
        stream = mock.MagicMock()
        stream.__enter__.return_value = stream
        stream.fileno.return_value = descriptor
        stream.read.return_value = b"x" * (iso_chain.MAX_LOG_BYTES + 1)
        with (
            mock.patch.object(Path, "open", return_value=stream),
            self.assertRaisesRegex(iso_chain.ValidationError, "exceeds 16 MiB"),
        ):
            iso_chain.verify_log(path)
        stream.read.assert_called_once_with(iso_chain.MAX_LOG_BYTES + 1)

    def test_ignores_marker_text_inside_an_echoed_command(self):
        echoed = "printf 'ISO_CHAIN_EVIDENCE: network-disabled interfaces=eth0,lo\\n'"
        self.assertEqual(self.verify(echoed + "\n" + valid_log()), iso_chain.PASS_LINES)

    def test_rejects_echoed_positive_marker_without_emitted_evidence(self):
        echoed = "printf 'ISO_CHAIN_EVIDENCE: network-disabled interfaces=lo\\n'"
        content = valid_log().replace("ISO_CHAIN_EVIDENCE: network-disabled interfaces=lo", echoed)
        with self.assertRaises(iso_chain.ValidationError):
            self.verify(content)

    def test_rejects_boot_id_with_trailing_junk(self):
        content = valid_log().replace(
            f"first-kernel boot_id={FIRST_ID}", f"first-kernel boot_id={FIRST_ID}-junk"
        )
        with self.assertRaisesRegex(iso_chain.ValidationError, "malformed boot ID"):
            self.verify(content)

    def test_rejects_boot_id_with_misplaced_hyphens(self):
        malformed = "1111111-11111-4111-8111-111111111111"
        content = valid_log().replace(FIRST_ID, malformed)
        with self.assertRaisesRegex(iso_chain.ValidationError, "malformed boot ID"):
            self.verify(content)


class SmokeTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.manifest = iso_chain.load_manifest_bytes(json.dumps(manifest_data()).encode())[0]

    def command(self, state="matched"):
        return iso_chain.qemu_command(
            Path("/tmp/test.iso"),
            Path("/tmp/a,b.qcow2"),
            self.manifest,
            self.root / "capture",
            state,
        )

    def test_exact_adapter_and_capture_topology(self):
        for state, macs in (
            ("matched", ["52:54:00:12:34:56"]),
            ("missing", ["52:54:00:12:34:57"]),
            ("duplicate", ["52:54:00:12:34:56"] * 2),
        ):
            with self.subTest(state=state):
                command = self.command(state)
                self.assertEqual(command[command.index("-nic") + 1], "none")
                self.assertEqual(command[command.index("-cpu") + 1], "power9")
                self.assertEqual(command[command.index("-m") + 1], "4096M")
                self.assertIn("pseries,accel=tcg", command)
                self.assertIn("-snapshot", command)
                self.assertIn("file=/tmp/a,,b.qcow2,format=qcow2,if=virtio", command)
                self.assertEqual(command.count("-netdev"), len(macs))
                self.assertEqual(command.count("-object"), len(macs))
                for index, mac in enumerate(macs):
                    self.assertIn(f"virtio-net-pci,netdev=net{index},mac={mac}", command)
                    self.assertIn(f"user,id=net{index},ipv6=off", command)
                    self.assertIn(
                        f"filter-dump,id=dump{index},netdev=net{index},"
                        f"file={self.root}/capture-net{index}.pcap",
                        command,
                    )

    def test_rejects_unknown_adapter_state(self):
        with self.assertRaisesRegex(iso_chain.ValidationError, "adapter state"):
            self.command("arbitrary")

    def test_accepts_bounded_explicit_memory(self):
        command = iso_chain.qemu_command(
            Path("/tmp/test.iso"),
            Path("/tmp/disk.qcow2"),
            self.manifest,
            self.root / "capture",
            "matched",
            8192,
        )
        self.assertEqual(command[command.index("-m") + 1], "8192M")
        for memory in (1023, 65537, True):
            with self.subTest(memory=memory), self.assertRaises(iso_chain.ValidationError):
                iso_chain.qemu_command(
                    Path("/tmp/test.iso"),
                    Path("/tmp/disk.qcow2"),
                    self.manifest,
                    self.root / f"capture-{memory}",
                    "matched",
                    memory,
                )

    def test_rejects_each_existing_capture_without_overwriting(self):
        for index in (0, 1):
            path = self.root / f"capture-net{index}.pcap"
            path.write_bytes(b"retain")
            with self.assertRaisesRegex(iso_chain.ValidationError, "capture"):
                self.command("duplicate")
            self.assertEqual(path.read_bytes(), b"retain")
            path.unlink()

    def test_rejects_dangling_capture_symlink(self):
        (self.root / "capture-net0.pcap").symlink_to(self.root / "missing")
        with self.assertRaisesRegex(iso_chain.ValidationError, "capture"):
            self.command()


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.iso = self.root / "launcher.iso"
        self.iso.write_bytes(b"iso")
        self.config = self.root / "manifest.json"
        _, canonical, _ = iso_chain.load_manifest_bytes(json.dumps(manifest_data()).encode())
        self.config.write_bytes(canonical)
        self.output = self.root / "install"
        self.manifest = iso_chain.load_manifest(self.config)[0]

    def args(self, **changes):
        values = {
            "iso": self.iso,
            "config": self.config,
            "output": self.output,
            "disk_size_gib": 20,
            "memory_mib": 4096,
            "install_timeout_seconds": 7200,
            "boot_timeout_seconds": 600,
        }
        values.update(changes)
        return SimpleNamespace(**values)

    def test_reference_kickstart_has_bounded_power_storage_and_boot_proof(self):
        path = Path("assets/kickstart/fedora-44-power9.ks")
        content = path.read_text()
        for expected in (
            "text",
            "rootpw --lock",
            "firstboot --disable",
            "ignoredisk --only-use=vda",
            "clearpart --all --initlabel --drives=vda",
            "@^server-product-environment",
            "%post --erroronfail",
            "/var/lib/iso-chain/install-complete",
            "installed-boot: passed boot_id=",
            "systemctl enable iso-chain-installed.service",
            "StandardOutput=journal+console",
            "StandardError=journal+console",
            "poweroff",
        ):
            self.assertIn(expected, content)
        for forbidden in ("http://", "https://", "ssh-rsa", "password=", ">/dev/hvc0"):
            self.assertNotIn(forbidden, content)

    def test_install_and_boot_commands_have_fixed_distinct_topology(self):
        install, boot = iso_chain.install_qemu_commands(
            self.iso,
            self.root / "disk.qcow2",
            self.manifest,
            self.root / "capture.pipe",
            4096,
        )
        for command in (install, boot):
            self.assertIn("pseries,accel=tcg", command)
            self.assertEqual(command[command.index("-cpu") + 1], "power9")
            self.assertIn("-nographic", command)
            self.assertNotIn("-display", command)
            self.assertNotIn("-serial", command)
            self.assertNotIn("-snapshot", command)
            self.assertEqual(command[command.index("-monitor") + 1], "none")
            self.assertNotIn("-qmp", command)
        self.assertIn("media=cdrom", " ".join(install))
        self.assertIn("filter-dump", " ".join(install))
        self.assertNotIn("media=cdrom", " ".join(boot))
        self.assertNotIn("filter-dump", " ".join(boot))
        self.assertEqual(boot[boot.index("-nic") + 1], "none")

    def test_boot_marker_requires_exactly_one_canonical_uuid(self):
        marker = f"installed-boot: passed boot_id={SECOND_ID}\n".encode()
        self.assertEqual(iso_chain._installed_boot_id(marker), SECOND_ID)
        prefixed = b"[   92.123456] iso-chain-installed[1274]: " + marker
        try:
            prefixed_id = iso_chain._installed_boot_id(prefixed)
        except iso_chain.ValidationError as error:
            self.fail(f"systemd-prefixed marker was rejected: {error}")
        self.assertEqual(prefixed_id, SECOND_ID)
        for content in (b"", marker + marker, b"installed-boot: passed boot_id=bad\n"):
            with self.subTest(content=content), self.assertRaises(iso_chain.ValidationError):
                iso_chain._installed_boot_id(content)

    def test_bounded_stream_never_writes_past_limit(self):
        destination = self.root / "bounded"
        with self.assertRaisesRegex(iso_chain.ValidationError, "limit"):
            iso_chain._copy_bounded_stream(io.BytesIO(b"abcdef"), destination, 5, "capture")
        self.assertEqual(destination.read_bytes(), b"abcde")

    def test_bounded_stream_copies_immediately_available_buffered_bytes(self):
        class BufferedPipe:
            def __init__(self):
                self.chunks = [b"guest diagnostic\n", b""]

            def read(self, _size):
                return b""

            def read1(self, _size):
                return self.chunks.pop(0)

        destination = self.root / "incremental"
        iso_chain._copy_bounded_stream(BufferedPipe(), destination, 64, "console")
        self.assertEqual(destination.read_bytes(), b"guest diagnostic\n")

    def test_bounded_stream_flushes_each_available_block_before_eof(self):
        class LiveBufferedPipe:
            def __init__(self):
                self.first = True
                self.blocked = threading.Event()
                self.release = threading.Event()

            def read(self, _size):
                return b""

            def read1(self, _size):
                if self.first:
                    self.first = False
                    return b"guest diagnostic\n"
                self.blocked.set()
                self.release.wait(1)
                return b""

        source = LiveBufferedPipe()
        destination = self.root / "live-incremental"
        errors = []

        def copy():
            try:
                iso_chain._copy_bounded_stream(source, destination, 64, "console")
            except (OSError, iso_chain.ValidationError, IndexError) as error:
                errors.append(error)

        thread = threading.Thread(target=copy)
        thread.start()
        try:
            self.assertTrue(source.blocked.wait(1), "reader did not consume the first block")
            self.assertEqual(destination.read_bytes(), b"guest diagnostic\n")
        finally:
            source.release.set()
            thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])

    def test_qemu_phase_rejects_timeout_nonzero_and_console_overflow(self):
        timeout_process = mock.MagicMock()
        timeout_process.stdout = io.BytesIO(b"")
        timeout_process.wait.side_effect = [
            subprocess.TimeoutExpired(["qemu"], 1),
            0,
        ]
        nonzero_process = mock.MagicMock()
        nonzero_process.stdout = io.BytesIO(b"")
        nonzero_process.wait.return_value = 2
        overflow_process = mock.MagicMock()
        overflow_process.stdout = io.BytesIO(b"overflow")
        overflow_process.wait.return_value = 0
        cases = (
            (timeout_process, "timed out", iso_chain.MAX_LOG_BYTES),
            (nonzero_process, "phase failed", iso_chain.MAX_LOG_BYTES),
            (overflow_process, "byte limit", 4),
        )
        for index, (process, reason, log_limit) in enumerate(cases):
            with (
                self.subTest(reason=reason),
                mock.patch("scripts.iso_chain.subprocess.Popen", return_value=process),
                mock.patch.object(iso_chain, "MAX_LOG_BYTES", log_limit),
                self.assertRaisesRegex(iso_chain.ValidationError, reason),
            ):
                iso_chain._run_qemu_phase(["qemu"], self.root / f"phase-{index}.log", 1)

    def test_qemu_phase_copies_fifo_capture_and_enforces_its_ceiling(self):
        fifo = self.root / "capture.pipe"
        capture = self.root / "capture.pcap"
        log = self.root / "console.log"
        program = (
            "import pathlib,sys; pathlib.Path(sys.argv[1]).write_bytes(b'pcap'); print('console')"
        )
        self.assertEqual(
            iso_chain._run_qemu_phase(
                [sys.executable, "-c", program, str(fifo)], log, 10, fifo, capture
            ),
            0,
        )
        self.assertEqual(capture.read_bytes(), b"pcap")
        self.assertEqual(log.read_text(), "console\n")
        self.assertFalse(fifo.exists())

        overflow_fifo = self.root / "overflow.pipe"
        overflow_capture = self.root / "overflow.pcap"
        overflow_log = self.root / "overflow.log"
        with (
            mock.patch.object(iso_chain, "MAX_INSTALL_CAPTURE_BYTES", 3),
            self.assertRaisesRegex(iso_chain.ValidationError, "byte limit"),
        ):
            iso_chain._run_qemu_phase(
                [sys.executable, "-c", program, str(overflow_fifo)],
                overflow_log,
                10,
                overflow_fifo,
                overflow_capture,
            )
        self.assertEqual(overflow_capture.read_bytes(), b"pca")
        self.assertFalse(overflow_fifo.exists())

    def test_successful_install_publishes_fresh_disk_logs_capture_and_result(self):
        def create_disk(command, **kwargs):
            self.assertEqual(command[:4], ["qemu-img", "create", "-f", "qcow2"])
            Path(command[4]).write_bytes(b"fresh")
            return subprocess.CompletedProcess(command, 0)

        def phase(command, log, timeout, capture_fifo=None, capture=None):
            disk = next(
                Path(value.split(",", 1)[0].split("=", 1)[1])
                for value in command
                if value.startswith("file=") and "format=qcow2" in value
            )
            if capture is not None:
                capture.write_bytes(b"pcap")
                log.write_text("install complete\n")
                disk.write_bytes(b"installed")
            else:
                log.write_text(f"installed-boot: passed boot_id={SECOND_ID}\n")
            return 0

        with (
            mock.patch("scripts.iso_chain.subprocess.run", side_effect=create_disk),
            mock.patch("scripts.iso_chain._run_qemu_phase", side_effect=phase),
        ):
            iso_chain.install_fedora(self.args())

        self.assertEqual(
            sorted(path.name for path in self.output.iterdir()),
            [
                "boot-console.log",
                "disk.qcow2",
                "install-console.log",
                "install.pcap",
                "result.json",
            ],
        )
        result = json.loads((self.output / "result.json").read_bytes())
        self.assertEqual(result["disk_size_gib"], 20)
        self.assertNotEqual(result["disk_sha256_before"], result["disk_sha256_after"])

    def test_install_rejects_unsafe_storage_process_and_result_states(self):
        self.output.mkdir()
        with self.assertRaisesRegex(iso_chain.ValidationError, "exists"):
            iso_chain.install_fedora(self.args())
        self.output.rmdir()
        for size in (7, 257, True):
            with self.subTest(size=size), self.assertRaises(iso_chain.ValidationError):
                iso_chain.install_fedora(self.args(disk_size_gib=size))

        with (
            mock.patch("scripts.iso_chain.shutil.disk_usage") as usage,
            self.assertRaisesRegex(iso_chain.ValidationError, "capture capacity"),
        ):
            usage.return_value = SimpleNamespace(free=1)
            iso_chain.install_fedora(self.args())

        for failure in (
            subprocess.CalledProcessError(1, ["qemu-img"]),
            subprocess.TimeoutExpired(["qemu-img"], 60),
        ):
            with (
                self.subTest(failure=failure),
                mock.patch("scripts.iso_chain.subprocess.run", side_effect=failure),
                self.assertRaisesRegex(iso_chain.ValidationError, "disk creation"),
            ):
                iso_chain.install_fedora(self.args())
            self.assertFalse(self.output.exists())

    def test_install_rejects_unchanged_disk_and_missing_boot_marker(self):
        def create_disk(command, **kwargs):
            Path(command[4]).write_bytes(b"fresh")
            return subprocess.CompletedProcess(command, 0)

        def unchanged_phase(command, log, timeout, capture_fifo=None, capture=None):
            if capture is not None:
                capture.write_bytes(b"pcap")
                log.write_text("install complete\n")
            else:
                log.write_text(f"installed-boot: passed boot_id={SECOND_ID}\n")
            return 0

        with (
            mock.patch("scripts.iso_chain.subprocess.run", side_effect=create_disk),
            mock.patch("scripts.iso_chain._run_qemu_phase", side_effect=unchanged_phase),
            self.assertRaisesRegex(iso_chain.ValidationError, "did not record"),
        ):
            iso_chain.install_fedora(self.args())
        self.assertFalse(self.output.exists())

        def missing_marker(command, log, timeout, capture_fifo=None, capture=None):
            if capture is not None:
                capture.write_bytes(b"pcap")
                log.write_text("install complete\n")
                disk = next(
                    Path(value.split(",", 1)[0].split("=", 1)[1])
                    for value in command
                    if value.startswith("file=") and "format=qcow2" in value
                )
                disk.write_bytes(b"installed")
            else:
                log.write_text("ordinary boot\n")
            return 0

        with (
            mock.patch("scripts.iso_chain.subprocess.run", side_effect=create_disk),
            mock.patch("scripts.iso_chain._run_qemu_phase", side_effect=missing_marker),
            self.assertRaisesRegex(iso_chain.ValidationError, "installed-boot"),
        ):
            iso_chain.install_fedora(self.args())
        self.assertFalse(self.output.exists())

    def test_parser_exposes_complete_install_contract(self):
        args = iso_chain.parser().parse_args(
            [
                "install-fedora",
                "--iso",
                str(self.iso),
                "--config",
                str(self.config),
                "--output",
                str(self.output),
                "--disk-size-gib",
                "32",
            ]
        )
        self.assertEqual(args.disk_size_gib, 32)
        self.assertEqual(args.memory_mib, 4096)


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.manifest, _, self.digest = iso_chain.load_manifest_bytes(
            json.dumps(manifest_data()).encode()
        )
        self.log = self.root / "console.log"
        self.pcap = self.root / "capture.pcap"
        self.pcap.write_bytes(b"pcap header")

    def content(self, profile="fedora"):
        return "\n".join(
            (
                "ISO_CHAIN: GRUB optical handoff",
                "[    0.000000] Kernel command line: "
                + " ".join(iso_chain._kernel_arguments(self.manifest, self.digest, profile)),
                "ISO_CHAIN: configuration passed",
                "adapter-match: passed",
                "profile: passed",
                (
                    "memory: passed memtotal_mib=8000 memavailable_mib=6000 "
                    "run_available_bytes=8589934592"
                ),
                "artifacts: passed",
                "kexec-load: passed",
                "kexec-exec: started",
            )
        )

    def verify(self, content, profile="fedora"):
        self.log.write_text(content)
        return iso_chain.verify_launcher_log(self.log, self.manifest, profile)

    def test_verifiers_exist(self):
        self.assertTrue(callable(getattr(iso_chain, "verify_launcher_log", None)))
        self.assertTrue(callable(getattr(iso_chain, "verify_pcap", None)))

    def test_accepts_exact_default_and_explicit_allowed_manual_profile(self):
        expected = (
            "configuration: passed",
            "adapter-match: passed",
            "profile: passed",
            "memory: passed",
            "artifacts: passed",
            "kexec-load: passed",
            "kexec-exec: started",
        )
        for profile in ("fedora", "rescue"):
            self.assertEqual(self.verify(self.content(profile), profile), expected)
        with self.assertRaises(iso_chain.ValidationError):
            self.verify(self.content("rescue"))
        with self.assertRaises(iso_chain.ValidationError):
            self.verify(self.content(), "unknown")

    def test_rejects_reordered_replayed_spoofed_or_failed_evidence(self):
        good = self.content()
        for bad in (
            "\n".join(reversed(good.splitlines())),
            good + "\nISO_CHAIN: configuration passed",
            good + "\nlauncher: failed",
            good + "\nkexec-exec: returned",
            good + "\nkexec-exec: failed",
            good + "\nkexec-unload: failed",
            good + "\n[FAILED] Failed to start iso-chain-launch.service.",
            good.replace("profile: passed", "printf 'profile: passed'"),
            good.replace(self.digest, "0" * 64),
            good.replace("iso_chain.profile=fedora", "iso_chain.profile=fedora-junk"),
            good.replace("iso_chain.profile=fedora", "iso_chain.profile=fedora " * 2),
            good.rsplit("\n", 1)[0],
        ):
            with self.subTest(bad=bad), self.assertRaises(iso_chain.ValidationError) as caught:
                self.verify(bad)
            self.assertNotIn(self.digest, str(caught.exception))

    def test_bounds_console_input(self):
        with (
            mock.patch.object(iso_chain, "MAX_LOG_BYTES", 32),
            self.assertRaisesRegex(iso_chain.ValidationError, "limit"),
        ):
            self.verify(self.content())

    def test_distinguishes_early_platform_diagnostics_from_launcher_failure(self):
        diagnostic = "[    0.9] secvar-sysfs: Failed to retrieve secvar operations\n"
        good = self.content().replace(
            "ISO_CHAIN: configuration passed", diagnostic + "ISO_CHAIN: configuration passed"
        )
        self.assertIn("kexec-exec: started", self.verify(good))
        self.assertIn("kexec-exec: started", self.verify(self.content() + "\n" + diagnostic))
        with self.assertRaises(iso_chain.ValidationError):
            self.verify(
                self.content().replace("artifacts: passed", diagnostic + "artifacts: passed")
            )

    def test_accepts_wrapped_launcher_and_second_kernel_command_lines(self):
        command_line = " ".join(iso_chain._kernel_arguments(self.manifest, self.digest, "fedora"))
        arguments = command_line.split()
        middle = len(arguments) // 2
        original = "[    0.000000] Kernel command line: " + command_line
        wrapped = (
            "[    0.000000] Kernel command line: "
            + " ".join(arguments[:middle])
            + " \\\n[    0.000000] Kernel command line: "
            + " ".join(arguments[middle:])
        )
        content = self.content().replace(original, wrapped)
        content += "\n[    0.000000] Kernel command line: inst.text console=hvc0"
        self.assertIn("kexec-exec: started", self.verify(content))

    def test_tcpdump_is_bounded_captured_and_filters_dhcp_or_ipv6(self):
        with mock.patch("scripts.iso_chain.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, b"", b"private banner")
            self.assertEqual(iso_chain.verify_pcap(self.pcap), "dhcp-ipv6-filter: absent")
        run.assert_called_once_with(
            [
                "tcpdump",
                "-nn",
                "-r",
                str(self.pcap),
                "-c",
                "1",
                "ip6 or (udp and (port 67 or port 68))",
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )

    def test_packet_match_and_tool_failure_never_echo_packet_contents(self):
        for outcome in (
            subprocess.CompletedProcess([], 0, b"private packet", b""),
            subprocess.CalledProcessError(1, ["tcpdump"], stderr=b"private packet"),
            subprocess.TimeoutExpired(["tcpdump"], 30, output=b"private packet"),
        ):
            with mock.patch("scripts.iso_chain.subprocess.run") as run:
                if isinstance(outcome, Exception):
                    run.side_effect = outcome
                else:
                    run.return_value = outcome
                with self.assertRaises(iso_chain.ValidationError) as caught:
                    iso_chain.verify_pcap(self.pcap)
                self.assertNotIn("private", str(caught.exception))

    def test_empty_or_oversized_pcap_is_not_absence_evidence(self):
        for size in (0, 64 * 1024 * 1024 + 1):
            with self.pcap.open("wb") as stream:
                stream.truncate(size)
            with mock.patch("scripts.iso_chain.subprocess.run") as run:
                with self.assertRaises(iso_chain.ValidationError):
                    iso_chain.verify_pcap(self.pcap)
                run.assert_not_called()


class FedoraEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.paths = {
            name: self.root / name
            for name in (
                "record.json",
                "manifest.json",
                "console.log",
                "access.jsonl",
                "capture.pcap",
                "disk-before.sha256",
                "disk-after.sha256",
            )
        }
        manifest, canonical, digest = iso_chain.load_manifest_bytes(
            json.dumps(manifest_data()).encode()
        )
        self.manifest = manifest
        self.manifest_digest = digest
        self.paths["manifest.json"].write_bytes(canonical)
        console = "\n".join(
            (
                "ISO_CHAIN: GRUB optical handoff",
                "[    0.000000] Kernel command line: "
                + " ".join(iso_chain._kernel_arguments(manifest, digest, "fedora")),
                "ISO_CHAIN: configuration passed",
                "adapter-match: passed",
                "profile: passed",
                (
                    "memory: passed memtotal_mib=8000 memavailable_mib=6000 "
                    "run_available_bytes=8589934592"
                ),
                "artifacts: passed",
                "kexec-load: passed",
                "kexec-exec: started",
            )
        )
        self.paths["console.log"].write_text(console)
        profile = manifest.profile("fedora")
        request_paths = (
            profile.kernel.path,
            profile.initramfs.path,
            profile.repository.treeinfo_path,
            profile.repository.repomd_path,
            "/repository/repodata/primary.xml.gz",
        )
        response_sizes = (6, 9, 10, 11, 20)
        access = b"".join(
            json.dumps(
                {
                    "method": "GET",
                    "path": path,
                    "status": 200,
                    "bytes": response_sizes[index - 1],
                    "index": index,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            + b"\n"
            for index, path in enumerate(request_paths, 1)
        )
        self.paths["access.jsonl"].write_bytes(access)
        self.paths["capture.pcap"].write_bytes(b"pcap")
        disk_digest = "a" * 64 + "\n"
        self.paths["disk-before.sha256"].write_text(disk_digest)
        self.paths["disk-after.sha256"].write_text(disk_digest)
        self.record = {
            "version": 1,
            "manifest_sha256": digest,
            "profile": "fedora",
            "qemu_memory_mib": 8192,
            "guest_memtotal_mib": 8000,
            "guest_memavailable_mib": 6000,
            "disk_label": "test-disk",
            "evidence_sha256": {
                key: hashlib.sha256(self.paths[name].read_bytes()).hexdigest()
                for key, name in (
                    ("manifest", "manifest.json"),
                    ("console", "console.log"),
                    ("access_log", "access.jsonl"),
                    ("pcap", "capture.pcap"),
                    ("disk_before", "disk-before.sha256"),
                    ("disk_after", "disk-after.sha256"),
                )
            },
            "same_run_collection": True,
            "installer_ready": True,
            "intended_disk_visible": True,
            "intended_source_confirmed": True,
        }
        self.write_record()

    def write_record(self):
        self.paths["record.json"].write_bytes(
            json.dumps(self.record, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        )

    def args(self):
        return SimpleNamespace(
            record=self.paths["record.json"],
            config=self.paths["manifest.json"],
            console_log=self.paths["console.log"],
            access_log=self.paths["access.jsonl"],
            pcap=self.paths["capture.pcap"],
            disk_hash_before=self.paths["disk-before.sha256"],
            disk_hash_after=self.paths["disk-after.sha256"],
        )

    def verify(self):
        with mock.patch("scripts.iso_chain.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, b"", b"")
            return iso_chain.verify_fedora_evidence(self.args())

    def test_accepts_bound_machine_evidence_and_labels_operator_observations(self):
        self.assertEqual(
            self.verify(),
            (
                "manifest: passed",
                "memory: passed",
                "http-evidence: passed",
                "disk-unchanged: passed",
                "dhcp-ipv6-filter: absent",
                "capture-provenance: operator-reviewed",
                "same-run: operator-reviewed",
                "installer-readiness: operator-reviewed",
                "storage-visibility: operator-reviewed",
                "intended-source: operator-reviewed",
            ),
        )

    def test_rejects_replacement_disk_change_missing_corroboration_and_false_flags(self):
        self.paths["console.log"].write_text("replacement")
        with self.assertRaises(iso_chain.ValidationError):
            self.verify()
        self.setUp()
        self.paths["disk-after.sha256"].write_text("b" * 64 + "\n")
        self.record["evidence_sha256"]["disk_after"] = hashlib.sha256(
            self.paths["disk-after.sha256"].read_bytes()
        ).hexdigest()
        self.write_record()
        with self.assertRaisesRegex(iso_chain.ValidationError, "disk"):
            self.verify()
        self.setUp()
        lines = self.paths["access.jsonl"].read_bytes().splitlines(keepends=True)
        self.paths["access.jsonl"].write_bytes(b"".join(lines[:-1]))
        self.record["evidence_sha256"]["access_log"] = hashlib.sha256(
            self.paths["access.jsonl"].read_bytes()
        ).hexdigest()
        self.write_record()
        with self.assertRaisesRegex(iso_chain.ValidationError, "corroboration"):
            self.verify()
        self.setUp()
        records = [
            json.loads(line) for line in self.paths["access.jsonl"].read_bytes().splitlines()
        ]
        records[-1]["path"] = "/repository/../profiles/outside"
        self.paths["access.jsonl"].write_bytes(
            b"".join(
                json.dumps(record, sort_keys=True, separators=(",", ":")).encode() + b"\n"
                for record in records
            )
        )
        self.record["evidence_sha256"]["access_log"] = hashlib.sha256(
            self.paths["access.jsonl"].read_bytes()
        ).hexdigest()
        self.write_record()
        with self.assertRaisesRegex(iso_chain.ValidationError, "path"):
            self.verify()
        self.setUp()
        records = [
            json.loads(line) for line in self.paths["access.jsonl"].read_bytes().splitlines()
        ]
        records.insert(0, records.pop())
        for index, record in enumerate(records, 1):
            record["index"] = index
        self.paths["access.jsonl"].write_bytes(
            b"".join(
                json.dumps(record, sort_keys=True, separators=(",", ":")).encode() + b"\n"
                for record in records
            )
        )
        self.record["evidence_sha256"]["access_log"] = hashlib.sha256(
            self.paths["access.jsonl"].read_bytes()
        ).hexdigest()
        self.write_record()
        with self.assertRaisesRegex(iso_chain.ValidationError, "order"):
            self.verify()
        for field in (
            "same_run_collection",
            "installer_ready",
            "intended_disk_visible",
            "intended_source_confirmed",
        ):
            self.setUp()
            self.record[field] = False
            self.write_record()
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(iso_chain.ValidationError, "operator"),
            ):
                self.verify()

    def test_rejects_noncanonical_duplicate_unknown_and_oversized_inputs(self):
        self.paths["record.json"].write_text('{"version":1,"version":1}\n')
        with self.assertRaises(iso_chain.ValidationError):
            self.verify()
        self.setUp()
        self.record["unknown"] = True
        self.write_record()
        with self.assertRaisesRegex(iso_chain.ValidationError, "unknown"):
            self.verify()
        for label in (
            "record",
            "manifest",
            "console",
            "access log",
            "packet capture",
            "disk hash",
        ):
            with (
                self.subTest(label=label),
                self.assertRaisesRegex(iso_chain.ValidationError, "limit"),
            ):
                iso_chain._read_evidence_file(self.paths["record.json"], label, 8)

    def test_parser_exposes_complete_verifier_contract(self):
        arguments = ["verify-fedora-evidence"]
        for option, name in (
            ("record", "record.json"),
            ("config", "manifest.json"),
            ("console-log", "console.log"),
            ("access-log", "access.jsonl"),
            ("pcap", "capture.pcap"),
            ("disk-hash-before", "disk-before.sha256"),
            ("disk-hash-after", "disk-after.sha256"),
        ):
            arguments.extend((f"--{option}", str(self.paths[name])))
        self.assertEqual(iso_chain.parser().parse_args(arguments).command, "verify-fedora-evidence")


class FedoraInstallEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        names = (
            "record.json",
            "manifest.json",
            "ks.cfg",
            "install-console.log",
            "boot-console.log",
            "access.jsonl",
            "result.json",
            "install.pcap",
            "disk-before.sha256",
            "disk-after.sha256",
        )
        self.paths = {name: self.root / name for name in names}
        kickstart = b"text\npoweroff\n"
        data = manifest_data()
        artifact = {
            "path": "/profiles/fedora-44/ks.cfg",
            "size": len(kickstart),
            "sha256": hashlib.sha256(kickstart).hexdigest(),
        }
        for profile in data["profiles"].values():
            profile["kickstart"] = artifact
        self.manifest, canonical, self.manifest_digest = iso_chain.load_manifest_bytes(
            json.dumps(data).encode()
        )
        self.paths["manifest.json"].write_bytes(canonical)
        self.paths["ks.cfg"].write_bytes(kickstart)
        self.paths["install-console.log"].write_text(
            "\n".join(
                (
                    "ISO_CHAIN: GRUB optical handoff",
                    "[    0.000000] Kernel command line: "
                    + " ".join(
                        iso_chain._kernel_arguments(self.manifest, self.manifest_digest, "fedora")
                    ),
                    "ISO_CHAIN: configuration passed",
                    "adapter-match: passed",
                    "profile: passed",
                    (
                        "memory: passed memtotal_mib=8000 memavailable_mib=6000 "
                        "run_available_bytes=8589934592"
                    ),
                    "artifacts: passed",
                    "kexec-load: passed",
                    "kexec-exec: started",
                    "Anaconda installation complete",
                )
            )
        )
        self.paths["boot-console.log"].write_text(f"installed-boot: passed boot_id={SECOND_ID}\n")
        profile = self.manifest.profile("fedora")
        request_paths = (
            profile.kernel.path,
            profile.initramfs.path,
            profile.repository.treeinfo_path,
            profile.repository.repomd_path,
            profile.kickstart.path,
            "/repository/repodata/primary.xml.gz",
        )
        response_sizes = (
            profile.kernel.size,
            profile.initramfs.size,
            profile.repository.treeinfo.size,
            profile.repository.repomd.size,
            profile.kickstart.size,
            20,
        )
        self.write_access(request_paths, response_sizes)
        self.paths["install.pcap"].write_bytes(b"pcap")
        self.paths["disk-before.sha256"].write_text("a" * 64 + "\n")
        self.paths["disk-after.sha256"].write_text("b" * 64 + "\n")
        self.result = {
            "version": 1,
            "qemu_memory_mib": 4096,
            "disk_size_gib": 20,
            "install_timeout_seconds": 7200,
            "boot_timeout_seconds": 600,
            "install_exit_status": 0,
            "boot_exit_status": 0,
            "disk_sha256_before": "a" * 64,
            "disk_sha256_after": "b" * 64,
            "disk_bytes_after": 1234,
        }
        self.write_result()
        self.record = {
            "version": 1,
            "manifest_sha256": self.manifest_digest,
            "profile": "fedora",
            "qemu_memory_mib": 4096,
            "disk_label": "fresh-fedora-disk",
            "evidence_sha256": {},
            "same_run_collection": True,
        }
        self.refresh_record_digests()

    def write_access(self, paths, sizes):
        self.paths["access.jsonl"].write_bytes(
            b"".join(
                json.dumps(
                    {
                        "method": "GET",
                        "path": path,
                        "status": 200,
                        "bytes": sizes[index - 1],
                        "index": index,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
                + b"\n"
                for index, path in enumerate(paths, 1)
            )
        )

    def write_result(self):
        self.paths["result.json"].write_bytes(
            json.dumps(self.result, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        )

    def refresh_record_digests(self):
        mapping = {
            "manifest": "manifest.json",
            "kickstart": "ks.cfg",
            "install_console": "install-console.log",
            "boot_console": "boot-console.log",
            "access_log": "access.jsonl",
            "result": "result.json",
            "install_pcap": "install.pcap",
            "disk_before": "disk-before.sha256",
            "disk_after": "disk-after.sha256",
        }
        self.record["evidence_sha256"] = {
            key: hashlib.sha256(self.paths[name].read_bytes()).hexdigest()
            for key, name in mapping.items()
        }
        self.paths["record.json"].write_bytes(
            json.dumps(self.record, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        )

    def args(self):
        return SimpleNamespace(
            record=self.paths["record.json"],
            config=self.paths["manifest.json"],
            kickstart=self.paths["ks.cfg"],
            install_console_log=self.paths["install-console.log"],
            boot_console_log=self.paths["boot-console.log"],
            access_log=self.paths["access.jsonl"],
            result=self.paths["result.json"],
            install_pcap=self.paths["install.pcap"],
            disk_hash_before=self.paths["disk-before.sha256"],
            disk_hash_after=self.paths["disk-after.sha256"],
        )

    def verify(self, packet_output=b""):
        with mock.patch("scripts.iso_chain.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, packet_output, b"")
            return iso_chain.verify_fedora_install_evidence(self.args())

    def test_accepts_bound_installation_evidence(self):
        self.assertEqual(
            self.verify(),
            (
                "manifest: passed",
                "kickstart: passed",
                "network-config: passed",
                "http-evidence: passed",
                "installation: passed",
                "disk-mutation: passed",
                "disk-only-boot: passed",
                "dhcp-ipv6-filter: absent",
                "same-run: operator-reviewed",
            ),
        )

    def test_rejects_replaced_inputs_noncanonical_records_and_false_same_run(self):
        self.paths["ks.cfg"].write_bytes(b"replacement")
        with self.assertRaisesRegex(iso_chain.ValidationError, "replaced"):
            self.verify()
        self.refresh_record_digests()
        with self.assertRaisesRegex(iso_chain.ValidationError, "Kickstart"):
            self.verify()
        self.setUp()
        self.record["unknown"] = True
        self.refresh_record_digests()
        with self.assertRaisesRegex(iso_chain.ValidationError, "unknown"):
            self.verify()
        self.setUp()
        self.record["same_run_collection"] = False
        self.refresh_record_digests()
        with self.assertRaisesRegex(iso_chain.ValidationError, "same-run"):
            self.verify()
        self.setUp()
        self.record["disk_label"] = "private value"
        self.refresh_record_digests()
        with self.assertRaisesRegex(iso_chain.ValidationError, "disk label") as caught:
            self.verify()
        self.assertNotIn("private value", str(caught.exception))
        self.setUp()
        self.record["version"] = True
        self.refresh_record_digests()
        with self.assertRaisesRegex(iso_chain.ValidationError, "identity"):
            self.verify()

    def test_rejects_boolean_values_for_integer_result_fields(self):
        for field, value in (
            ("install_exit_status", False),
            ("boot_exit_status", False),
            ("disk_bytes_after", True),
            ("version", True),
        ):
            self.setUp()
            self.result[field] = value
            self.write_result()
            self.refresh_record_digests()
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(iso_chain.ValidationError, "process result"),
            ):
                self.verify()

    def test_rejects_http_result_boot_disk_and_network_false_positives(self):
        records = [
            json.loads(line) for line in self.paths["access.jsonl"].read_bytes().splitlines()
        ]
        records.insert(0, records.pop(4))
        for index, record in enumerate(records, 1):
            record["index"] = index
        self.write_access(
            [record["path"] for record in records], [record["bytes"] for record in records]
        )
        self.refresh_record_digests()
        with self.assertRaisesRegex(iso_chain.ValidationError, "order"):
            self.verify()

        self.setUp()
        records = [
            json.loads(line) for line in self.paths["access.jsonl"].read_bytes().splitlines()
        ]
        records.append({**records[4], "index": len(records) + 1})
        self.write_access(
            [record["path"] for record in records], [record["bytes"] for record in records]
        )
        self.refresh_record_digests()
        with self.assertRaisesRegex(iso_chain.ValidationError, "Kickstart"):
            self.verify()

        self.setUp()
        records = [
            json.loads(line) for line in self.paths["access.jsonl"].read_bytes().splitlines()
        ][:-1]
        self.write_access(
            [record["path"] for record in records], [record["bytes"] for record in records]
        )
        self.refresh_record_digests()
        with self.assertRaisesRegex(iso_chain.ValidationError, "post-kexec"):
            self.verify()

        self.setUp()
        self.result["install_exit_status"] = 1
        self.write_result()
        self.refresh_record_digests()
        with self.assertRaisesRegex(iso_chain.ValidationError, "process result"):
            self.verify()

        self.setUp()
        opaque = "untrusted-boot-value"
        self.paths["boot-console.log"].write_text(opaque)
        self.paths["install-console.log"].write_text(
            self.paths["install-console.log"].read_text()
            + f"\ninstalled-boot: passed boot_id={SECOND_ID}\n"
        )
        self.refresh_record_digests()
        with self.assertRaises(iso_chain.ValidationError) as caught:
            self.verify()
        self.assertNotIn(opaque, str(caught.exception))

        self.setUp()
        self.paths["disk-after.sha256"].write_text("a" * 64 + "\n")
        self.result["disk_sha256_after"] = "a" * 64
        self.write_result()
        self.refresh_record_digests()
        with self.assertRaisesRegex(iso_chain.ValidationError, "disk"):
            self.verify()

        self.setUp()
        with self.assertRaisesRegex(iso_chain.ValidationError, "DHCP or IPv6"):
            self.verify(packet_output=b"forbidden packet")

    def test_parser_exposes_complete_install_evidence_contract(self):
        arguments = ["verify-fedora-install-evidence"]
        for option, name in (
            ("record", "record.json"),
            ("config", "manifest.json"),
            ("kickstart", "ks.cfg"),
            ("install-console-log", "install-console.log"),
            ("boot-console-log", "boot-console.log"),
            ("access-log", "access.jsonl"),
            ("result", "result.json"),
            ("install-pcap", "install.pcap"),
            ("disk-hash-before", "disk-before.sha256"),
            ("disk-hash-after", "disk-after.sha256"),
        ):
            arguments.extend((f"--{option}", str(self.paths[name])))
        self.assertEqual(
            iso_chain.parser().parse_args(arguments).command,
            "verify-fedora-install-evidence",
        )


class InspectTests(unittest.TestCase):
    def setUp(self):
        self.temp = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(self.temp)
        self.iso = self.root / "result.iso"
        self.iso.write_bytes(b"iso")

    def test_extracts_and_returns_canonical_manifest(self):
        def fake_run(command, check):
            self.assertTrue(check)
            self.assertEqual(
                command[:5], ["xorriso", "-osirrox", "on", "-indev", str(self.iso.resolve())]
            )
            self.assertEqual(command[-2], "/iso-chain/config.json")
            Path(command[-1]).write_text(json.dumps(manifest_data(), indent=2))

        with mock.patch("scripts.iso_chain.subprocess.run", side_effect=fake_run):
            embedded = iso_chain.inspect_iso(self.iso)
        self.assertEqual(
            embedded, iso_chain.load_manifest_bytes(json.dumps(manifest_data()).encode())[1]
        )

    def test_rejects_invalid_iso_and_invalid_extraction_without_echoing_input(self):
        with self.assertRaisesRegex(iso_chain.ValidationError, "ISO"):
            iso_chain.inspect_iso(self.root / "missing.iso")

        opaque_value = "untrusted-input"

        def fake_run(command, check):
            Path(command[-1]).write_text('{"source":"' + opaque_value + '"}')

        with (
            mock.patch("scripts.iso_chain.subprocess.run", side_effect=fake_run),
            self.assertRaises(iso_chain.ValidationError) as caught,
        ):
            iso_chain.inspect_iso(self.iso)
        self.assertNotIn(opaque_value, str(caught.exception))

    def test_bounds_extracted_manifest_before_revalidation(self):
        def fake_run(command, check):
            Path(command[-1]).write_bytes(b" " * (64 * 1024 + 1))

        with (
            mock.patch("scripts.iso_chain.subprocess.run", side_effect=fake_run),
            self.assertRaisesRegex(iso_chain.ValidationError, "64 KiB"),
        ):
            iso_chain.inspect_iso(self.iso)


class FedoraSourceTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.iso = self.root / "Fedora-Server-dvd-ppc64le-44.iso"
        self.iso.write_bytes(b"verified Fedora image")
        self.enterContext(
            mock.patch.object(iso_chain, "FEDORA_ISO_SIZE", self.iso.stat().st_size, create=True)
        )
        self.digest = hashlib.sha256(self.iso.read_bytes()).hexdigest()
        self.output = self.root / "source"
        self.kickstart = self.root / "ks.cfg"
        self.kickstart.write_bytes(b"text\npoweroff\n")
        self.commands = []
        self.cpio_input = None

    def args(self, **changes):
        values = {
            "iso": self.iso,
            "iso_sha256": self.digest,
            "minimum_memory_mib": 4096,
            "kickstart": self.kickstart,
            "output": self.output,
        }
        values.update(changes)
        return SimpleNamespace(**values)

    def extracted_tree(self, root):
        treeinfo = """[general]
family=Fedora
version=44
arch=ppc64le
variant=Server
[images-ppc64le]
kernel=images/pxeboot/vmlinuz
initrd=images/pxeboot/initrd.img
[stage2]
mainimage=images/install.img
"""
        files = {
            ".treeinfo": treeinfo.encode(),
            "images/pxeboot/vmlinuz": b"kernel",
            "images/pxeboot/initrd.img": b"\xfd7zXZ\x00initramfs",
            "images/install.img": b"runtime",
            "repodata/repomd.xml": b"metadata",
        }
        for name, content in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

    def fake_run(self, command, **kwargs):
        self.commands.append(command)
        if command[0] == "xorriso":
            self.assertTrue(Path(command[-1]).is_dir())
            self.extracted_tree(Path(command[-1]))
        elif command[0] == "cpio":
            self.cpio_input = kwargs["input"]
            kwargs["stdout"].write(b"newc")
        elif command[0] == "xz":
            kwargs["stdout"].write(b"compressed-newc")
        return subprocess.CompletedProcess(command, 0)

    def test_verifies_digest_before_fixed_extraction_and_writes_canonical_profile(self):
        with mock.patch("scripts.iso_chain.subprocess.run", side_effect=self.fake_run):
            iso_chain.prepare_fedora_source(self.args())

        self.assertEqual(
            self.commands[0],
            [
                "xorriso",
                "-osirrox",
                "on",
                "-indev",
                mock.ANY,
                "-extract",
                "/",
                mock.ANY,
            ],
        )
        self.assertNotEqual(Path(self.commands[0][4]), self.iso.resolve())
        self.assertEqual(self.commands[1][:3], ["cpio", "--create", "--format=newc"])
        self.assertEqual(
            self.cpio_input,
            b"./iso-chain\n./iso-chain/install.img\n./iso-chain/ks.cfg\n"
            b"./usr/lib/dracut/hooks/initqueue/settled/90-iso-chain-stage2.sh\n",
        )
        self.assertEqual(self.commands[2][:4], ["xz", "--check=crc32", "--threads=1", "--stdout"])
        profile_bytes = (self.output / "profile.json").read_bytes()
        profile = json.loads(profile_bytes)
        self.assertEqual(
            profile_bytes,
            json.dumps(profile, sort_keys=True, separators=(",", ":")).encode() + b"\n",
        )
        manifest = manifest_data(profiles={"fedora": profile})
        parsed = iso_chain.load_manifest_bytes(json.dumps(manifest).encode())[0].profile("fedora")
        self.assertEqual(parsed.kernel.path, "/profiles/fedora-44/vmlinuz")
        self.assertEqual(
            parsed.kickstart.sha256, hashlib.sha256(self.kickstart.read_bytes()).hexdigest()
        )
        self.assertEqual(parsed.minimum_memory_mib, 4096)
        self.assertEqual(
            (self.output / "profiles/fedora-44/initramfs.img").read_bytes(),
            b"\xfd7zXZ\x00initramfscompressed-newc",
        )
        self.assertEqual(
            sorted(path.name for path in (self.output / "profiles/fedora-44").iterdir()),
            ["initramfs.img", "ks.cfg", "vmlinuz"],
        )

    def test_rejects_unsafe_kickstart_without_publication(self):
        cases = []
        empty = self.root / "empty.ks"
        empty.write_bytes(b"")
        cases.append(empty)
        oversized = self.root / "oversized.ks"
        oversized.write_bytes(b"x" * (1024 * 1024 + 1))
        cases.append(oversized)
        symlink = self.root / "symlink.ks"
        symlink.symlink_to(self.kickstart)
        cases.append(symlink)
        cases.append(self.root / "missing.ks")
        for kickstart in cases:
            with (
                self.subTest(kickstart=kickstart.name),
                mock.patch("scripts.iso_chain.subprocess.run") as run,
                self.assertRaises(iso_chain.ValidationError),
            ):
                iso_chain.prepare_fedora_source(self.args(kickstart=kickstart))
            run.assert_not_called()
            self.assertFalse(self.output.exists())

    def test_wrong_digest_and_bad_metadata_do_not_extract_or_publish(self):
        with (
            mock.patch("scripts.iso_chain.subprocess.run") as run,
            self.assertRaisesRegex(iso_chain.ValidationError, "digest"),
        ):
            iso_chain.prepare_fedora_source(self.args(iso_sha256="0" * 64))
        run.assert_not_called()
        self.assertFalse(self.output.exists())

        oversized = b"x" * (iso_chain.FEDORA_ISO_SIZE + 1)
        self.iso.write_bytes(oversized)
        with (
            mock.patch("scripts.iso_chain.subprocess.run") as run,
            self.assertRaisesRegex(iso_chain.ValidationError, "size"),
        ):
            iso_chain.prepare_fedora_source(
                self.args(iso_sha256=hashlib.sha256(oversized).hexdigest())
            )
        run.assert_not_called()
        self.assertFalse(self.output.exists())
        self.iso.write_bytes(b"verified Fedora image")

        def bad_extract(command, **kwargs):
            if command[0] == "xorriso":
                self.extracted_tree(Path(command[-1]))
                (Path(command[-1]) / ".treeinfo").write_bytes(b"x" * (64 * 1024 + 1))
            return subprocess.CompletedProcess(command, 0)

        with (
            mock.patch("scripts.iso_chain.subprocess.run", side_effect=bad_extract),
            self.assertRaisesRegex(iso_chain.ValidationError, "treeinfo"),
        ):
            iso_chain.prepare_fedora_source(self.args())
        self.assertFalse(self.output.exists())

    def test_extracts_the_private_verified_copy_if_the_source_path_changes(self):
        verified = self.iso.read_bytes()

        def replace_source(command, **kwargs):
            if command[0] == "xorriso":
                self.iso.write_bytes(b"replacement")
                extracted = Path(command[4])
                self.assertNotEqual(extracted, self.iso.resolve())
                self.assertEqual(extracted.read_bytes(), verified)
            return self.fake_run(command, **kwargs)

        with mock.patch("scripts.iso_chain.subprocess.run", side_effect=replace_source):
            iso_chain.prepare_fedora_source(self.args())

        self.assertTrue((self.output / "profile.json").is_file())

    def test_publication_race_does_not_replace_destination(self):
        def race(command, **kwargs):
            result = self.fake_run(command, **kwargs)
            if command[0] == "xz":
                self.output.mkdir()
                (self.output / "retain").write_text("operator-owned")
            return result

        with (
            mock.patch("scripts.iso_chain.subprocess.run", side_effect=race),
            self.assertRaisesRegex(iso_chain.ValidationError, "appeared"),
        ):
            iso_chain.prepare_fedora_source(self.args())
        self.assertEqual((self.output / "retain").read_text(), "operator-owned")

    def test_parser_exposes_complete_command_contract(self):
        args = iso_chain.parser().parse_args(
            [
                "prepare-fedora-source",
                "--iso",
                str(self.iso),
                "--iso-sha256",
                self.digest,
                "--minimum-memory-mib",
                "4096",
                "--kickstart",
                str(self.kickstart),
                "--output",
                str(self.output),
            ]
        )
        self.assertEqual(args.command, "prepare-fedora-source")
        self.assertEqual(args.minimum_memory_mib, 4096)
        self.assertEqual(args.kickstart, self.kickstart)


class FedoraServerTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.tree = self.root / "tree"
        (self.tree / "repository/repodata").mkdir(parents=True)
        (self.tree / "repository/repodata/repomd.xml").write_bytes(b"metadata")
        self.log = self.root / "access.jsonl"

    def test_serves_files_and_writes_canonical_privacy_safe_records(self):
        outside = self.root / "outside"
        outside.write_text("secret")
        (self.tree / "escape").symlink_to(outside)
        server = iso_chain._fedora_server(self.tree, "127.0.0.1", 0, self.log)
        self.assertNotIsInstance(server, iso_chain.http.server.ThreadingHTTPServer)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        port = server.server_address[1]
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/repository/repodata/repomd.xml", timeout=5
        ) as response:
            self.assertEqual(response.read(), b"metadata")
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/missing", timeout=5)
        caught.exception.close()
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/escape", timeout=5)
        caught.exception.close()
        server.shutdown()
        thread.join(5)

        lines = self.log.read_bytes().splitlines(keepends=True)
        records = [json.loads(line) for line in lines]
        self.assertEqual([record["index"] for record in records], [1, 2, 3])
        self.assertEqual(records[0]["path"], "/repository/repodata/repomd.xml")
        self.assertEqual(records[0]["status"], 200)
        self.assertEqual(records[0]["bytes"], 8)
        self.assertEqual(records[1]["status"], 404)
        self.assertEqual(records[2]["status"], 404)
        for line, record in zip(lines, records, strict=True):
            self.assertEqual(
                line,
                json.dumps(record, sort_keys=True, separators=(",", ":")).encode() + b"\n",
            )
            self.assertEqual(set(record), {"method", "path", "status", "bytes", "index"})
        self.assertNotIn(b"127.0.0.1", self.log.read_bytes())

    def test_rejects_existing_log_and_symlink_escape(self):
        self.log.write_text("retain\n")
        with self.assertRaisesRegex(iso_chain.ValidationError, "access log"):
            iso_chain._fedora_server(self.tree, "127.0.0.1", 0, self.log)
        self.assertEqual(self.log.read_text(), "retain\n")

    def test_parser_exposes_server_contract(self):
        args = iso_chain.parser().parse_args(
            [
                "serve-fedora-source",
                "--directory",
                str(self.tree),
                "--bind",
                "127.0.0.1",
                "--port",
                "8000",
                "--access-log",
                str(self.log),
            ]
        )
        self.assertEqual(args.command, "serve-fedora-source")
        self.assertEqual(args.port, 8000)


class PrepareTests(unittest.TestCase):
    def setUp(self):
        self.temp = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(self.temp)
        self.kernel_tree = self.root / "modules" / "6.17.1"
        self.kernel_tree.mkdir(parents=True)
        self.output = self.root / "initramfs.img"

    def args(self, **changes):
        values = {"kernel_version": "6.17.1", "output": self.output}
        values.update(changes)
        return SimpleNamespace(**values)

    def test_prepare_rejects_non_ppc64le_before_running_a_tool(self):
        with (
            mock.patch.object(platform, "machine", return_value="x86_64"),
            mock.patch("scripts.iso_chain.subprocess.run") as run,
            self.assertRaisesRegex(iso_chain.ValidationError, "ppc64le"),
        ):
            iso_chain.prepare_initramfs(self.args())
        run.assert_not_called()

    def test_prepare_checks_tools_flags_kernel_and_assets_before_dracut(self):
        assets = self.root / "assets"
        assets.mkdir()
        with (
            mock.patch.object(platform, "machine", return_value="ppc64le"),
            mock.patch.object(iso_chain, "DRACUT_ASSETS", assets),
            mock.patch.object(iso_chain, "KERNEL_MODULES", self.root / "modules"),
            mock.patch("scripts.iso_chain.shutil.which", return_value="/usr/bin/dracut"),
            mock.patch("scripts.iso_chain.subprocess.run") as run,
            self.assertRaisesRegex(iso_chain.ValidationError, "launcher asset"),
        ):
            iso_chain.prepare_initramfs(self.args())
        run.assert_not_called()

    def test_prepare_uses_fixed_dracut_arguments_and_publishes_once(self):
        required_flags = "--no-hostonly --reproducible --include --install --force-drivers"

        def fake_run(command, check, **kwargs):
            self.assertTrue(check)
            if command == ["/usr/bin/dracut", "--help"]:
                self.assertTrue(kwargs["capture_output"])
                return SimpleNamespace(stdout=required_flags)
            self.assertEqual(command[:3], ["/usr/bin/dracut", "--no-hostonly", "--reproducible"])
            self.assertIn("--add", command)
            self.assertIn("systemd", command)
            self.assertIn("--force-drivers", command)
            self.assertIn("virtio_net virtio_pci virtio_blk virtio_scsi", command)
            for target in (
                "/usr/libexec/iso-chain-launch.sh",
                "/etc/systemd/system/iso-chain-launch.service",
                "/etc/systemd/system/iso-chain.target",
            ):
                self.assertIn(target, command)
            installed = command[command.index("--install") + 1]
            for tool in ("sha256sum", "kexec", "mktemp", "stat", "sync"):
                self.assertIn(tool, installed)
            self.assertIn("--kver", command)
            self.assertEqual(command[command.index("--kver") + 1], "6.17.1")
            Path(command[-1]).write_bytes(b"initramfs")
            return SimpleNamespace(stdout="")

        with (
            mock.patch.object(platform, "machine", return_value="ppc64le"),
            mock.patch.object(iso_chain, "KERNEL_MODULES", self.root / "modules"),
            mock.patch("scripts.iso_chain.shutil.which", return_value="/usr/bin/dracut"),
            mock.patch("scripts.iso_chain.subprocess.run", side_effect=fake_run),
        ):
            iso_chain.prepare_initramfs(self.args())
        self.assertEqual(self.output.read_bytes(), b"initramfs")

        with (
            mock.patch.object(platform, "machine", return_value="ppc64le"),
            self.assertRaisesRegex(iso_chain.ValidationError, "already exists"),
        ):
            iso_chain.prepare_initramfs(self.args())

    def test_launcher_units_are_rootless_oneshot_and_terminal(self):
        assets = iso_chain.DRACUT_ASSETS
        service = (assets / "iso-chain-launch.service").read_text()
        target = (assets / "iso-chain.target").read_text()
        self.assertIn("DefaultDependencies=no", service)
        self.assertIn("After=systemd-udev-settle.service", service)
        self.assertIn("Type=oneshot", service)
        self.assertIn("RemainAfterExit=yes", service)
        self.assertIn("TimeoutStartSec=infinity", service)
        self.assertIn("StandardOutput=journal+console", service)
        self.assertIn("StandardError=journal+console", service)
        self.assertIn("OnFailure=emergency.target", service)
        self.assertIn("DefaultDependencies=no", target)
        self.assertIn("Requires=iso-chain-launch.service", target)
        self.assertIn("Requires=sysinit.target", target)
        self.assertIn("After=systemd-udev-settle.service iso-chain-launch.service", target)
        self.assertIn("After=sysinit.target", target)
        self.assertIn("OnFailure=emergency.target", target)
