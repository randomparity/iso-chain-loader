# openSUSE installer launcher

openSUSE Leap 15.6 profiles hand off to linuxrc and YaST, interactive only.

## Modes

An `opensuse`/`15.6` profile pins the Leap 15.6 `boot/ppc64le/linux` and `boot/ppc64le/initrd`.

A manifest with an openSUSE profile allows only the default route and at most one DNS server,
because linuxrc's `ifcfg=` carries one gateway. The launcher downloads only the two pins and
starts linuxrc with `ifcfg=<mac>=<address>,<gateway>[,<dns>]`, `hostname=`, `install=` naming
`source` plus the repository path, `textmode=1`, and `self_update=0`. linuxrc then loads the
installation system from that repository and checks each part against the digests its initrd
carries.

## Example manifests

Use the [openSUSE structural fixture](../../examples/opensuse-interactive.json);
[replace its synthetic values](building-media.md#synthetic-configuration-examples) before building.

## Verify the release

Trust starts from the tree's signed `CHECKSUMS`. Check it with the openSUSE Project Signing Key
(`AD485664E901B867051AB15F35A2F86E29B700A4`), whose expiry is 2026-06-19; `gpgv` still exits 0 for
the expired key, so read `gpg --show-keys` for the date rather than relying on a warning. The key
file comes from the same server as `CHECKSUMS`, so the `grep` below requires the signature to be
from that fingerprint rather than from whatever key the file holds. If it prints the stop message,
do not continue, whatever `gpgv` printed:

```sh
B=https://download.opensuse.org/distribution/leap/15.6/repo/oss
mkdir -p "$HOME/iso-build/opensuse/tree/boot/ppc64le" "$HOME/iso-build/opensuse/tree/media.1"
cd "$HOME/iso-build/opensuse"
curl --fail -O "$B/CHECKSUMS" -O "$B/CHECKSUMS.asc" -O "$B/gpg-pubkey-29b700a4-62b07e22.asc"
gpg --dearmor < gpg-pubkey-29b700a4-62b07e22.asc > opensuse.gpg
if gpgv --status-fd 1 --keyring ./opensuse.gpg CHECKSUMS.asc CHECKSUMS |
  grep -q 'VALIDSIG .* AD485664E901B867051AB15F35A2F86E29B700A4$'; then
  curl --fail -o tree/media.1/products "$B/media.1/products"
  curl --fail -o tree/boot/ppc64le/linux "$B/boot/ppc64le/linux"
  curl --fail -o tree/boot/ppc64le/initrd "$B/boot/ppc64le/initrd"
else
  echo 'CHECKSUMS is not signed by the openSUSE key; stop' >&2
fi
```

## Prepare the profile

`prepare-opensuse-source` needs the tree to hold `media.1/products`, `boot/ppc64le/linux`, and
`boot/ppc64le/initrd`. It requires `CHECKSUMS` to list all three, `media.1/products` to be exactly
`/ openSUSE-Leap 15.6-1`, and both boot files to match their entries. It writes a `profile.json`
that pins the mirror's copies. It runs no subprocess and makes no network request.

```sh
scripts/iso_chain.py prepare-opensuse-source \
  --checksums "$HOME/iso-build/opensuse/CHECKSUMS" \
  --tree "$HOME/iso-build/opensuse/tree" \
  --repository-path /distribution/leap/15.6/repo/oss \
  --minimum-memory-mib 6400 --output "$HOME/iso-build/opensuse-prepared"
```

## Memory floor

As for [Rocky](rocky.md#memory-floor), the launcher's `/run` gate sets the memory floor: it needs
space for the 249 MB kernel and initrd plus 1 GiB. Under QEMU pSeries POWER9, 6,144 MiB stops at
`run-space` and 6,656 MiB (`MemTotal` 6,529 MiB) reaches YaST
(`docs/experiments/2026-10-02-opensuse-installer.md`). Hence 6400; give the guest at least 6,656
MiB.

## Source tree and smoke stop point

A local tree needs, below `distribution/leap/15.6/repo/oss/`: `CHECKSUMS` and `CHECKSUMS.asc`,
`media.1/`, `repodata/`, the `gpg-pubkey-*.asc` keys, `control.xml`, and `boot/ppc64le/`'s `linux`,
`initrd`, `config`, `common`, `root`, `bind`, `control.xml`, and `cracklib-dict-full.rpm`. Check the
pins with [`validate-external-source`](sources.md#validate-source-pins), then
[build](building-media.md#build-the-iso) and [`smoke`](verification.md#installer-smoke-proof) with
`--memory-mib 6656` or more. Answer No to the online repositories, choose a role, and stop at
Suggested Partitioning; never begin the installation. Any linuxrc digest dialog or YaST signature
warning fails the run. linuxrc reads `autoinst.xml` from `source` without a digest check and starts
AutoYaST if one is served, so serve only a trusted tree and stop at once if YaST shows "Preparing
System for Automated Installation". YaST also fetches release notes from `doc.opensuse.org`, so the
HTTP evidence covers `source` only. It admits `HEAD` requests (200 status, 0 bytes) and ten optional
paths that return 404 once each, all for openSUSE only. `verify-launcher-log` compares the installer
command line whole and requires linuxrc's `IP addresses:` line to show the manifest address.

## Unattended installation

openSUSE has no unattended mode. `build` and `container-build` refuse a manifest carrying
`ssh_authorized_keys` and `login_user` unless every profile is Rocky or RHEL, or every profile is
Ubuntu ([target-bound media](target-bound-media.md)).

## Proof status

Each record has its own result and boundary sections:

- [openSUSE installer VM experiment](../experiments/2026-10-02-opensuse-installer.md): QEMU pSeries/POWER9,
  interactive.
- [openSUSE btrfs installed disk VM experiment](../experiments/2026-10-04-opensuse-btrfs-installed-disk.md):
  QEMU pSeries/POWER9.
- [FTP launcher installs and credential residue](../experiments/2026-10-27-ftp-installs-and-residue.md):
  QEMU pSeries/POWER9, interactive readiness only.

No openSUSE record covers native PowerVM.

## Privacy and proof limits

Keep manifests, media, source trees, console logs, access logs, disk hashes and packet captures in
private storage (`umask 077`), using fresh output paths for every run, because they can contain
machine or network identifiers. Local checks and CI do not build or boot media. Emulator results
establish only their recorded QEMU boundary; native PowerVM requires separate proof.
