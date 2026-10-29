# RHEL installer launcher

Red Hat Enterprise Linux 9.0 through 10.2 profiles hand off to Anaconda, interactive or, with
login values, unattended.

## Modes

A manifest profile can select a Red Hat Enterprise Linux release: `rhel` with `release` one of `9.0`
through `9.8` or `10.0`, `10.1`, or `10.2` ([ADR 0028](../adr/0028-add-rhel-installer-profiles.md)).
Its fields are [Rocky's](rocky.md#modes): a Fedora profile's without `kickstart`, with a
`repository.path` ending in `/BaseOS/ppc64le/os`. The launcher downloads and checks the four pins,
does not mount the launcher media, and kexecs Anaconda with `inst.repo=` and no `inst.ks=`, so the
installer starts interactive. A manifest carrying `ssh_authorized_keys` and `login_user` makes the
profile unattended instead ([ADR
0031](../adr/0031-install-rhel-unattended-from-a-derived-kickstart.md)): `build` derives a Kickstart
from `assets/kickstart/rhel-unattended.ks`, carries it on the launcher ISO, and the launcher mounts
the media and passes `inst.ks=` before `inst.repo=`, with the same blank-disk guards and completion
marker as Rocky. RHEL's BaseOS `.treeinfo` names no AppStream repository, so the launcher also
passes `inst.addrepo=AppStream,` followed by the source and the sibling `/AppStream/ppc64le/os`
path.

## Example manifests

Use the [interactive](../../examples/rhel-interactive.json) or
[keyed unattended](../../examples/rhel-unattended.json) structural fixture;
[replace its synthetic values](building-media.md#synthetic-configuration-examples) before building.

## Verify the release

Red Hat publishes no signed checksum for the boot ISO, so the trust anchor is weaker than for the
other distributions. Take the digest from the mirror's `*.SHA256SUM` beside the boot ISO, and
pass `--digest-source mirror-sha256sum` to acknowledge that the digest is unsigned.
`prepare-rhel-source` refuses any other value and prints `digest-source: mirror-sha256sum` on
success; the value is not written to `profile.json`. The flag cannot check provenance, so compare
the digest with the checksum Red Hat shows for that release before you run the command, since the
mirror, the `SHA256SUM`, and the boot ISO travel the same unauthenticated channel. Copy BaseOS's
`.treeinfo` and `repomd.xml` from the same mirror, here an authenticated FTP one (ADR 0016,
ADR 0027). `M` below carries the FTP userinfo, so use a per-run account, and keep the value out of
shell history and off a shared host's process list:

```sh
M='ftp://<REDACTED-FTP-MIRROR>/<path-to-release>/RHEL-9.8.0-GA'
mkdir -p "$HOME/iso-build/rhel/tree/repodata" && cd "$HOME/iso-build/rhel"
curl --fail -o tree/.treeinfo "$M/BaseOS/ppc64le/os/.treeinfo"
curl --fail -o tree/repodata/repomd.xml "$M/BaseOS/ppc64le/os/repodata/repomd.xml"
curl --fail -O "$M/BaseOS/ppc64le/iso/<boot-iso-name>.iso"
curl --fail "$M/BaseOS/ppc64le/iso/<boot-iso-name>.SHA256SUM"
```

## Prepare the profile

`prepare-rhel-source` requires the `.treeinfo` to name Red Hat Enterprise Linux at the given
`--release` for ppc64le `BaseOS`, to list the ISO digest for `images/boot.iso`, and to name no
`AppStream` variant. It extracts the kernel and initrd from the ISO, checks them against
`.treeinfo`, and writes a `profile.json` that pins the mirror's copies. It makes no network request
and needs `xorriso`; on macOS run it in the build image, as shown for
[`prepare-fedora-source`](fedora.md#prepare-the-profile).

```sh
scripts/iso_chain.py prepare-rhel-source \
  --iso "$HOME/iso-build/rhel/<boot-iso-name>.iso" \
  --iso-sha256 <digest-from-the-SHA256SUM> --digest-source mirror-sha256sum \
  --release 9.8 --tree "$HOME/iso-build/rhel/tree" \
  --repository-path /<path-to-release>/RHEL-9.8.0-GA/BaseOS/ppc64le/os \
  --minimum-memory-mib 6400 --output "$HOME/iso-build/rhel-prepared"
```

## Memory floor

The memory floor is Rocky's, 6400, until a RHEL boot measures its own.

## Source tree and smoke stop point

No RHEL-specific source tree layout or smoke stop point is stated. The evidence verifiers treat RHEL
as they treat [Rocky](rocky.md#source-tree-and-smoke-stop-point): the four pins, then BaseOS and
AppStream paths, with the two optional `images/` probe 404s admitted once each. For RHEL,
`verify-launcher-log` also requires exactly one `inst.addrepo=AppStream,` argument naming the
sibling AppStream path.

## Unattended installation

The Kickstart has no `repo` line and the launcher configures no subscription registration. The
unattended install is not yet exercised by an install harness or install evidence verifier;
[issue 97](https://github.com/randomparity/iso-chain-loader/issues/97) tracks them.

## Operator Kickstart

A RHEL profile can instead carry your own Kickstart in `operator_kickstart`
([ADR 0034](../adr/0034-carry-operator-installer-configuration-in-the-manifest.md)). Embed the
file in the manifest:

```sh
jq --rawfile text install.ks '.profiles.rhel.operator_kickstart = $text' base.json
```

Every profile in the manifest must then carry an operator file, and the manifest must carry no
`login_user`, `ssh_authorized_keys` or `install` values. `build` stages the composed file as
`/profiles/rhel/ks.cfg` and binds its size and SHA-256 on the kernel command line, so the
launcher hands off as it does for the derived Kickstart. The composition is a fixed `%pre` blank-disk
guard (exactly one non-optical disk, zero first and last MiB), your text unchanged, then a last
`%post` that sets `iso_chain_installed=1` in `/boot/grub2/grubenv`; the file may not exceed 1 MiB
once composed. The ISO's menu then boots only a marked disk.

The file owns users, root, privileges, host name, installed network and partitioning; the tool does
not read or check it. Install GRUB to the one disk, close every section with `%end`, end with
`reboot`, and keep the firmware boot order with `bootloader --leavebootorder`. The tool does not
police network or source commands, but passing evidence will need the file to fetch only from the
manifest source. The manifest and composed file carry the text
in the clear, so keep both private.
The launcher still passes `inst.repo=` and, for RHEL, `inst.addrepo=AppStream,`, so the file needs no
`repo` line. Check the manifest with [`validate-config`](building-media.md#validate-configuration-offline);
the [operator example](../../examples/rhel-operator.json) is a synthetic starting point. `validate-config` reads no
Kickstart syntax, and no RHEL install harness or evidence verifier exists yet (#97).

## Proof status

- [RHEL installer PowerVM experiment](../experiments/2026-10-15-rhel-installer.md): native
  PowerVM, interactive, RHEL 9.8 and 10.2 only; read its boundary section for what it covers.

The unattended install has no install-harness or verifier proof yet
([issue 97](https://github.com/randomparity/iso-chain-loader/issues/97)).

## Privacy and proof limits

Keep manifests, media, source trees, console logs, access logs, disk hashes and packet captures in
private storage (`umask 077`), using fresh output paths for every run, because they can contain
machine or network identifiers. Local checks and CI do not build or boot media. Emulator results
establish only their recorded QEMU boundary; native PowerVM requires separate proof.
