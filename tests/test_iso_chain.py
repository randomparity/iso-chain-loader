import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from scripts import iso_chain

FIRST_ID = "11111111-1111-4111-8111-111111111111"
SECOND_ID = "22222222-2222-4222-8222-222222222222"


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

    def args(self, **changes):
        values = {
            "grub_modules": self.modules,
            "kernel": self.kernel,
            "initramfs": self.initramfs,
            "kernel_args": "root=/dev/vda3 rootflags=subvol=root ro",
            "output": self.output,
        }
        values.update(changes)
        return SimpleNamespace(**values)

    def test_build_stages_fixed_config_and_publishes_once(self):
        def fake_run(command, check):
            self.assertTrue(check)
            self.assertEqual(command[:3], ["grub2-mkrescue", "-d", str(self.modules.resolve())])
            stage = Path(command[-1])
            config = (stage / "boot/grub/grub.cfg").read_text()
            self.assertIn("ISO_CHAIN: GRUB optical handoff", config)
            self.assertIn("console=hvc0 rd.neednet=0 ip=off iso_chain_stage=optical", config)
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
            {"kernel_args": "root=/dev/vda3\nmenuentry bad"},
            {"kernel_args": "root=/dev/vda3 ip=dhcp"},
            {"kernel_args": "root=/dev/vda3 rd.neednet=1"},
            {"kernel_args": "root=/dev/vda3 quiet;reboot"},
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
