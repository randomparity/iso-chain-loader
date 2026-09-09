import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from scripts import iso_chain

FIRST_ID = "11111111-1111-4111-8111-111111111111"
SECOND_ID = "22222222-2222-4222-8222-222222222222"


def manifest_data(**changes):
    data = {
        "version": 1,
        "lpar": "sys-r1",
        "network": {
            "mac": "52:54:00:12:34:56",
            "address": "10.0.2.15/24",
            "routes": [{"destination": "0.0.0.0/0", "gateway": "10.0.2.2"}],
            "dns": ["10.0.2.3"],
        },
        "source": "http://10.0.2.2:8000/probe",
        "profiles": ["fedora", "rhel"],
        "selected_profile": "fedora",
    }
    data.update(changes)
    return data


class ManifestTests(unittest.TestCase):
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
            (manifest_data(profiles=[]), "profiles"),
            (manifest_data(profiles=["fedora", "fedora"]), "profiles"),
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
            (manifest_data(source=f"http://10.0.2.2/probe?{opaque_value}"), "source"),
            (manifest_data(source="https://10.0.2.2/probe"), "source"),
            (manifest_data(source="http://10.0.2.2/a?ignored=value"), "source"),
        )
        for data, field in cases:
            with (
                self.subTest(data=data),
                self.assertRaisesRegex(iso_chain.ValidationError, field) as caught,
            ):
                self.load(data)
            self.assertNotIn(opaque_value, str(caught.exception))

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
            self.assertIn("menuentry 'rhel'", config)
            self.assertIn("iso_chain.mac=52:54:00:12:34:56", config)
            self.assertIn("iso_chain.address=10.0.2.15/24", config)
            self.assertIn("iso_chain.route=0.0.0.0/0,10.0.2.2", config)
            self.assertIn("iso_chain.dns=10.0.2.3", config)
            self.assertIn("iso_chain.source=http://10.0.2.2:8000/probe", config)
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
        other.write_text(json.dumps(manifest_data(selected_profile="rhel")))
        configs = []

        def fake_run(command, check):
            configs.append((Path(command[-1]) / "boot/grub/grub.cfg").read_text())
            Path(command[-2]).write_bytes(b"iso")

        with mock.patch("scripts.iso_chain.subprocess.run", side_effect=fake_run):
            iso_chain.build_iso(self.args(output=self.root / "first.iso"))
            iso_chain.build_iso(self.args(config=other, output=self.root / "second.iso"))
        self.assertIn('set default="fedora"', configs[0])
        self.assertIn('set default="rhel"', configs[1])
        self.assertNotEqual(configs[0], configs[1])

        huge_profile = "p" + "a" * 2047
        huge_manifest = iso_chain.Manifest(
            version=1,
            lpar="sys-r1",
            network=iso_chain.NetworkConfig(
                mac="52:54:00:12:34:56",
                address="10.0.2.15/24",
                routes=(("0.0.0.0/0", "10.0.2.2"),),
                dns=("10.0.2.3",),
            ),
            source="http://10.0.2.2:8000/probe",
            profiles=(huge_profile,),
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

    def test_qemu_command_is_fixed_and_network_disabled(self):
        command = iso_chain.qemu_command(Path("/tmp/test.iso"), Path("/tmp/disk.qcow2"))
        self.assertEqual(command.count("-nic"), 1)
        for flag, value in {
            "-nic": "none",
            "-cpu": "power9",
            "-machine": "pseries,accel=tcg",
        }.items():
            self.assertEqual(command[command.index(flag) + 1], value)
        self.assertIn("-snapshot", command)
        self.assertIn("scsi-cd,drive=cdrom,bootindex=1", command)
        self.assertIn(
            "file=/tmp/test.iso,format=raw,media=cdrom,readonly=on,if=none,id=cdrom", command
        )
        self.assertIn(
            "file=/tmp/a,,b,format=qcow2,if=virtio",
            iso_chain.qemu_command(Path("x"), Path("/tmp/a,b")),
        )

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
