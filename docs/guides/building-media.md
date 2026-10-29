# Building launcher media

This guide checks a manifest offline, adapts the synthetic examples, prepares the launcher kernel
and initramfs, and builds the launcher ISO. Each distribution's source preparation is in its own
guide; the [README](../../README.md) links them.

## Validate configuration offline

Before preparing artifacts or building media, check a private manifest's content and local
renderability with Python 3.14 and this checkout's built-in unattended templates:

```sh
python scripts/iso_chain.py validate-config --config manifest.json
# Or compose a target request with its base manifest only in memory:
python scripts/iso_chain.py validate-config --target target.json --base-config base.json
```

The [complete structural fixtures](#synthetic-configuration-examples) cover the supported
installation modes and the target/base input form.

Supply exactly one input form. Each JSON input must be a regular file of at most 2 MiB.
The command checks the existing manifest/target rules, profile/login compatibility, unattended
rendering where applicable, and launcher argument limits for every carried profile. Bound
manifests can pass this content check without publication options. Success exits 0 and prints:

```text
configuration: passed (manifest content and profile/login compatibility)
renderability: passed (unattended content and launcher arguments for every carried profile)
not checked: artifact files/digests, source reachability, build, boot, install
```

Validation failure exits 2 with a safe field/rule error on stderr and no success report. The
command makes no network calls, invokes no subprocesses, and writes no output artifacts; it
neither emits a composed manifest nor requires GRUB, a container engine, or artifact files.
This is a snapshot content check. Continue with the profile's existing `prepare-*` and
`build`/`container-build` sequence to verify local build inputs, or use
[validate source pins](sources.md#validate-source-pins) for the separate network artifact check.
Neither content validation nor pin validation proves a successful build, boot, or installation.

## Synthetic configuration examples

These checked-in JSON files are **structural fixtures**, with synthetic network values, an
example-domain source and fake artifact sizes/digests. They are not authenticated pins or
boot-ready media. They carry no deployed identity or credentials. The keyed examples contain
only a public test key; replace it with your own public key before creating private media.

| Mode | Complete input |
| --- | --- |
| Fedora 44 with the existing Kickstart fixture | [fedora.json](../../examples/fedora.json) |
| Rocky 9.8 interactive | [rocky-interactive.json](../../examples/rocky-interactive.json) |
| openSUSE Leap 15.6 interactive | [opensuse-interactive.json](../../examples/opensuse-interactive.json) |
| Ubuntu 26.04.1 interactive | [ubuntu-interactive.json](../../examples/ubuntu-interactive.json) |
| Rocky 9.8 keyed unattended | [rocky-unattended.json](../../examples/rocky-unattended.json) |
| Ubuntu 26.04.1 keyed unattended | [ubuntu-unattended.json](../../examples/ubuntu-unattended.json) |
| Rocky target/base form | [target.json](../../examples/target.json) + [base.json](../../examples/base.json) |

From the checkout root, these commands exercise the real offline validator:

```sh
python scripts/iso_chain.py validate-config --config examples/fedora.json
python scripts/iso_chain.py validate-config --target examples/target.json --base-config examples/base.json
```

Copy the matching example into private storage (`umask 077`). Replace `lpar`, the MAC, address,
routes, DNS and `source` with your declared target and source values. For keyed modes replace
`login_user` and `ssh_authorized_keys`; the pair must remain together. The documentation-only
network values are not a recommended network configuration.

Run the matching `prepare-*` sequence ([Fedora](fedora.md#prepare-the-profile),
[Rocky](rocky.md#prepare-the-profile), [RHEL](rhel.md#prepare-the-profile),
[Ubuntu](ubuntu.md#prepare-the-profile) or [openSUSE](opensuse.md#prepare-the-profile)) against
verified release inputs. Replace the whole
value at `profiles.<name>` with the resulting `profile.json` object, rather than adding a
`profile.json` field or replacing the manifest root. Set `selected_profile` to that exact map
key. This replaces the fake paths, sizes, digests and memory requirement with preparation
output. For Fedora, stage the digest-matching Kickstart under `--profiles`: the example's
`/profiles/fedora-44/ks.cfg` corresponds to `<profiles-directory>/fedora-44/ks.cfg`.

In the target/base form, put the prepared object at `base.json`'s `profiles.rocky`. The target's
`profile: "rocky-9.8"` matches the object's distribution-release, whereas `rocky` is its map key.
The target supplies the machine/network values and a synthetic `operation_binding`; replace that
binding with the actual operation's value when using the existing
[publication workflow](target-bound-media.md).
Offline validation composes only in memory. Revalidate your adapted inputs, then follow the
existing [build sequence](#build-the-iso); a passing content check still proves no artifact digest, source
reachability, build, boot or installation.

## Building the launcher initramfs on macOS

`prepare-initramfs` runs dracut against an installed ppc64le kernel, so it needs a ppc64le host.
`container-prepare-initramfs` runs it inside `iso-chain-initramfs:44`, an image built for
`linux/ppc64le` from `Containerfile.initramfs` with the same pinned Fedora 44 base as the ISO build
image. It publishes the image's kernel and the launcher initramfs built for it into an existing
directory that does not already hold `vmlinuz` or `initramfs.img`:

```sh
just build-initramfs-image
mkdir -p "$HOME/iso-build/launcher"
.venv/bin/python scripts/iso_chain.py container-prepare-initramfs \
  --output-dir "$HOME/iso-build/launcher"
```

On a non-ppc64le host the engine emulates ppc64le, which is slow: about two minutes for the image
and one for the initramfs on Docker Desktop for macOS arm64, the verified host. Podman needs
`qemu-user-static` inside its machine, and Docker on Linux needs a registered ppc64le
`binfmt_misc` handler; neither has been verified here. The launcher initramfs carries the virtio
drivers for QEMU and `ibmveth`, `ibmvscsi`, `sr_mod`, and `isofs` for PowerVM partitions.

On a ppc64le Linux host with Python 3.14, dracut, systemd, iproute, curl, and the matching kernel
modules, run the same step directly:

```sh
sudo python3 scripts/iso_chain.py prepare-initramfs --kernel-version VERSION --output FILE
```

## Building the launcher ISO on macOS

macOS does not provide `grub2-mkrescue` or `xorriso` for the `powerpc-ieee1275`
target. `container-build` runs the same `build` implementation inside a pinned
Fedora image instead, using `podman` when it is on `PATH` and `docker`
otherwise; `--engine NAME` selects one explicitly. Build the image once, then
build the ISO:

```sh
just build-image
mkdir -p "$HOME/iso-build"
.venv/bin/python scripts/iso_chain.py container-build --config MANIFEST \\
  --kernel FILE --initramfs FILE --profiles DIR --output "$HOME/iso-build/launcher.iso"
```

`container-build` mounts the repository tree read-only and the directory holding each path argument
at its own absolute path inside the container — read-only, except the output directory, which is
writable — so the engine's file sharing must reach the manifest, the kernel, the initramfs, the
profile directory, and the output directory, and the output directory must already exist. Every
other file in those directories
is visible to the container, and when the output directory also holds an input, that input sits in a
writable mount and is protected by the build implementation rather than by the mount. The output
directory must not be the repository root itself, because the repository's own mount would then have
to be writable; an output directory inside or above the repository is mounted separately, and the
deeper mount wins. A mount source containing a comma is rejected before any container starts. The
image carries the packaged `powerpc-ieee1275` GRUB modules, so `--grub-modules` is optional and
defaults to the image's module directory; pass it to use a different module set.

The image lives in the detected engine's own image store, so build it with the same engine that
builds the ISO: `just build-image` detects the engine the same way, and `container-build` names the
exact build command in its error when the image is missing.

The ISO is written by the container process. With the engine verified here (Docker Desktop on
macOS) it belongs to the invoking user; a rootful engine can create it as `root` inside the shared
mount, so check `ls -l` after the first build and correct ownership if a later step must read it as
another user.

Inspect an ISO inside the same image. Its directory must be mounted writable,
because `inspect` extracts the embedded manifest into a temporary directory
beside the ISO:

```sh
ENGINE=$(command -v podman || command -v docker)
"$ENGINE" run --rm \
  --mount type=bind,source=REPO,target=REPO,readonly \
  --mount type=bind,source=ISO-DIR,target=ISO-DIR \
  iso-chain-builder:44 python3 REPO/scripts/iso_chain.py inspect ISO-DIR/launcher.iso
```

`smoke`, `install-fedora`, `install-rocky`, and `install-ubuntu` still require ppc64le QEMU and do
not run on macOS.

## Build the ISO

Build the ISO from the launcher payload, its kernel, the prepared profile directory, and the
manifest. `build` checks every profile artifact against the manifest before staging it on the
ISO; `inspect` returns the embedded manifest's canonical JSON. Each ISO binds one partition's
network, so expect one ISO of about 100 MB per partition.

```sh
umask 077
PRIVATE=$(mktemp -d)
.venv/bin/python scripts/iso_chain.py container-build --config MANIFEST \
  --kernel "$HOME/iso-build/launcher/vmlinuz" \
  --initramfs "$HOME/iso-build/launcher/initramfs.img" \
  --profiles "$HOME/iso-build/prepared" --output "$HOME/iso-build/launcher.iso"
```

## Privacy and proof limits

Keep manifests, media, source trees, console logs, access logs, disk hashes and packet captures in
private storage (`umask 077`), using fresh output paths for every run, because they can contain
machine or network identifiers. Local checks and CI do not build or boot media. Emulator results
establish only their recorded QEMU boundary; native PowerVM requires separate proof.
