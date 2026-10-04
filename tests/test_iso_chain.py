import dataclasses
import hashlib
import io
import json
import os
import platform
import re
import shlex
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from scripts import iso_chain

FIRST_ID = "11111111-1111-4111-8111-111111111111"
SECOND_ID = "22222222-2222-4222-8222-222222222222"
KEY = "ssh-ed25519 AAAA test-key"
REPOSITORY = Path(__file__).resolve().parents[1]
INTERRUPTIBLE_CLI = (
    "import signal, sys; from scripts import iso_chain; "
    "iso_chain.MAX_INSTALL_CAPTURE_BYTES = 1; "
    "signal.signal(signal.SIGHUP, signal.SIG_DFL); "
    "signal.signal(signal.SIGTERM, signal.SIG_DFL); "
    "raise SystemExit(iso_chain.main())"
)
FAKE_INSTALL_TOOL = """#!{python}
import os, pathlib, sys, time
name = pathlib.Path(sys.argv[0]).name
if name == "qemu-img" and os.environ["FAKE_HANG"] != name:
    pathlib.Path(sys.argv[4]).write_bytes(b"fresh")
    sys.exit(0)
for value in sys.argv:
    if value.startswith("filter-dump,"):
        capture = open(value.rsplit("file=", 1)[1], "wb")
pid = pathlib.Path(os.environ["FAKE_PIDS"], name + ".tmp")
pid.write_text(str(os.getpid()))
pid.replace(pid.with_suffix(""))
time.sleep(60)
"""


def manifest_data(**changes):
    profile = {
        "distribution": "fedora",
        "release": "44",
        "kernel": {"path": "/repository/ppc/ppc64/vmlinuz", "size": 6, "sha256": "1" * 64},
        "initramfs": {
            "path": "/repository/ppc/ppc64/initrd.img",
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
        "version": 4,
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


def ubuntu_profile():
    return {
        "distribution": "ubuntu",
        "release": "26.04.1",
        "kernel": {"path": "/ubuntu/netboot/ppc64el/linux", "size": 6, "sha256": "6" * 64},
        "initramfs": {
            "path": "/ubuntu/netboot/ppc64el/initrd",
            "size": 9,
            "sha256": "7" * 64,
        },
        "live_iso": {
            "path": "/ubuntu/ubuntu-26.04.1-live-server-ppc64el.iso",
            "size": 13,
            "sha256": "8" * 64,
        },
        "minimum_memory_mib": 4096,
    }


def ubuntu_manifest_data(**changes):
    return manifest_data(
        **{"profiles": {"ubuntu": ubuntu_profile()}, "selected_profile": "ubuntu", **changes}
    )


def rocky_profile():
    base = "/pub/rocky/9.8/BaseOS/ppc64le/os"
    return {
        "distribution": "rocky",
        "release": "9.8",
        "kernel": {"path": f"{base}/ppc/ppc64/vmlinuz", "size": 6, "sha256": "a" * 64},
        "initramfs": {"path": f"{base}/ppc/ppc64/initrd.img", "size": 9, "sha256": "b" * 64},
        "repository": {
            "path": base,
            "treeinfo": {"size": 10, "sha256": "c" * 64},
            "repomd": {"size": 11, "sha256": "d" * 64},
        },
        "minimum_memory_mib": 4096,
    }


def rocky_manifest_data(**changes):
    return manifest_data(
        **{"profiles": {"rocky": rocky_profile()}, "selected_profile": "rocky", **changes}
    )


def opensuse_profile():
    base = "/distribution/leap/15.6/repo/oss"
    return {
        "distribution": "opensuse",
        "release": "15.6",
        "kernel": {"path": f"{base}/boot/ppc64le/linux", "size": 6, "sha256": "e" * 64},
        "initramfs": {"path": f"{base}/boot/ppc64le/initrd", "size": 9, "sha256": "f" * 64},
        "repository": {"path": base},
        "minimum_memory_mib": 4096,
    }


def opensuse_manifest_data(**changes):
    return manifest_data(
        **{"profiles": {"opensuse": opensuse_profile()}, "selected_profile": "opensuse", **changes}
    )


def target_request(**changes):
    network = dict(manifest_data()["network"])
    del network["mac"]
    data = {
        "format": "iso-chain-target-v1",
        "profile": "rocky-9.8",
        "lpar": "sys-r1",
        "mac": "52:54:00:12:34:56",
        "network": network,
        "operation_binding": "0" * 32,
    }
    data.update(changes)
    return data


def base_manifest(**changes):
    data = {
        "version": 4,
        "source": "http://10.0.2.2:8000",
        "profiles": {"rocky": rocky_profile(), "ubuntu": ubuntu_profile()},
    }
    data.update(changes)
    return data


class TargetRequestTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.target = self.root / "target.json"
        self.base = self.root / "base.json"
        self.base.write_text(json.dumps(base_manifest()))

    def compose(self, request):
        self.target.write_text(json.dumps(request))
        return iso_chain.load_manifest_bytes(
            iso_chain.compose_target_manifest(self.target, self.base)
        )

    def test_composes_one_profile_manifest(self):
        manifest, _, _ = self.compose(target_request())
        self.assertEqual([name for name, _ in manifest.profiles], ["rocky"])
        self.assertEqual(manifest.selected_profile, "rocky")
        self.assertEqual(manifest.network.mac, "52:54:00:12:34:56")
        self.assertEqual(manifest.operation_binding, "0" * 32)
        unbound = target_request()
        del unbound["operation_binding"]
        self.assertIsNone(self.compose(unbound)[0].operation_binding)

    def test_rejects_bad_requests_without_echo(self):
        opaque = "opaque-request-value"
        network = target_request()["network"]
        cases = [
            target_request(format="iso-chain-target-v2"),
            target_request(profile="fedora-44"),
            target_request(profile=[opaque]),
            target_request(ssh_authorized_keys=[opaque]),
            target_request(ssh_authorized_keys=[opaque + "\n"], login_user="core"),
            target_request(ssh_authorized_keys=[KEY], login_user=opaque.upper()),
            target_request(network=dict(network, address=opaque)),
            target_request(network=dict(network, mac=opaque)),
            target_request(mac=opaque),
            target_request(lpar=opaque.upper()),
            target_request(profile="ubuntu-26.04.1", network=dict(network, dns=["10.0.2.3"] * 3)),
        ]
        for request in cases:
            with (
                self.subTest(request=request),
                self.assertRaises(iso_chain.ValidationError) as caught,
            ):
                self.compose(request)
            self.assertNotIn(opaque, str(caught.exception))
        bases = [
            (base_manifest(profiles={"rocky": rocky_profile(), "rocky2": rocky_profile()}), "one"),
            (base_manifest(lpar="sys-r1"), "base"),
            (base_manifest(profiles=[rocky_profile()]), "base.profiles"),
            (base_manifest(profiles={}), "base.profiles"),
        ]
        for base, message in bases:
            self.base.write_text(json.dumps(base))
            with (
                self.subTest(base=base),
                self.assertRaisesRegex(iso_chain.ValidationError, message),
            ):
                self.compose(target_request())
        self.base.write_text(json.dumps(base_manifest()))
        self.target.write_text("[" * (iso_chain.MAX_MANIFEST_BYTES + 1))
        with self.assertRaisesRegex(iso_chain.ValidationError, "target file: exceeds 2 MiB"):
            iso_chain.compose_target_manifest(self.target, self.base)
        self.target.write_text("[" * iso_chain.MAX_MANIFEST_BYTES)
        with self.assertRaisesRegex(iso_chain.ValidationError, "target JSON: invalid"):
            iso_chain.compose_target_manifest(self.target, self.base)
        with self.assertRaisesRegex(iso_chain.ValidationError, "manifest JSON: invalid"):
            iso_chain.load_manifest_bytes(b"[" * (64 * 1024))
        self.target.write_text('{"format": "iso-chain-target-v1", "format": "x"}')
        with self.assertRaisesRegex(iso_chain.ValidationError, "duplicate key"):
            iso_chain.compose_target_manifest(self.target, self.base)

    def test_composes_login_values(self):
        manifest, canonical, _ = self.compose(
            target_request(ssh_authorized_keys=[KEY], login_user="core")
        )
        self.assertEqual(manifest.ssh_authorized_keys, (KEY,))
        self.assertEqual(manifest.login_user, "core")
        self.assertIn(b'"login_user":"core"', canonical)
        self.assertIn(b'"ssh_authorized_keys":["' + KEY.encode() + b'"]', canonical)

    def test_accepts_maximal_escaped_request(self):
        keys = ["\U0001f600" * iso_chain.MAX_KEY_LENGTH] * iso_chain.MAX_KEYS
        manifest, _, _ = self.compose(target_request(ssh_authorized_keys=keys, login_user="core"))
        self.assertEqual(manifest.ssh_authorized_keys, tuple(keys))


class ManifestV4Tests(unittest.TestCase):
    def setUp(self):
        self.temp = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(self.temp)

    def load(self, data, name="manifest.json"):
        path = self.root / name
        path.write_text(json.dumps(data))
        return iso_chain.load_manifest(path)

    def test_operation_binding_is_optional_and_exact(self):
        manifest, _, digest = self.load(manifest_data())
        self.assertIsNone(manifest.operation_binding)
        bound, bound_canonical, bound_digest = self.load(manifest_data(operation_binding="0" * 32))
        self.assertEqual(bound.operation_binding, "0" * 32)
        self.assertIn(b'"operation_binding":"' + b"0" * 32 + b'"', bound_canonical)
        self.assertNotEqual(digest, bound_digest)
        rebuilt = json.dumps(
            iso_chain._manifest_data(bound),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        self.assertEqual(rebuilt.encode() + b"\n", bound_canonical)
        for value in ("A" * 32, "0" * 31, 7, None, "opaque-binding-value"):
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(iso_chain.ValidationError, "operation_binding") as caught,
            ):
                self.load(manifest_data(operation_binding=value))
            self.assertNotIn("opaque-binding-value", str(caught.exception))

    def test_login_values_are_optional_bounded_and_not_echoed(self):
        keyless, plain, plain_digest = self.load(manifest_data())
        self.assertNotIn(b"login_user", plain)
        self.assertNotIn(b"ssh_authorized_keys", plain)
        self.assertEqual((keyless.ssh_authorized_keys, keyless.login_user), ((), None))
        keys = [KEY, "ssh-ed25519 AAAA \u043a\u043b\u044e\u0447"]
        manifest, canonical, digest = self.load(
            manifest_data(ssh_authorized_keys=keys, login_user="core")
        )
        self.assertEqual(manifest.ssh_authorized_keys, tuple(keys))
        self.assertEqual(manifest.login_user, "core")
        self.assertNotEqual(digest, plain_digest)
        self.assertEqual(iso_chain._canonical_bytes(iso_chain._manifest_data(manifest)), canonical)
        self.assertEqual(iso_chain._canonical_bytes(iso_chain._manifest_data(keyless)), plain)
        opaque = "opaque-login"
        cases = [
            ({"ssh_authorized_keys": [opaque]}, "must appear together"),
            ({"login_user": opaque}, "must appear together"),
            ({"ssh_authorized_keys": [], "login_user": "core"}, "1 to 16 keys"),
            ({"ssh_authorized_keys": [KEY] * 17, "login_user": "core"}, "1 to 16 keys"),
            ({"ssh_authorized_keys": opaque, "login_user": "core"}, "1 to 16 keys"),
            ({"ssh_authorized_keys": [7], "login_user": "core"}, r"\[0\]"),
            ({"ssh_authorized_keys": [""], "login_user": "core"}, r"\[0\]"),
            ({"ssh_authorized_keys": [KEY, "a" * 8193], "login_user": "core"}, r"\[1\]"),
            ({"ssh_authorized_keys": [opaque + "\nb"], "login_user": "core"}, r"\[0\]"),
            ({"ssh_authorized_keys": [opaque + "\u2028"], "login_user": "core"}, r"\[0\]"),
            ({"ssh_authorized_keys": [KEY], "login_user": "Opaque-login"}, "login_user"),
            ({"ssh_authorized_keys": [KEY], "login_user": "0" + opaque}, "login_user"),
            ({"ssh_authorized_keys": [KEY], "login_user": "a" * 33}, "login_user"),
            ({"ssh_authorized_keys": [KEY], "login_user": 7}, "login_user"),
            ({"ssh_authorized_keys": [KEY], "login_user": opaque + "\n"}, "login_user"),
        ]
        for changes, message in cases:
            with (
                self.subTest(changes=changes),
                self.assertRaisesRegex(iso_chain.ValidationError, message) as caught,
            ):
                self.load(manifest_data(**changes))
            self.assertNotIn(opaque, str(caught.exception))
        self.load(manifest_data(ssh_authorized_keys=["a" * 8192] * 16, login_user="_" + "a" * 31))

    def test_ubuntu_profile_parses_exact_fields(self):
        manifest, _, _ = self.load(ubuntu_manifest_data())
        profile = manifest.profile("ubuntu")
        self.assertEqual(profile.live_iso.path, "/ubuntu/ubuntu-26.04.1-live-server-ppc64el.iso")
        self.assertEqual(profile.live_iso.size, 13)
        self.assertIsNone(profile.repository)
        self.assertIsNone(profile.kickstart)

    def test_ubuntu_profile_rejects_shape_and_release_without_echoing_input(self):
        fedora = manifest_data()["profiles"]["fedora"]
        cases = []
        cases.append(dict(ubuntu_profile(), kickstart=fedora["kickstart"]))
        missing = ubuntu_profile()
        del missing["live_iso"]
        cases.append(missing)
        img = ubuntu_profile()
        img["live_iso"] = dict(img["live_iso"], path="/ubuntu/secret-live.img")
        cases.append(img)
        big = ubuntu_profile()
        big["live_iso"] = dict(big["live_iso"], size=4 * 1024**3 + 1)
        cases.append(big)
        cases.append(dict(ubuntu_profile(), release="26.04"))
        cases.append(dict(fedora, distribution="debian"))
        for profile in cases:
            data = ubuntu_manifest_data(profiles={"ubuntu": profile})
            with self.subTest(profile=profile), self.assertRaises(iso_chain.ValidationError) as e:
                self.load(data)
            for leaked in ("secret-live", '26.04"', "debian", str(4 * 1024**3 + 1)):
                self.assertNotIn(leaked, str(e.exception))
        with self.assertRaisesRegex(
            iso_chain.ValidationError,
            "must be fedora/44, opensuse/15.6, rocky/9.8, or ubuntu/26.04.1",
        ):
            self.load(ubuntu_manifest_data(profiles={"ubuntu": cases[4]}))

    def test_ubuntu_profile_requires_the_handoff_network_subset(self):
        message = (
            "profiles.ubuntu: ubuntu handoff supports only the default route and at most "
            "two DNS servers"
        )
        extra_route = manifest_data()["network"]
        extra_route["routes"].append({"destination": "192.0.2.0/24", "gateway": "10.0.2.2"})
        three_dns = dict(manifest_data()["network"], dns=["10.0.2.3", "10.0.2.4", "10.0.2.5"])
        mixed = manifest_data(network=extra_route)
        mixed["profiles"]["ubuntu"] = ubuntu_profile()
        for data in (
            ubuntu_manifest_data(network=extra_route),
            ubuntu_manifest_data(network=three_dns),
            mixed,
        ):
            with (
                self.subTest(data=data),
                self.assertRaisesRegex(iso_chain.ValidationError, message),
            ):
                self.load(data)
        self.load(manifest_data(network=extra_route))
        two_dns = dict(manifest_data()["network"], dns=["10.0.2.3", "10.0.2.4"])
        self.load(ubuntu_manifest_data(network=two_dns))

    def test_ubuntu_kernel_arguments_name_the_live_iso(self):
        manifest, _, digest = self.load(ubuntu_manifest_data())
        arguments = iso_chain._kernel_arguments(manifest, digest, "ubuntu")
        self.assertIn(
            "iso_chain.profile_live_iso_path=/ubuntu/ubuntu-26.04.1-live-server-ppc64el.iso",
            arguments,
        )
        self.assertIn("iso_chain.profile_distribution=ubuntu", arguments)
        self.assertIn("iso_chain.profile_release=26.04.1", arguments)
        for prefix in (
            "iso_chain.profile_repository_path=",
            "iso_chain.profile_treeinfo",
            "iso_chain.profile_repomd",
            "iso_chain.profile_kickstart",
        ):
            self.assertFalse(any(argument.startswith(prefix) for argument in arguments))
        fedora, _, fedora_digest = self.load(manifest_data(), "fedora.json")
        self.assertFalse(
            any(
                argument.startswith("iso_chain.profile_live_iso_path=")
                for argument in iso_chain._kernel_arguments(fedora, fedora_digest, "fedora")
            )
        )

    def test_ubuntu_handoff_matches_the_static_network(self):
        manifest, _, _ = self.load(ubuntu_manifest_data())
        self.assertEqual(
            iso_chain._ubuntu_handoff(manifest, manifest.profile("ubuntu"), None),
            [
                "ip=10.0.2.15::10.0.2.2:255.255.255.0:sys-r1::off:10.0.2.3",
                "BOOTIF=01-52-54-00-12-34-56",
                "iso-url=http://10.0.2.2:8000/ubuntu/ubuntu-26.04.1-live-server-ppc64el.iso",
                "console=hvc0",
                "ipv6.disable=1",
            ],
        )
        no_dns = dict(manifest_data()["network"], dns=[])
        manifest, _, _ = self.load(ubuntu_manifest_data(network=no_dns), "no-dns.json")
        self.assertEqual(
            iso_chain._ubuntu_handoff(manifest, manifest.profile("ubuntu"), None)[0],
            "ip=10.0.2.15::10.0.2.2:255.255.255.0:sys-r1::off",
        )

    def test_rocky_profile_parses_without_kickstart(self):
        manifest, _, _ = self.load(rocky_manifest_data())
        profile = manifest.profile("rocky")
        self.assertEqual(profile.repository.path, "/pub/rocky/9.8/BaseOS/ppc64le/os")
        self.assertIsNone(profile.kickstart)
        self.assertIsNone(profile.live_iso)

    def test_rocky_profile_rejects_shape_suffix_and_release(self):
        fedora = manifest_data()["profiles"]["fedora"]
        suffix = rocky_profile()
        suffix["repository"] = dict(suffix["repository"], path="/secret/repository")
        cases = (
            (dict(rocky_profile(), kickstart=fedora["kickstart"]), "profiles.rocky: unknown field"),
            (suffix, "profiles.rocky.repository.path: must end in /BaseOS/ppc64le/os"),
            (dict(rocky_profile(), release="9"), "must be fedora/44, opensuse/15.6, rocky/9.8"),
        )
        for profile, message in cases:
            data = rocky_manifest_data(profiles={"rocky": profile})
            with self.subTest(message=message), self.assertRaises(iso_chain.ValidationError) as e:
                self.load(data)
            self.assertIn(message, str(e.exception))
            self.assertNotIn("secret", str(e.exception))

    def test_rocky_profile_allows_every_network_shape(self):
        network = manifest_data()["network"]
        network["routes"].append({"destination": "192.0.2.0/24", "gateway": "10.0.2.2"})
        network["dns"] = ["10.0.2.3", "10.0.2.4", "10.0.2.5"]
        self.load(rocky_manifest_data(network=network))

    def test_rocky_kernel_arguments_carry_the_repository_and_no_kickstart(self):
        manifest, _, digest = self.load(rocky_manifest_data())
        arguments = iso_chain._kernel_arguments(manifest, digest, "rocky")
        self.assertIn(
            "iso_chain.profile_repository_path=/pub/rocky/9.8/BaseOS/ppc64le/os", arguments
        )
        self.assertIn("iso_chain.profile_treeinfo_size=10", arguments)
        self.assertIn("iso_chain.profile_repomd_sha256=" + "d" * 64, arguments)
        for prefix in ("iso_chain.profile_kickstart", "iso_chain.profile_live_iso_path"):
            self.assertFalse(any(argument.startswith(prefix) for argument in arguments))

    def test_rocky_manifest_data_round_trips_to_the_canonical_digest(self):
        manifest, canonical, digest = self.load(rocky_manifest_data())
        rebuilt = (
            json.dumps(iso_chain._manifest_data(manifest), sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode()
        self.assertEqual(rebuilt, canonical)
        self.assertEqual(hashlib.sha256(rebuilt).hexdigest(), digest)

    def test_opensuse_profile_parses_with_a_path_only_repository(self):
        manifest, _, _ = self.load(opensuse_manifest_data())
        profile = manifest.profile("opensuse")
        self.assertEqual(profile.repository.path, "/distribution/leap/15.6/repo/oss")
        self.assertIsNone(profile.repository.treeinfo)
        self.assertIsNone(profile.repository.repomd)
        self.assertIsNone(profile.kickstart)
        self.assertIsNone(profile.live_iso)

    def test_opensuse_profile_rejects_shape_and_release_without_echoing_input(self):
        with_treeinfo = opensuse_profile()
        with_treeinfo["repository"] = dict(
            with_treeinfo["repository"], treeinfo={"size": 10, "sha256": "c" * 64}
        )
        secret_path = opensuse_profile()
        secret_path["repository"] = {"path": "/secret?token=1"}
        cases = (
            (with_treeinfo, "profiles.opensuse.repository: unknown field"),
            (dict(opensuse_profile(), release="15.5"), "must be fedora/44, opensuse/15.6, rocky"),
            (secret_path, "profiles.opensuse.repository.path"),
        )
        for profile, message in cases:
            data = opensuse_manifest_data(profiles={"opensuse": profile})
            with self.subTest(message=message), self.assertRaises(iso_chain.ValidationError) as e:
                self.load(data)
            self.assertIn(message, str(e.exception))
            self.assertNotIn("secret", str(e.exception))

    def test_opensuse_profile_requires_the_handoff_network_subset(self):
        message = (
            "profiles.opensuse: opensuse handoff supports only the default route and at most "
            "one DNS server"
        )
        extra_route = manifest_data()["network"]
        extra_route["routes"].append({"destination": "192.0.2.0/24", "gateway": "10.0.2.2"})
        two_dns = dict(manifest_data()["network"], dns=["10.0.2.3", "10.0.2.4"])
        for network in (extra_route, two_dns):
            with (
                self.subTest(network=network),
                self.assertRaisesRegex(iso_chain.ValidationError, message),
            ):
                self.load(opensuse_manifest_data(network=network))
        self.load(manifest_data(network=extra_route))

    def test_opensuse_kernel_arguments(self):
        manifest, _, digest = self.load(opensuse_manifest_data())
        arguments = iso_chain._kernel_arguments(manifest, digest, "opensuse")
        self.assertIn(
            "iso_chain.profile_repository_path=/distribution/leap/15.6/repo/oss", arguments
        )
        for prefix in (
            "iso_chain.profile_treeinfo",
            "iso_chain.profile_repomd",
            "iso_chain.profile_kickstart",
            "iso_chain.profile_live_iso",
        ):
            self.assertFalse(any(argument.startswith(prefix) for argument in arguments))

    def test_opensuse_manifest_round_trips(self):
        manifest, canonical, digest = self.load(opensuse_manifest_data())
        rebuilt = (
            json.dumps(iso_chain._manifest_data(manifest), sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode()
        self.assertEqual(rebuilt, canonical)
        self.assertEqual(hashlib.sha256(rebuilt).hexdigest(), digest)

    def test_rejects_version_3(self):
        with self.assertRaisesRegex(
            iso_chain.ValidationError, "manifest version: 3 is no longer supported"
        ):
            self.load(manifest_data(version=3))

    def test_rejects_non_media_kickstart_paths(self):
        for path in (
            "/ks.cfg",
            "/profiles/ks.cfg",
            "/profiles/a/b/ks.cfg",
            "/boot/ks.cfg",
            "/profiles/a+b/ks.cfg",
        ):
            data = manifest_data()
            data["profiles"]["fedora"] = dict(
                data["profiles"]["fedora"],
                kickstart={"path": path, "size": 12, "sha256": "5" * 64},
            )
            with (
                self.subTest(path=path),
                self.assertRaisesRegex(iso_chain.ValidationError, "media path"),
            ):
                self.load(data)

    def test_rejects_conflicting_shared_media_path(self):
        data = manifest_data()
        rescue = dict(data["profiles"]["rescue"])
        rescue["kickstart"] = dict(rescue["kickstart"], sha256="9" * 64)
        data["profiles"]["rescue"] = rescue
        with self.assertRaisesRegex(iso_chain.ValidationError, "reuses a media path"):
            self.load(data)

    def test_kernel_arguments_carry_the_media_kickstart(self):
        manifest, _, digest = self.load(manifest_data())
        arguments = iso_chain._kernel_arguments(manifest, digest, "fedora")
        for argument in (
            "iso_chain.profile_kickstart_path=/profiles/fedora-44/ks.cfg",
            "iso_chain.profile_kickstart_size=12",
            f"iso_chain.profile_kickstart_sha256={'5' * 64}",
        ):
            self.assertIn(argument, arguments)

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

    def test_accepts_https_source(self):
        manifest, _, _ = self.load(manifest_data(source="https://mirror.example"))
        self.assertEqual(manifest.source, "https://mirror.example")

    def test_accepts_https_source_with_canonical_base_path(self):
        manifest, _, _ = self.load(manifest_data(source="https://mirror.example/fedora/44"))
        self.assertEqual(manifest.source, "https://mirror.example/fedora/44")

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

    def test_rejects_manifest_larger_than_2_mib(self):
        path = self.root / "large.json"
        path.write_bytes(b" " * (iso_chain.MAX_MANIFEST_BYTES + 1))
        with self.assertRaisesRegex(iso_chain.ValidationError, "exceeds 2 MiB"):
            iso_chain.load_manifest(path)

    def test_profile_contract_and_derived_repository_paths(self):
        manifest, _, _ = self.load(manifest_data())
        profile = manifest.profile("fedora")
        self.assertEqual(profile.distribution, "fedora")
        self.assertEqual(profile.release, "44")
        self.assertEqual(profile.repository.treeinfo.path, "/repository/.treeinfo")
        self.assertEqual(profile.repository.repomd.path, "/repository/repodata/repomd.xml")
        self.assertEqual(profile.kickstart.path, "/profiles/fedora-44/ks.cfg")
        self.assertEqual(profile.minimum_memory_mib, 4096)

    def test_kernel_arguments_bind_the_selected_profile(self):
        manifest, _, digest = self.load(manifest_data())
        arguments = iso_chain._kernel_arguments(manifest, digest, "fedora")
        self.assertIn("iso_chain.lpar=sys-r1", arguments)
        self.assertIn("iso_chain.profile_distribution=fedora", arguments)
        self.assertIn("iso_chain.profile_release=44", arguments)
        self.assertIn("iso_chain.profile_kernel_path=/repository/ppc/ppc64/vmlinuz", arguments)
        self.assertIn("iso_chain.profile_kernel_size=6", arguments)
        self.assertIn("iso_chain.profile_kernel_sha256=" + "1" * 64, arguments)
        self.assertIn("iso_chain.profile_repository_path=/repository", arguments)
        self.assertIn("iso_chain.profile_treeinfo_sha256=" + "3" * 64, arguments)
        self.assertIn("iso_chain.profile_repomd_sha256=" + "4" * 64, arguments)
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

    def test_accepts_fedora_repository_filename_characters(self):
        self.assertEqual(
            iso_chain._url_path(
                "/repository/Packages/c/compsize-1.5^git20250123.d79eacf-15.fc44.ppc64le.rpm",
                "path",
            ),
            "/repository/Packages/c/compsize-1.5^git20250123.d79eacf-15.fc44.ppc64le.rpm",
        )


def write_profile_tree(root: Path) -> dict:
    content = b"ks\n"
    directory = root / "profiles/fedora-44"
    directory.mkdir(parents=True)
    (directory / "ks.cfg").write_bytes(content)
    data = manifest_data()
    for profile in data["profiles"].values():
        profile["kickstart"] = {
            "path": "/profiles/fedora-44/ks.cfg",
            "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }
    return data


def installer_command_line(manifest, digest, kickstart_argument=None):
    if kickstart_argument is None:
        path = manifest.profile("fedora").kickstart.path
        kickstart_argument = f"inst.ks=cdrom:LABEL={iso_chain._volume_id(digest)}:{path}"
    return (
        "[    1.000000] Kernel command line: inst.text rd.neednet=1 "
        f"{kickstart_argument} console=hvc0 ipv6.disable=1"
    )


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
        self.profiles = self.root / "prepared"
        self.config = self.root / "manifest.json"
        self.config.write_text(json.dumps(write_profile_tree(self.profiles)))

    def args(self, **changes):
        values = {
            "grub_modules": self.modules,
            "kernel": self.kernel,
            "initramfs": self.initramfs,
            "config": self.config,
            "output": self.output,
            "profiles": self.profiles,
            "target": None,
            "base_config": None,
            "publish_dir": None,
            "publish_url": None,
        }
        values.update(changes)
        return SimpleNamespace(**values)

    def publish_args(self, request):
        publish = self.root / "publish"
        publish.mkdir(exist_ok=True)
        target = self.root / "target.json"
        target.write_text(json.dumps(request))
        base = self.root / "base.json"
        base.write_text(json.dumps(base_manifest()))
        return self.args(
            config=None,
            output=None,
            target=target,
            base_config=base,
            publish_dir=publish,
            publish_url="https://media.example/iso",
        )

    def test_refuses_login_values_unless_all_rocky_or_all_ubuntu_before_grub(self):
        login = {"ssh_authorized_keys": [KEY], "login_user": "core"}
        fedora = json.loads(self.config.read_text())
        mixed = rocky_manifest_data(
            profiles={"rocky": rocky_profile(), "ubuntu": ubuntu_profile()}, **login
        )
        beside_fedora = ubuntu_manifest_data(
            profiles={"ubuntu": ubuntu_profile(), "fedora": manifest_data()["profiles"]["fedora"]},
            **login,
        )
        for data in (
            dict(fedora, **login),
            opensuse_manifest_data(**login),
            mixed,
            beside_fedora,
        ):
            self.config.write_text(json.dumps(data))
            with (
                self.subTest(profiles=sorted(data["profiles"])),
                mock.patch("scripts.iso_chain.subprocess.run") as run,
                self.assertRaisesRegex(
                    iso_chain.ValidationError,
                    "every profile must be rocky, or every profile ubuntu",
                ),
            ):
                iso_chain.build_iso(self.args())
            run.assert_not_called()

    def test_refuses_an_unrenderable_ubuntu_lpar_without_echoing_it(self):
        data = ubuntu_manifest_data(ssh_authorized_keys=[KEY], login_user="core", lpar="sys-r1-")
        self.config.write_text(json.dumps(data))
        with (
            mock.patch("scripts.iso_chain.subprocess.run") as run,
            self.assertRaisesRegex(iso_chain.ValidationError, "lpar") as caught,
        ):
            iso_chain.build_iso(self.args())
        run.assert_not_called()
        self.assertNotIn("sys-r1-", str(caught.exception))

    def test_ubuntu_login_values_stage_and_bind_user_data(self):
        data = ubuntu_manifest_data(ssh_authorized_keys=[KEY], login_user="core")
        self.config.write_text(json.dumps(data))
        manifest, _, digest = iso_chain.load_manifest(self.config)
        rendered = iso_chain._ubuntu_user_data(manifest)
        sha256 = hashlib.sha256(rendered).hexdigest()
        empty = self.root / "empty-profiles"
        empty.mkdir()

        def fake_run(command, check, **kwargs):
            stage = Path(command[5])
            self.assertEqual((stage / "user-data").read_bytes(), rendered)
            self.assertEqual((stage / "meta-data").read_bytes(), b"")
            self.assertFalse((stage / "profiles").exists())
            config = (stage / "boot/grub/grub.cfg").read_text()
            self.assertIn(f" iso_chain.profile_user_data_size={len(rendered)} ", config)
            self.assertIn(f" iso_chain.profile_user_data_sha256={sha256} ", config)
            self.assertIn("load_env --file", config)
            Path(command[4]).write_bytes(b"iso")

        with mock.patch("scripts.iso_chain.subprocess.run", side_effect=fake_run) as run:
            result = json.loads(iso_chain.build_iso(self.args(profiles=empty)))
        run.assert_called_once()
        self.assertEqual((result["distribution"], result["release"]), ("ubuntu", "26.04.1"))
        self.assertNotIn("core", json.dumps(result))
        arguments = iso_chain._kernel_arguments(manifest, digest, "ubuntu")
        live = arguments.index(
            "iso_chain.profile_live_iso_path=/ubuntu/ubuntu-26.04.1-live-server-ppc64el.iso"
        )
        self.assertEqual(
            arguments[live + 1 : live + 3],
            [
                f"iso_chain.profile_user_data_size={len(rendered)}",
                f"iso_chain.profile_user_data_sha256={sha256}",
            ],
        )
        self.assertEqual(iso_chain._profile_user_data(manifest, "ubuntu"), rendered)

    def test_keyless_ubuntu_command_line_names_no_user_data(self):
        manifest, _, digest = iso_chain.load_manifest_bytes(
            json.dumps(ubuntu_manifest_data()).encode()
        )
        arguments = iso_chain._kernel_arguments(manifest, digest, "ubuntu")
        self.assertFalse(any("user_data" in argument for argument in arguments))
        self.assertIsNone(iso_chain._profile_user_data(manifest, "ubuntu"))

    def test_refuses_unrenderable_rocky_login_values_without_echoing_them(self):
        opaque = "--opaque-key-value"
        for changes, field in (
            ({"ssh_authorized_keys": [KEY, opaque], "login_user": "core"}, r"\[1\]"),
            ({"ssh_authorized_keys": [KEY], "login_user": "core", "lpar": "sys-r1-"}, "lpar"),
        ):
            self.config.write_text(json.dumps(rocky_manifest_data(**changes)))
            with (
                self.subTest(field=field),
                mock.patch("scripts.iso_chain.subprocess.run") as run,
                self.assertRaisesRegex(iso_chain.ValidationError, field) as caught,
            ):
                iso_chain.build_iso(self.args())
            run.assert_not_called()
            self.assertNotIn(opaque, str(caught.exception))
            self.assertNotIn("sys-r1-", str(caught.exception))

    def test_rocky_login_values_stage_and_bind_a_derived_kickstart(self):
        data = rocky_manifest_data(ssh_authorized_keys=[KEY], login_user="core")
        self.config.write_text(json.dumps(data))
        manifest, _, digest = iso_chain.load_manifest(self.config)
        rendered = iso_chain._rocky_kickstart(manifest)
        empty = self.root / "empty-profiles"
        empty.mkdir()

        def fake_run(command, check, **kwargs):
            stage = Path(command[5])
            self.assertEqual((stage / "profiles/rocky/ks.cfg").read_bytes(), rendered)
            config = (stage / "boot/grub/grub.cfg").read_text()
            self.assertIn("iso_chain.profile_kickstart_path=/profiles/rocky/ks.cfg ", config)
            self.assertIn(f"iso_chain.profile_kickstart_size={len(rendered)} ", config)
            sha256 = hashlib.sha256(rendered).hexdigest()
            self.assertIn(f"iso_chain.profile_kickstart_sha256={sha256} ", config)
            Path(command[4]).write_bytes(b"iso")

        with mock.patch("scripts.iso_chain.subprocess.run", side_effect=fake_run) as run:
            result = json.loads(iso_chain.build_iso(self.args(profiles=empty)))
        run.assert_called_once()
        self.assertEqual((result["distribution"], result["release"]), ("rocky", "9.8"))
        self.assertNotIn("core", json.dumps(result))
        self.assertEqual(
            iso_chain._kernel_arguments(manifest, digest, "rocky")[-7:-4],
            [
                "iso_chain.profile_kickstart_path=/profiles/rocky/ks.cfg",
                f"iso_chain.profile_kickstart_size={len(rendered)}",
                f"iso_chain.profile_kickstart_sha256={hashlib.sha256(rendered).hexdigest()}",
            ],
        )

    def test_keyless_rocky_command_line_names_no_kickstart(self):
        manifest, _, digest = iso_chain.load_manifest_bytes(
            json.dumps(rocky_manifest_data()).encode()
        )
        arguments = iso_chain._kernel_arguments(manifest, digest, "rocky")
        self.assertFalse(any("kickstart" in argument for argument in arguments))
        self.assertIsNone(iso_chain._profile_kickstart(manifest, "rocky"))

    def test_build_returns_canonical_media_result(self):
        data = json.loads(self.config.read_text())
        self.config.write_text(
            json.dumps(dict(data, profiles={"fedora": data["profiles"]["fedora"]}))
        )

        def fake_run(command, check, **kwargs):
            self.assertIs(kwargs["stdout"], sys.stderr)
            Path(command[4]).write_bytes(b"iso")

        with mock.patch("scripts.iso_chain.subprocess.run", side_effect=fake_run):
            encoded = iso_chain.build_iso(self.args())
        self.assertTrue(encoded.endswith(b"}\n"))
        result = json.loads(encoded)
        self.assertEqual(
            encoded, json.dumps(result, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        )
        self.assertEqual(
            sorted(result),
            [
                "architecture",
                "distribution",
                "format",
                "iso_sha256",
                "iso_size",
                "mac",
                "manifest_sha256",
                "network",
                "release",
            ],
        )
        self.assertEqual(result["format"], "iso-chain-media-v1")
        self.assertEqual(result["architecture"], "ppc64le")
        self.assertEqual(result["iso_sha256"], hashlib.sha256(b"iso").hexdigest())
        self.assertEqual(result["iso_size"], 3)
        self.assertEqual(result["manifest_sha256"], iso_chain.load_manifest(self.config)[2])
        self.assertEqual((result["distribution"], result["release"]), ("fedora", "44"))
        self.assertEqual(result["mac"], "52:54:00:12:34:56")
        self.assertEqual(
            result["network"],
            {
                "address": "10.0.2.15/24",
                "routes": [{"destination": "0.0.0.0/0", "gateway": "10.0.2.2"}],
                "dns": ["10.0.2.3"],
            },
        )

    def test_multi_profile_prepared_build_prints_no_result(self):
        self.config.write_text(
            json.dumps(
                manifest_data(profiles=base_manifest()["profiles"], selected_profile="rocky")
            )
        )

        def fake_run(command, check, **kwargs):
            Path(command[4]).write_bytes(b"iso")

        with mock.patch("scripts.iso_chain.subprocess.run", side_effect=fake_run):
            self.assertEqual(iso_chain.build_iso(self.args()), b"")
        self.assertTrue(self.output.is_file())

    def test_publishes_by_digest_with_url(self):
        args = self.publish_args(target_request())

        def fake_run(command, check, **kwargs):
            config = (Path(command[5]) / "boot/grub/grub.cfg").read_text()
            self.assertIn("menuentry 'rocky'", config)
            self.assertNotIn("menuentry 'ubuntu'", config)
            Path(command[4]).write_bytes(b"iso")

        with mock.patch("scripts.iso_chain.subprocess.run", side_effect=fake_run):
            result = json.loads(iso_chain.build_iso(args))
            with self.assertRaisesRegex(iso_chain.ValidationError, "appeared during build"):
                iso_chain.build_iso(args)
        name = hashlib.sha256(b"iso").hexdigest() + ".iso"
        self.assertEqual([path.name for path in args.publish_dir.iterdir()], [name])
        self.assertEqual(result["url"], "https://media.example/iso/" + name)
        self.assertEqual(result["operation_binding"], "0" * 32)
        self.assertEqual((result["distribution"], result["release"]), ("rocky", "9.8"))

    def test_rejects_input_and_publish_forms_before_tool(self):
        published = self.publish_args(target_request())
        unbound = target_request()
        del unbound["operation_binding"]
        unbound_path = self.root / "unbound.json"
        unbound_path.write_text(json.dumps(unbound))
        bound_config = self.root / "bound-manifest.json"
        bound_config.write_text(
            json.dumps(
                manifest_data(
                    profiles=base_manifest()["profiles"],
                    selected_profile="rocky",
                    operation_binding="0" * 32,
                )
            )
        )
        cases = [
            self.args(config=None),
            self.args(target=published.target),
            self.args(target=published.target, base_config=published.base_config),
            self.args(output=None),
            self.args(publish_dir=published.publish_dir),
            self.args(output=None, publish_dir=published.publish_dir),
            self.args(output=None, publish_url=published.publish_url),
            SimpleNamespace(**{**vars(published), "publish_url": "ftp://opaque-host"}),
            SimpleNamespace(**{**vars(published), "publish_url": "https://opaque-host/a/"}),
            SimpleNamespace(**{**vars(published), "publish_url": "https://opaque-host/a?"}),
            SimpleNamespace(**{**vars(published), "publish_url": "https://opaque-host/a#"}),
            self.args(config=None, target=published.target, base_config=published.base_config),
            SimpleNamespace(**{**vars(published), "target": unbound_path}),
            SimpleNamespace(
                **{**vars(published), "target": None, "base_config": None, "config": bound_config}
            ),
        ]
        with mock.patch("scripts.iso_chain.subprocess.run") as run:
            for args in cases:
                with (
                    self.subTest(args=vars(args)),
                    self.assertRaises(iso_chain.ValidationError) as caught,
                ):
                    iso_chain.build_iso(args)
                self.assertNotIn("opaque-host", str(caught.exception))
        run.assert_not_called()

    def test_build_stages_manifest_menu_and_publishes_once(self):
        def fake_run(command, check, **kwargs):
            self.assertTrue(check)
            self.assertEqual(command[:3], ["grub2-mkrescue", "-d", str(self.modules.resolve())])
            digest = iso_chain.load_manifest(self.config)[2]
            self.assertEqual(command[6:], ["--", "-volid", "ISO_CHAIN_" + digest[:16].upper()])
            stage = Path(command[5])
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
                line for line in config.splitlines() if line.startswith("set iso_chain_args_")
            ):
                self.assertIn("ipv6.disable=1", command_line.strip("'").split())
            self.assertIn("rd.systemd.unit=iso-chain.target", config)
            self.assertEqual(
                (stage / "iso-chain/config.json").read_bytes(),
                iso_chain.load_manifest(self.config)[1],
            )
            self.assertEqual(
                [(stage / name).read_bytes() for name in ("boot/vmlinuz", "boot/initramfs.img")],
                [b"kernel", b"initramfs"],
            )
            self.assertEqual(
                sorted(path.name for path in (stage / "profiles").rglob("*") if path.is_file()),
                ["ks.cfg"],
            )
            self.assertEqual((stage / "profiles/fedora-44/ks.cfg").read_bytes(), b"ks\n")
            Path(command[4]).write_bytes(b"iso")

        with mock.patch("scripts.iso_chain.subprocess.run", side_effect=fake_run):
            iso_chain.build_iso(self.args())
        self.assertEqual(self.output.read_bytes(), b"iso")

    def test_ubuntu_manifest_stages_no_kickstart(self):
        self.config.write_text(json.dumps(ubuntu_manifest_data()))
        empty = self.root / "empty-profiles"
        empty.mkdir()

        def fake_run(command, check, **kwargs):
            stage = Path(command[5])
            self.assertFalse((stage / "profiles").exists())
            self.assertFalse((stage / "user-data").exists())
            self.assertFalse((stage / "meta-data").exists())
            config = (stage / "boot/grub/grub.cfg").read_text()
            self.assertIn("iso_chain.profile_live_iso_path=", config)
            self.assertNotIn("load_env", config)
            Path(command[4]).write_bytes(b"iso")

        with mock.patch("scripts.iso_chain.subprocess.run", side_effect=fake_run) as run:
            iso_chain.build_iso(self.args(profiles=empty))
        run.assert_called_once()
        self.assertEqual(self.output.read_bytes(), b"iso")

    def test_rocky_manifest_stages_no_kickstart(self):
        self.config.write_text(json.dumps(rocky_manifest_data()))
        empty = self.root / "empty-profiles"
        empty.mkdir()

        def fake_run(command, check, **kwargs):
            stage = Path(command[5])
            self.assertFalse((stage / "profiles").exists())
            config = (stage / "boot/grub/grub.cfg").read_text()
            self.assertIn("iso_chain.profile_repository_path=/pub/rocky/9.8/", config)
            self.assertNotIn("iso_chain.profile_kickstart", config)
            Path(command[4]).write_bytes(b"iso")

        with mock.patch("scripts.iso_chain.subprocess.run", side_effect=fake_run) as run:
            iso_chain.build_iso(self.args(profiles=empty))
        run.assert_called_once()

    def test_opensuse_profile_stages_nothing(self):
        self.config.write_text(json.dumps(opensuse_manifest_data()))
        empty = self.root / "empty-profiles"
        empty.mkdir()

        def fake_run(command, check, **kwargs):
            stage = Path(command[5])
            self.assertFalse((stage / "profiles").exists())
            config = (stage / "boot/grub/grub.cfg").read_text()
            self.assertIn("iso_chain.profile_repository_path=/distribution/leap/15.6/", config)
            self.assertNotIn("iso_chain.profile_treeinfo", config)
            Path(command[4]).write_bytes(b"iso")

        with mock.patch("scripts.iso_chain.subprocess.run", side_effect=fake_run) as run:
            iso_chain.build_iso(self.args(profiles=empty))
        run.assert_called_once()

    def test_rejects_profile_digest_mismatch_before_running_tool(self):
        for name, content, label in (
            ("ks.cfg", b"k", "profile Kickstart: size does not match"),
            ("ks.cfg", b"kX\n", "profile Kickstart does not match the manifest"),
        ):
            target = self.profiles / "profiles/fedora-44" / name
            original = target.read_bytes()
            target.write_bytes(content)
            self.addCleanup(target.write_bytes, original)
            with (
                self.subTest(name=name),
                mock.patch("scripts.iso_chain.subprocess.run") as run,
                self.assertRaisesRegex(iso_chain.ValidationError, label),
            ):
                iso_chain.build_iso(self.args())
            run.assert_not_called()
            target.write_bytes(original)

    def test_build_rejects_bad_inputs_before_running_tool(self):
        for changes in (
            {"kernel": self.root / "missing"},
            {"initramfs": self.modules},
            {"grub_modules": self.kernel},
            {"config": self.root / "missing.json"},
            {"profiles": self.root / "missing"},
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

        def race(command, check, **kwargs):
            Path(command[4]).write_bytes(b"generated")
            self.output.write_bytes(b"racer")

        with (
            mock.patch("scripts.iso_chain.subprocess.run", side_effect=race),
            self.assertRaisesRegex(iso_chain.ValidationError, "appeared during build"),
        ):
            iso_chain.build_iso(self.args())
        self.assertEqual(self.output.read_bytes(), b"racer")

    def test_builds_distinct_manifests_and_rejects_too_long_command_before_tool(self):
        other = self.root / "other.json"
        other.write_text(
            json.dumps({**json.loads(self.config.read_text()), "selected_profile": "rescue"})
        )
        configs = []

        def fake_run(command, check, **kwargs):
            configs.append((Path(command[5]) / "boot/grub/grub.cfg").read_text())
            Path(command[4]).write_bytes(b"iso")

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

    def test_menu_entries_fit_the_powervm_cas_reboot_buffer(self):
        manifest, _, digest = iso_chain.load_manifest_bytes(json.dumps(manifest_data()).encode())
        config = iso_chain._grub_config(manifest, digest)
        entries = re.findall(r"^ *menuentry .*?^ *}$", config, re.MULTILINE | re.DOTALL)
        self.assertEqual(len(entries), len(manifest.profiles) + 1)
        installed, *profile_entries = entries
        self.assertIn("--id installed_disk", installed)
        self.assertLess(len(installed.encode()), 1024)
        for index, ((profile, _), entry) in enumerate(zip(manifest.profiles, profile_entries)):
            with self.subTest(profile=profile):
                arguments = " ".join(iso_chain._kernel_arguments(manifest, digest, profile))
                self.assertIn(f"set iso_chain_args_{index}='{arguments}'\n", config)
                self.assertIn(f"linux /boot/vmlinuz $iso_chain_args_{index}\n", entry)
                self.assertNotIn("iso_chain.", entry)
                self.assertLess(len(entry.encode()), 1024)

    def test_menu_offers_an_installed_disk_by_default(self):
        search = (
            "for iso_chain_directory in /grub2 /boot/grub2 /grub /boot/grub; do\n"
            '    if [ -z "$iso_chain_disk" ]; then\n'
            "        if search --no-floppy --file --set=iso_chain_disk"
            " $iso_chain_directory/grubenv; then\n"
            "            set iso_chain_config=$iso_chain_directory/grub.cfg\n"
            "        fi\n"
            "    fi\n"
            "done\n"
            'if [ -n "$iso_chain_disk" ]; then\n'
            "    set default=installed_disk\n"
            "    menuentry 'installed disk' --id installed_disk {\n"
            "        echo 'ISO_CHAIN: GRUB installed-disk handoff'\n"
            "        configfile ($iso_chain_disk)$iso_chain_config\n"
            "    }\n"
            "fi\n"
        )
        for data in (
            manifest_data(),
            rocky_manifest_data(),
            ubuntu_manifest_data(),
            opensuse_manifest_data(),
        ):
            manifest, _, digest = iso_chain.load_manifest_bytes(json.dumps(data).encode())
            with self.subTest(profiles=[name for name, _ in manifest.profiles]):
                config = iso_chain._grub_config(manifest, digest)
                self.assertTrue(
                    config.startswith(f'set timeout=5\nset default="{manifest.selected_profile}"\n')
                )
                self.assertEqual(config.count(search), 1)
                self.assertLess(config.index("set iso_chain_args_0="), config.index(search))
                first_profile = manifest.profiles[0][0]
                self.assertEqual(
                    config.index(search) + len(search),
                    config.index(f"menuentry '{first_profile}'"),
                )
                self.assertEqual(config.count("installed_disk"), 2)
                self.assertNotIn("load_env", config)

    def test_keyed_menu_requires_the_completion_marker(self):
        search = (
            "for iso_chain_directory in /grub2 /boot/grub2 /grub /boot/grub; do\n"
            '    if [ -z "$iso_chain_disk" ]; then\n'
            "        if search --no-floppy --file --set=iso_chain_disk"
            " $iso_chain_directory/grubenv; then\n"
            "            set iso_chain_config=$iso_chain_directory/grub.cfg\n"
            "            set iso_chain_env=$iso_chain_directory/grubenv\n"
            "        fi\n"
            "    fi\n"
            "done\n"
            'if [ -n "$iso_chain_disk" ]; then\n'
            "    load_env --file ($iso_chain_disk)$iso_chain_env iso_chain_installed\n"
            '    if [ "$iso_chain_installed" != 1 ]; then\n'
            "        unset iso_chain_disk\n"
            "    fi\n"
            "fi\n"
            'if [ -n "$iso_chain_disk" ]; then\n'
            "    set default=installed_disk\n"
        )
        for factory in (rocky_manifest_data, ubuntu_manifest_data):
            data = factory(ssh_authorized_keys=[KEY], login_user="core")
            manifest, _, digest = iso_chain.load_manifest_bytes(json.dumps(data).encode())
            with self.subTest(profile=manifest.selected_profile):
                config = iso_chain._grub_config(manifest, digest)
                self.assertEqual(config.count(search), 1)
                self.assertEqual(config.count("installed_disk"), 2)
                self.assertTrue(
                    config.startswith(f'set timeout=5\nset default="{manifest.selected_profile}"\n')
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


class RockyKickstartTests(unittest.TestCase):
    def render(self, keys=(KEY,), **changes):
        data = rocky_manifest_data(ssh_authorized_keys=list(keys), login_user="core", **changes)
        manifest, _, _ = iso_chain.load_manifest_bytes(json.dumps(data).encode())
        return iso_chain._rocky_kickstart(manifest).decode()

    def test_every_key_round_trips_through_the_kickstart_tokenizer(self):
        keys = [
            "ssh-ed25519 AAAA a'b",
            'ssh-ed25519 AAAA "q" \\ # %pre $(id) `id`',
            "%post",
            "%end ssh-ed25519 AAAA",
            "ssh-ed25519 AAAA \u043a\u043b\u044e\u0447",
        ]
        rendered = self.render(keys)
        lines = [line for line in rendered.splitlines() if line.startswith("sshkey ")]
        self.assertEqual(
            [shlex.split(line, comments=True) for line in lines],
            [["sshkey", "--username=core", key] for key in keys],
        )
        self.assertEqual(rendered.count("\nuser --name=core\n"), 1)
        for header, count in (("%pre", 1), ("%post", 2), ("%packages", 1)):
            headers = [line.split(" ")[0] for line in rendered.splitlines()]
            self.assertEqual(headers.count(header), count, header)
        self.assertEqual(rendered.splitlines()[-1], "reboot")
        for forbidden in ("poweroff", "halt", "shutdown", "rootpw --plaintext", "--password"):
            self.assertNotIn(forbidden, rendered)

    def test_generated_lines_start_with_fixed_commands(self):
        template = iso_chain.ROCKY_KICKSTART.read_text()
        rendered = self.render(["ssh-ed25519 AAAA one", "ssh-ed25519 AAAA two"])
        self.assertTrue(rendered.endswith(template))
        generated = rendered[: -len(template)]
        section = False
        for line in generated.splitlines():
            if line.startswith("%post"):
                section = True
            elif line == "%end":
                section = False
            elif not section:
                self.assertIn(line.split(" ")[0], ("network", "user", "sshkey"))

    def test_the_largest_login_values_fit_the_kickstart_bound(self):
        rendered = self.render(["'" * iso_chain.MAX_KEY_LENGTH] * iso_chain.MAX_KEYS)
        self.assertLessEqual(len(rendered.encode()), iso_chain.MAX_KICKSTART_BYTES)
        wide = self.render(["\U0001f511" * iso_chain.MAX_KEY_LENGTH] * iso_chain.MAX_KEYS)
        self.assertLessEqual(len(wide.encode()), iso_chain.MAX_KICKSTART_BYTES)

    def test_names_no_fixed_device_and_keeps_the_installer_disk_guard(self):
        rendered = self.render()
        self.assertIsNone(re.search(r"\b(?:[vsh]d[a-z]+|nvme\d+n\d+)\b", rendered))
        pre = rendered[rendered.index("%pre ") : rendered.index("%end", rendered.index("%pre "))]
        for option in ("--only-use=", "--drives=", "--boot-drive=", "--ondisk="):
            values = re.findall(re.escape(option) + r"(\S+)", pre)
            self.assertTrue(values, option)
            self.assertEqual(set(values), {"$disk"}, option)
        for guard in (
            '[ "$count" -eq 1 ] || { echo "iso-chain-disk: failed count=$count" >&2; exit 1; }',
            "for skip in 0 $((sectors - 2048)); do",
            '[ "${found%% *}" = "$zero" ] || { echo \'iso-chain-disk: failed blank\' >&2; exit 1; }',
            "zero=" + hashlib.sha256(bytes(1024 * 1024)).hexdigest(),
            'case "${entry##*/}" in sr*) continue ;; esac',
        ):
            self.assertIn(guard, pre)
        self.assertIn("%pre --erroronfail --interpreter=/bin/sh\n", rendered)
        self.assertIn('--leavebootorder --append="console=hvc0 ipv6.disable=1"\n', rendered)

    def test_renders_the_manifest_host_name_and_persistent_static_network(self):
        rendered = self.render(
            network={
                "mac": "52:54:00:12:34:56",
                "address": "10.0.2.15/24",
                "routes": [
                    {"destination": "192.0.2.0/24", "gateway": "10.0.2.4"},
                    {"destination": "0.0.0.0/0", "gateway": "10.0.2.2"},
                ],
                "dns": ["10.0.2.3", "10.0.2.5"],
            }
        )
        self.assertIn("\nnetwork --hostname=sys-r1\n", "\n" + rendered)
        keyfile = (
            "[connection]\nid=iso-chain\ntype=ethernet\nautoconnect=true\n\n"
            "[ethernet]\nmac-address=52:54:00:12:34:56\n\n"
            "[ipv4]\nmethod=manual\naddress1=10.0.2.15/24\ngateway=10.0.2.2\n"
            "route1=192.0.2.0/24,10.0.2.4\ndns=10.0.2.3;10.0.2.5;\n\n"
            "[ipv6]\nmethod=disabled\n"
        )
        self.assertIn(keyfile, rendered)
        self.assertIn(
            "rm -f /etc/NetworkManager/system-connections/* "
            "/etc/sysconfig/network-scripts/ifcfg-*\n",
            rendered,
        )
        self.assertIn(
            "restorecon /etc/NetworkManager/system-connections/iso-chain.nmconnection\n", rendered
        )
        no_dns = self.render(
            network={**rocky_manifest_data()["network"], "dns": []},
        )
        self.assertNotIn("dns=", no_dns)

    def test_ends_with_the_completion_marker_after_every_rendered_step(self):
        rendered = self.render()
        marker = (
            "%post --erroronfail --interpreter=/bin/sh\n"
            "# ADR 0021: the last change of a finished install; the menu boots only a marked disk.\n"
            "set -eu\n"
            "grub2-editenv /boot/grub2/grubenv set iso_chain_installed=1\n"
            "%end\n"
            "\n"
            "reboot\n"
        )
        self.assertTrue(rendered.endswith(marker))
        self.assertEqual(rendered.count("iso_chain_installed"), 1)
        self.assertLess(rendered.index("ISO_CHAIN_KEYFILE"), rendered.rindex("%post "))

    def test_rendering_is_deterministic_and_bound_to_login_values(self):
        self.assertEqual(self.render(), self.render())
        self.assertNotEqual(self.render(), self.render(["ssh-ed25519 AAAA other"]))


class UbuntuUserDataTests(unittest.TestCase):
    def render(self, keys=(KEY,), **changes):
        data = ubuntu_manifest_data(ssh_authorized_keys=list(keys), login_user="core", **changes)
        manifest, _, _ = iso_chain.load_manifest_bytes(json.dumps(data).encode())
        return iso_chain._ubuntu_user_data(manifest)

    def document(self, rendered: bytes) -> dict:
        header, body = rendered.decode().split("\n", 1)
        self.assertEqual(header, "#cloud-config")
        document = json.loads(body)
        self.assertEqual(list(document), ["autoinstall"])
        return document["autoinstall"]

    def test_every_key_round_trips_as_one_quoted_value(self):
        keys = [
            "ssh-ed25519 AAAA a'b",
            'ssh-ed25519 AAAA "q" \\ # %pre $(id) `id`',
            "- item",
            "key: {value}, [list] &anchor *alias !tag |block >fold",
            "ssh-ed25519 AAAA \u043a\u043b\u044e\u0447 \U0001f511",
        ]
        autoinstall = self.document(self.render(keys))
        self.assertEqual(
            autoinstall["user-data"],
            {
                "hostname": "sys-r1",
                "disable_root": True,
                "users": [
                    {
                        "name": "core",
                        "lock_passwd": True,
                        "shell": "/bin/bash",
                        "ssh_authorized_keys": keys,
                    }
                ],
            },
        )

    def test_renders_the_static_network_matched_by_mac(self):
        network = {
            "mac": "52:54:00:12:34:56",
            "address": "10.0.2.15/24",
            "routes": [{"destination": "0.0.0.0/0", "gateway": "10.0.2.2"}],
            "dns": ["10.0.2.3", "10.0.2.5"],
        }
        autoinstall = self.document(self.render(network=network))
        self.assertEqual(
            autoinstall["network"],
            {
                "version": 2,
                "ethernets": {
                    "iso0": {
                        "match": {"macaddress": "52:54:00:12:34:56"},
                        "addresses": ["10.0.2.15/24"],
                        "routes": [{"to": "default", "via": "10.0.2.2"}],
                        "nameservers": {"addresses": ["10.0.2.3", "10.0.2.5"]},
                        "dhcp4": False,
                        "dhcp6": False,
                        "accept-ra": False,
                        "link-local": [],
                    }
                },
            },
        )
        no_dns = self.document(self.render(network={**network, "dns": []}))
        self.assertNotIn("nameservers", no_dns["network"]["ethernets"]["iso0"])

    def test_template_installs_offline_with_guard_marker_and_reboot(self):
        autoinstall = self.document(self.render())
        self.assertEqual(autoinstall["version"], 1)
        self.assertEqual(
            autoinstall["apt"],
            {"geoip": False, "fallback": "offline-install", "mirror-selection": {"primary": []}},
        )
        self.assertEqual(autoinstall["refresh-installer"], {"update": False})
        self.assertEqual(autoinstall["storage"], {"layout": {"name": "direct"}})
        self.assertEqual(autoinstall["ssh"], {"install-server": True, "allow-pw": False})
        self.assertEqual(autoinstall["shutdown"], "reboot")
        self.assertEqual(
            autoinstall["late-commands"],
            [
                [
                    "curtin",
                    "in-target",
                    "--target=/target",
                    "--",
                    "grub-editenv",
                    "/boot/grub/grubenv",
                    "set",
                    "iso_chain_installed=1",
                ]
            ],
        )
        self.assertNotIn("identity", autoinstall)
        [[shell, flag, script]] = autoinstall["early-commands"]
        self.assertEqual((shell, flag), ("sh", "-c"))
        for guard in (
            '[ "$count" -eq 1 ] || { echo "autoinstall-disk: failed count=$count" >&2; exit 1; }',
            "for skip in 0 $((sectors - 2048)); do",
            "zero=" + hashlib.sha256(bytes(1024 * 1024)).hexdigest(),
            'case "${entry##*/}" in sr*) continue ;; esac',
            'echo "autoinstall-disk: passed $disk"',
        ):
            self.assertIn(guard, script)

    def test_rendering_names_no_device_and_no_launcher_failure_text(self):
        rendered = self.render().decode()
        self.assertNotIn("iso-chain", rendered)
        self.assertIsNone(re.search(r"\b(?:[vsh]d[a-z]+|nvme\d+n\d+)\b", rendered))
        for forbidden in ("poweroff", "sudo", "password", "passwd:", "groups"):
            self.assertNotIn(forbidden, rendered)

    def test_the_largest_login_values_fit_the_user_data_bound(self):
        wide = self.render(["\U0001f511" * iso_chain.MAX_KEY_LENGTH] * iso_chain.MAX_KEYS)
        self.assertLessEqual(len(wide), iso_chain.MAX_USER_DATA_BYTES)
        escaped = self.render(['"\\' * (iso_chain.MAX_KEY_LENGTH // 2)] * iso_chain.MAX_KEYS)
        self.assertLessEqual(len(escaped), iso_chain.MAX_USER_DATA_BYTES)

    def test_refuses_an_lpar_ending_in_a_hyphen(self):
        with self.assertRaisesRegex(iso_chain.ValidationError, "lpar") as caught:
            self.render(lpar="sys-r1-")
        self.assertNotIn("sys-r1-", str(caught.exception))

    def test_refuses_root_as_the_login_user(self):
        data = ubuntu_manifest_data(ssh_authorized_keys=[KEY], login_user="root")
        manifest, _, _ = iso_chain.load_manifest_bytes(json.dumps(data).encode())
        with self.assertRaisesRegex(iso_chain.ValidationError, "manifest login_user"):
            iso_chain._ubuntu_user_data(manifest)

    def test_rendering_is_deterministic_and_bound_to_login_values(self):
        self.assertEqual(self.render(), self.render())
        self.assertNotEqual(self.render(), self.render(["ssh-ed25519 AAAA other"]))


class ContainerBuildTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.manifest = self.root / "manifest.json"
        self.manifest.write_text(json.dumps(manifest_data()))
        self.kernel = self.root / "vmlinuz"
        self.kernel.write_bytes(b"kernel")
        self.initramfs = self.root / "initramfs.img"
        self.initramfs.write_bytes(b"initramfs")
        self.output = self.root / "launcher.iso"
        self.profiles = self.root / "prepared"
        self.profiles.mkdir()

    def args(self, **changes):
        values = {
            "config": self.manifest,
            "kernel": self.kernel,
            "initramfs": self.initramfs,
            "output": self.output,
            "profiles": self.profiles,
            "grub_modules": None,
            "engine": None,
            "image": iso_chain.CONTAINER_IMAGE,
            "target": None,
            "base_config": None,
            "publish_dir": None,
            "publish_url": None,
        }
        values.update(changes)
        return SimpleNamespace(**values)

    def mounts(self, command):
        return [command[index + 1] for index, token in enumerate(command) if token == "--mount"]

    def inner(self, command):
        return command[command.index(iso_chain.CONTAINER_PYTHON) :]

    def test_composes_one_mount_per_directory_and_keeps_the_output_writable(self):
        command = iso_chain.container_build_command(self.args(), "docker")
        repository = iso_chain.REPOSITORY_ROOT
        self.assertEqual(
            self.mounts(command),
            [
                f"type=bind,source={repository},target={repository},readonly",
                f"type=bind,source={self.root},target={self.root}",
                f"type=bind,source={self.profiles},target={self.profiles},readonly",
            ],
        )
        self.assertEqual(
            self.inner(command),
            [
                iso_chain.CONTAINER_PYTHON,
                str(repository / "scripts/iso_chain.py"),
                "build",
                "--grub-modules",
                iso_chain.CONTAINER_MODULE_DIRECTORY,
                "--kernel",
                str(self.kernel),
                "--initramfs",
                str(self.initramfs),
                "--profiles",
                str(self.profiles),
                "--config",
                str(self.manifest),
                "--output",
                str(self.output),
            ],
        )

    def publish_args(self, request, **changes):
        requests = self.root / "requests"
        requests.mkdir(exist_ok=True)
        target = requests / f"target-{len(list(requests.iterdir()))}.json"
        target.write_text(json.dumps(request))
        base = self.root / "base.json"
        base.write_text(json.dumps(base_manifest()))
        publish = self.root / "publish"
        publish.mkdir(exist_ok=True)
        values = {
            "config": None,
            "output": None,
            "target": target,
            "base_config": base,
            "publish_dir": publish,
            "publish_url": "https://media.example",
        }
        return self.args(**{**values, **changes})

    def test_refuses_unrenderable_login_values_before_engine(self):
        login = {"ssh_authorized_keys": [KEY], "login_user": "core"}
        ubuntu = self.publish_args(target_request(profile="ubuntu-26.04.1", **login))
        self.assertEqual(iso_chain.container_build_command(ubuntu, "docker")[0], "docker")
        dashed_lpar = self.publish_args(
            target_request(profile="ubuntu-26.04.1", lpar="sys-r1-", **login)
        )
        with self.assertRaisesRegex(iso_chain.ValidationError, "lpar"):
            iso_chain.container_build_command(dashed_lpar, "docker")
        rocky = self.publish_args(target_request(**login))
        self.assertEqual(iso_chain.container_build_command(rocky, "docker")[0], "docker")
        dashed = self.publish_args(
            target_request(ssh_authorized_keys=["-oProxyCommand=x"], login_user="core")
        )
        with self.assertRaisesRegex(iso_chain.ValidationError, "must not start with -"):
            iso_chain.container_build_command(dashed, "docker")

    def test_forwards_target_and_publish_inputs(self):
        args = self.publish_args(target_request())
        command = iso_chain.container_build_command(args, "docker")
        mounts = self.mounts(command)
        requests = args.target.parent
        self.assertIn(f"type=bind,source={requests},target={requests},readonly", mounts)
        self.assertIn(f"type=bind,source={args.publish_dir},target={args.publish_dir}", mounts)
        inner = self.inner(command)
        self.assertEqual(
            inner[inner.index("--target") :],
            [
                "--target",
                str(args.target),
                "--base-config",
                str(args.base_config),
                "--publish-dir",
                str(args.publish_dir),
                "--publish-url",
                "https://media.example",
            ],
        )
        self.assertNotIn("--output", inner)
        self.assertNotIn("--config", inner)

    def test_rejects_target_and_publish_inputs_before_engine(self):
        unbound = target_request()
        del unbound["operation_binding"]
        cases = (
            (self.publish_args(target_request(mac="opaque-mac")), "network.mac"),
            (self.publish_args(unbound), "operation_binding"),
            (self.publish_args(target_request(), publish_url="ftp://opaque-host"), "publish_url"),
            (
                self.publish_args(target_request(), publish_dir=iso_chain.REPOSITORY_ROOT),
                "must not be the repository root",
            ),
            (self.args(output=None), "--output"),
        )
        for args, message in cases:
            with (
                self.subTest(message=message),
                self.assertRaisesRegex(iso_chain.ValidationError, message) as caught,
            ):
                iso_chain.container_build_command(args, "docker")
            self.assertNotIn("opaque", str(caught.exception))

    def test_binds_a_supplied_module_directory_read_only(self):
        modules = self.root / "modules"
        modules.mkdir()
        (modules / "modinfo.sh").write_text("grub_modinfo_target_cpu=powerpc\n")
        command = iso_chain.container_build_command(self.args(grub_modules=modules), "docker")
        self.assertIn(f"type=bind,source={modules},target={modules},readonly", self.mounts(command))
        self.assertEqual(self.inner(command)[4], str(modules))

    def test_refuses_paths_it_cannot_mount(self):
        comma = self.root / "comma,dir"
        comma.mkdir()
        kernel = comma / "vmlinuz"
        kernel.write_bytes(b"kernel")
        cases = (
            (self.args(kernel=kernel), "cannot contain a comma"),
            (self.args(output=Path("/launcher.iso")), "filesystem root"),
            (self.args(kernel=self.root / "missing"), "kernel: unavailable"),
            (
                self.args(output=iso_chain.REPOSITORY_ROOT / "launcher.iso"),
                "must not be the repository root",
            ),
        )
        for args, message in cases:
            with (
                self.subTest(message=message),
                self.assertRaisesRegex(iso_chain.ValidationError, message),
            ):
                iso_chain.container_build_command(args, "docker")
        self.output.write_bytes(b"iso")
        with self.assertRaisesRegex(iso_chain.ValidationError, "already exists"):
            iso_chain.container_build_command(self.args(), "docker")

    def test_refuses_an_unavailable_engine_before_running_anything(self):
        with (
            mock.patch("scripts.iso_chain.shutil.which", return_value=None),
            mock.patch("scripts.iso_chain.subprocess.run") as run,
            mock.patch("scripts.iso_chain.os.execvp") as execute,
            self.assertRaisesRegex(iso_chain.ValidationError, "install podman or docker"),
        ):
            iso_chain.container_build(self.args())
        run.assert_not_called()
        execute.assert_not_called()

    def test_reports_an_unavailable_image_with_the_engine_diagnostic(self):
        stderr = b"warning: something\nCannot connect to the Docker daemon at unix:///sock\n"
        with (
            mock.patch("scripts.iso_chain.shutil.which", return_value="/usr/bin/docker"),
            mock.patch("scripts.iso_chain.subprocess.run") as run,
            mock.patch("scripts.iso_chain.os.execvp") as execute,
            self.assertRaisesRegex(
                iso_chain.ValidationError, "Cannot connect to the Docker daemon"
            ),
        ):
            run.return_value = subprocess.CompletedProcess([], 1, b"", stderr)
            iso_chain.container_build(self.args())
        run.assert_called_once_with(
            ["/usr/bin/docker", "image", "inspect", iso_chain.CONTAINER_IMAGE],
            check=False,
            capture_output=True,
        )
        execute.assert_not_called()

    def test_mounts_an_output_directory_inside_the_repository_separately(self):
        nested = iso_chain.REPOSITORY_ROOT / "docs"
        command = iso_chain.container_build_command(
            self.args(output=nested / "launcher.iso"), "docker"
        )
        repository = iso_chain.REPOSITORY_ROOT
        self.assertEqual(
            self.mounts(command),
            [
                f"type=bind,source={repository},target={repository},readonly",
                f"type=bind,source={self.root},target={self.root},readonly",
                f"type=bind,source={nested},target={nested}",
                f"type=bind,source={self.profiles},target={self.profiles},readonly",
            ],
        )

    def test_prefers_podman_and_falls_back_to_docker(self):
        def both(name):
            return f"/opt/bin/{name}" if name in iso_chain.CONTAINER_ENGINES else None

        def docker_only(name):
            return "/usr/local/bin/docker" if name == "docker" else None

        with mock.patch("scripts.iso_chain.shutil.which", side_effect=both):
            self.assertEqual(iso_chain._container_engine(None), "/opt/bin/podman")
        with mock.patch("scripts.iso_chain.shutil.which", side_effect=docker_only):
            self.assertEqual(iso_chain._container_engine(None), "/usr/local/bin/docker")

    def test_honours_an_explicit_engine_and_names_a_missing_one(self):
        def podman_only(name):
            return "/usr/bin/podman" if name == "podman" else None

        with mock.patch("scripts.iso_chain.shutil.which", side_effect=podman_only):
            self.assertEqual(iso_chain._container_engine("podman"), "/usr/bin/podman")
            with self.assertRaisesRegex(iso_chain.ValidationError, "unavailable: docker"):
                iso_chain._container_engine("docker")
        with (
            mock.patch("scripts.iso_chain.shutil.which", return_value=None),
            self.assertRaisesRegex(iso_chain.ValidationError, "install podman or docker"),
        ):
            iso_chain._container_engine(None)

    def test_executes_the_detected_engine_with_the_composed_argv(self):
        with (
            mock.patch("scripts.iso_chain.shutil.which", return_value="/usr/bin/podman"),
            mock.patch("scripts.iso_chain.subprocess.run") as run,
            mock.patch("scripts.iso_chain.os.execvp") as execute,
        ):
            run.return_value = subprocess.CompletedProcess([], 0, b"", b"")
            args = self.args(image="other:1")
            expected = iso_chain.container_build_command(args, "/usr/bin/podman")
            iso_chain.container_build(args)
        self.assertEqual(execute.call_args.args[0], "/usr/bin/podman")
        self.assertEqual(execute.call_args.args[1], expected)
        run.assert_called_once_with(
            ["/usr/bin/podman", "image", "inspect", "other:1"],
            check=False,
            capture_output=True,
        )


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

    def test_install_fedora_rejects_a_selected_ubuntu_profile(self):
        _, canonical, _ = iso_chain.load_manifest_bytes(json.dumps(ubuntu_manifest_data()).encode())
        self.config.write_bytes(canonical)
        with (
            mock.patch("scripts.iso_chain.subprocess.run") as run,
            self.assertRaisesRegex(
                iso_chain.ValidationError, "install-fedora requires a selected Fedora profile"
            ),
        ):
            iso_chain.install_fedora(self.args())
        run.assert_not_called()
        self.assertFalse(self.output.exists())

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
            "systemctl mask serial-getty@hvc0.service",
            "systemctl enable iso-chain-installed.service",
            "StandardOutput=journal+console",
            "StandardError=journal+console",
            "poweroff",
        ):
            self.assertIn(expected, content)
        for forbidden in ("http://", "https://", "ssh-rsa", "password=", ">/dev/hvc0"):
            self.assertNotIn(forbidden, content)

    def test_powervm_kickstart_differs_from_the_reference_only_in_its_disk(self):
        reference = Path("assets/kickstart/fedora-44-power9.ks").read_text()
        powervm = Path("assets/kickstart/fedora-44-powervm.ks").read_text()
        self.assertNotIn("vda", powervm)
        self.assertIn("ignoredisk --only-use=sda", powervm)
        self.assertIn("clearpart --all --initlabel --drives=sda", powervm)
        self.assertEqual(powervm.replace("sda", "vda"), reference)
        self.assertLessEqual(len(powervm.encode()), iso_chain.MAX_KICKSTART_BYTES)

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

    def fake_disk(self, command, **kwargs):
        self.assertEqual(command[:4], ["qemu-img", "create", "-f", "qcow2"])
        Path(command[4]).write_bytes(b"fresh")
        return subprocess.CompletedProcess(command, 0)

    def fake_phase(self, command, log, timeout, capture_fifo=None, capture=None):
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

    def test_terminating_signals_raise_once_and_keep_an_ignore(self):
        names = (signal.SIGHUP, signal.SIGTERM)
        for name in names:
            self.addCleanup(signal.signal, name, signal.signal(name, signal.SIG_DFL))
        with iso_chain._terminating_signals():
            with self.assertRaises(iso_chain.Terminated) as raised:
                signal.raise_signal(signal.SIGHUP)
            self.assertEqual(raised.exception.signum, signal.SIGHUP)
            self.assertEqual([signal.getsignal(name) for name in names], [signal.SIG_IGN] * 2)
        self.assertEqual([signal.getsignal(name) for name in names], [signal.SIG_DFL] * 2)
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
        with iso_chain._terminating_signals():
            self.assertIs(signal.getsignal(signal.SIGHUP), signal.SIG_IGN)
            self.assertIs(signal.getsignal(signal.SIGTERM), iso_chain._raise_terminated)
        self.assertIs(signal.getsignal(signal.SIGHUP), signal.SIG_IGN)

    def test_main_translates_signals_only_for_install_commands(self):
        for name in (signal.SIGHUP, signal.SIGTERM):
            self.addCleanup(signal.signal, name, signal.signal(name, signal.SIG_DFL))
        paths = ["--iso", str(self.iso), "--config", str(self.config), "--output", "out"]
        seen = []

        def record(*_):
            seen.append(signal.getsignal(signal.SIGTERM))
            return "ok"

        for command, function, arguments, translated in (
            ("install-fedora", "install_fedora", paths, True),
            ("install-rocky", "install_rocky", paths, True),
            ("install-ubuntu", "install_ubuntu", paths, True),
            ("verify-pcap", "verify_pcap", [str(self.iso)], False),
        ):
            seen.clear()
            with (
                self.subTest(command=command),
                mock.patch.object(iso_chain, function, side_effect=record),
                mock.patch.object(sys, "argv", ["iso_chain", command, *arguments]),
                mock.patch("sys.stdout"),
            ):
                self.assertEqual(iso_chain.main(), 0)
                self.assertEqual(seen == [iso_chain._raise_terminated], translated)

    def test_signal_after_publication_keeps_the_published_result(self):
        publish = iso_chain._publish_directory

        def publish_then_signal(source, destination):
            publish(source, destination)
            raise iso_chain.Terminated(signal.SIGTERM)

        with (
            mock.patch("scripts.iso_chain.subprocess.run", side_effect=self.fake_disk),
            mock.patch("scripts.iso_chain._run_qemu_phase", side_effect=self.fake_phase),
            mock.patch("scripts.iso_chain._publish_directory", side_effect=publish_then_signal),
            self.assertRaises(iso_chain.Terminated),
        ):
            iso_chain.install_fedora(self.args())
        self.assertTrue((self.output / "result.json").is_file())
        self.assertEqual(list(self.root.glob(".iso-chain-install-*")), [])

    def test_signalled_install_stops_children_and_removes_staging(self):
        tools, pids = self.root / "tools", self.root / "pids"
        tools.mkdir()
        pids.mkdir()
        for name in ("qemu-img", "qemu-system-ppc64"):
            (tools / name).write_text(FAKE_INSTALL_TOOL.format(python=sys.executable))
            (tools / name).chmod(0o755)
        for hang, signum in (
            ("qemu-system-ppc64", signal.SIGTERM),
            ("qemu-system-ppc64", signal.SIGHUP),
            ("qemu-img", signal.SIGTERM),
        ):
            with self.subTest(hang=hang, signum=signum):
                pid_file = pids / hang
                pid_file.unlink(missing_ok=True)
                environment = dict(
                    os.environ,
                    PATH=f"{tools}{os.pathsep}{os.environ['PATH']}",
                    FAKE_HANG=hang,
                    FAKE_PIDS=str(pids),
                )
                cli = subprocess.Popen(
                    [
                        sys.executable,
                        "-c",
                        INTERRUPTIBLE_CLI,
                        "install-fedora",
                        "--iso",
                        str(self.iso),
                        "--config",
                        str(self.config),
                        "--output",
                        str(self.output),
                        "--disk-size-gib",
                        "20",
                        "--memory-mib",
                        "4096",
                        "--install-timeout-seconds",
                        "60",
                        "--boot-timeout-seconds",
                        "60",
                    ],
                    cwd=REPOSITORY,
                    env=environment,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                self.addCleanup(cli.communicate)
                self.addCleanup(cli.kill)
                deadline = time.monotonic() + 30
                while not pid_file.exists() and time.monotonic() < deadline:
                    if cli.poll() is not None:
                        self.fail(f"install exited early: {cli.communicate()[1]}")
                    time.sleep(0.05)
                child = int(pid_file.read_text())
                os.kill(cli.pid, signum)
                _, stderr = cli.communicate(timeout=60)
                self.assertEqual(cli.returncode, 128 + signum)
                self.assertIn(f"error: interrupted by {signal.Signals(signum).name}", stderr)
                self.assertEqual(list(self.root.glob(".iso-chain-install-*")), [])
                self.assertFalse(self.output.exists())
                with self.assertRaises(ProcessLookupError):
                    os.kill(child, 0)
                    os.kill(child, signal.SIGKILL)

    def test_successful_install_publishes_fresh_disk_logs_capture_and_result(self):
        with (
            mock.patch("scripts.iso_chain.subprocess.run", side_effect=self.fake_disk),
            mock.patch("scripts.iso_chain._run_qemu_phase", side_effect=self.fake_phase),
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

    def rocky_config(self, **changes):
        data = rocky_manifest_data(
            **{"ssh_authorized_keys": [KEY], "login_user": "core", **changes}
        )
        _, canonical, _ = iso_chain.load_manifest_bytes(json.dumps(data).encode())
        self.config.write_bytes(canonical)

    def test_install_rocky_requires_an_unattended_rocky_profile(self):
        self.rocky_config()
        keyless = self.root / "keyless.json"
        keyless.write_bytes(
            iso_chain.load_manifest_bytes(json.dumps(rocky_manifest_data()).encode())[1]
        )
        fedora = self.root / "fedora.json"
        fedora.write_bytes(iso_chain.load_manifest_bytes(json.dumps(manifest_data()).encode())[1])
        for config in (keyless, fedora):
            with (
                self.subTest(config=config.name),
                mock.patch("scripts.iso_chain.subprocess.run") as run,
                mock.patch("scripts.iso_chain._run_qemu_phase") as phase,
                self.assertRaisesRegex(iso_chain.ValidationError, "install-rocky requires"),
            ):
                iso_chain.install_rocky(self.args(config=config))
            run.assert_not_called()
            phase.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_install_rocky_reboots_into_the_disk_with_the_iso_and_nic_attached(self):
        self.rocky_config()
        calls = []

        def create_disk(command, **kwargs):
            Path(command[4]).write_bytes(b"fresh")
            return subprocess.CompletedProcess(command, 0)

        def phase(command, log, timeout, capture_fifo=None, capture=None, until=None):
            calls.append((command, timeout, until))
            capture.write_bytes(b"pcap")
            if until is None:
                log.write_text("reboot: Restarting system\n")
                disk = next(
                    Path(value.split(",", 1)[0].split("=", 1)[1])
                    for value in command
                    if value.startswith("file=") and "format=qcow2" in value
                )
                disk.write_bytes(b"installed")
            else:
                log.write_text("sys-r1 login: ")
            return 0

        with (
            mock.patch("scripts.iso_chain.subprocess.run", side_effect=create_disk),
            mock.patch("scripts.iso_chain._run_qemu_phase", side_effect=phase),
        ):
            iso_chain.install_rocky(self.args(boot_timeout_seconds=900))
        self.assertEqual([until for _, _, until in calls], [None, b"sys-r1 login:"])
        self.assertEqual([timeout for _, timeout, _ in calls], [7200, 900])
        for command, _, _ in calls:
            joined = " ".join(command)
            self.assertEqual(command[-1], "-no-reboot")
            self.assertIn("media=cdrom", joined)
            self.assertIn("bootindex=1", joined)
            self.assertIn("mac=52:54:00:12:34:56", joined)
            self.assertIn("filter-dump", joined)
        self.assertEqual(
            sorted(path.name for path in self.output.iterdir()),
            [
                "boot-console.log",
                "boot.pcap",
                "disk.qcow2",
                "install-console.log",
                "install.pcap",
                "result.json",
            ],
        )
        result = json.loads((self.output / "result.json").read_bytes())
        self.assertEqual(result["boot_stop"], "login-prompt")
        self.assertNotIn("boot_exit_status", result)
        self.assertEqual(result["disk_sha256_after"], hashlib.sha256(b"installed").hexdigest())

    def test_install_rocky_rejects_an_install_that_left_the_disk_unchanged(self):
        self.rocky_config()

        def create_disk(command, **kwargs):
            Path(command[4]).write_bytes(b"fresh")
            return subprocess.CompletedProcess(command, 0)

        def phase(command, log, timeout, capture_fifo=None, capture=None, until=None):
            capture.write_bytes(b"pcap")
            log.write_text("console\n")
            return 0

        with (
            mock.patch("scripts.iso_chain.subprocess.run", side_effect=create_disk),
            mock.patch("scripts.iso_chain._run_qemu_phase", side_effect=phase) as run_phase,
            self.assertRaisesRegex(iso_chain.ValidationError, "did not record"),
        ):
            iso_chain.install_rocky(self.args())
        self.assertEqual(run_phase.call_count, 1)
        self.assertFalse(self.output.exists())

    def test_install_ubuntu_requires_an_unattended_ubuntu_profile(self):
        keyless = self.root / "keyless.json"
        keyless.write_bytes(
            iso_chain.load_manifest_bytes(json.dumps(ubuntu_manifest_data()).encode())[1]
        )
        self.rocky_config()
        for config in (keyless, self.config):
            with (
                self.subTest(config=config.name),
                mock.patch("scripts.iso_chain.subprocess.run") as run,
                mock.patch("scripts.iso_chain._run_qemu_phase") as phase,
                self.assertRaisesRegex(iso_chain.ValidationError, "install-ubuntu requires"),
            ):
                iso_chain.install_ubuntu(self.args(config=config))
            run.assert_not_called()
            phase.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_install_ubuntu_reboots_into_the_disk_with_the_iso_and_nic_attached(self):
        data = ubuntu_manifest_data(ssh_authorized_keys=[KEY], login_user="core")
        self.config.write_bytes(iso_chain.load_manifest_bytes(json.dumps(data).encode())[1])
        calls = []

        def create_disk(command, **kwargs):
            Path(command[4]).write_bytes(b"fresh")
            return subprocess.CompletedProcess(command, 0)

        def phase(command, log, timeout, capture_fifo=None, capture=None, until=None):
            calls.append((command, until))
            capture.write_bytes(b"pcap")
            if until is None:
                disk = next(
                    Path(value.split(",", 1)[0].split("=", 1)[1])
                    for value in command
                    if value.startswith("file=") and "format=qcow2" in value
                )
                disk.write_bytes(b"installed")
            log.write_text("console\n")
            return 0

        with (
            mock.patch("scripts.iso_chain.subprocess.run", side_effect=create_disk),
            mock.patch("scripts.iso_chain._run_qemu_phase", side_effect=phase),
        ):
            iso_chain.install_ubuntu(self.args())
        self.assertEqual([until for _, until in calls], [None, b"sys-r1 login:"])
        for command, _ in calls:
            self.assertEqual(command[-1], "-no-reboot")
            self.assertIn("bootindex=1", " ".join(command))
        result = json.loads((self.output / "result.json").read_bytes())
        self.assertEqual(result["boot_stop"], "login-prompt")
        self.assertEqual(result["disk_sha256_after"], hashlib.sha256(b"installed").hexdigest())

    def test_parser_exposes_the_ubuntu_install_contract(self):
        args = iso_chain.parser().parse_args(
            ["install-ubuntu", "--iso", "a.iso", "--config", "m.json", "--output", "out"]
        )
        self.assertEqual(
            (args.command, args.disk_size_gib, args.memory_mib), ("install-ubuntu", 20, 8192)
        )
        self.assertEqual((args.install_timeout_seconds, args.boot_timeout_seconds), (14400, 3600))

    def test_qemu_phase_stops_at_its_console_marker(self):
        waiting = "import sys,time; print('booting'); print('sys-r1 login: ', end='', flush=True); time.sleep(60)"
        log = self.root / "marker.log"
        started = time.monotonic()
        self.assertEqual(
            iso_chain._run_qemu_phase(
                [sys.executable, "-c", waiting], log, 30, until=b"sys-r1 login:"
            ),
            0,
        )
        self.assertLess(time.monotonic() - started, 20)
        self.assertEqual(log.read_text(), "booting\nsys-r1 login: ")
        for program, reason in (
            ("print('booted')", "before its console marker"),
            ("import time; time.sleep(60)", "timed out"),
        ):
            with (
                self.subTest(reason=reason),
                self.assertRaisesRegex(iso_chain.ValidationError, reason),
            ):
                iso_chain._run_qemu_phase(
                    [sys.executable, "-c", program],
                    self.root / f"{len(reason)}.log",
                    2,
                    until=b"sys-r1 login:",
                )

    def test_parser_exposes_the_rocky_install_contract(self):
        args = iso_chain.parser().parse_args(
            ["install-rocky", "--iso", "a.iso", "--config", "m.json", "--output", "out"]
        )
        self.assertEqual(
            (args.disk_size_gib, args.memory_mib),
            (20, 8192),
        )
        self.assertEqual((args.install_timeout_seconds, args.boot_timeout_seconds), (14400, 3600))

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
                "disk: passed",
                "media: passed",
                "artifacts: passed",
                "kexec-load: passed",
                "kexec-exec: started",
                installer_command_line(self.manifest, self.digest),
            )
        )

    def verify(self, content, profile="fedora"):
        self.log.write_text(content)
        return iso_chain.verify_launcher_log(self.log, self.manifest, profile)

    def test_recomputes_the_digest_of_non_ascii_login_values(self):
        data = manifest_data(ssh_authorized_keys=[KEY + " \u043a\u043b\u044e\u0447"])
        data["login_user"] = "core"
        self.manifest, _, self.digest = iso_chain.load_manifest_bytes(json.dumps(data).encode())
        self.verify(self.content())

    def test_verifiers_exist(self):
        self.assertTrue(callable(getattr(iso_chain, "verify_launcher_log", None)))
        self.assertTrue(callable(getattr(iso_chain, "verify_pcap", None)))

    def test_accepts_exact_default_and_explicit_allowed_manual_profile(self):
        expected = (
            "configuration: passed",
            "adapter-match: passed",
            "profile: passed",
            "memory: passed",
            "disk: passed",
            "media: passed",
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

    def test_rejects_missing_or_misordered_disk_marker(self):
        missing = self.content().replace("disk: passed\n", "")
        with self.assertRaises(iso_chain.ValidationError):
            self.verify(missing)
        with self.assertRaises(iso_chain.ValidationError):
            self.verify(missing.replace("profile: passed", "disk: passed\nprofile: passed"))
        with self.assertRaisesRegex(iso_chain.ValidationError, "failure evidence"):
            self.verify(self.content().replace("disk: passed", "disk: failed"))

    def test_rejects_missing_or_failed_media_marker(self):
        with self.assertRaises(iso_chain.ValidationError):
            self.verify(self.content().replace("media: passed\n", ""))
        with self.assertRaisesRegex(iso_chain.ValidationError, "failure evidence"):
            self.verify(self.content().replace("media: passed", "media: failed"))

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
            good.replace("\nkexec-exec: started", ""),
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
        installer = installer_command_line(self.manifest, self.digest)
        content = content.replace(
            installer,
            installer.replace(" console=", " \\\n[    1.000000] Kernel command line: console="),
        )
        self.assertIn("kexec-exec: started", self.verify(content))

    def test_requires_one_exact_installer_kickstart_label(self):
        good = self.content()
        installer = installer_command_line(self.manifest, self.digest)
        label = iso_chain._volume_id(self.digest)
        expected = f"inst.ks=cdrom:LABEL={label}:/profiles/fedora-44/ks.cfg"
        self.assertIn(expected, good)
        kickstart_variants = (
            good.replace(" " + expected, ""),
            good.replace(label, "ISO_CHAIN_0000000000000000"),
            good.replace(":/profiles/fedora-44/ks.cfg", ":/profiles/other/ks.cfg"),
            good.replace(expected, expected + " " + expected),
            good.replace(expected, expected + " ks=cdrom:/ks.cfg"),
            good.replace(expected, expected + " inst.ks"),
            good.replace(expected, expected + ' "ks=hd:sdb:/other.ks"'),
            good.replace(expected, f'"{expected}"'),
        )
        command_line_variants = (
            good.replace("\n" + installer, ""),
            good.replace("\n" + installer, "").replace(
                "kexec-exec: started", installer + "\nkexec-exec: started"
            ),
            good + "\nAnaconda starting\n" + installer,
            good + " \\",
            good + "\n" + installer,
        )
        for pattern, variants in (
            ("installer Kickstart evidence", kickstart_variants),
            ("installer kernel command line", command_line_variants),
        ):
            for bad in variants:
                with (
                    self.subTest(bad=bad),
                    self.assertRaisesRegex(iso_chain.ValidationError, pattern) as caught,
                ):
                    self.verify(bad)
                self.assertNotIn(self.digest, str(caught.exception))
                self.assertNotIn(label, str(caught.exception))
        launcher = good.splitlines()[1]
        with self.assertRaisesRegex(
            iso_chain.ValidationError, "one contiguous launcher kernel command line"
        ):
            self.verify(good.replace(launcher + "\n", ""))

    def test_tcpdump_is_bounded_captured_and_filters_dhcp_or_ipv6(self):
        with mock.patch("scripts.iso_chain.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, b"", b"private banner")
            self.assertEqual(iso_chain.verify_pcap(self.pcap), "dhcp-ipv6-filter: absent")
        run.assert_called_once_with(
            [
                "tcpdump",
                "-nn",
                "-r",
                str(self.pcap.resolve()),
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


class InstallerEvidenceTests(unittest.TestCase):
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
                "disk: passed",
                "media: passed",
                "artifacts: passed",
                "kexec-load: passed",
                "kexec-exec: started",
                installer_command_line(manifest, digest),
            )
        )
        self.paths["console.log"].write_text(console)
        profile = manifest.profile("fedora")
        request_paths = (
            profile.kernel.path,
            profile.initramfs.path,
            profile.repository.treeinfo.path,
            profile.repository.repomd.path,
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
            return iso_chain.verify_installer_evidence(self.args())

    def test_reads_manifest_above_64_kib(self):
        limits = {}
        read = iso_chain._read_evidence_file

        def record(path, label, maximum):
            limits[label] = maximum
            if label == "manifest":
                raise iso_chain.ValidationError("stop")
            return read(path, label, maximum)

        with (
            mock.patch("scripts.iso_chain._read_evidence_file", side_effect=record),
            self.assertRaisesRegex(iso_chain.ValidationError, "stop"),
        ):
            iso_chain.verify_installer_evidence(self.args())
        self.assertEqual(limits["manifest"], 2 * 1024 * 1024)

    def write_access_with_failures(self, failed_paths):
        records = self.paths["access.jsonl"].read_bytes().splitlines()
        for path in failed_paths:
            failed = dict(json.loads(records[-1]), path=path, status=404, bytes=7)
            failed["index"] = len(records) + 1
            records.append(json.dumps(failed, sort_keys=True, separators=(",", ":")).encode())
        self.paths["access.jsonl"].write_bytes(b"\n".join(records) + b"\n")
        self.record["evidence_sha256"]["access_log"] = hashlib.sha256(
            self.paths["access.jsonl"].read_bytes()
        ).hexdigest()
        self.write_record()

    def test_accepts_each_fedora_anaconda_probe_404_once(self):
        # A v4 Fedora stage1 fetches install.img from the repository and probes these (ADR 0011).
        self.write_access_with_failures(
            ["/repository/images/updates.img", "/repository/images/product.img"]
        )
        self.assertIn("http-evidence: passed", self.verify())

    def test_rejects_a_repeated_probe_or_other_fedora_404(self):
        for failed in (
            ["/repository/images/updates.img", "/repository/images/updates.img"],
            ["/repository/Packages/missing.rpm"],
        ):
            with self.subTest(failed=failed):
                self.setUp()
                self.write_access_with_failures(failed)
                with self.assertRaisesRegex(iso_chain.ValidationError, "failed or reordered"):
                    self.verify()

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

    def test_rejects_installer_kickstart_from_another_label(self):
        console = self.paths["console.log"].read_text()
        label = iso_chain._volume_id(self.manifest_digest)
        self.paths["console.log"].write_text(console.replace(label, "ISO_CHAIN_0000000000000000"))
        self.record["evidence_sha256"]["console"] = hashlib.sha256(
            self.paths["console.log"].read_bytes()
        ).hexdigest()
        self.write_record()
        with self.assertRaisesRegex(iso_chain.ValidationError, "installer Kickstart evidence"):
            self.verify()

    def test_rejects_kernel_request_on_origin(self):
        records = [
            json.loads(line) for line in self.paths["access.jsonl"].read_bytes().splitlines()
        ]
        records.append(
            {**records[-1], "path": "/profiles/fedora-44/vmlinuz", "index": len(records) + 1}
        )
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
        with self.assertRaisesRegex(iso_chain.ValidationError, "outside the selected profile"):
            self.verify()

    def test_rejects_repeated_kernel_request(self):
        records = [
            json.loads(line) for line in self.paths["access.jsonl"].read_bytes().splitlines()
        ]
        records.append({**records[0], "index": len(records) + 1})
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
        with self.assertRaisesRegex(iso_chain.ValidationError, "missing a required artifact"):
            self.verify()

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
        arguments = ["verify-installer-evidence"]
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
        self.assertEqual(
            iso_chain.parser().parse_args(arguments).command, "verify-installer-evidence"
        )


class UbuntuEvidenceTests(unittest.TestCase):
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
        self.write_inputs(ubuntu_manifest_data())

    def write_inputs(self, data, sizes=(6, 9, 13)):
        manifest, canonical, digest = iso_chain.load_manifest_bytes(json.dumps(data).encode())
        self.manifest = manifest
        profile = manifest.profile("ubuntu")
        self.paths["manifest.json"].write_bytes(canonical)
        self.handoff = iso_chain._ubuntu_handoff(manifest, profile, None)
        self.write_console(self.handoff)
        self.write_access(
            [
                (profile.kernel.path, sizes[0]),
                (profile.initramfs.path, sizes[1]),
                (profile.live_iso.path, sizes[2]),
            ]
        )
        self.paths["capture.pcap"].write_bytes(b"pcap")
        self.paths["disk-before.sha256"].write_text("a" * 64 + "\n")
        self.paths["disk-after.sha256"].write_text("a" * 64 + "\n")
        self.record = {
            "version": 1,
            "manifest_sha256": digest,
            "profile": "ubuntu",
            "qemu_memory_mib": 8192,
            "guest_memtotal_mib": 8000,
            "guest_memavailable_mib": 6000,
            "disk_label": "test-disk",
            "same_run_collection": True,
            "installer_ready": True,
            "intended_disk_visible": True,
            "intended_source_confirmed": True,
        }

    def write_console(self, handoff, launcher_extra=()):
        digest = hashlib.sha256(self.paths["manifest.json"].read_bytes()).hexdigest()
        console = "\n".join(
            (
                "ISO_CHAIN: GRUB optical handoff",
                "[    0.000000] Kernel command line: "
                + " ".join(iso_chain._kernel_arguments(self.manifest, digest, "ubuntu")),
                "ISO_CHAIN: configuration passed",
                "adapter-match: passed",
                "profile: passed",
                (
                    "memory: passed memtotal_mib=8000 memavailable_mib=6000 "
                    "run_available_bytes=8589934592"
                ),
                "disk: passed",
                *launcher_extra,
                "artifacts: passed",
                "kexec-load: passed",
                "kexec-exec: started",
                "[    0.000000] Kernel command line: " + " ".join(handoff),
            )
        )
        self.paths["console.log"].write_text(console)

    def write_access(self, requests):
        self.paths["access.jsonl"].write_bytes(
            b"".join(
                json.dumps(
                    {"method": "GET", "path": path, "status": 200, "bytes": size, "index": index},
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
                + b"\n"
                for index, (path, size) in enumerate(requests, 1)
            )
        )

    def verify(self):
        self.record["evidence_sha256"] = {
            key: hashlib.sha256(self.paths[name].read_bytes()).hexdigest()
            for key, name in (
                ("manifest", "manifest.json"),
                ("console", "console.log"),
                ("access_log", "access.jsonl"),
                ("pcap", "capture.pcap"),
                ("disk_before", "disk-before.sha256"),
                ("disk_after", "disk-after.sha256"),
            )
        }
        self.paths["record.json"].write_bytes(
            json.dumps(self.record, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        )
        args = SimpleNamespace(
            record=self.paths["record.json"],
            config=self.paths["manifest.json"],
            console_log=self.paths["console.log"],
            access_log=self.paths["access.jsonl"],
            pcap=self.paths["capture.pcap"],
            disk_hash_before=self.paths["disk-before.sha256"],
            disk_hash_after=self.paths["disk-after.sha256"],
        )
        with mock.patch("scripts.iso_chain.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, b"", b"")
            return iso_chain.verify_installer_evidence(args)

    def test_accepts_ubuntu_evidence_without_media_marker(self):
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
                "installer-network: operator-reviewed",
            ),
        )
        self.assertNotIn(
            "media: passed",
            iso_chain.verify_launcher_log(self.paths["console.log"], self.manifest, "ubuntu"),
        )

    def test_rejects_missing_repeated_quoted_or_different_handoff(self):
        ip, bootif, url, *tail = self.handoff
        self.assertEqual(tail, ["console=hvc0", "ipv6.disable=1"])
        for handoff in (
            [ip, bootif, *tail],
            [ip, bootif, url, url, *tail],
            [ip, bootif, '"' + url + '"', "console=hvc1", tail[1]],
            [ip, "BOOTIF=01-52-54-00-12-34-57", url, *tail],
            [ip.replace(":off", ":dhcp"), bootif, url, *tail],
            [ip, bootif, url.replace(".iso", "-other.iso"), *tail],
            [ip, bootif, url, "url" + url.removeprefix("iso-url"), *tail],
            [ip, bootif, url, "cloud-config-url=http://10.0.2.2:8000/config", *tail],
            [ip, bootif, url, "ds=nocloud", *tail],
            [ip, bootif, url, "console=hvc0"],
        ):
            self.write_console(handoff)
            with (
                self.subTest(handoff=handoff),
                self.assertRaisesRegex(iso_chain.ValidationError, "installer handoff evidence"),
            ):
                self.verify()

    def test_rejects_http_evidence_other_than_the_three_pinned_requests(self):
        profile = self.manifest.profile("ubuntu")
        kernel, initramfs, iso = (
            (profile.kernel.path, 6),
            (profile.initramfs.path, 9),
            (profile.live_iso.path, 13),
        )
        for requests in (
            [initramfs, kernel, iso],
            [kernel, initramfs, iso, ("/ubuntu/other", 5)],
            [kernel, initramfs, (iso[0], 12)],
            [kernel, initramfs],
            [kernel, initramfs, iso, iso],
        ):
            self.write_access(requests)
            with (
                self.subTest(requests=requests),
                self.assertRaisesRegex(iso_chain.ValidationError, "HTTP evidence must be exactly"),
            ):
                self.verify()

    def test_rejects_a_404_record(self):
        self.write_access(
            [
                (self.manifest.profile("ubuntu").kernel.path, 6),
                (self.manifest.profile("ubuntu").initramfs.path, 9),
                (self.manifest.profile("ubuntu").live_iso.path, 13),
                ("/ubuntu/missing", 7),
            ]
        )
        records = self.paths["access.jsonl"].read_bytes().splitlines()
        records[-1] = records[-1].replace(b'"status":200', b'"status":404')
        self.paths["access.jsonl"].write_bytes(b"\n".join(records) + b"\n")
        with self.assertRaisesRegex(iso_chain.ValidationError, "failed or reordered"):
            self.verify()

    def test_unattended_ubuntu_requires_media_and_the_whole_casper_line(self):
        data = ubuntu_manifest_data(ssh_authorized_keys=[KEY], login_user="core")
        self.write_inputs(data)
        manifest, _, digest = iso_chain.load_manifest_bytes(json.dumps(data).encode())
        label = "ISO_CHAIN_" + digest[:16].upper()
        unattended = iso_chain._ubuntu_handoff(manifest, manifest.profile("ubuntu"), label)
        self.assertEqual(
            unattended[3:],
            [
                "autoinstall",
                "ds=nocloud",
                f"cc:datasource:%20{{NoCloud:%20{{fs_label:%20{label}}}}}%20end_cc",
                "console=hvc0",
                "---",
                "ipv6.disable=1",
                "rd.systemd.mask=systemd-networkd.service",
                "rd.systemd.mask=systemd-networkd.socket",
            ],
        )
        self.write_console(unattended, launcher_extra=("media: passed",))
        log = self.paths["console.log"]
        self.assertIn("media: passed", iso_chain.verify_launcher_log(log, manifest, "ubuntu"))
        for handoff, extra, message in (
            (unattended, (), "launcher evidence"),
            (self.handoff, ("media: passed",), "installer handoff evidence"),
            ([arg for arg in unattended if arg != "autoinstall"], ("media: passed",), "handoff"),
            ([*unattended, "url=http://10.0.2.2:8000/x"], ("media: passed",), "handoff"),
            (
                [arg.replace(label, label.lower()) for arg in unattended],
                ("media: passed",),
                "handoff",
            ),
        ):
            self.write_console(handoff, launcher_extra=extra)
            with (
                self.subTest(handoff=handoff, extra=extra),
                self.assertRaisesRegex(iso_chain.ValidationError, message),
            ):
                iso_chain.verify_launcher_log(log, manifest, "ubuntu")

    def test_accepts_a_live_iso_larger_than_2_gib(self):
        data = ubuntu_manifest_data()
        size = 3 * 1024**3
        data["profiles"]["ubuntu"]["live_iso"]["size"] = size
        self.write_inputs(data, sizes=(6, 9, size))
        self.assertEqual(self.verify()[2], "http-evidence: passed")


class RockyEvidenceTests(unittest.TestCase):
    write_access = UbuntuEvidenceTests.write_access
    verify = UbuntuEvidenceTests.verify

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
            json.dumps(rocky_manifest_data()).encode()
        )
        self.manifest = manifest
        self.profile = manifest.profile("rocky")
        self.paths["manifest.json"].write_bytes(canonical)
        self.repo = f"inst.repo={manifest.source}{self.profile.repository.path}"
        self.write_console([self.repo])
        self.pins = [
            (self.profile.kernel.path, 6),
            (self.profile.initramfs.path, 9),
            (self.profile.repository.treeinfo.path, 10),
            (self.profile.repository.repomd.path, 11),
        ]
        self.base = self.profile.repository.path
        self.appstream = "/pub/rocky/9.8/AppStream/ppc64le/os/repodata/repomd.xml"
        self.write_access(
            [*self.pins, (f"{self.base}/images/install.img", 20), (self.appstream, 5)]
        )
        self.paths["capture.pcap"].write_bytes(b"pcap")
        self.paths["disk-before.sha256"].write_text("a" * 64 + "\n")
        self.paths["disk-after.sha256"].write_text("a" * 64 + "\n")
        self.record = {
            "version": 1,
            "manifest_sha256": digest,
            "profile": "rocky",
            "qemu_memory_mib": 8192,
            "guest_memtotal_mib": 8000,
            "guest_memavailable_mib": 6000,
            "disk_label": "test-disk",
            "same_run_collection": True,
            "installer_ready": True,
            "intended_disk_visible": True,
            "intended_source_confirmed": True,
        }

    def write_console(self, installer):
        digest = hashlib.sha256(self.paths["manifest.json"].read_bytes()).hexdigest()
        self.paths["console.log"].write_text(
            "\n".join(
                (
                    "ISO_CHAIN: GRUB optical handoff",
                    "[    0.000000] Kernel command line: "
                    + " ".join(iso_chain._kernel_arguments(self.manifest, digest, "rocky")),
                    "ISO_CHAIN: configuration passed",
                    "adapter-match: passed",
                    "profile: passed",
                    (
                        "memory: passed memtotal_mib=8000 memavailable_mib=6000 "
                        "run_available_bytes=8589934592"
                    ),
                    "disk: passed",
                    "artifacts: passed",
                    "kexec-load: passed",
                    "kexec-exec: started",
                    "[    1.000000] Kernel command line: inst.text rd.neednet=1 "
                    + " ".join(installer)
                    + " console=hvc0 ipv6.disable=1",
                )
            )
        )

    def write_access_with_status(self, requests):
        """Write (path, size, status[, method]) requests; the method defaults to GET."""
        self.write_access([request[:2] for request in requests])
        records = [
            dict(json.loads(line), status=request[2], method=(*request[3:], "GET")[0])
            for line, request in zip(
                self.paths["access.jsonl"].read_bytes().splitlines(), requests, strict=True
            )
        ]
        self.paths["access.jsonl"].write_bytes(
            b"".join(
                json.dumps(record, sort_keys=True, separators=(",", ":")).encode() + b"\n"
                for record in records
            )
        )

    def test_accepts_rocky_evidence_without_media_marker(self):
        result = self.verify()
        self.assertEqual(result[2], "http-evidence: passed")
        self.assertEqual(result[-1], "intended-source: operator-reviewed")
        self.assertNotIn(
            "media: passed",
            iso_chain.verify_launcher_log(self.paths["console.log"], self.manifest, "rocky"),
        )

    def test_rejects_kickstart_or_wrong_repository_handoff(self):
        for installer, message in (
            ([self.repo, "inst.ks=cdrom:/ks.cfg"], "installer Kickstart evidence"),
            ([self.repo, '"ks=http://10.0.2.2/ks.cfg"'], "installer Kickstart evidence"),
            ([], "installer repository evidence"),
            ([self.repo, self.repo], "installer repository evidence"),
            ([self.repo + "/other"], "installer repository evidence"),
        ):
            self.write_console(installer)
            with (
                self.subTest(installer=installer),
                self.assertRaisesRegex(iso_chain.ValidationError, message),
            ):
                self.verify()

    def test_accepts_the_appstream_sibling_and_optional_probe_404s(self):
        self.write_access_with_status(
            [
                *((path, size, 200) for path, size in self.pins),
                (f"{self.base}/images/install.img", 20, 200),
                (f"{self.base}/images/updates.img", 7, 404),
                (f"{self.base}/images/product.img", 7, 404),
                (self.appstream, 5, 200),
            ]
        )
        self.assertEqual(self.verify()[2], "http-evidence: passed")

    def test_rejects_other_paths_failures_and_probe_only_corroboration(self):
        pins = [(path, size, 200) for path, size in self.pins]
        probes = [
            (f"{self.base}/images/updates.img", 7, 404),
            (f"{self.base}/images/product.img", 7, 404),
        ]
        install = (f"{self.base}/images/install.img", 20, 200)
        for requests, message in (
            ([*pins, install, ("/pub/rocky/9.8/extras/x", 5, 200)], "outside the selected"),
            ([*pins, install, (f"{self.base}/images/other.img", 7, 404)], "failed or reordered"),
            ([*pins, install, probes[0], probes[0]], "failed or reordered"),
            ([*pins, *probes], "lacks post-kexec repository corroboration"),
            ([probes[0], *pins, install], "failed or reordered"),
        ):
            self.write_access_with_status(requests)
            with (
                self.subTest(requests=requests),
                self.assertRaisesRegex(iso_chain.ValidationError, message),
            ):
                self.verify()

    def test_rejects_head_requests(self):
        self.write_access_with_status(
            [
                *((path, size, 200) for path, size in self.pins),
                (f"{self.base}/repodata/repomd.xml", 0, 200, "HEAD"),
                (f"{self.base}/images/install.img", 20, 200),
            ]
        )
        with self.assertRaisesRegex(iso_chain.ValidationError, "access log method is invalid"):
            self.verify()

    def unattended(self):
        data = rocky_manifest_data(ssh_authorized_keys=[KEY], login_user="core")
        self.manifest, canonical, digest = iso_chain.load_manifest_bytes(json.dumps(data).encode())
        self.paths["manifest.json"].write_bytes(canonical)
        path = iso_chain._profile_kickstart(self.manifest, "rocky")[0].path
        return f"inst.ks=cdrom:LABEL={iso_chain._volume_id(digest)}:{path}"

    def test_unattended_rocky_requires_media_kickstart_and_repository_evidence(self):
        kickstart = self.unattended()
        self.write_console([kickstart, self.repo])
        console = self.paths["console.log"].read_text()
        self.paths["console.log"].write_text(
            console.replace("disk: passed\n", "disk: passed\nmedia: passed\n")
        )
        self.assertIn(
            "media: passed",
            iso_chain.verify_launcher_log(self.paths["console.log"], self.manifest, "rocky"),
        )
        for installer, message in (
            ([self.repo], "installer Kickstart evidence"),
            ([kickstart], "installer repository evidence"),
            ([kickstart, self.repo + "/other"], "installer repository evidence"),
            ([kickstart, self.repo, self.repo], "installer repository evidence"),
        ):
            self.write_console(installer)
            console = self.paths["console.log"].read_text()
            self.paths["console.log"].write_text(
                console.replace("disk: passed\n", "disk: passed\nmedia: passed\n")
            )
            with (
                self.subTest(installer=installer),
                self.assertRaisesRegex(iso_chain.ValidationError, message),
            ):
                iso_chain.verify_launcher_log(self.paths["console.log"], self.manifest, "rocky")
        self.write_console([kickstart, self.repo])
        with self.assertRaisesRegex(iso_chain.ValidationError, "reordered launcher evidence"):
            iso_chain.verify_launcher_log(self.paths["console.log"], self.manifest, "rocky")

    def test_rejects_kernel_caller_field(self):
        self.write_console([self.repo])
        console = self.paths["console.log"].read_text()
        self.paths["console.log"].write_text(
            console.replace("[    1.000000] Kernel", "[    1.000000][    T0] Kernel")
        )
        with self.assertRaisesRegex(
            iso_chain.ValidationError, "one contiguous installer kernel command line"
        ):
            self.verify()


class OpenSUSEEvidenceTests(unittest.TestCase):
    write_access = UbuntuEvidenceTests.write_access
    write_access_with_status = RockyEvidenceTests.write_access_with_status
    verify = UbuntuEvidenceTests.verify

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
            json.dumps(opensuse_manifest_data()).encode()
        )
        self.manifest = manifest
        self.profile = manifest.profile("opensuse")
        self.paths["manifest.json"].write_bytes(canonical)
        self.handoff = iso_chain._opensuse_handoff(manifest, self.profile)
        self.write_console(self.handoff)
        self.base = self.profile.repository.path
        self.pins = [
            (self.profile.kernel.path, 6, 200),
            (self.profile.initramfs.path, 9, 200),
        ]
        self.later = [
            (f"{self.base}/CHECKSUMS", 5, 200),
            (f"{self.base}/boot/ppc64le/root", 20, 200),
        ]
        self.probes = [(f"{self.base}/{path}", 7, 404) for path in iso_chain.OPENSUSE_PROBES]
        self.head = (f"{self.base}/repodata/repomd.xml", 0, 200, "HEAD")
        self.write_access_with_status([*self.pins, *self.later])
        self.paths["capture.pcap"].write_bytes(b"pcap")
        self.paths["disk-before.sha256"].write_text("a" * 64 + "\n")
        self.paths["disk-after.sha256"].write_text("a" * 64 + "\n")
        self.record = {
            "version": 1,
            "manifest_sha256": digest,
            "profile": "opensuse",
            "qemu_memory_mib": 8192,
            "guest_memtotal_mib": 8000,
            "guest_memavailable_mib": 6000,
            "disk_label": "test-disk",
            "same_run_collection": True,
            "installer_ready": True,
            "intended_disk_visible": True,
            "intended_source_confirmed": True,
        }

    def write_console(self, installer, network=("IP addresses:", "  10.0.2.15"), caller="[    T0]"):
        digest = hashlib.sha256(self.paths["manifest.json"].read_bytes()).hexdigest()
        self.paths["console.log"].write_text(
            "\r\n".join(
                (
                    "ISO_CHAIN: GRUB optical handoff",
                    "[    0.000000] Kernel command line: "
                    + " ".join(iso_chain._kernel_arguments(self.manifest, digest, "opensuse")),
                    "ISO_CHAIN: configuration passed",
                    "adapter-match: passed",
                    "profile: passed",
                    (
                        "memory: passed memtotal_mib=8000 memavailable_mib=6000 "
                        "run_available_bytes=8589934592"
                    ),
                    "disk: passed",
                    "artifacts: passed",
                    "kexec-load: passed",
                    "kexec-exec: started",
                    f"[    1.000000]{caller} Kernel command line: " + " ".join(installer),
                    *network,
                )
            )
        )

    def test_accepts_opensuse_evidence_without_media_marker(self):
        result = self.verify()
        self.assertEqual(result[2], "http-evidence: passed")
        self.assertEqual(result[-1], "intended-source: operator-reviewed")
        self.assertNotIn(
            "media: passed",
            iso_chain.verify_launcher_log(self.paths["console.log"], self.manifest, "opensuse"),
        )

    def test_accepts_kernel_caller_field(self):
        for caller in ("[    T0]", "[  T123]", "[    C1]", ""):
            self.write_console(self.handoff, caller=caller)
            with self.subTest(caller=caller):
                self.assertEqual(self.verify()[2], "http-evidence: passed")

    def test_accepts_http_head_and_each_probe_404_once(self):
        self.write_access_with_status([*self.pins, self.head, *self.probes, *self.later])
        self.assertEqual(self.verify()[2], "http-evidence: passed")

    def test_rejects_other_http_evidence(self):
        pins, later, probes, head = self.pins, self.later, self.probes, self.head
        kernel = (self.profile.kernel.path, 6, 200)
        for requests, message in (
            ([*pins, *later, (f"{self.base}/other", 7, 404)], "failed or reordered"),
            ([*pins, *later, probes[0], probes[0]], "failed or reordered"),
            ([*pins, *later, (f"{self.base}/autoinst.xml", 7, 200)], "installer probe"),
            ([*pins, *later, kernel], "repeats a launcher artifact"),
            ([*pins, *later, ("/distribution/leap/other", 5, 200)], "outside the selected"),
            ([*pins, *probes], "lacks post-kexec repository corroboration"),
            ([*pins, head, *probes], "lacks post-kexec repository corroboration"),
            ([head, *pins, *later], "invalid launcher request order"),
            ([probes[0], *pins, *later], "invalid launcher request order"),
            ([pins[1], pins[0], *later], "invalid launcher request order"),
            ([(pins[0][0], 5, 200), pins[1], *later], "invalid launcher request order"),
            ([*pins, (*head[:2], 404, "HEAD"), *later], "invalid HEAD response"),
            ([*pins, (head[0], 4, 200, "HEAD"), *later], "invalid HEAD response"),
            ([*pins, (head[0], 0, 200), *later], "empty response"),
        ):
            self.write_access_with_status(requests)
            with (
                self.subTest(requests=requests),
                self.assertRaisesRegex(iso_chain.ValidationError, message),
            ):
                self.verify()

    def test_rejects_wrong_handoff(self):
        ifcfg, hostname, install, *rest = self.handoff
        handoff = "installer handoff evidence"
        network = "installer network evidence"
        for installer, lines, message in (
            ([ifcfg.replace("10.0.2.3", "10.0.2.4"), hostname, install, *rest], None, handoff),
            ([ifcfg.removesuffix(",10.0.2.3"), hostname, install, *rest], None, handoff),
            ([ifcfg, hostname, *rest], None, handoff),
            ([*self.handoff, "repo=http://x/y"], None, handoff),
            ([*self.handoff, "insecure=1"], None, handoff),
            ([*self.handoff, "Self-Update=1"], None, handoff),
            ([*self.handoff, *rest], None, handoff),
            ([ifcfg, hostname, install + "/other", *rest], None, handoff),
            (self.handoff, (), network),
            (self.handoff, ("IP addresses:",), network),
            (self.handoff, ("IP addresses:", "  10.0.2.16"), network),
            (self.handoff, ("IP addresses:", "  10.0.2.15", "IP addresses:", "10.0.2.15"), network),
        ):
            self.write_console(installer, *(() if lines is None else (lines,)))
            with (
                self.subTest(installer=installer, lines=lines),
                self.assertRaisesRegex(iso_chain.ValidationError, message),
            ):
                self.verify()

    def test_accepts_quoted_handoff_arguments(self):
        self.write_console([f'"{argument}"' for argument in self.handoff])
        self.assertEqual(self.verify()[2], "http-evidence: passed")


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
                    "disk: passed",
                    "media: passed",
                    "artifacts: passed",
                    "kexec-load: passed",
                    "kexec-exec: started",
                    installer_command_line(self.manifest, self.manifest_digest),
                    "Anaconda installation complete",
                )
            )
        )
        self.paths["boot-console.log"].write_text(f"installed-boot: passed boot_id={SECOND_ID}\n")
        profile = self.manifest.profile("fedora")
        request_paths = (
            profile.kernel.path,
            profile.initramfs.path,
            profile.repository.treeinfo.path,
            profile.repository.repomd.path,
            "/repository/repodata/primary.xml.gz",
        )
        response_sizes = (
            profile.kernel.size,
            profile.initramfs.size,
            profile.repository.treeinfo.size,
            profile.repository.repomd.size,
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

    def write_access_with_failures(self, failed_paths):
        records = self.paths["access.jsonl"].read_bytes().splitlines()
        for path in failed_paths:
            failed = dict(json.loads(records[-1]), path=path, status=404, bytes=7)
            failed["index"] = len(records) + 1
            records.append(json.dumps(failed, sort_keys=True, separators=(",", ":")).encode())
        self.paths["access.jsonl"].write_bytes(b"\n".join(records) + b"\n")
        self.refresh_record_digests()

    def test_accepts_each_anaconda_probe_404_once(self):
        # Fedora's stage1 probes these beside install.img, which v4 takes from the repository.
        self.write_access_with_failures(
            ["/repository/images/updates.img", "/repository/images/product.img"]
        )
        self.assertIn("http-evidence: passed", self.verify())

    def test_rejects_probe_404s_as_the_only_repository_traffic(self):
        profile = self.manifest.profile("fedora")
        pins = (profile.kernel, profile.initramfs)
        pins += (profile.repository.treeinfo, profile.repository.repomd)
        self.write_access([pin.path for pin in pins], [pin.size for pin in pins])
        self.write_access_with_failures(
            ["/repository/images/updates.img", "/repository/images/product.img"]
        )
        with self.assertRaisesRegex(iso_chain.ValidationError, "lacks post-kexec repository"):
            self.verify()

    def test_rejects_a_probe_404_before_the_launcher_requests(self):
        self.write_access_with_failures(["/repository/images/updates.img"])
        records = self.paths["access.jsonl"].read_bytes().splitlines()
        records.insert(0, records.pop())
        self.paths["access.jsonl"].write_bytes(
            b"".join(
                json.dumps(
                    dict(json.loads(line), index=index), sort_keys=True, separators=(",", ":")
                ).encode()
                + b"\n"
                for index, line in enumerate(records, 1)
            )
        )
        self.refresh_record_digests()
        with self.assertRaisesRegex(iso_chain.ValidationError, "failed or reordered"):
            self.verify()

    def test_rejects_a_repeated_probe_or_other_repository_404(self):
        for failed in (
            ["/repository/images/product.img", "/repository/images/product.img"],
            ["/repository/Packages/missing.rpm"],
        ):
            with self.subTest(failed=failed):
                self.setUp()
                self.write_access_with_failures(failed)
                with self.assertRaisesRegex(iso_chain.ValidationError, "failed or reordered"):
                    self.verify()

    def test_rejects_a_non_fedora_profile(self):
        _, canonical, digest = iso_chain.load_manifest_bytes(
            json.dumps(ubuntu_manifest_data()).encode()
        )
        self.paths["manifest.json"].write_bytes(canonical)
        self.record["manifest_sha256"] = digest
        self.record["profile"] = "ubuntu"
        self.refresh_record_digests()
        with self.assertRaisesRegex(
            iso_chain.ValidationError, "installation evidence requires a Fedora profile"
        ):
            self.verify()

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

    def test_rejects_installer_kickstart_from_another_label(self):
        console = self.paths["install-console.log"].read_text()
        label = iso_chain._volume_id(self.manifest_digest)
        self.paths["install-console.log"].write_text(
            console.replace(label, "ISO_CHAIN_0000000000000000")
        )
        self.refresh_record_digests()
        with self.assertRaisesRegex(iso_chain.ValidationError, "installer Kickstart evidence"):
            self.verify()

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
        records.insert(0, records.pop(2))
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
        records.append(
            {**records[-1], "path": "/profiles/fedora-44/ks.cfg", "index": len(records) + 1}
        )
        self.write_access(
            [record["path"] for record in records], [record["bytes"] for record in records]
        )
        self.refresh_record_digests()
        with self.assertRaisesRegex(iso_chain.ValidationError, "outside the repository"):
            self.verify()

        self.setUp()
        records = [
            json.loads(line) for line in self.paths["access.jsonl"].read_bytes().splitlines()
        ]
        records.append({**records[0], "index": len(records) + 1})
        self.write_access(
            [record["path"] for record in records], [record["bytes"] for record in records]
        )
        self.refresh_record_digests()
        with self.assertRaisesRegex(iso_chain.ValidationError, "exactly one kernel"):
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


class RockyInstallEvidenceTests(unittest.TestCase):
    write_access = FedoraInstallEvidenceTests.write_access
    write_result = FedoraInstallEvidenceTests.write_result

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        names = (
            "record.json",
            "manifest.json",
            "install-console.log",
            "boot-console.log",
            "access.jsonl",
            "result.json",
            "install.pcap",
            "boot.pcap",
            "disk-before.sha256",
            "disk-after.sha256",
        )
        self.paths = {name: self.root / name for name in names}
        data = rocky_manifest_data(ssh_authorized_keys=[KEY], login_user="core")
        self.manifest, canonical, digest = iso_chain.load_manifest_bytes(json.dumps(data).encode())
        self.paths["manifest.json"].write_bytes(canonical)
        profile = self.manifest.profile("rocky")
        path = iso_chain._profile_kickstart(self.manifest, "rocky")[0].path
        repo = f"inst.repo={self.manifest.source}{profile.repository.path}"
        self.install_lines = [
            "ISO_CHAIN: GRUB optical handoff",
            "[    0.000000] Kernel command line: "
            + " ".join(iso_chain._kernel_arguments(self.manifest, digest, "rocky")),
            "ISO_CHAIN: configuration passed",
            "adapter-match: passed",
            "profile: passed",
            "memory: passed memtotal_mib=8000 memavailable_mib=6000 run_available_bytes=8589934592",
            "disk: passed",
            "media: passed",
            "artifacts: passed",
            "kexec-load: passed",
            "kexec-exec: started",
            (
                "[    1.000000] Kernel command line: inst.text rd.neednet=1 "
                f"inst.ks=cdrom:LABEL={iso_chain._volume_id(digest)}:{path} {repo} console=hvc0"
            ),
            "[ 4000.000000] reboot: Restarting system",
        ]
        self.paths["install-console.log"].write_text("\n".join(self.install_lines) + "\n")
        self.boot_lines = [
            "\x1b[1;1HSLOF booting",
            "ISO_CHAIN: GRUB installed-disk handoff",
            "[    0.000000] Linux version 5.14.0",
            "",
            "sys-r1 login: ",
        ]
        self.paths["boot-console.log"].write_text("\n".join(self.boot_lines))
        base = profile.repository.path
        self.requests = [
            (profile.kernel.path, profile.kernel.size, 200),
            (profile.initramfs.path, profile.initramfs.size, 200),
            (profile.repository.treeinfo.path, profile.repository.treeinfo.size, 200),
            (profile.repository.repomd.path, profile.repository.repomd.size, 200),
            (f"{base}/images/install.img", 20, 200),
            (f"{base}/images/updates.img", 7, 404),
            (f"{base}/images/product.img", 7, 404),
            ("/pub/rocky/9.8/AppStream/ppc64le/os/repodata/repomd.xml", 5, 200),
            (f"{base}/Packages/b/bash.rpm", 30, 200),
        ]
        self.write_requests(self.requests)
        self.paths["install.pcap"].write_bytes(b"pcap")
        self.paths["boot.pcap"].write_bytes(b"boot pcap")
        self.paths["disk-before.sha256"].write_text("a" * 64 + "\n")
        self.paths["disk-after.sha256"].write_text("b" * 64 + "\n")
        self.result = {
            "version": 1,
            "qemu_memory_mib": 8192,
            "disk_size_gib": 20,
            "install_timeout_seconds": 14400,
            "boot_timeout_seconds": 3600,
            "install_exit_status": 0,
            "boot_stop": "login-prompt",
            "disk_sha256_before": "a" * 64,
            "disk_sha256_after": "b" * 64,
            "disk_bytes_after": 1234,
        }
        self.write_result()
        self.record = {
            "version": 1,
            "manifest_sha256": digest,
            "profile": "rocky",
            "qemu_memory_mib": 8192,
            "disk_label": "fresh-rocky-disk",
            "evidence_sha256": {},
            "same_run_collection": True,
        }
        self.refresh_record_digests()

    def write_requests(self, requests):
        self.write_access([path for path, _, _ in requests], [size for _, size, _ in requests])
        records = [
            dict(json.loads(line), status=status)
            for line, (_, _, status) in zip(
                self.paths["access.jsonl"].read_bytes().splitlines(), requests, strict=True
            )
        ]
        self.paths["access.jsonl"].write_bytes(
            b"".join(
                json.dumps(record, sort_keys=True, separators=(",", ":")).encode() + b"\n"
                for record in records
            )
        )

    def refresh_record_digests(self):
        mapping = {
            "manifest": "manifest.json",
            "install_console": "install-console.log",
            "boot_console": "boot-console.log",
            "access_log": "access.jsonl",
            "result": "result.json",
            "install_pcap": "install.pcap",
            "boot_pcap": "boot.pcap",
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

    def verify(self, packet_output=b""):
        args = SimpleNamespace(
            record=self.paths["record.json"],
            config=self.paths["manifest.json"],
            install_console_log=self.paths["install-console.log"],
            boot_console_log=self.paths["boot-console.log"],
            access_log=self.paths["access.jsonl"],
            result=self.paths["result.json"],
            install_pcap=self.paths["install.pcap"],
            boot_pcap=self.paths["boot.pcap"],
            disk_hash_before=self.paths["disk-before.sha256"],
            disk_hash_after=self.paths["disk-after.sha256"],
        )
        with mock.patch("scripts.iso_chain.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, packet_output, b"")
            return iso_chain.verify_rocky_install_evidence(args)

    def rejects(self, message):
        self.refresh_record_digests()
        with self.assertRaisesRegex(iso_chain.ValidationError, message):
            self.verify()
        self.setUp()

    def test_accepts_bound_unattended_installation_evidence(self):
        self.assertEqual(
            self.verify(),
            (
                "manifest: passed",
                "kickstart: passed",
                "network-config: passed",
                "http-evidence: passed",
                "installation: passed",
                "reboot: passed",
                "disk-mutation: passed",
                "installed-disk-boot: passed",
                "install-dhcp-ipv6-filter: absent",
                "boot-dhcp-ipv6-filter: absent",
                "same-run: operator-reviewed",
            ),
        )

    def test_rejects_keyless_or_non_rocky_manifests(self):
        for data, profile in (
            (rocky_manifest_data(), "rocky"),
            (manifest_data(), "fedora"),
        ):
            _, canonical, digest = iso_chain.load_manifest_bytes(json.dumps(data).encode())
            self.paths["manifest.json"].write_bytes(canonical)
            self.record.update(manifest_sha256=digest, profile=profile)
            with self.subTest(profile=profile):
                self.rejects("requires an unattended Rocky profile")

    def test_rejects_replaced_inputs_and_unchanged_disks(self):
        self.paths["boot.pcap"].write_bytes(b"replacement")
        with self.assertRaisesRegex(iso_chain.ValidationError, "replaced"):
            self.verify()
        self.setUp()
        self.paths["disk-after.sha256"].write_text("a" * 64 + "\n")
        self.result["disk_sha256_after"] = "a" * 64
        self.write_result()
        self.rejects("installation mutation")
        for field, value in (("boot_stop", "timeout"), ("boot_exit_status", 0)):
            self.result.pop("boot_stop")
            self.result[field] = value
            self.write_result()
            with self.subTest(field=field):
                self.rejects("process result")

    def test_rejects_a_power_off_or_missing_reboot(self):
        restart = self.install_lines[-1]
        for tail in (
            [],
            [restart, restart],
            [restart, "[ 4001.000000] reboot: Power down"],
            ["[ 4000.000000] reboot: Power down"],
        ):
            self.paths["install-console.log"].write_text(
                "\n".join(self.install_lines[:-1] + tail) + "\n"
            )
            with self.subTest(tail=tail):
                self.rejects("one reboot")

    def test_rejects_traffic_outside_baseos_and_appstream_and_repeated_probes(self):
        base = self.manifest.profile("rocky").repository.path
        for extra, message in (
            [("/pub/rocky/9.8/extras/x", 5, 200), "outside the repository"],
            [(f"{base}/images/updates.img", 7, 404), "failed or reordered"],
            [(f"{base}/images/other.img", 7, 404), "failed or reordered"],
        ):
            self.write_requests([*self.requests, extra])
            with self.subTest(extra=extra):
                self.rejects(message)

    def test_rejects_probe_404s_as_the_only_repository_traffic(self):
        self.write_requests(self.requests[:4] + self.requests[5:7])
        self.rejects("lacks post-kexec repository traffic")

    def test_rejects_a_probe_404_before_the_launcher_requests(self):
        self.write_requests([self.requests[5], *self.requests[:5], *self.requests[6:]])
        self.rejects("failed or reordered")

    def test_rejects_launcher_evidence_without_the_unattended_kickstart(self):
        lines = [line for line in self.install_lines if not line.startswith("[    1.0")]
        lines.insert(-1, "[    1.000000] Kernel command line: inst.text console=hvc0")
        self.paths["install-console.log"].write_text("\n".join(lines) + "\n")
        self.rejects("installer Kickstart evidence")

    def test_accepts_kernel_messages_after_the_login_prompt(self):
        self.paths["boot-console.log"].write_text(
            "\n".join(self.boot_lines[:-1])
            + "\r\nsys-r1 login: [   86.426247] block dm-0: the capability attribute"
        )
        self.refresh_record_digests()
        self.assertEqual(self.verify()[7], "installed-disk-boot: passed")

    def test_rejects_a_boot_that_did_not_reach_the_installed_login_through_the_iso(self):
        handoff = "ISO_CHAIN: GRUB installed-disk handoff"
        for lines in (
            [line for line in self.boot_lines if line != handoff],
            [handoff, *self.boot_lines],
            ["ISO_CHAIN: GRUB optical handoff", *self.boot_lines],
            [*self.boot_lines[:-1], "ISO_CHAIN: configuration passed", "sys-r1 login: "],
            self.boot_lines[:-1],
            ["sys-r1 login: ", *self.boot_lines[:-1]],
            [*self.boot_lines[:-1], "other login: "],
        ):
            self.paths["boot-console.log"].write_text("\n".join(lines))
            with self.subTest(lines=lines):
                self.rejects("boot console")

    def test_rejects_dhcp_or_ipv6_in_either_capture(self):
        with self.assertRaisesRegex(iso_chain.ValidationError, "DHCP or IPv6"):
            self.verify(packet_output=b"forbidden packet")

    def test_parser_exposes_the_rocky_install_evidence_contract(self):
        arguments = ["verify-rocky-install-evidence"]
        for option in (
            "record",
            "config",
            "install-console-log",
            "boot-console-log",
            "access-log",
            "result",
            "install-pcap",
            "boot-pcap",
            "disk-hash-before",
            "disk-hash-after",
        ):
            arguments.extend((f"--{option}", "x"))
        self.assertEqual(
            iso_chain.parser().parse_args(arguments).command, "verify-rocky-install-evidence"
        )


class UbuntuInstallEvidenceTests(unittest.TestCase):
    write_access = FedoraInstallEvidenceTests.write_access
    write_result = FedoraInstallEvidenceTests.write_result
    write_requests = RockyInstallEvidenceTests.write_requests
    refresh_record_digests = RockyInstallEvidenceTests.refresh_record_digests
    rejects = RockyInstallEvidenceTests.rejects

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        names = (
            "record.json",
            "manifest.json",
            "install-console.log",
            "boot-console.log",
            "access.jsonl",
            "result.json",
            "install.pcap",
            "boot.pcap",
            "disk-before.sha256",
            "disk-after.sha256",
        )
        self.paths = {name: self.root / name for name in names}
        data = ubuntu_manifest_data(ssh_authorized_keys=[KEY], login_user="core")
        self.manifest, canonical, digest = iso_chain.load_manifest_bytes(json.dumps(data).encode())
        self.paths["manifest.json"].write_bytes(canonical)
        profile = self.manifest.profile("ubuntu")
        handoff = iso_chain._ubuntu_handoff(self.manifest, profile, iso_chain._volume_id(digest))
        self.install_lines = [
            "ISO_CHAIN: GRUB optical handoff",
            "[    0.000000] Kernel command line: "
            + " ".join(iso_chain._kernel_arguments(self.manifest, digest, "ubuntu")),
            "ISO_CHAIN: configuration passed",
            "adapter-match: passed",
            "profile: passed",
            "memory: passed memtotal_mib=8000 memavailable_mib=6000 run_available_bytes=8589934592",
            "disk: passed",
            "media: passed",
            "artifacts: passed",
            "kexec-load: passed",
            "kexec-exec: started",
            "[    0.000000] Kernel command line: " + " ".join(handoff),
            'echo "autoinstall-disk: passed $disk"',
            "autoinstall-disk: passed vda",
            "[  900.000000] reboot: Restarting system",
        ]
        self.paths["install-console.log"].write_text("\n".join(self.install_lines) + "\n")
        self.boot_lines = [
            "ISO_CHAIN: GRUB installed-disk handoff",
            "[    0.000000] Linux version 7.0.0",
            "sys-r1 login: ",
        ]
        self.paths["boot-console.log"].write_text("\n".join(self.boot_lines))
        self.requests = [
            (profile.kernel.path, profile.kernel.size, 200),
            (profile.initramfs.path, profile.initramfs.size, 200),
            (profile.live_iso.path, profile.live_iso.size, 200),
        ]
        self.write_requests(self.requests)
        self.paths["install.pcap"].write_bytes(b"pcap")
        self.paths["boot.pcap"].write_bytes(b"boot pcap")
        self.paths["disk-before.sha256"].write_text("a" * 64 + "\n")
        self.paths["disk-after.sha256"].write_text("b" * 64 + "\n")
        self.result = {
            "version": 1,
            "qemu_memory_mib": 8192,
            "disk_size_gib": 20,
            "install_timeout_seconds": 14400,
            "boot_timeout_seconds": 3600,
            "install_exit_status": 0,
            "boot_stop": "login-prompt",
            "disk_sha256_before": "a" * 64,
            "disk_sha256_after": "b" * 64,
            "disk_bytes_after": 1234,
        }
        self.write_result()
        self.record = {
            "version": 1,
            "manifest_sha256": digest,
            "profile": "ubuntu",
            "qemu_memory_mib": 8192,
            "disk_label": "fresh-ubuntu-disk",
            "evidence_sha256": {},
            "same_run_collection": True,
        }
        self.refresh_record_digests()

    def verify(self, packet_output=b""):
        args = SimpleNamespace(
            record=self.paths["record.json"],
            config=self.paths["manifest.json"],
            install_console_log=self.paths["install-console.log"],
            boot_console_log=self.paths["boot-console.log"],
            access_log=self.paths["access.jsonl"],
            result=self.paths["result.json"],
            install_pcap=self.paths["install.pcap"],
            boot_pcap=self.paths["boot.pcap"],
            disk_hash_before=self.paths["disk-before.sha256"],
            disk_hash_after=self.paths["disk-after.sha256"],
        )
        with mock.patch("scripts.iso_chain.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, packet_output, b"")
            return iso_chain.verify_ubuntu_install_evidence(args)

    def test_accepts_bound_unattended_installation_evidence(self):
        self.assertEqual(
            self.verify(),
            (
                "manifest: passed",
                "user-data: passed",
                "network-config: passed",
                "http-evidence: passed",
                "installation: passed",
                "reboot: passed",
                "disk-mutation: passed",
                "installed-disk-boot: passed",
                "install-dhcp-ipv6-filter: absent",
                "boot-dhcp-ipv6-filter: absent",
                "same-run: operator-reviewed",
            ),
        )

    def test_rejects_keyless_or_non_ubuntu_manifests(self):
        for data, profile in (
            (ubuntu_manifest_data(), "ubuntu"),
            (rocky_manifest_data(ssh_authorized_keys=[KEY], login_user="core"), "rocky"),
        ):
            _, canonical, digest = iso_chain.load_manifest_bytes(json.dumps(data).encode())
            self.paths["manifest.json"].write_bytes(canonical)
            self.record.update(manifest_sha256=digest, profile=profile)
            with self.subTest(profile=profile):
                self.rejects("requires an unattended Ubuntu profile")

    def test_rejects_traffic_beyond_the_three_pinned_requests(self):
        profile = self.manifest.profile("ubuntu")
        for requests in (
            [*self.requests, ("/ubuntu/dists/resolute/Release", 5, 200)],
            [*self.requests, (profile.live_iso.path, profile.live_iso.size, 200)],
            self.requests[:2],
        ):
            self.write_requests(requests)
            with self.subTest(requests=len(requests)):
                self.rejects("HTTP evidence must be exactly")

    def test_requires_autoinstall_markers_for_one_disk_after_the_handoff(self):
        marker = "autoinstall-disk: passed vda"
        lines = self.install_lines
        replayed = [*lines[:-1], marker, lines[-1]]
        self.paths["install-console.log"].write_text("\n".join(replayed) + "\n")
        self.refresh_record_digests()
        self.assertEqual(self.verify()[1], "user-data: passed")
        for changed in (
            [line for line in lines if line != marker],
            [*lines[:-1], "autoinstall-disk: passed vdb", lines[-1]],
            [*lines[:10], marker, *[line for line in lines[10:] if line != marker]],
            [line if line != marker else "autoinstall-disk: passed $disk" for line in lines],
        ):
            self.paths["install-console.log"].write_text("\n".join(changed) + "\n")
            with self.subTest(changed=changed):
                self.rejects("autoinstall")

    def test_rejects_a_missing_reboot_unchanged_disk_or_direct_boot(self):
        self.paths["install-console.log"].write_text("\n".join(self.install_lines[:-1]) + "\n")
        self.rejects("one reboot")
        self.paths["disk-after.sha256"].write_text("a" * 64 + "\n")
        self.result["disk_sha256_after"] = "a" * 64
        self.write_result()
        self.rejects("installation mutation")
        self.paths["boot-console.log"].write_text("\n".join(self.boot_lines[1:]))
        self.rejects("boot console")

    def test_rejects_a_keyless_casper_line(self):
        profile = self.manifest.profile("ubuntu")
        lines = list(self.install_lines)
        lines[11] = "[    0.000000] Kernel command line: " + " ".join(
            iso_chain._ubuntu_handoff(self.manifest, profile, None)
        )
        self.paths["install-console.log"].write_text("\n".join(lines) + "\n")
        self.rejects("installer handoff evidence")

    def test_parser_exposes_the_ubuntu_install_evidence_contract(self):
        arguments = ["verify-ubuntu-install-evidence"]
        for option in (
            "record",
            "config",
            "install-console-log",
            "boot-console-log",
            "access-log",
            "result",
            "install-pcap",
            "boot-pcap",
            "disk-hash-before",
            "disk-hash-after",
        ):
            arguments.extend((f"--{option}", "x"))
        self.assertEqual(
            iso_chain.parser().parse_args(arguments).command, "verify-ubuntu-install-evidence"
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

    def test_result_reports_prepared_and_refuses_bound_media(self):
        single = manifest_data(profiles={"fedora": manifest_data()["profiles"]["fedora"]})
        embedded = single

        def fake_run(command, check):
            Path(command[-1]).write_text(json.dumps(embedded))

        with mock.patch("scripts.iso_chain.subprocess.run", side_effect=fake_run):
            result = json.loads(iso_chain.inspect_result(self.iso))
            embedded = dict(single, operation_binding="0" * 32)
            with self.assertRaisesRegex(iso_chain.ValidationError, "operation_binding"):
                iso_chain.inspect_result(self.iso)
            embedded = manifest_data(profiles=base_manifest()["profiles"], selected_profile="rocky")
            with self.assertRaisesRegex(iso_chain.ValidationError, "exactly one profile"):
                iso_chain.inspect_result(self.iso)
        self.assertEqual(result["format"], "iso-chain-media-v1")
        self.assertEqual(result["iso_sha256"], hashlib.sha256(b"iso").hexdigest())
        self.assertEqual(result["iso_size"], 3)
        self.assertEqual(
            result["manifest_sha256"],
            iso_chain.load_manifest_bytes(json.dumps(single).encode())[2],
        )
        self.assertNotIn("url", result)
        self.assertNotIn("operation_binding", result)

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
            Path(command[-1]).write_bytes(b" " * (iso_chain.MAX_MANIFEST_BYTES + 1))

        with (
            mock.patch("scripts.iso_chain.subprocess.run", side_effect=fake_run),
            self.assertRaisesRegex(iso_chain.ValidationError, "exceeds 2 MiB"),
        ):
            iso_chain.inspect_iso(self.iso)


NETINST_IMAGES = {
    "ppc/ppc64/vmlinuz": b"kernel",
    "ppc/ppc64/initrd.img": b"\xfd7zXZ\x00initramfs",
}


class FedoraSourceTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.iso = self.root / "Fedora-Everything-netinst-ppc64le-44.iso"
        self.iso.write_bytes(b"verified Fedora image")
        self.digest = hashlib.sha256(self.iso.read_bytes()).hexdigest()
        self.tree = self.root / "tree"
        (self.tree / "repodata").mkdir(parents=True)
        (self.tree / "repodata/repomd.xml").write_bytes(b"metadata")
        self.write_treeinfo()
        self.output = self.root / "source"
        self.kickstart = self.root / "ks.cfg"
        self.kickstart.write_bytes(b"text\npoweroff\n")
        self.commands = []
        self.images = dict(NETINST_IMAGES)

    def write_treeinfo(self, variant="Everything", omit=None, boot_digest=None):
        checksums = {"images/boot.iso": boot_digest or self.digest}
        checksums.update(
            {path: hashlib.sha256(content).hexdigest() for path, content in NETINST_IMAGES.items()}
        )
        lines = ["[checksums]"]
        lines += [f"{path} = sha256:{digest}" for path, digest in checksums.items() if path != omit]
        lines += [
            "[general]",
            "family = Fedora",
            "version = 44",
            "arch = ppc64le",
            f"variant = {variant}",
            "[images-ppc64le]",
            "kernel = ppc/ppc64/vmlinuz",
            "initrd = ppc/ppc64/initrd.img",
            "[stage2]",
            "mainimage = images/install.img",
        ]
        (self.tree / ".treeinfo").write_text("\n".join(lines) + "\n")

    def args(self, **changes):
        values = {
            "iso": self.iso,
            "iso_sha256": self.digest,
            "tree": self.tree,
            "repository_path": "/pub/fedora-secondary/releases/44/Everything/ppc64le/os",
            "minimum_memory_mib": 4096,
            "kickstart": self.kickstart,
            "output": self.output,
        }
        values.update(changes)
        return SimpleNamespace(**values)

    def fake_run(self, command, **kwargs):
        self.commands.append(command)
        if command[0] == "xorriso":
            Path(command[-1]).write_bytes(self.images[command[-2].lstrip("/")])
        return subprocess.CompletedProcess(command, 0)

    def test_verifies_digest_before_fixed_extraction_and_writes_canonical_profile(self):
        with mock.patch("scripts.iso_chain.subprocess.run", side_effect=self.fake_run):
            iso_chain.prepare_fedora_source(self.args())

        self.assertEqual(
            [command[6] for command in self.commands],
            ["/ppc/ppc64/vmlinuz", "/ppc/ppc64/initrd.img"],
        )
        for command in self.commands:
            self.assertEqual(
                command,
                ["xorriso", "-osirrox", "on", "-indev", mock.ANY, "-extract", mock.ANY, mock.ANY],
            )
            self.assertNotEqual(Path(command[4]), self.iso.resolve())
            self.assertEqual(Path(command[-1]).parent, Path(command[4]).parent)
        profile_bytes = (self.output / "profile.json").read_bytes()
        profile = json.loads(profile_bytes)
        self.assertEqual(
            profile_bytes,
            json.dumps(profile, sort_keys=True, separators=(",", ":")).encode() + b"\n",
        )
        manifest = manifest_data(profiles={"fedora": profile})
        parsed = iso_chain.load_manifest_bytes(json.dumps(manifest).encode())[0].profile("fedora")
        repository = "/pub/fedora-secondary/releases/44/Everything/ppc64le/os"
        for artifact, path in (
            (parsed.kernel, "ppc/ppc64/vmlinuz"),
            (parsed.initramfs, "ppc/ppc64/initrd.img"),
        ):
            self.assertEqual(artifact.path, f"{repository}/{path}")
            self.assertEqual(artifact.size, len(NETINST_IMAGES[path]))
            self.assertEqual(artifact.sha256, hashlib.sha256(NETINST_IMAGES[path]).hexdigest())
        self.assertEqual(
            parsed.repository.path, "/pub/fedora-secondary/releases/44/Everything/ppc64le/os"
        )
        self.assertEqual(
            parsed.repository.treeinfo.sha256,
            hashlib.sha256((self.tree / ".treeinfo").read_bytes()).hexdigest(),
        )
        self.assertEqual(parsed.repository.repomd.sha256, hashlib.sha256(b"metadata").hexdigest())
        self.assertEqual(
            parsed.kickstart.sha256, hashlib.sha256(self.kickstart.read_bytes()).hexdigest()
        )
        self.assertEqual(parsed.minimum_memory_mib, 4096)
        self.assertEqual(
            sorted(path.name for path in self.output.iterdir()), ["profile.json", "profiles"]
        )
        self.assertEqual(
            sorted(path.name for path in (self.output / "profiles/fedora-44").iterdir()),
            ["ks.cfg"],
        )

    def test_accepts_a_server_tree(self):
        self.write_treeinfo(variant="Server")
        with mock.patch("scripts.iso_chain.subprocess.run", side_effect=self.fake_run):
            iso_chain.prepare_fedora_source(self.args())
        self.assertTrue((self.output / "profile.json").is_file())

    def test_rejects_untrusted_tree_metadata_before_extraction(self):
        cases = (
            ({"variant": "Workstation"}, "Everything or Server"),
            ({"omit": "images/boot.iso"}, "metadata"),
            ({"omit": "ppc/ppc64/vmlinuz"}, "metadata"),
            ({"omit": "ppc/ppc64/initrd.img"}, "metadata"),
            ({"boot_digest": "0" * 64}, "boot.iso does not match the netinst ISO"),
        )
        for changes, message in cases:
            self.write_treeinfo(**changes)
            with (
                self.subTest(changes=changes),
                mock.patch("scripts.iso_chain.subprocess.run") as run,
                self.assertRaisesRegex(iso_chain.ValidationError, message),
            ):
                iso_chain.prepare_fedora_source(self.args())
            run.assert_not_called()
            self.assertFalse(self.output.exists())

    def test_rejects_non_sha256_checksum_entries(self):
        treeinfo = self.tree / ".treeinfo"
        treeinfo.write_text(
            treeinfo.read_text().replace(
                "ppc/ppc64/initrd.img = sha256:", "ppc/ppc64/initrd.img = md5:"
            )
        )
        with (
            mock.patch("scripts.iso_chain.subprocess.run") as run,
            self.assertRaisesRegex(iso_chain.ValidationError, "must be SHA-256"),
        ):
            iso_chain.prepare_fedora_source(self.args())
        run.assert_not_called()

    def test_rejects_an_extracted_image_that_differs_from_treeinfo(self):
        self.images["ppc/ppc64/initrd.img"] = b"tampered"
        with (
            mock.patch("scripts.iso_chain.subprocess.run", side_effect=self.fake_run),
            self.assertRaisesRegex(iso_chain.ValidationError, "does not match .treeinfo"),
        ):
            iso_chain.prepare_fedora_source(self.args())
        self.assertFalse(self.output.exists())

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

    def test_kickstart_descriptor_survives_path_replacement(self):
        replacement = self.root / "replacement.ks"
        replacement.write_bytes(b"replacement\n")
        original_open = os.open

        def open_and_replace(path, flags, **kwargs):
            descriptor = original_open(path, flags, **kwargs)
            if Path(path) == self.kickstart:
                self.kickstart.unlink()
                self.kickstart.symlink_to(replacement)
            return descriptor

        with (
            mock.patch("scripts.iso_chain.os.open", side_effect=open_and_replace),
            mock.patch("scripts.iso_chain.subprocess.run", side_effect=self.fake_run),
        ):
            iso_chain.prepare_fedora_source(self.args())
        self.assertEqual(
            (self.output / "profiles/fedora-44/ks.cfg").read_bytes(), b"text\npoweroff\n"
        )

    def test_wrong_digest_and_bad_metadata_do_not_extract_or_publish(self):
        self.write_treeinfo(boot_digest="0" * 64)
        with (
            mock.patch("scripts.iso_chain.subprocess.run") as run,
            self.assertRaisesRegex(iso_chain.ValidationError, "digest"),
        ):
            iso_chain.prepare_fedora_source(self.args(iso_sha256="0" * 64))
        run.assert_not_called()
        self.assertFalse(self.output.exists())
        self.write_treeinfo()

        oversized = b"x" * (len(self.iso.read_bytes()) + 1)
        self.iso.write_bytes(oversized)
        self.write_treeinfo(boot_digest=hashlib.sha256(oversized).hexdigest())
        with (
            mock.patch.object(iso_chain, "MAX_INSTALLER_ISO_BYTES", len(oversized) - 1),
            mock.patch("scripts.iso_chain.subprocess.run") as run,
            self.assertRaisesRegex(iso_chain.ValidationError, "size"),
        ):
            iso_chain.prepare_fedora_source(
                self.args(iso_sha256=hashlib.sha256(oversized).hexdigest())
            )
        run.assert_not_called()
        self.assertFalse(self.output.exists())
        self.iso.write_bytes(b"verified Fedora image")
        self.write_treeinfo()

        (self.tree / ".treeinfo").write_bytes(b"x" * (64 * 1024 + 1))
        with (
            mock.patch("scripts.iso_chain.subprocess.run") as run,
            self.assertRaisesRegex(iso_chain.ValidationError, "treeinfo"),
        ):
            iso_chain.prepare_fedora_source(self.args())
        run.assert_not_called()
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
            if command[-2] == "/ppc/ppc64/initrd.img":
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
                "--tree",
                str(self.tree),
                "--repository-path",
                "/pub/fedora/44",
                "--minimum-memory-mib",
                "4096",
                "--kickstart",
                str(self.kickstart),
                "--output",
                str(self.output),
            ]
        )
        self.assertEqual(args.command, "prepare-fedora-source")
        self.assertEqual(args.tree, self.tree)
        self.assertEqual(args.repository_path, "/pub/fedora/44")
        self.assertEqual(args.minimum_memory_mib, 4096)
        self.assertEqual(args.kickstart, self.kickstart)


class RockySourceTests(unittest.TestCase):
    fake_run = FedoraSourceTests.fake_run
    repository = "/pub/rocky/9.8/BaseOS/ppc64le/os"

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.iso = self.root / "Rocky-9.8-ppc64le-boot.iso"
        self.iso.write_bytes(b"verified Rocky image")
        self.digest = hashlib.sha256(self.iso.read_bytes()).hexdigest()
        self.tree = self.root / "tree"
        (self.tree / "repodata").mkdir(parents=True)
        (self.tree / "repodata/repomd.xml").write_bytes(b"metadata")
        self.write_treeinfo()
        self.output = self.root / "source"
        self.commands = []
        self.images = dict(NETINST_IMAGES)

    def write_treeinfo(self, family="Rocky Linux", appstream="../../../AppStream/ppc64le/os/"):
        checksums = {"images/boot.iso": self.digest}
        checksums.update(
            {path: hashlib.sha256(content).hexdigest() for path, content in NETINST_IMAGES.items()}
        )
        lines = ["[checksums]", *(f"{path} = sha256:{value}" for path, value in checksums.items())]
        lines += [
            "[general]",
            f"family = {family}",
            "version = 9.8",
            "arch = ppc64le",
            "variant = BaseOS",
            "[images-ppc64le]",
            "kernel = ppc/ppc64/vmlinuz",
            "initrd = ppc/ppc64/initrd.img",
        ]
        if appstream is not None:
            lines += ["[variant-AppStream]", f"repository = {appstream}"]
        (self.tree / ".treeinfo").write_text("\n".join(lines) + "\n")

    def args(self, **changes):
        values = {
            "iso": self.iso,
            "iso_sha256": self.digest,
            "tree": self.tree,
            "repository_path": self.repository,
            "minimum_memory_mib": 3072,
            "output": self.output,
        }
        values.update(changes)
        return SimpleNamespace(**values)

    def test_writes_a_kickstart_free_rocky_profile(self):
        with mock.patch("scripts.iso_chain.subprocess.run", side_effect=self.fake_run):
            iso_chain.prepare_rocky_source(self.args())
        self.assertEqual(
            [command[6] for command in self.commands],
            ["/ppc/ppc64/vmlinuz", "/ppc/ppc64/initrd.img"],
        )
        self.assertEqual([path.name for path in self.output.iterdir()], ["profile.json"])
        profile = json.loads((self.output / "profile.json").read_bytes())
        self.assertNotIn("kickstart", profile)
        manifest = rocky_manifest_data(profiles={"rocky": profile})
        parsed = iso_chain.load_manifest_bytes(json.dumps(manifest).encode())[0].profile("rocky")
        self.assertEqual(parsed.kernel.path, f"{self.repository}/ppc/ppc64/vmlinuz")
        self.assertEqual(
            parsed.initramfs.sha256,
            hashlib.sha256(NETINST_IMAGES["ppc/ppc64/initrd.img"]).hexdigest(),
        )
        self.assertEqual(parsed.repository.repomd.sha256, hashlib.sha256(b"metadata").hexdigest())
        self.assertEqual(parsed.minimum_memory_mib, 3072)

    def test_accepts_the_appstream_path_without_its_trailing_slash(self):
        self.write_treeinfo(appstream="../../../AppStream/ppc64le/os")
        with mock.patch("scripts.iso_chain.subprocess.run", side_effect=self.fake_run):
            iso_chain.prepare_rocky_source(self.args())
        self.assertTrue((self.output / "profile.json").is_file())

    def test_rejects_untrusted_inputs_before_extraction(self):
        cases = (
            ({"family": "Fedora"}, {}, "Rocky treeinfo: expected Rocky Linux 9.8 ppc64le BaseOS"),
            ({"appstream": "../AppStream/"}, {}, "AppStream is not the sibling repository"),
            ({"appstream": "../../../AppStream/ppc64le/os//"}, {}, "AppStream is not the sibling"),
            ({"appstream": None}, {}, "AppStream is not the sibling repository"),
            ({}, {"iso_sha256": "0" * 64}, "boot.iso does not match"),
            ({}, {"repository_path": "/secret/os"}, "must end in /BaseOS/ppc64le/os"),
        )
        for treeinfo, changes, message in cases:
            self.write_treeinfo(**treeinfo)
            with (
                self.subTest(treeinfo=treeinfo, changes=changes),
                mock.patch("scripts.iso_chain.subprocess.run") as run,
                self.assertRaisesRegex(iso_chain.ValidationError, message) as error,
            ):
                iso_chain.prepare_rocky_source(self.args(**changes))
            run.assert_not_called()
            self.assertNotIn("secret", str(error.exception))
            self.assertFalse(self.output.exists())

    def test_rejects_an_iso_digest_mismatch_and_an_existing_output(self):
        self.iso.write_bytes(b"other image")
        with (
            mock.patch("scripts.iso_chain.subprocess.run") as run,
            self.assertRaisesRegex(iso_chain.ValidationError, "Rocky ISO digest does not match"),
        ):
            iso_chain.prepare_rocky_source(self.args())
        run.assert_not_called()
        self.output.mkdir()
        with self.assertRaisesRegex(iso_chain.ValidationError, "output already exists"):
            iso_chain.prepare_rocky_source(self.args())

    def test_parser_accepts_the_command(self):
        args = iso_chain.parser().parse_args(
            [
                "prepare-rocky-source",
                *("--iso", "a.iso", "--iso-sha256", "0" * 64, "--tree", "t"),
                *("--repository-path", self.repository, "--minimum-memory-mib", "3072"),
                *("--output", "out"),
            ]
        )
        self.assertEqual(args.command, "prepare-rocky-source")
        self.assertFalse(hasattr(args, "kickstart"))


class OpenSUSESourceTests(unittest.TestCase):
    repository = "/distribution/leap/15.6/repo/oss"

    def setUp(self):
        self.files = {
            "media.1/products": iso_chain.OPENSUSE_PRODUCTS,
            "boot/ppc64le/linux": b"kernel",
            "boot/ppc64le/initrd": b"initramfs",
        }
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.tree = self.root / "tree"
        for relative, content in self.files.items():
            (self.tree / relative).parent.mkdir(parents=True, exist_ok=True)
            (self.tree / relative).write_bytes(content)
        self.checksums = self.root / "CHECKSUMS"
        self.write_checksums()
        self.output = self.root / "source"

    def write_checksums(self, *, skip=(), extra=(), upper=False, spaces="  ", products=None):
        lines = []
        files = {**self.files, "media.1/products": products or self.files["media.1/products"]}
        for relative, content in files.items():
            if relative in skip:
                continue
            digest = hashlib.sha256(content).hexdigest()
            lines.append(f"{digest.upper() if upper else digest}{spaces}{relative}")
        lines += ["", f"{'1' * 64}  boot/other", *extra]
        self.checksums.write_text("\n".join(lines) + "\n")

    def args(self, **changes):
        values = {
            "checksums": self.checksums,
            "tree": self.tree,
            "repository_path": self.repository,
            "minimum_memory_mib": 4096,
            "output": self.output,
        }
        values.update(changes)
        return SimpleNamespace(**values)

    def test_writes_an_opensuse_profile(self):
        with mock.patch("scripts.iso_chain.subprocess.run") as run:
            iso_chain.prepare_opensuse_source(self.args())
        run.assert_not_called()
        self.assertEqual([path.name for path in self.output.iterdir()], ["profile.json"])
        profile = json.loads((self.output / "profile.json").read_bytes())
        base = self.repository
        self.assertEqual(
            profile,
            {
                "distribution": "opensuse",
                "release": "15.6",
                "kernel": {
                    "path": f"{base}/boot/ppc64le/linux",
                    "size": 6,
                    "sha256": hashlib.sha256(b"kernel").hexdigest(),
                },
                "initramfs": {
                    "path": f"{base}/boot/ppc64le/initrd",
                    "size": 9,
                    "sha256": hashlib.sha256(b"initramfs").hexdigest(),
                },
                "repository": {"path": base},
                "minimum_memory_mib": 4096,
            },
        )
        manifest = opensuse_manifest_data(profiles={"opensuse": profile})
        parsed = iso_chain.load_manifest_bytes(json.dumps(manifest).encode())[0].profile("opensuse")
        self.assertIsNone(parsed.repository.treeinfo)

    def test_rejects_untrusted_inputs_without_leaving_output(self):
        def tamper(relative, content):
            (self.tree / relative).write_bytes(content)

        def products_15_5():
            products = b"/ openSUSE-Leap 15.5-1\n"
            tamper("media.1/products", products)
            self.write_checksums(products=products)

        cases = (
            ("one space", lambda: self.write_checksums(spaces=" "), "malformed or repeated"),
            ("upper case", lambda: self.write_checksums(upper=True), "malformed or repeated"),
            (
                "repeat",
                lambda: self.write_checksums(extra=[f"{'2' * 64}  boot/other"]),
                "malformed or repeated",
            ),
            (
                "missing entry",
                lambda: self.write_checksums(skip=("boot/ppc64le/initrd",)),
                "openSUSE CHECKSUMS: missing a boot or product entry",
            ),
            (
                "oversized",
                lambda: self.checksums.write_bytes(b"\n" * (2**20 + 1)),
                "CHECKSUMS: exceeds",
            ),
            (
                "modified kernel",
                lambda: tamper("boot/ppc64le/linux", b"kerneL"),
                "openSUSE tree: boot/ppc64le/linux does not match CHECKSUMS",
            ),
            (
                "missing initrd",
                lambda: (self.tree / "boot/ppc64le/initrd").unlink(),
                "openSUSE tree boot/ppc64le/initrd: unavailable",
            ),
            (
                "wrong products digest",
                lambda: self.write_checksums(products=b"/ openSUSE-Leap 15.6-2\n"),
                "openSUSE tree: not the Leap 15.6 repository",
            ),
            ("wrong release", products_15_5, "openSUSE tree: not the Leap 15.6 repository"),
        )
        for name, mutate, message in cases:
            with self.subTest(name):
                self.setUp()
                mutate()
                with (
                    mock.patch("scripts.iso_chain.subprocess.run") as run,
                    self.assertRaisesRegex(iso_chain.ValidationError, message),
                ):
                    iso_chain.prepare_opensuse_source(self.args())
                run.assert_not_called()
                self.assertFalse(self.output.exists())

    def test_rejects_arguments_before_reading_the_tree(self):
        cases = (
            {"repository_path": "/secret//oss"},
            {"minimum_memory_mib": 0},
            {"minimum_memory_mib": 65537},
            {"checksums": self.root / "absent"},
            {"tree": self.root / "absent"},
        )
        for changes in cases:
            with (
                self.subTest(changes=changes),
                mock.patch("scripts.iso_chain._bounded_file") as read,
                self.assertRaises(iso_chain.ValidationError) as error,
            ):
                iso_chain.prepare_opensuse_source(self.args(**changes))
            read.assert_not_called()
            self.assertNotIn("secret", str(error.exception))
            self.assertFalse(self.output.exists())

    def test_rejects_an_existing_output(self):
        self.output.mkdir()
        with (
            mock.patch("scripts.iso_chain._bounded_file") as read,
            self.assertRaisesRegex(iso_chain.ValidationError, "output already exists"),
        ):
            iso_chain.prepare_opensuse_source(self.args())
        read.assert_not_called()

    def test_parser_dispatches(self):
        argv = [
            "prepare-opensuse-source",
            *("--checksums", str(self.checksums), "--tree", str(self.tree)),
            *("--repository-path", self.repository, "--minimum-memory-mib", "4096"),
            *("--output", str(self.output)),
        ]
        self.assertEqual(iso_chain.parser().parse_args(argv).command, "prepare-opensuse-source")
        with mock.patch.object(sys, "argv", ["iso_chain.py", *argv]):
            self.assertEqual(iso_chain.main(), 0)
        self.assertTrue((self.output / "profile.json").is_file())


class UbuntuSourceTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.iso = self.root / "ubuntu-26.04.1-live-server-ppc64el.iso"
        self.iso.write_bytes(b"verified Ubuntu image")
        self.digest = hashlib.sha256(self.iso.read_bytes()).hexdigest()
        self.output = self.root / "source"
        self.commands = []
        self.members = {
            "/.disk/info": (
                b'Ubuntu-Server 26.04.1 LTS "Resolute Raccoon" - Release ppc64el (20260826)\n'
            ),
            "/casper/vmlinux": b"kernel",
            "/casper/initrd": b"initramfs",
        }

    def args(self, **changes):
        values = {
            "iso": self.iso,
            "iso_sha256": self.digest,
            "release_path": "/ubuntu/releases/26.04.1/release",
            "minimum_memory_mib": 4096,
            "output": self.output,
        }
        values.update(changes)
        return SimpleNamespace(**values)

    def fake_run(self, command, **kwargs):
        self.commands.append(command)
        Path(command[7]).write_bytes(self.members[command[6]])
        return subprocess.CompletedProcess(command, 0)

    def prepare(self, **changes):
        with mock.patch("scripts.iso_chain.subprocess.run", side_effect=self.fake_run):
            iso_chain.prepare_ubuntu_source(self.args(**changes))

    def test_verifies_digest_then_extracts_and_writes_canonical_profile(self):
        self.prepare()
        self.assertEqual(
            [command[6] for command in self.commands],
            ["/.disk/info", "/casper/vmlinux", "/casper/initrd"],
        )
        for command in self.commands:
            self.assertEqual(
                command,
                ["xorriso", "-osirrox", "on", "-indev", mock.ANY, "-extract", mock.ANY, mock.ANY],
            )
            self.assertNotEqual(Path(command[4]), self.iso.resolve())
        profile_bytes = (self.output / "profile.json").read_bytes()
        profile = json.loads(profile_bytes)
        self.assertEqual(
            profile_bytes,
            json.dumps(profile, sort_keys=True, separators=(",", ":")).encode() + b"\n",
        )
        data = manifest_data(profiles={"ubuntu": profile}, selected_profile="ubuntu")
        parsed = iso_chain.load_manifest_bytes(json.dumps(data).encode())[0].profile("ubuntu")
        release = "/ubuntu/releases/26.04.1/release"
        for artifact, path, content in (
            (parsed.kernel, "netboot/ppc64el/linux", b"kernel"),
            (parsed.initramfs, "netboot/ppc64el/initrd", b"initramfs"),
        ):
            self.assertEqual(artifact.path, f"{release}/{path}")
            self.assertEqual(artifact.size, len(content))
            self.assertEqual(artifact.sha256, hashlib.sha256(content).hexdigest())
            self.assertEqual((self.output / path).read_bytes(), content)
        self.assertEqual(
            parsed.live_iso,
            iso_chain.Artifact(
                f"{release}/ubuntu-26.04.1-live-server-ppc64el.iso",
                len(b"verified Ubuntu image"),
                self.digest,
            ),
        )
        self.assertEqual(parsed.minimum_memory_mib, 4096)
        self.assertEqual(
            sorted(path.name for path in self.output.iterdir()), ["netboot", "profile.json"]
        )
        self.assertEqual(
            sorted(path.name for path in (self.output / "netboot/ppc64el").iterdir()),
            ["initrd", "linux"],
        )

    def test_wrong_digest_does_not_extract_or_publish(self):
        with self.assertRaisesRegex(iso_chain.ValidationError, "digest does not match"):
            self.prepare(iso_sha256="0" * 64)
        self.assertEqual(self.commands, [])
        self.assertFalse(self.output.exists())

    def test_rejects_wrong_release_or_oversized_disk_info(self):
        for info in (
            b'Ubuntu-Server 24.04.5 LTS "Noble Numbat" - Release ppc64el (20260101)\n',
            b'Ubuntu-Server 26.04.1 LTS "Resolute Raccoon" - Release arm64 (20260826)\n',
            b"x" * 4097,
        ):
            self.members["/.disk/info"] = info
            with self.subTest(info=info[:30]), self.assertRaises(iso_chain.ValidationError):
                self.prepare()
            self.assertFalse(self.output.exists())

    def test_existing_output_is_refused_before_copy(self):
        self.output.mkdir()
        with self.assertRaisesRegex(iso_chain.ValidationError, "already exists"):
            self.prepare()
        self.assertEqual(self.commands, [])

    def test_parser_exposes_complete_command_contract(self):
        args = iso_chain.parser().parse_args(
            [
                "prepare-ubuntu-source",
                "--iso",
                str(self.iso),
                "--iso-sha256",
                self.digest,
                "--release-path",
                "/ubuntu/releases/26.04.1/release",
                "--minimum-memory-mib",
                "4096",
                "--output",
                str(self.output),
            ]
        )
        self.assertEqual(args.command, "prepare-ubuntu-source")
        self.assertEqual(args.iso, self.iso)
        self.assertEqual(args.release_path, "/ubuntu/releases/26.04.1/release")
        self.assertEqual(args.minimum_memory_mib, 4096)
        self.assertEqual(args.output, self.output)


class SourceServerTests(unittest.TestCase):
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
        server = iso_chain._source_server(self.tree, "127.0.0.1", 0, self.log)
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
            iso_chain._source_server(self.tree, "127.0.0.1", 0, self.log)
        self.assertEqual(self.log.read_text(), "retain\n")

    def test_parser_exposes_server_contract(self):
        args = iso_chain.parser().parse_args(
            [
                "serve-source",
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
        self.assertEqual(args.command, "serve-source")
        self.assertEqual(args.port, 8000)


class ExternalSourceTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.tree = self.root / "tree"
        for path, size in (
            ("repository/ppc/ppc64/vmlinuz", 6),
            ("repository/ppc/ppc64/initrd.img", 9),
            ("repository/.treeinfo", 10),
            ("repository/repodata/repomd.xml", 11),
        ):
            target = self.tree / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(bytes([size]) * size)
        self.log = self.root / "access.jsonl"
        self.server = iso_chain._source_server(self.tree, "127.0.0.1", 0, self.log)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.thread.join, 5)
        self.addCleanup(self.server.shutdown)

    def manifest(self):
        return iso_chain.load_manifest_bytes(
            json.dumps(
                manifest_data(
                    source=f"http://127.0.0.1:{self.server.server_address[1]}",
                    profiles={
                        "fedora": {
                            **manifest_data()["profiles"]["fedora"],
                            "kernel": {
                                "path": "/repository/ppc/ppc64/vmlinuz",
                                "size": 6,
                                "sha256": hashlib.sha256(bytes([6]) * 6).hexdigest(),
                            },
                            "initramfs": {
                                "path": "/repository/ppc/ppc64/initrd.img",
                                "size": 9,
                                "sha256": hashlib.sha256(bytes([9]) * 9).hexdigest(),
                            },
                            "repository": {
                                "path": "/repository",
                                "treeinfo": {
                                    "size": 10,
                                    "sha256": hashlib.sha256(bytes([10]) * 10).hexdigest(),
                                },
                                "repomd": {
                                    "size": 11,
                                    "sha256": hashlib.sha256(bytes([11]) * 11).hexdigest(),
                                },
                            },
                            "kickstart": {
                                "path": "/profiles/fedora-44/ks.cfg",
                                "size": 12,
                                "sha256": hashlib.sha256(bytes([12]) * 12).hexdigest(),
                            },
                        }
                    },
                )
            ).encode()
        )[0]

    def test_validates_declared_artifacts(self):
        result = iso_chain.validate_external_source(self.manifest(), "fedora", 5)
        self.assertEqual(
            [item["path"] for item in result],
            [
                "/repository/ppc/ppc64/vmlinuz",
                "/repository/ppc/ppc64/initrd.img",
                "/repository/.treeinfo",
                "/repository/repodata/repomd.xml",
            ],
        )

    def test_validates_ubuntu_artifacts(self):
        for path, size in (
            ("ubuntu/netboot/ppc64el/linux", 6),
            ("ubuntu/netboot/ppc64el/initrd", 9),
            ("ubuntu/ubuntu-26.04.1-live-server-ppc64el.iso", 13),
        ):
            target = self.tree / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(bytes([size]) * size)
        profile = ubuntu_profile()
        for name, size in (("kernel", 6), ("initramfs", 9), ("live_iso", 13)):
            profile[name]["sha256"] = hashlib.sha256(bytes([size]) * size).hexdigest()
        manifest = iso_chain.load_manifest_bytes(
            json.dumps(
                ubuntu_manifest_data(
                    source=f"http://127.0.0.1:{self.server.server_address[1]}",
                    profiles={"ubuntu": profile},
                )
            ).encode()
        )[0]
        result = iso_chain.validate_external_source(manifest, "ubuntu", 5)
        self.assertEqual(
            [item["path"] for item in result],
            [
                "/ubuntu/netboot/ppc64el/linux",
                "/ubuntu/netboot/ppc64el/initrd",
                "/ubuntu/ubuntu-26.04.1-live-server-ppc64el.iso",
            ],
        )

    def test_rejects_digest_mismatch(self):
        manifest = self.manifest()
        with self.assertRaisesRegex(iso_chain.ValidationError, "does not match"):
            iso_chain.validate_external_source(
                dataclasses.replace(
                    manifest,
                    profiles=(
                        (
                            "fedora",
                            dataclasses.replace(
                                manifest.profile("fedora"),
                                repository=dataclasses.replace(
                                    manifest.profile("fedora").repository,
                                    treeinfo=dataclasses.replace(
                                        manifest.profile("fedora").repository.treeinfo,
                                        sha256="0" * 64,
                                    ),
                                ),
                            ),
                        ),
                    ),
                ),
                "fedora",
                5,
            )

    def test_rejects_size_mismatch(self):
        manifest = self.manifest()
        profile = manifest.profile("fedora")
        with self.assertRaisesRegex(iso_chain.ValidationError, "does not match"):
            iso_chain.validate_external_source(
                dataclasses.replace(
                    manifest,
                    profiles=(
                        (
                            "fedora",
                            dataclasses.replace(
                                profile,
                                repository=dataclasses.replace(
                                    profile.repository,
                                    treeinfo=dataclasses.replace(
                                        profile.repository.treeinfo, size=11
                                    ),
                                ),
                            ),
                        ),
                    ),
                ),
                "fedora",
                5,
            )

    def test_parser_exposes_external_contract(self):
        args = iso_chain.parser().parse_args(
            ["validate-external-source", "--config", "manifest.json", "--profile", "fedora"]
        )
        self.assertEqual(args.command, "validate-external-source")
        self.assertEqual(args.timeout_seconds, 30)


class ExternalMirrorOptInTests(unittest.TestCase):
    @unittest.skipUnless(
        os.environ.get("ISO_CHAIN_EXTERNAL_MIRROR")
        and os.environ.get("ISO_CHAIN_EXTERNAL_MANIFEST"),
        "set ISO_CHAIN_EXTERNAL_MIRROR and ISO_CHAIN_EXTERNAL_MANIFEST to run",
    )
    def test_explicit_mirror_has_no_fallback(self):
        manifest, _, _ = iso_chain.load_manifest(Path(os.environ["ISO_CHAIN_EXTERNAL_MANIFEST"]))
        mirror = iso_chain._validate_source(os.environ["ISO_CHAIN_EXTERNAL_MIRROR"])
        manifest = dataclasses.replace(manifest, source=mirror)
        result = iso_chain.validate_external_source(manifest, manifest.selected_profile, 30)
        self.assertEqual(len(result), 2)


class ContainerPrepareTests(unittest.TestCase):
    def setUp(self):
        self.output = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()

    def args(self, **changes):
        values = {
            "output_dir": self.output,
            "engine": None,
            "image": iso_chain.CONTAINER_INITRAMFS_IMAGE,
        }
        values.update(changes)
        return SimpleNamespace(**values)

    def test_command_runs_ppc64le_with_read_only_repository_and_writable_output(self):
        repository = iso_chain.REPOSITORY_ROOT
        command = iso_chain.container_prepare_initramfs_command(self.args(), "docker")
        self.assertEqual(
            command,
            [
                "docker",
                "run",
                "--rm",
                "--platform",
                "linux/ppc64le",
                "--mount",
                f"type=bind,source={repository},target={repository},readonly",
                "--mount",
                f"type=bind,source={self.output},target={self.output}",
                iso_chain.CONTAINER_INITRAMFS_IMAGE,
                "/bin/sh",
                "-euc",
                iso_chain.CONTAINER_INITRAMFS_SCRIPT,
                "iso-chain",
                str(repository),
                str(self.output),
            ],
        )

    def test_refuses_outputs_it_would_replace_or_cannot_mount(self):
        for name in ("vmlinuz", "initramfs.img"):
            target = self.output / name
            target.write_bytes(b"existing")
            with (
                self.subTest(name=name),
                self.assertRaisesRegex(
                    iso_chain.ValidationError, f"output already exists: {target}"
                ),
            ):
                iso_chain.container_prepare_initramfs_command(self.args(), "docker")
            target.unlink()
        for output_dir, message in (
            (iso_chain.REPOSITORY_ROOT, "must not be the repository root"),
            (self.output / "missing", "output directory: unavailable"),
        ):
            with (
                self.subTest(output_dir=output_dir),
                self.assertRaisesRegex(iso_chain.ValidationError, message),
            ):
                iso_chain.container_prepare_initramfs_command(
                    self.args(output_dir=output_dir), "docker"
                )

    def test_reports_an_unavailable_image_with_its_build_command(self):
        with (
            mock.patch("scripts.iso_chain.shutil.which", return_value="/usr/bin/docker"),
            mock.patch("scripts.iso_chain.subprocess.run") as run,
            mock.patch("scripts.iso_chain.os.execvp") as execute,
            self.assertRaisesRegex(
                iso_chain.ValidationError,
                "--platform linux/ppc64le --file Containerfile.initramfs",
            ),
        ):
            run.return_value = subprocess.CompletedProcess([], 1, b"", b"No such image\n")
            iso_chain.container_prepare_initramfs(self.args())
        execute.assert_not_called()

    def test_executes_the_detected_engine_with_the_composed_argv(self):
        with (
            mock.patch("scripts.iso_chain.shutil.which", return_value="/usr/bin/docker"),
            mock.patch("scripts.iso_chain.subprocess.run") as run,
            mock.patch("scripts.iso_chain.os.execvp") as execute,
        ):
            run.return_value = subprocess.CompletedProcess([], 0, b"", b"")
            expected = iso_chain.container_prepare_initramfs_command(self.args(), "/usr/bin/docker")
            iso_chain.container_prepare_initramfs(self.args())
        run.assert_called_once_with(
            ["/usr/bin/docker", "image", "inspect", iso_chain.CONTAINER_INITRAMFS_IMAGE],
            check=False,
            capture_output=True,
        )
        self.assertEqual(execute.call_args.args, ("/usr/bin/docker", expected))

    def test_parser_exposes_the_command(self):
        args = iso_chain.parser().parse_args(
            ["container-prepare-initramfs", "--output-dir", str(self.output)]
        )
        self.assertEqual(args.command, "container-prepare-initramfs")
        self.assertEqual(args.output_dir, self.output)
        self.assertEqual(args.image, iso_chain.CONTAINER_INITRAMFS_IMAGE)


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
            self.assertIn(
                "virtio_net virtio_pci virtio_blk virtio_scsi ibmveth ibmvscsi ibmvfc nvme sr_mod "
                "isofs",
                command,
            )
            for target in (
                "/usr/libexec/iso-chain-launch.sh",
                "/etc/systemd/system/iso-chain-launch.service",
                "/etc/systemd/system/iso-chain.target",
            ):
                self.assertIn(target, command)
            installed = command[command.index("--install") + 1]
            for tool in ("sha256sum", "kexec", "mktemp", "stat", "sync", "/usr/bin/dd"):
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
