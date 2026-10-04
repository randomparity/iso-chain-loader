# openSUSE btrfs Installed Disk Implementation Plan

Goal: the launcher menu boots an installed openSUSE Leap 15.6 disk by default. Spec:
`docs/workflow/specs/2026-10-04-opensuse-btrfs-installed-disk-design.md`; ADR 0024.

Architecture: `INSTALLED_DISK_MENU` sets GRUB's `btrfs_relative_path=y` before ADR 0018's
search, so the builder GRUB's patched `btrfs.mod` resolves the four paths inside each btrfs
device's default subvolume. Nothing else in the build or launcher changes.

Tech stack: Python 3.14 standard library, GRUB 2.12 script, `unittest`, QEMU pSeries for the
proof.

Expected implementation size: 90–140 changed lines (M) — about 3 Python, 4 unit-test, 15 README
and AGENTS.md, 1 ADR 0018 banner, and 70–115 experiment-record lines; design artifacts excluded.

## Global Constraints

- Standard library only in `scripts/`; ruff line length 100; annotate every function.
- Markdown is linted by rumdl at line length 100.
- `just check` and `just check-tests` stay green; `.secrets.baseline` covers only `Justfile`, so
  no line-number refresh is needed.
- Private evidence (DVD, profile, disks, console logs) stays under `~/iso-chain-private/` with
  `umask 077` and is never committed; the record cites digests only.
- ADR 0018's body is not edited; only a one-line banner is added to its Status section.

## File map

- `scripts/iso_chain.py` — owns the menu text. Change: prepend the line to `INSTALLED_DISK_MENU`
  and extend its comment. `COMPLETION_MENU` and `_grub_config` are untouched.
- `tests/test_iso_chain.py` — `BuildTests` expectations.
- `docs/adr/0018-boot-installed-disk-and-require-blank-target.md` — Status banner pointing to 0024.
- `README.md`, `AGENTS.md` — describe the btrfs resolution.
- `docs/experiments/2026-10-04-opensuse-btrfs-installed-disk.md` — new QEMU record.

## Task 1: Menu line

Files: modify `scripts/iso_chain.py`, `tests/test_iso_chain.py`.

Interfaces: consumes `iso_chain.INSTALLED_DISK_MENU: str`,
`iso_chain._grub_config(manifest: Manifest, digest: str) -> str`, and the fixtures
`manifest_data`, `rocky_manifest_data`, `ubuntu_manifest_data`, `opensuse_manifest_data`, `KEY`.
Provides the same names with the new menu text.

### Verification

- **Menu text.** Mode: focused-test. `BuildTests.test_menu_offers_an_installed_disk_by_default`
  and `BuildTests.test_keyed_menu_requires_the_completion_marker`. Red: `config.count(search)` is
  0. Green: `.venv/bin/python -m unittest -v tests.test_iso_chain.BuildTests`.

### Steps

1. In both tests, change the first line of the `search` string from
   `"for iso_chain_directory in /grub2 /boot/grub2 /grub /boot/grub; do\n"` to
   `"set btrfs_relative_path=y\n"` followed by that line, and after
   `self.assertEqual(config.count(search), 1)` add
   `self.assertEqual(config.count("btrfs_relative_path"), 1)`.
2. Run the green command; expect both tests to fail on `assertEqual(config.count(search), 1)`.
3. In `scripts/iso_chain.py`, make the constant and its comment read:

   ```python
   # powerpc-ieee1275 GRUB has no chainloader, so an installed disk boots through its own grub.cfg.
   # grubenv marks an installed GRUB directory; the launcher ISO carries none (ADR 0018). The
   # builder GRUB's btrfs.mod resolves paths in the default subvolume, as openSUSE's snapper
   # layout needs, when btrfs_relative_path is y (ADR 0024).
   INSTALLED_DISK_MENU = """\
   set btrfs_relative_path=y
   for iso_chain_directory in /grub2 /boot/grub2 /grub /boot/grub; do
   ```

   with the rest of the string unchanged.
4. Run the green command; expect OK. Run `just check-tests` and `just check`; expect exit 0.
5. Commit `feat: resolve installed-disk paths in the btrfs default subvolume`.

Rollback: revert the commit; no persisted state changes outside built media.

## Task 2: QEMU proof and documents

Files: create `docs/experiments/2026-10-04-opensuse-btrfs-installed-disk.md`; modify `README.md`,
`AGENTS.md`, and ADR 0018's Status section.

Interfaces: consumes Task 1's commit, the `build` path through `container_build_command`, the
`iso-chain-builder:44` and `iso-chain-initramfs:44` images, and the Fedora Cloud 44 disk of
`docs/experiments/2026-10-02-installed-disk-boot.md` in private storage.

### Verification

- **QEMU proof.** Mode: task-test-not-applicable; GRUB, SLOF, and the Leap boot on a ppc64le guest
  have no host-side executable observation.
- **Documents.** Mode: task-test-not-applicable; prose with no executable consumer, linted by
  `just check-markdown`.

### Steps

1. Leap disk: verify the Leap 15.6 ppc64le DVD's `.sha256` with `gpgv` and the openSUSE key, then
   install onto a fresh 20 GiB qcow2 under QEMU (TCG, POWER9, 8 GiB) from the DVD's
   `boot/ppc64le/linux` and `initrd`, `install=cd:/`, and a private AutoYaST profile with no
   partitioning section (YaST's default proposal), the `base` pattern, and `final_halt`. Read the
   disk with `guestfish --ro`. Gate: the default subvolume must be `@/.snapshots/1/snapshot` and
   hold `/boot/grub2/grubenv`; otherwise grow the disk and reinstall, or stop and report.
2. Build an unkeyed one-profile openSUSE manifest from the 2026-10-02 openSUSE record's pins and
   QEMU's user-mode addresses, a fresh launcher initramfs, and two ISOs from it with a clean tree:
   one at Task 1's commit, one at the branch's fork point on `main`.
3. Boot each arm ISO first, as `smoke` lays out drives, writing each console to a file:
   (a) Leap disk overlay with Task 1's ISO, until `login:`; (b) Leap disk overlay with the base
   ISO, until `disk: failed`; (c) a Fedora Cloud 44 overlay with Task 1's ISO, until `login:`;
   (d) a raw btrfs disk made by `mkfs.btrfs -r` with `boot/grub2/grubenv` and a `grub.cfg` that
   echoes a marker at its top level and no other default subvolume, with Task 1's ISO, until the
   marker.
4. Write the experiment record with Result, Inputs and environment, Arms, and Boundary sections,
   citing commits, ISO digests, and the console lines Success 2–4 name.
5. If arm (a) fails to reach `login:`, revert Task 1's commit, rewrite ADR 0024 whole (title,
   file name, Decision, Consequences, Considered & rejected) as "openSUSE stays
   installer-default" with the arm's evidence, keep the record of the failure, and skip steps 6
   and 7's btrfs text. Steps 6 and 7 below apply only when arm (a) passes.
6. ADR 0018 Status: add a blockquote banner, `**Amended by` linked to ADR 0024's file, then
   `(2026-10-04): the search resolves btrfs paths in the default subvolume, so the openSUSE
   consequence below no longer holds.` ADR 0024's "Keep openSUSE installer-default" bullet gains
   a closing sentence linking the experiment record: it booted a Leap 15.6 disk the same way.
7. README menu paragraph: after the ADR 0018 sentence add "On btrfs it looks inside the default
   subvolume, which is where openSUSE's snapper layout keeps them (ADR 0024)." AGENTS.md: the
   same clause in the menu stage; "twenty-three accepted, binding ADRs (0001–0023)" to
   "twenty-four accepted, binding ADRs (0001–0024)"; add ADR 0024 after ADR 0023 in Important
   Files; add the experiment to the Project Overview's proof list.
8. Run `just check`; expect exit 0. Commit `docs: record the openSUSE btrfs installed-disk proof`.
