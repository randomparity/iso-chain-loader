# ISO-Carried Installer Artifacts — Implementation Plan

**Goal:** the launcher boots Fedora from kernel and prepared-initramfs bytes carried on its own ISO,
and fetches only pinned `.treeinfo`/`repomd.xml` plus repository traffic from a public HTTPS
mirror.

**Architecture:** Manifest v4 turns kernel, initramfs, and Kickstart paths into ISO media paths.
`build` stages them after checking their digests. The dracut launcher mounts the one optical
device whose `/iso-chain/config.json` digest matches the command line, then copies and verifies
the artifacts and kexecs as before. Preparation reads a local copy of one mirror tree, checked
against its `.treeinfo`. A `linux/ppc64le` container builds the launcher initramfs on any host.

**Tech stack:** Python 3.14 stdlib (`scripts/iso_chain.py`), POSIX sh (`assets/dracut/`), Bash
test harness, `unittest`, podman or docker.

Spec: `docs/workflow/specs/2026-10-01-iso-carried-artifacts-design.md`. ADR 0011.

Expected implementation size: 550–800 changed lines (L). Derived from the file map below:
`iso_chain.py` ~220, launcher ~90, Python tests ~260, shell tests ~120, container/Justfile ~25,
README/AGENTS ~80.

## Global Constraints

- Python 3.14, stdlib only in `scripts/`. Every function annotated. `ValidationError` for operator
  errors.
- Line length 100 (ruff, rumdl). Run `uv run --no-sync` only where the repo uses it. This repo
  uses `.venv/bin/...` and `just`.
- No DHCP, no IPv6, no redirects, no alternate source or device, no silent fallback.
- The launcher's guest locale is C, and the shell harness pins `LC_ALL=C`.
- `.secrets.baseline` records Justfile line numbers. Append new Justfile recipes at the **end** of
  the file, and run `just check-secrets`.
- The base image digest is the one already in `Containerfile`:
  `fedora:44@sha256:43b29f65a41eb9c35e1cd5323e3bdf3b655c2357a9f4f1ff2f9c2798e5045d80`, a
  multi-arch index (it resolved for `--platform linux/ppc64le`; verify in Task 6, step 1).
- Guardrails: `just check-tests` (about 5 s) after every task, and `just check` before every
  commit. Commit after each task, using conventional commits.

## File map

| File | Today owns | Change |
|---|---|---|
| `scripts/iso_chain.py` | manifest, build, prepare, evidence, CLI | v4, staging, tree prep, container prep, evidence |
| `assets/dracut/iso-chain-launch.sh` | guest launcher | media discovery and copy, no Kickstart download |
| `tests/test_iso_chain.py` | Python behaviour | v4, staging, tree prep, container prep, evidence |
| `tests/test_iso_chain_launch.sh` | launcher black box | fake mount/umount/udevadm, media fixtures |
| `Containerfile.initramfs` (new) | — | ppc64le dracut image |
| `Justfile` | recipes | append `build-initramfs-image` |
| `README.md`, `AGENTS.md` | operator docs | v4 workflow |

No compatibility path is retained. Manifest v3 is rejected outright (pre-release, ADR 0006
precedent), and `--iso`/`--iso-sha256` are removed.

---

## Task 1 — Manifest v4

**Files:** `scripts/iso_chain.py`, `tests/test_iso_chain.py`.

**Interfaces.** It produces `MEDIA_PATH: re.Pattern`, `_media_artifact(value: object, field: str,
maximum: int) -> Artifact`, and `_external_artifacts(profile) -> tuple[Artifact, Artifact]`
(treeinfo, repomd). `Manifest.version == 4`, and `_kernel_arguments` emits no
`profile_kickstart_*`. Later tasks rely on all of these.

**Verification.**

- v4 acceptance and v3 rejection. Mode: focused-test. `ManifestV4Tests.test_rejects_version_3`.
  Red: v3 is accepted. Green: `.venv/bin/python -m unittest tests.test_iso_chain.ManifestV4Tests`.
- Media-path rule and cross-profile conflict. Mode: focused-test.
  `test_rejects_non_media_paths` and `test_rejects_conflicting_shared_media_path`. Red: accepted.
  Green: same command.
- Command line without Kickstart. Mode: focused-test. `test_kernel_arguments_omit_kickstart`.
  Red: the arguments are present.
- External artifacts narrowed. Mode: focused-test. Update
  `ExternalSourceTests.test_success`-style cases to expect two results. Red: five results.

Steps:

1. In `tests/test_iso_chain.py`, set `manifest_data()`'s `"version": 4`, and rename
   `ManifestV3Tests` to `ManifestV4Tests`. Add:

   ```python
   def test_rejects_version_3(self):
       encoded = json.dumps(manifest_data(version=3)).encode()
       with self.assertRaisesRegex(iso_chain.ValidationError, "version 3 is no longer supported"):
           iso_chain.load_manifest_bytes(encoded)


   def test_rejects_non_media_paths(self):
       for path in ("/vmlinuz", "/profiles/vmlinuz", "/profiles/a/b/vmlinuz", "/boot/vmlinuz"):
           data = manifest_data()
           data["profiles"]["fedora"] = dict(
               data["profiles"]["fedora"], kernel={"path": path, "size": 6, "sha256": "1" * 64}
           )
           with (
               self.subTest(path=path),
               self.assertRaisesRegex(iso_chain.ValidationError, "media path"),
           ):
               iso_chain.load_manifest_bytes(json.dumps(data).encode())


   def test_rejects_repeated_media_path_within_profile(self):
       data = manifest_data()
       profile = dict(data["profiles"]["fedora"])
       profile["initramfs"] = dict(profile["initramfs"], path=profile["kernel"]["path"])
       data["profiles"]["fedora"] = profile
       with self.assertRaisesRegex(iso_chain.ValidationError, "distinct media paths"):
           iso_chain.load_manifest_bytes(json.dumps(data).encode())


   def test_rejects_conflicting_shared_media_path(self):
       data = manifest_data()
       rescue = dict(data["profiles"]["rescue"])
       rescue["kernel"] = dict(rescue["kernel"], sha256="9" * 64)
       data["profiles"]["rescue"] = rescue
       with self.assertRaisesRegex(iso_chain.ValidationError, "reuses a media path"):
           iso_chain.load_manifest_bytes(json.dumps(data).encode())


   def test_kernel_arguments_omit_kickstart(self):
       manifest, _, digest = iso_chain.load_manifest_bytes(json.dumps(manifest_data()).encode())
       arguments = iso_chain._kernel_arguments(manifest, digest, "fedora")
       self.assertFalse([a for a in arguments if a.startswith("iso_chain.profile_kickstart")])
   ```

2. Run `.venv/bin/python -m unittest tests.test_iso_chain.ManifestV4Tests`. Expect FAIL, with
   `must be exactly 3` errors and the assertions not raised.

3. In `scripts/iso_chain.py`, add a constant after `URI_PATH`:

   ```python
   MEDIA_PATH = re.compile(r"^/profiles/[A-Za-z0-9._~+^-]+/[A-Za-z0-9._~+^-]+$")
   ```

   Add after `_artifact`:

   ```python
   def _media_artifact(value: object, field: str, maximum: int) -> Artifact:
       artifact = _artifact(value, field, maximum)
       if MEDIA_PATH.fullmatch(artifact.path) is None or any(
           part in (".", "..") for part in artifact.path.split("/")
       ):
           _manifest_error(f"{field}.path", "must be a media path /profiles/<directory>/<file>")
       return artifact
   ```

   In `_installer_profile`, build `kernel`, `initramfs`, and `kickstart` with `_media_artifact`
   (same maxima), then before `return`:

   ```python
   if len({kernel.path, initramfs.path, kickstart.path}) != 3:
       _manifest_error(field, "must name distinct media paths")
   ```

   In `load_manifest_bytes`, replace the version check:

   ```python
   version = root["version"]
   if type(version) is int and version == 3:
       _manifest_error(
           "version", "3 is no longer supported; regenerate the profile with prepare-fedora-source"
       )
   if type(version) is not int or version != 4:
       _manifest_error("version", "must be exactly 4")
   ```

   After building `profiles`:

   ```python
   media: dict[str, Artifact] = {}
   for name, profile in profiles:
       for artifact in (profile.kernel, profile.initramfs, profile.kickstart):
           if media.setdefault(artifact.path, artifact) != artifact:
               _manifest_error(
                   f"profiles.{name}", "reuses a media path with a different size or digest"
               )
   ```

   Set `Manifest(version=4, ...)`. In `_kernel_arguments`, delete the three
   `iso_chain.profile_kickstart_*` entries. Change `_external_artifacts` to return
   `(profile.repository.treeinfo, profile.repository.repomd)`.

4. Run `just check-tests`. Expect the new tests to pass. Every other failure must trace to
   `version` 3 literals, Kickstart arguments, or five-artifact external validation. Fix those
   tests to the v4 contract and nothing else: `ExternalSourceTests` now serves and expects only
   `.treeinfo` and `repomd.xml`, and the launcher-log fixtures rebuild their command line from
   `_kernel_arguments`. Expect `OK`.

5. `just check`, then commit: `feat: replace manifest v3 with ISO media paths in v4`.

---

## Task 2 — Build stages profile artifacts

**Files:** `scripts/iso_chain.py` (`build_iso`, `container_build_command`, `parser`,
`_copy_with_sha256`), `tests/test_iso_chain.py` (`BuildTests`, `ContainerBuildTests`).

**Interfaces.** Consumes Task 1's `Manifest` with media paths. Produces
`_stage_profile_artifacts(manifest: Manifest, profiles: Path, stage: Path) -> None`, and a required
`--profiles` on `build` and `container-build`.

**Verification.**

- Staging. Mode: focused-test. `BuildTests.test_stages_profile_artifacts`: the mkrescue mock sees
  `stage/profiles/fedora-44/{vmlinuz,initramfs.img,ks.cfg}` with the manifest bytes. Red: absent.
- Mismatch refused before mkrescue. Mode: focused-test.
  `BuildTests.test_rejects_profile_digest_mismatch` with `run.assert_not_called()`. Red: mkrescue
  runs.
- Container mount. Mode: focused-test.
  `ContainerBuildTests.test_mounts_profiles_read_only`. Red: no mount.

Steps:

1. Add a fixture helper in `tests/test_iso_chain.py`:

   ```python
   def write_profile_tree(root: Path) -> dict:
       files = {"vmlinuz": b"kernel", "initramfs.img": b"initramfs", "ks.cfg": b"ks\n"}
       directory = root / "profiles/fedora-44"
       directory.mkdir(parents=True)
       entries = {}
       for name, content in files.items():
           (directory / name).write_bytes(content)
           entries[name] = {
               "path": f"/profiles/fedora-44/{name}",
               "size": len(content),
               "sha256": hashlib.sha256(content).hexdigest(),
           }
       data = manifest_data()
       for profile in data["profiles"].values():
           profile["kernel"] = entries["vmlinuz"]
           profile["initramfs"] = entries["initramfs.img"]
           profile["kickstart"] = entries["ks.cfg"]
       return data
   ```

   Write the two `BuildTests` cases. They call `build_iso` with `profiles=root` and patch
   `subprocess.run`. A side effect copies `stage/profiles` contents into a dict, then writes the
   output ISO, following the existing `BuildTests` pattern. The mismatch case writes `b"kernex"`
   (same size) to `vmlinuz` and asserts `ValidationError("profile kernel does not match the
   manifest")` and `run.assert_not_called()`.

2. Run `.venv/bin/python -m unittest tests.test_iso_chain.BuildTests`. Expect FAIL
   (`AttributeError`: no `profiles` argument).

3. Implement:

   ```python
   def _stage_profile_artifacts(manifest: Manifest, profiles: Path, stage: Path) -> None:
       root = _path(profiles, "profile artifact directory", "directory")
       for _, profile in manifest.profiles:
           for label, artifact in (
               ("kernel", profile.kernel),
               ("initramfs", profile.initramfs),
               ("Kickstart", profile.kickstart),
           ):
               target = stage / artifact.path.lstrip("/")
               if target.exists():
                   continue
               source = _regular_file(root / artifact.path.lstrip("/"), f"profile {label}")
               target.parent.mkdir(parents=True, exist_ok=True)
               if _copy_with_sha256(source, target, artifact.size) != artifact.sha256:
                   raise ValidationError(f"profile {label} does not match the manifest")
   ```

   `target.exists()` skips a path that an earlier profile has already staged. Task 1 guarantees
   identical bytes for a shared path. Call it in `build_iso` after writing `grub.cfg` and before
   `grub2-mkrescue`, with `Path(args.profiles)`. In `_copy_with_sha256`, change the label
   `"Fedora ISO: must be a regular file"` to `"source: must be a regular file"`. Confirm that
   `_copy_with_sha256` raises on a size mismatch; if it does not, add
   `if copied != expected_size: raise ValidationError("source: size does not match")`. Add
   `"profiles"` to the `build` and `container-build` required arguments in `parser()`. In
   `container_build_command`, add
   `profiles = _path(Path(args.profiles), "profile artifact directory", "directory")`, append
   `(profiles, False)` to `sources`, and pass `"--profiles", str(profiles)` after `--initramfs`.

4. Run `just check-tests`. Expect `OK`. Update existing `BuildTests` and `ContainerBuildTests`
   argument namespaces with a `profiles` directory built by `write_profile_tree`.

5. `just check`, then commit: `feat: stage profile artifacts on the launcher ISO`.

---

## Task 3 — Launcher reads artifacts from the media

**Files:** `assets/dracut/iso-chain-launch.sh`, `scripts/iso_chain.py` (`DRACUT_DRIVERS`,
`DRACUT_TOOLS`), `tests/test_iso_chain_launch.sh`, `tests/test_iso_chain.py`
(`PrepareTests` driver assertion).

**Interfaces.** Console markers `media: passed` and `media: failed` (stage), with reasons
`kernel-media`, `kernel-size`, `kernel-digest`, `initramfs-*`, `media-unmount`, and
`treeinfo-http`/`-size`/`-digest`. Task 5 consumes `media: passed`.

**Verification.**

- One matching device leads to kexec with exactly two curl calls and none to `ks.cfg`. Mode:
  focused-test, harness main path. Red: five calls.
- Zero devices, two matching devices, or a mount failure all give `media: failed`. Mode:
  focused-test, faults `media-none`, `media-duplicate`, `mount`. Red: no marker.
- Media kernel with a wrong size or wrong digest. Mode: focused-test, faults `media-size` and
  `media-digest`, giving `kernel-size: failed` and `kernel-digest: failed` with no curl and no
  kexec. Red: the marker is missing.
- Dracut driver and tool lists. Mode: focused-test. `PrepareTests` asserts
  `"virtio_net virtio_pci virtio_blk virtio_scsi ibmveth ibmvscsi sr_mod isofs"`. Red: the old
  string.

Steps:

1. Harness (`tests/test_iso_chain_launch.sh`):
   - Add fake commands to `write_fake_commands`, and `chmod +x` them:

     ```bash
     cat >"$workspace/bin/udevadm" <<'EOF'
     #!/usr/bin/env bash
     printf 'udevadm %s\n' "$*" >> "$ISO_CHAIN_CALLS"
     EOF
     cat >"$workspace/bin/mount" <<'EOF'
     #!/usr/bin/env bash
     printf 'mount %s\n' "$*" >> "$ISO_CHAIN_CALLS"
     test "${ISO_CHAIN_FAULT:-}" != mount || exit 32
     [ "$1 $2 $3" = "-t iso9660 -o" ] && [ "$4" = ro,nodev,nosuid,noexec ] || exit 32
     cp -R "$5/." "$6/"
     EOF
     cat >"$workspace/bin/umount" <<'EOF'
     #!/usr/bin/env bash
     printf 'umount %s\n' "$*" >> "$ISO_CHAIN_CALLS"
     find "$1" -mindepth 1 -delete
     EOF
     ```

   - Remove the curl cases for `*/vmlinuz`, `*/initramfs.img`, and `*/ks.cfg`, plus the three
     `kickstart-*` fault lines.
   - Compute `config_digest=$(printf 'config' | "$workspace/bin/sha256sum" | cut -d' ' -f1)`
     after `write_fake_commands`. In `command_line`, replace the literal `aaaa…` digest with
     `$config_digest` and delete the two `profile_kickstart_*` printf lines.
   - In `run_launcher`, build media fixtures after `mkdir -p "$net" "$run_dir"`:

     ```bash
     local media="$workspace/media"
     rm -rf "$media"
     make_device() {
         mkdir -p "$1/iso-chain" "$1/profiles/fedora-44"
         printf 'config' >"$1/iso-chain/config.json"
         printf 'kernel' >"$1/profiles/fedora-44/vmlinuz"
         printf 'initramfs' >"$1/profiles/fedora-44/initramfs.img"
     }
     case "$fault" in
     media-none) mkdir -p "$media" ;;
     media-duplicate) make_device "$media/sr0"; make_device "$media/sr1" ;;
     *) make_device "$media/sr0" ;;
     esac
     [ "$fault" != media-size ] || printf 'x' >"$media/sr0/profiles/fedora-44/vmlinuz"
     [ "$fault" != media-digest ] || printf 'tamper' >"$media/sr0/profiles/fedora-44/vmlinuz"
     ```

     Export `ISO_CHAIN_MEDIA_DEVICES="$media/sr*"` in the launcher invocation.
   - Update the main-path assertions:
     - `grep -qx 'media: passed'` appears before `artifacts: passed`;
     - the curl count is `2`;
     - `grep -Fq 'mount -t iso9660 -o ro,nodev,nosuid,noexec'`;
     - no line in calls contains `ks.cfg`;
     - the HTTPS cases look for `https://192.0.2.2/repository/.treeinfo` and
       `https://192.0.2.2/fedora/44/repository/.treeinfo`.
   - Delete the Kickstart argument loop and the duplicate-Kickstart case.
   - Fault loop: change the list to
     `ip curl size digest media-none media-duplicate mount media-size media-digest memory
     availability space load execute unload`, with these reasons:

     | Fault | Reason |
     |---|---|
     | `curl` | `treeinfo-http: failed` |
     | `size` | `treeinfo-size: failed` |
     | `digest` | `treeinfo-digest: failed` |
     | `media-none`, `media-duplicate`, `mount` | `media: failed` |
     | `media-size` | `kernel-size: failed` |
     | `media-digest` | `kernel-digest: failed` |

     The `digest` case asserts the curl count is `1` and that kexec was not called. The media
     faults assert that no call line starts with `curl` or `kexec`.

2. Run `bash tests/test_iso_chain_launch.sh`. Expect `test failure: missing media marker` or
   similar.

3. Launcher (`assets/dracut/iso-chain-launch.sh`):
   - Add globals after `run_dir`:

     ```sh
     media_devices=${ISO_CHAIN_MEDIA_DEVICES:-/dev/sr*}
     media_dir=
     media_mounted=
     ```

   - Make `cleanup` unmount first:

     ```sh
     cleanup() {
         [ -z "$media_mounted" ] || umount "$media_dir" || true
         [ -z "$workspace" ] || rm -rf "$workspace"
         [ -z "$resolver_temporary" ] || rm -f "$resolver_temporary"
     }
     ```

     The `|| true` here is justified. The trap runs on an exit path that has already printed its
     failure marker, and a failed unmount must not mask that status.
   - Delete the `kickstart_*` initialisers, the three `case` arms, and the two validation lines.
   - Replace `download_artifact` with a shared verifier plus two sources:

     ```sh
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

     find_media() {
         udevadm settle --timeout=60 || return 1
         media_dir="$workspace/media"
         mkdir "$media_dir" || return 1
         matches=0
         media_device=
         for device in $media_devices; do
             [ -e "$device" ] || continue
             mount -t iso9660 -o ro,nodev,nosuid,noexec "$device" "$media_dir" || continue
             found=$(sha256sum "$media_dir/iso-chain/config.json" 2>/dev/null) || found=
             umount "$media_dir" || return 1
             [ "${found%% *}" = "$config_digest" ] || continue
             matches=$((matches + 1))
             media_device=$device
         done
         [ "$matches" -eq 1 ] || return 1
         mount -t iso9660 -o ro,nodev,nosuid,noexec "$media_device" "$media_dir" || return 1
         media_mounted=1
     }
     ```

     `|| found=` is not a fallback. A device with no config, or an unreadable one, is simply not
     a match. `|| continue` on mount skips non-iso9660 devices during discovery, and only an
     exactly-one match proceeds.
   - Replace the body of `launch_fedora` between `workspace=$(mktemp …)` and
     `printf 'artifacts: passed'`:

     ```sh
     find_media || { stage_failure media; return 1; }
     printf '%s\n' 'media: passed'
     copy_media_artifact kernel "$kernel_path" "$kernel_size" "$kernel_digest" || return 1
     copy_media_artifact initramfs \
         "$initramfs_path" "$initramfs_size" "$initramfs_digest" || return 1
     umount "$media_dir" || { stage_failure media-unmount; return 1; }
     media_mounted=
     download_artifact treeinfo \
         "$repository_path/.treeinfo" "$treeinfo_size" "$treeinfo_digest" || return 1
     download_artifact repomd \
         "$repository_path/repodata/repomd.xml" "$repomd_size" "$repomd_digest" || return 1
     ```

   - In `check_capacity`:
     `download_bytes=$((executable_bytes + treeinfo_size + repomd_size))`.
   - The kexec calls reference `$workspace/kernel` and `$workspace/initramfs` and stay unchanged.

4. `scripts/iso_chain.py`:
   - `DRACUT_DRIVERS = "virtio_net virtio_pci virtio_blk virtio_scsi ibmveth ibmvscsi sr_mod isofs"`.
   - Append `/usr/bin/mount /usr/bin/umount /usr/bin/cat` to `DRACUT_TOOLS`.
   - Update the `PrepareTests` assertion at the line that asserts the driver string.

5. Run `just check-tests`. Expect `launcher shell tests: passed` and `OK`.

6. `just check`, then commit: `feat: read installer artifacts from the launcher media`.

---

## Task 4 — Prepare from a local mirror tree

**Files:** `scripts/iso_chain.py` (`_treeinfo_paths` replaced by `_treeinfo_images`,
`prepare_fedora_source`, `parser`, remove `FEDORA_ISO_SIZE`), `tests/test_iso_chain.py`
(`FedoraSourceTests`).

**Interfaces.** It produces the CLI `prepare-fedora-source --tree DIR --repository-path PATH
--kickstart FILE --minimum-memory-mib N --output OUT`. Its output is
`OUT/profiles/fedora-44/{vmlinuz,initramfs.img,ks.cfg}` and `OUT/profile.json`, matching the v4
profile schema, with `repository.path = PATH`.

**Verification.**

- An Everything tree with correct checksums publishes the profile. Mode: focused-test.
  `test_prepares_everything_tree`: the `profile.json` loads inside a v4 manifest, and
  `repository.path` equals the argument. Red: `--tree` is unknown.
- Variant outside {Everything, Server}. Mode: focused-test. `test_rejects_variant`. Red: accepted.
- Missing checksum entry. Mode: focused-test. `test_rejects_missing_checksum`.
- Checksum mismatch. Mode: focused-test. `test_rejects_checksum_mismatch`, with
  `run.assert_not_called()` for the cpio/xz subprocess.
- No network use. Mode: task-test-not-applicable. The function contains no `urllib` call, and
  the absence of a call cannot fail meaningfully in a unit test. Review covers it.

Steps:

1. Fixture helper:

   ```python
   def write_mirror_tree(root: Path, variant="Everything", break_checksum=None, omit=None):
       files = {
           "ppc/ppc64/vmlinuz": b"kernel",
           "ppc/ppc64/initrd.img": b"\xfd7zXZ\x00initrd",
           "images/install.img": b"runtime",
       }
       lines = ["[checksums]"]
       for path, content in files.items():
           (root / path).parent.mkdir(parents=True, exist_ok=True)
           (root / path).write_bytes(content)
           digest = hashlib.sha256(content).hexdigest()
           if path == break_checksum:
               digest = "0" * 64
           if path != omit:
               lines.append(f"{path} = sha256:{digest}")
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
       (root / ".treeinfo").write_text("\n".join(lines) + "\n")
       (root / "repodata").mkdir()
       (root / "repodata/repomd.xml").write_bytes(b"<repomd/>")
   ```

   Replace the `--iso` tests in `FedoraSourceTests` with the four cases above. Patch
   `iso_chain._append_stage2_bundle` in the success case with a side effect that writes
   `b"prepared"` to its `output` argument. The bundle's own behaviour keeps its existing tests.

2. Run `.venv/bin/python -m unittest tests.test_iso_chain.FedoraSourceTests`. Expect FAIL.

3. Implement:

   ```python
   FEDORA_VARIANTS = ("Everything", "Server")


   def _treeinfo_images(tree: Path) -> tuple[Path, Path, Path]:
       encoded = _bounded_file(tree / ".treeinfo", "Fedora treeinfo", MAX_TREEINFO_BYTES)
       parser = configparser.ConfigParser(interpolation=None)
       parser.optionxform = str
       try:
           parser.read_string(encoded.decode("utf-8"))
           identity = tuple(parser["general"][name] for name in ("family", "version", "arch"))
           variant = parser["general"]["variant"]
           values = (
               parser["images-ppc64le"]["kernel"],
               parser["images-ppc64le"]["initrd"],
               parser["stage2"]["mainimage"],
           )
           checksums = [parser["checksums"][value] for value in values]
       except (UnicodeDecodeError, configparser.Error, KeyError) as error:
           raise ValidationError("Fedora treeinfo: missing or malformed metadata") from error
       if identity != ("Fedora", "44", "ppc64le") or variant not in FEDORA_VARIANTS:
           raise ValidationError("Fedora treeinfo: expected Fedora 44 ppc64le Everything or Server")
       paths = []
       for value, checksum in zip(values, checksums, strict=True):
           if URI_PATH.fullmatch("/" + value) is None or any(
               part in ("", ".", "..") for part in value.split("/")
           ):
               raise ValidationError("Fedora treeinfo: contains a noncanonical path")
           kind, _, digest = checksum.partition(":")
           if kind != "sha256" or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
               raise ValidationError("Fedora treeinfo: checksum entries must be SHA-256")
           path = _regular_file(tree / value, "Fedora treeinfo artifact")
           if _file_sha256(path) != digest:
               raise ValidationError("Fedora treeinfo artifact does not match its checksum")
           paths.append(path)
       return paths[0], paths[1], paths[2]
   ```

   Rewrite `prepare_fedora_source`:
   - drop the ISO copy and the `xorriso` extraction;
   - `tree = _path(Path(args.tree).absolute(), "Fedora tree", "directory")`;
   - `repository_path = _url_path(args.repository_path, "repository path")`;
   - `kernel, initramfs, runtime = _treeinfo_images(tree)`;
   - `repomd = _regular_file(tree / "repodata/repomd.xml", "Fedora repository metadata")`;
   - keep the `profiles/fedora-44` publication and `_append_stage2_bundle` unchanged;
   - set `"repository": {"path": repository_path, "treeinfo": _artifact_data(tree /
     ".treeinfo", None, 2**20), "repomd": _artifact_data(repomd, None, 2**20)}`;
   - stop creating `tree/"repository"`.

   Delete `_treeinfo_paths` and `FEDORA_ISO_SIZE`. In `parser()`, replace `--iso`/`--iso-sha256`
   with `--tree` (Path) and `--repository-path` (str), both required.

4. Run `just check-tests`. Expect `OK`. Remove tests that only exercised the deleted DVD path.

5. `just check`, then commit: `feat: prepare the Fedora profile from a mirror tree copy`.

---

## Task 5 — Evidence verifiers follow the new request shape

**Files:** `scripts/iso_chain.py` (`_verify_http_requests`, `_verify_install_http_requests`,
`verify_launcher_log`), `tests/test_iso_chain.py` (`FedoraEvidenceTests`,
`FedoraInstallEvidenceTests`, `EvidenceTests`).

**Interfaces.** Consumes Task 3's `media: passed` marker and Task 1's narrowed launcher artifacts.

**Verification.**

- Pre-install HTTP evidence accepts treeinfo, repomd, then repository traffic, and rejects a
  kernel request on the origin. Mode: focused-test.
  `FedoraEvidenceTests.test_rejects_kernel_request_on_origin`. Red: accepted.
- Install HTTP evidence needs no Kickstart request. Mode: focused-test.
  `FedoraInstallEvidenceTests.test_accepts_two_launcher_requests`. Red: `exactly one Kickstart`.
- Launcher log requires `media: passed`. Mode: focused-test.
  `test_rejects_missing_media_marker`. Red: accepted.

Steps:

1. Update the evidence fixtures:
   - access-log records drop the kernel, initramfs, and Kickstart rows;
   - console fixtures insert `media: passed` after the memory line;
   - add the three tests above.
2. Run the three classes. Expect FAIL.
3. Implement:
   - `_verify_http_requests`: `launcher_artifacts` is treeinfo and repomd only. Delete the
     kernel/initramfs exactly-once clause.
   - `_verify_install_http_requests`: the same tuple, and delete the
     `paths.count(profile.kickstart.path)` rule.
   - `verify_launcher_log`: add `"media: failed"` to the failure tuple, and change the
     post-memory marker loop to `("media: passed", "artifacts: passed", "kexec-load: passed",
     "kexec-exec: started")`.
4. Run `just check-tests`. Expect `OK`.
5. `just check`, then commit: `feat: verify launcher evidence for media-carried artifacts`.

---

## Task 6 — ppc64le container for `prepare-initramfs`

**Files:** `Containerfile.initramfs` (new), `scripts/iso_chain.py`, `Justfile` (append),
`tests/test_iso_chain.py` (`ContainerPrepareTests`, new).

**Interfaces.** It produces `CONTAINER_INITRAMFS_IMAGE = "iso-chain-initramfs:44"`,
`container_prepare_initramfs_command(args: argparse.Namespace, engine: str) -> list[str]`,
`container_prepare_initramfs(args) -> None`, and
`_require_container_image(engine: str, image: str, containerfile: str, platform: str | None)`,
which `container_build` now also uses. The CLI is `container-prepare-initramfs --output-dir DIR
[--engine] [--image]`.

**Verification.**

- Command shape. Mode: focused-test. `test_command_runs_ppc64le_with_mounts`:
  - `--platform linux/ppc64le` is present;
  - the repository is mounted read-only and the output read-write;
  - the arguments end with `/bin/sh -euc <script> iso-chain <repo> <out>`.

  Red: no function.
- Refusals. Mode: focused-test. `test_refuses_existing_outputs` covers `vmlinuz` and
  `initramfs.img`. `test_refuses_repository_root`. Both assert no engine call.
- Image actually builds the initramfs. Mode: task-test-not-applicable for CI, because CI builds
  no media (AGENTS.md). It is proved by running Task 6 step 6 locally and recording the output in
  the PR.

Steps:

1. Confirm the base digest is a multi-arch index:

   ```sh
   docker manifest inspect fedora:44@sha256:43b29f65a41eb9c35e1cd5323e3bdf3b655c2357a9f4f1ff2f9c2798e5045d80 \
       | grep -c ppc64le
   ```

   Expect a count ≥ 1. If it is 0, stop: the spec's shared-pin premise is false, so return to
   design.

2. Create `Containerfile.initramfs`:

   ```dockerfile
   # ppc64le image for prepare-initramfs: dracut, one Fedora kernel, and the launcher's tools.
   # Built with --platform linux/ppc64le; non-ppc64le hosts run it under emulation.
   FROM fedora:44@sha256:43b29f65a41eb9c35e1cd5323e3bdf3b655c2357a9f4f1ff2f9c2798e5045d80

   RUN dnf --assumeyes --setopt=install_weak_deps=False install \
           dracut \
           kernel-core \
           kexec-tools \
           iproute \
           curl \
           systemd \
           util-linux-core \
           ca-certificates \
           python3.14 \
       && dnf clean all
   ```

3. Tests in a new `ContainerPrepareTests` class:
   - the command test asserts the exact list built for a temp output dir with
     `REPOSITORY_ROOT` patched to a temp repo;
   - the refusal tests assert `ValidationError` messages
     `output already exists: <path>` and `output directory must not be the repository root`.

   Run them and expect FAIL.

4. Implement in `scripts/iso_chain.py`:

   ```python
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


   def container_prepare_initramfs_command(args: argparse.Namespace, engine: str) -> list[str]:
       repository = _path(REPOSITORY_ROOT, "repository root", "directory")
       output = _path(Path(args.output_dir).absolute(), "output directory", "directory")
       if output == repository:
           raise ValidationError("output directory must not be the repository root")
       for source in (repository, output):
           if source == Path("/") or "," in str(source):
               raise ValidationError("container mount source is not supported")
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
   ```

   Extract the image check from `container_build` into `_require_container_image(engine, image,
   containerfile, platform)`. It reproduces today's message, with `--platform <p>` inserted when
   `platform` is set. Then:

   ```python
   def container_prepare_initramfs(args: argparse.Namespace) -> None:
       engine = _container_engine(args.engine)
       command = container_prepare_initramfs_command(args, engine)
       _require_container_image(engine, args.image, "Containerfile.initramfs", "linux/ppc64le")
       os.execvp(engine, command)
   ```

   Add the subparser (`--output-dir` required Path, `--engine`, `--image` defaulting to
   `CONTAINER_INITRAMFS_IMAGE`) and the dispatch in `main()`.

5. Append to the **end** of `Justfile`:

   ```just
   build-initramfs-image:
       #!/bin/sh
       set -eu
       engine=$(command -v podman || command -v docker) || {
           echo "error: neither podman nor docker is on PATH" >&2
           exit 1
       }
       "$engine" build --platform linux/ppc64le --file Containerfile.initramfs \
           --tag iso-chain-initramfs:44 .
   ```

   Run `just check-justfile` and `just check-secrets`. Expect both green. If `check-justfile`
   reorders recipes, refresh the `.secrets.baseline` line numbers in the same commit.

6. Local proof (not CI). Bound the first run generously, since it is emulated:

   ```sh
   just build-initramfs-image
   mkdir -p "$HOME/iso-build/launcher" && \
     .venv/bin/python scripts/iso_chain.py container-prepare-initramfs \
       --output-dir "$HOME/iso-build/launcher"
   ls -l "$HOME/iso-build/launcher"
   ```

   Expect `vmlinuz` and `initramfs.img`. Then check that the drivers exist for that kernel:

   ```sh
   docker run --rm --platform linux/ppc64le iso-chain-initramfs:44 sh -c \
     'v=$(ls /usr/lib/modules); for m in ibmveth ibmvscsi sr_mod isofs; do \
       modinfo -k "$v" -F filename "$m"; done'
   ```

   Each prints a path or `(builtin)`. If a module is missing, `kernel-modules` is required in
   `Containerfile.initramfs`. Add it, and record the change in the PR.

7. `just check`, then commit: `feat: build the launcher initramfs in a ppc64le container`.

---

## Task 7 — Operator documentation

**Files:** `README.md`, `AGENTS.md`.

**Verification.** Mode: task-test-not-applicable. These are prose pages that no executable
consumer parses. `just check-markdown` covers the form, and step 2 below covers truth.

Steps:

1. `README.md`: replace the worked sequence for prepare, build, and serve with this order:
   1. copy the five mirror files with `curl`, using the URLs from `.treeinfo`;
   2. `prepare-fedora-source --tree … --repository-path /pub/fedora-secondary/releases/44/Everything/ppc64le/os`;
   3. paste `profile.json` into a v4 manifest with
      `"source": "https://dl.fedoraproject.org"`;
   4. `validate-external-source`;
   5. `just build-initramfs-image` and `container-prepare-initramfs`;
   6. `container-build --profiles <prepared>`.

   State that a local QEMU run serves a full tree copy with `serve-fedora-source` and sets
   `source` to it. `AGENTS.md`: manifest v4, the media-path rule, the new subcommand, the drivers,
   and that `prepare-fedora-source` no longer needs `xorriso`.
2. Re-run each documented command that runs on this host, through
   `container-prepare-initramfs` and `container-build`, against the live artifacts from Task 6.
   Fix any step that fails as written.
3. `just check`, then commit: `docs: document the ISO-carried artifact workflow`.

## Deferrals

None. The live POWER9 run is owned by issue #6.
