# Reusable install presets

This guide composes a prepared base, an optional shared block and per-system definitions, and
documents the bundled Rocky and Ubuntu presets.

## Reusable private blocks

Target-v2 selects `rocky-9.8-minimal` or `ubuntu-26.04.1-server`, revision `1`, and accepts
`--block-config` with `--target` and `--base-config` on validate-config, build and container-build.
The prepared base still owns only version, source and artifact profiles. Each system supplies
its own lpar, MAC and address. The optional block supplies shared routes, DNS and login values.
System leaves override block leaves; lists replace in order, and login user/keys replace as a pair.
Missing leaves inherit; empty DNS/packages clear those lists; empty routes/keys and null fail.
Every supplied value is validated, including values a later layer overrides.

The [Rocky block](../../examples/preset-block.json),
[Ubuntu block](../../examples/ubuntu-block.json), [Rocky A](../../examples/rocky-system-a.json)/
[B](../../examples/rocky-system-b.json) and [Ubuntu A](../../examples/ubuntu-system-a.json)/
[B](../../examples/ubuntu-system-b.json) are synthetic offline fixtures. The block's key token is
**not an SSH key**. `ExampleConfigurationTests.test_preset_systems` composes each block and system
with a base derived from the matching `*-unattended.json` fixture's fake pins; no artifacts are
downloaded, built or installed. Run it with:

```sh
.venv/bin/python -m unittest -v tests.test_iso_chain.ExampleConfigurationTests.test_preset_systems
```

Rocky and Ubuntu revision 1 render the bounded settings below: Rocky into its derived Kickstart,
Ubuntu into JSON-encoded autoinstall content.
Complete effective settings and preset identity are bound into canonical manifest v4. Offline
validation proves renderability, not package availability or a successful installation.
See the [approved contract](../workflow/specs/2026-10-17-reusable-install-presets-design.md).
Existing target-v1 and manifests without `install` retain their bytes and behavior. Older tools
reject the new opt-in formats; update consumers before using them.

## Rocky customization

The bundled [Rocky preset](../../assets/presets/rocky-9.8-minimal-v1.json) records revision 1's defaults.
Select it by id/revision in the target; this catalog file is policy documentation, not a build
configuration or a user-editable template. Allowed timezone values are `UTC`, `Etc/UTC`,
`America/New_York`, `Europe/London`, and `Asia/Tokyo`; locales are `en_US.UTF-8` and `en_GB.UTF-8`;
keyboards are `us` and `gb`. Packages may contain at most 64 distinct bare names matching
`[a-z0-9][a-z0-9+_.-]{0,127}`, in the requested order. They add to the mandatory minimal
environment; options, exclusions, groups, globs, versions and installer hooks are refused.

For two systems, copy the synthetic shared block and Rocky A/B definitions into private storage
outside the checkout (`umask 077`, directory mode 0700, file mode 0600). Replace their synthetic
identity, network and non-key values with your own. The London-settings variant is complete:
[block](../../examples/rocky-london-block.json), [system A](../../examples/rocky-london-system-a.json)
and [system B](../../examples/rocky-london-system-b.json). The block's `install` object selects
`Europe/London`, `en_GB.UTF-8`, keyboard `gb` and package `tmux`; system A sets
`"install": {"packages": []}` to clear the packages and system B inherits them. The test
`ExampleConfigurationTests.test_rocky_london_settings` validates both compositions and asserts these
effective values. Each system still supplies its own lpar, MAC and address.

Prepare a real base using the [Rocky source sequence](rocky.md#verify-the-release), including its
signature verification and digest-checked source preparation, plus the [launcher
preparation](building-media.md#building-the-launcher-initramfs-on-macos). Keep only version, source
and profiles in the base; use the exact approved source with the required BaseOS and AppStream
content. The [synthetic example pins](building-media.md#synthetic-configuration-examples) cannot
build media. Validate each private system with `validate-config --target SYSTEM --base-config BASE
--block-config BLOCK`, then use those same three arguments in the existing [`build` or
`container-build` sequence](building-media.md#build-the-iso), with fresh output paths for each ISO.
Restrict publication-directory access: the media exposes the effective network and login
identifiers.

No repository is added. Optional packages must exist in the selected source; availability and
dependency resolution happen during installation. Missing packages fail installation without a
completion marker. Installed packages retain the existing unpinned repository-content limitation.
The blank-disk/controller guards, completion marker and unprivileged key-only login remain fixed.

Run the [Rocky install proof](rocky.md#unattended-installation) with the effective embedded manifest
and the same commit that built the media. Its canonical evidence must bind console, access log,
captures and disk hashes. On a disposable overlay of the installed disk, inspect `/etc/localtime`,
`/etc/locale.conf`, `/etc/vconsole.conf` and `rpm -q tmux` for system B, as well as login privileges
and the completion marker. Keep this inspection with the private evidence. Renderer/unit evidence
alone establishes neither package availability nor a successful install. The [Rocky preset
experiment](../experiments/2026-10-26-rocky-preset-install.md) records a QEMU run of system B with
this inspection; QEMU proof does not establish native PowerVM behavior.

For real media, follow the distribution guide's preparation steps
([Rocky](rocky.md#prepare-the-profile), [Ubuntu](ubuntu.md#prepare-the-profile)) for authentic
digest-checked bases.
Copy block/system files outside the checkout into owner-only storage, replace synthetic identity
and key values, retain `umask 077`, use fresh output paths and restrict publication access.
Media and resolved manifests disclose the effective network/login values and source credentials.

## Ubuntu reusable preset

The bundled [Ubuntu preset](../../assets/presets/ubuntu-26.04.1-server-v1.json), `ubuntu-26.04.1-server`
revision `1`, selects exactly Ubuntu 26.04.1 from the prepared base. The catalog contains only
policy; it supplies no source, artifact pins or system identity.

| Setting | Default | Allowed values |
| --- | --- | --- |
| `timezone` | `Etc/UTC` | `UTC`, `Etc/UTC`, `America/New_York`, `Europe/London`, `Asia/Tokyo` |
| `locale` | `en_US.UTF-8` | `en_US.UTF-8`, `en_GB.UTF-8` |
| `keyboard` | `us` | `us`, `gb`; variant is always empty |
| `packages` | `[]` | Only `[]`; arbitrary extras have no verified offline package closure |

The [Ubuntu block](../../examples/ubuntu-block.json) shares London time, British English, routes, DNS
and login values. [System A](../../examples/ubuntu-system-a.json) inherits the default US keyboard;
[system B](../../examples/ubuntu-system-b.json) selects the British keyboard. Each supplies a distinct
synthetic identity. Replace the example addresses, identities and non-key token in private copies.
Keep `umask 077`, owner-only input/output directories and restricted access to published media.
Never put private definitions, generated manifests, media or evidence in Git.

First follow the [signature verification](ubuntu.md#verify-the-release) and
[`prepare-ubuntu-source`](ubuntu.md#prepare-the-profile) sequence and the
[launcher preparation](../../README.md#host-and-task-prerequisites) requirements. Create a private artifact base
containing only `version`, your explicit approved `source`, and the prepared `profiles`; use the
preparation's actual sizes and hashes. The offline example fixtures contain fake pins and cannot
build usable media. With that base and the prepared launcher payload, use the existing
[`validate-config`](building-media.md#validate-configuration-offline),
[`build` or `container-build`](building-media.md#build-the-iso) sequence with these input arguments for each system:

```sh
--base-config /private/run/ubuntu-base.json \
--block-config /private/run/ubuntu-block.json \
--target /private/run/ubuntu-system-a.json
```

These are argument fragments, not standalone commands. Select system B's private file for the
second build and use a fresh output path for each ISO. No mirror, source, package download,
storage, installer refresh or privilege setting is added by this preset. Manifests without
`install` keep their existing user-data bytes; opt-in settings explicitly render timezone, locale
and keyboard.

Run `install-ubuntu` and `verify-ubuntu-install-evidence` with the media-building commit,
collecting the canonical console, access-log, capture and disk evidence described in the
[Ubuntu unattended installation](ubuntu.md#unattended-installation) section. Read the
published disk with `guestfish --ro` before any inspection boot, so a later boot cannot supply a
missing setting: `/etc/localtime`, `/etc/timezone`, `/etc/default/locale`, `/etc/default/keyboard`
and the completion marker. Then check the locked/unprivileged user on a disposable overlay, and
record what you find with that run.

Subiquity applies the keyboard during installation but leaves the timezone and locale to
cloud-init on the installed system's first boot, after the completion marker. When `install` is
present, the user data therefore also carries one fixed late command, run in the target before the
marker command, that links `/etc/localtime`, writes `/etc/timezone`, generates the locale and sets
`LANG` in `/etc/default/locale` from the effective values (ADR 0033). If it fails, the install
stops without the marker. Manifests without `install` keep their legacy user data and leave both
settings to cloud-init. Do not add a mirror or another late command to force a setting.
The [Ubuntu preset experiment](../experiments/2026-10-26-ubuntu-preset-install.md) records the
QEMU runs of system B that exposed the deferral and an acceptance run with London time, British
English and the British keyboard. Its canonical evidence passed, and the published disk, read
without booting it again, held all three settings. QEMU is not native PowerVM proof.

## Privacy and proof limits

Keep manifests, media, source trees, console logs, access logs, disk hashes and packet captures in
private storage (`umask 077`), using fresh output paths for every run, because they can contain
machine or network identifiers. Local checks and CI do not build or boot media. Emulator results
establish only their recorded QEMU boundary; native PowerVM requires separate proof.
