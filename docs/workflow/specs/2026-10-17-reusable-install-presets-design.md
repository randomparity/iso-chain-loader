# Reusable installation presets

Status: operator-approved contract (2026-10-17); not implemented.
Scope: #100, under #99. Implementation belongs to #101, Rocky rendering/proof to #102,
Ubuntu rendering/proof to #103. Decision: [ADR 0032](../../adr/0032-reusable-install-presets.md).

## Problem and selected approach

The existing base supplies prepared artifact pins, and `compose_target_manifest` adds one
system's identity. Fixed Rocky and Ubuntu templates supply install policy. Add a bounded
preset/block/system composition arm at that existing boundary, without a second build system.
A preset supplies policy, never prepared artifacts, sources, credentials or system identity.
The resulting manifest remains the only input used by renderers, inspect and evidence readers.

Alternatives: extending target-v1 with inheritance would change its strict grammar; manifest v5
would force old configurations to migrate. A new target version and optional manifest-v4 field
preserve existing inputs and make older consumers reject new settings visibly.

## Input and resolution contract

Approved invocation surface: `validate-config`, `build` and `container-build` retain `--target`
plus `--base-config`; add optional `--block-config` only for target-v2. `--config` excludes these
three flags. Target-v1 rejects `--block-config` and keeps its existing grammar and behavior.
No discovery, environment defaults, include files, directory scans, interpolation or new command.

Each input is one UTF-8 JSON object, at most 2 MiB, read with the existing bounded regular-file
reader. Reject duplicate and unknown keys at each object level, wrong exact types (including
boolean-as-integer), null, empty strings and noncanonical values. Do not trim or case-fold.
Preset and block inputs cannot supply required system identity. A missing block is the empty
layer; an explicitly supplied block still needs its format marker.

| Object | Required fields | Optional fields |
| --- | --- | --- |
| Target-v2 root | `format`, `preset`, `lpar`, `mac`, `network` | `install`, `login_user`, `ssh_authorized_keys`, `operation_binding` |
| Target-v2 `network` | `address` | `routes`, `dns` |
| Target-v2 `preset` | `id`, `revision` | none |
| Block root | `format` | `network`, `install`, `login_user`, `ssh_authorized_keys` |
| Block `network` | none | `routes`, `dns` |
| Layer `install` | none | `timezone`, `locale`, `keyboard`, `packages` |

Format strings are exactly `iso-chain-target-v2` and `iso-chain-block-v1`.
`preset.id` is exactly `rocky-9.8-minimal` or `ubuntu-26.04.1-server`; `revision` is integer `1`.
Each id/revision is immutable policy bundled with the tool, not a filesystem path or remote
lookup. No floating revision, alias, user-supplied preset or inheritance between presets.
A later semantic/default change requires a new explicitly selected revision. Unknown revisions
fail; implementing a renderer does not change revision 1's meaning.

| Preset | Exact distribution/release in prepared base | Default install values |
| --- | --- | --- |
| `rocky-9.8-minimal`, revision 1 | `rocky`, `9.8` | `UTC`, `en_US.UTF-8`, `us`, `[]` |
| `ubuntu-26.04.1-server`, revision 1 | `ubuntu`, `26.04.1` | `Etc/UTC`, `en_US.UTF-8`, `us`, `[]` |

Defaults above are ordered timezone, locale, keyboard, packages. The artifact base retains
exactly `version`, `source`, `profiles`; it cannot carry installation settings. Select exactly
one profile by the preset's distribution/release, using the existing unique-match rule. Do not
invent hashes, change source, select a different release or accept a fallback profile.

Resolve only the listed leaves, preset then block then system. A supplied scalar replaces the
lower value; a supplied list replaces the whole list in its original order. Omitted leaves
inherit. Empty `install`/block `network` objects inherit everything. No generic recursive merge.
`packages: []` clears optional packages, `dns: []` removes DNS servers; empty routes or keys fail.
Null never means deletion or inheritance. Validate supplied values even when a later layer would
override them, then validate the resolved network and distro combination.

Login is one atomic pair: a layer supplies both `login_user` and `ssh_authorized_keys`, or neither.
A system pair replaces the complete block pair. Presets supply neither. The effective pair is
required for target-v2; missing keys do not turn a requested preset into an interactive install.
Existing no-login target-v1 and manifest behavior remains unchanged.

`lpar`, `mac`, `network.address` and optional `operation_binding` appear only in the system.
Reuse current canonical identifier/MAC/IPv4 validation: lpar is `[a-z][a-z0-9-]{0,31}`, with no
trailing hyphen for unattended use; MAC is lower-case unicast; address is canonical IPv4 CIDR.
Require effective routes (1–16, unique canonical destinations, exactly one default, on-subnet
canonical IPv4 gateways) and DNS (0–3 canonical IPv4 addresses). Ubuntu retains default-route-only
and at most two DNS servers. No default route or address is invented. Operation binding, when
present, is 32 lower-case hex digits, retaining the existing publication coupling.
Login uses `[a-z_][a-z0-9_-]{0,31}`, 1–16 keys, each 1–8,192 printable characters; retain renderer
refusals of leading-hyphen keys for Rocky and root login for Ubuntu. Block values may be private
identifiers; they never belong in tracked presets.

## Supported installation settings

Revision 1 deliberately offers a small, host-independent allowlist; supporting another value
requires a reviewed catalog revision, not reliance on the development host's locale/tz database.

| Setting | Values and bounds | Rocky rendering | Ubuntu rendering |
| --- | --- | --- | --- |
| `timezone` | One of `UTC`, `Etc/UTC`, `America/New_York`, `Europe/London`, `Asia/Tokyo`; at most 64 ASCII characters | `timezone VALUE --utc` | `timezone` scalar plus in-target step (ADR 0033) |
| `locale` | `en_US.UTF-8` or `en_GB.UTF-8`; at most 32 ASCII characters | `lang VALUE` | `locale` scalar plus in-target step (ADR 0033) |
| `keyboard` | `us` or `gb`; at most 16 ASCII characters | `keyboard VALUE` | `keyboard: {layout: VALUE, variant: ""}` |
| `packages` | Rocky: 0–64 distinct names, each 1–128 ASCII characters matching `[a-z0-9][a-z0-9+_.-]{0,127}`; Ubuntu: exactly `[]` | One optional name per `%packages` line after mandatory minimal environment | No `packages` key |

Rocky package names exclude options, exclusions, groups, environments, globs, versions, URLs,
whitespace and shell syntax. The builder-owned `@^minimal-environment` and `--excludedocs` remain;
`packages` selects additions, not a replacement base system. Requested names must be available
from the existing approved source's BaseOS/AppStream content. No repository is added, and a missing
package fails installation without a completion marker; no `--ignoremissing`. Offline validation
checks grammar and capability, not repository availability or dependency resolution. Repository
content remains subject to ADR 0013's unpinned installed-package residual.

Ubuntu revision 1 rejects a nonempty package list before external commands. The current
[ADR 0020](../../adr/0020-install-ubuntu-unattended-from-iso-carried-user-data.md) installs offline
with no candidate mirrors; no verified ISO package closure supports arbitrary extras. An empty
list expresses no additional package request. Preserve empty mirror candidates, offline fallback,
refresh disabled, no snaps and existing source selection. Do not probe mirrors or add downloads.
Supporting extras needs a separate approved availability/source contract.

Ubuntu's documented autoinstall interface exposes locale, keyboard and timezone; its `packages`
list invokes apt installation. This is interface evidence, not proof that a particular ppc64le
ISO can apply a locale offline. See the [Canonical reference](https://canonical-subiquity.readthedocs-hosted.com/en/latest/reference/autoinstall-reference.html).
The renderer issue must prove the selected nondefault locale/keyboard/timezone with the prepared
ISO; if proof exposes an unavailable locale, hold that capability for an operator decision,
without adding a mirror, silently reverting to defaults or claiming the proof passed.

### Ubuntu in-target settings (ADR 0033)

The first #103 proof showed Subiquity defers timezone and locale to cloud-init's first installed
boot, after the completion marker. When `install` is present, `_ubuntu_user_data` therefore
prepends one fixed entry to the template's `late-commands`, before the marker command:
`curtin in-target --target=/target -- sh -c SCRIPT sh TZ LOCALE`. `SCRIPT` is a module
constant: `set -eu`, `ln -sf "/usr/share/zoneinfo/$1" /etc/localtime`,
`printf '%s\n' "$1" >/etc/timezone`, `locale-gen "$2"`, `update-locale "LANG=$2"`. `TZ` and
`LOCALE` are the effective values already restricted to the allowlists above; nothing else is
interpolated. A failing step aborts the install before the marker. Manifests without `install`
keep legacy bytes. Proof reads `/etc/localtime`, `/etc/timezone`, `/etc/default/locale` and
`/etc/default/keyboard` from the published disk read-only, before any inspection boot.

## Manifest binding and consumers

Manifest version remains integer `4`. Add one optional root `install` object containing exactly
`preset`, `timezone`, `locale`, `keyboard`, `packages`; `preset` has exactly `id`, `revision`.
Its fields are complete effective values, not overrides. Revalidate the preset/release match and
allowlists; direct `--config` cannot bypass these checks. Require exactly one matching carried
profile and the login pair when `install` is present. Multi-profile legacy configs remain valid
without `install`, including mixed Rocky/RHEL keyed media. No new profile fields are introduced.

The new object is included in canonical UTF-8 JSON (`ensure_ascii=False`, sorted keys, compact
separators, one newline) and SHA-256. Key ordering is irrelevant; list ordering remains significant.
The 2 MiB bound also applies to resolved output; do not emit an oversized composed manifest.
No file paths, provenance layers, ignored values or timestamps enter the effective manifest.
The preset identity/revision is bound even when two revisions could resolve identical settings.

`load_manifest_bytes` and `_manifest_data` preserve the object without loss. `compose_target_manifest`
selects the input-version arm; `_configuration_manifest` validates renderer capability and renders
before any build/container subprocess. `_kickstart` applies settings only for the matching Rocky
profile, leaving its shared RHEL path unchanged; `_ubuntu_user_data` applies only the bounded keys.
The derived content's existing size/SHA-256, kernel arguments, embedded manifest and media result
bind those exact bytes. Keep existing 1 MiB content and command-line/GRUB bounds.

`inspect` must validate and report the embedded canonical manifest digest including `install`;
existing result field sets stay unchanged. Launcher-log and install-evidence verifiers recompute
rendered content from the same effective object, never consult block/system files or the current
preset defaults. The guest keeps verifying manifest/content digests and does not parse new JSON.
Evidence remains verified with the commit that built the media; an old tool must not verify a
new-setting manifest by dropping its unknown field.

Compatibility is opt-in: existing manifest-v4 and target-v1/base inputs without `install` retain
canonical bytes, digest, derived content and behavior. Target-v1 keeps refusing `install` and
`preset`; old tools reject target-v2 and the new manifest field. Update callers to a supporting
revision before sending either; no silent downgrade, auto-conversion or new media-result schema.
Manifest v3 remains rejected. This decision requires no external consumer to change until opting in.

In #101, parse/resolve both preset identities but refuse unsupported nondefault effective settings
before external commands until their renderer lands. Default-valued settings may use existing
renderer bytes only when those settings are demonstrably equivalent, with tests pinning that
behavior. New Ubuntu defaults may retain omitted locale/keyboard keys until #103 supplies their
explicit rendering. This equivalence is a capability gate, not permission to ignore customization.
The two catalog entries and their user-facing customization documentation ship with #102/#103;
The #101 examples must clearly distinguish offline contract tests from available build capabilities.

## Safety and privacy

Settings cannot alter sources, repositories, networking mode, storage, partitioning, installer
hooks, root lock, groups/sudo, completion markers, installed-disk lookup, controller checks or
blank-disk checks. Preserve key-only unprivileged login, no DHCP/IPv6, size/hash checks and
no-replace publication. RHEL, Fedora and openSUSE receive no new preset or custom setting path.

Keep real block/system/base files, generated manifests, ISOs and evidence outside the checkout.
Use `umask 077`, owner-only directories and files, fresh output paths, and restricted publish
access; possession of media exposes network/login identifiers and potentially source credentials.
Do not log rejected values or private paths. Errors name fixed schema fields and violated rules;
JSON error field values use a fixed allowlist rather than attacker-controlled field names.
No production data, generated hashes, credentials or apparently usable fake pins enter examples.

## Synthetic resolution example

These are approved data shapes, not currently runnable commands. All identities below are
synthetic. A real run must separately prepare a digest-checked artifact base; no pins are supplied
here. A public example SSH key is represented by a conspicuous non-key token and must be replaced
in a private file before installation. The example shows composition, not boot-ready media.

```json
{
  "format": "iso-chain-block-v1",
  "network": {
    "routes": [{"destination": "0.0.0.0/0", "gateway": "192.0.2.1"}],
    "dns": ["192.0.2.53"]
  },
  "login_user": "example_user",
  "ssh_authorized_keys": ["<SYNTHETIC-PUBLIC-KEY>"],
  "install": {"timezone": "Europe/London", "packages": ["tmux"]}
}
```

```json
{
  "format": "iso-chain-target-v2",
  "preset": {"id": "rocky-9.8-minimal", "revision": 1},
  "lpar": "example-a",
  "mac": "02:00:00:00:00:01",
  "network": {"address": "192.0.2.10/24"},
  "install": {"packages": []}
}
```

A second system changes only lpar to `example-b`, MAC to `02:00:00:00:00:02`, address to
`192.0.2.11/24`, and omits its `install`. Resolution for A is London/en_US.UTF-8/us/no optional
packages; B is London/en_US.UTF-8/us/`["tmux"]`. Both inherit the block's route, DNS and login
pair; neither inherits identity. Effective A's manifest contains:

```json
{"install":{"preset":{"id":"rocky-9.8-minimal","revision":1},"timezone":"Europe/London","locale":"en_US.UTF-8","keyboard":"us","packages":[]}}
```

This excerpt omits existing required manifest fields and is not a complete manifest. Canonical
serialization sorts its keys. For Ubuntu use the Ubuntu preset id, omit block packages, keep
both distinct system identities, and set B's `install` to `{"keyboard":"gb"}`. A resolves to
London/en_US.UTF-8/us/`[]`; B to London/en_US.UTF-8/gb/`[]`. Both select the separately prepared
Ubuntu profile. Supplying the Rocky block's `tmux` for Ubuntu is an error even if a later layer
would clear it. This deliberately tests supplied-value validation.

## Verification matrix and delivery

| Owner | Contract or evidence | Required observation |
| --- | --- | --- |
| #100 | Scope, schemas, defaults, compatibility, source model | Operator approves exact decisions; independent design review and Markdown/whitespace/secrets checks pass; no runtime claim |
| #101 | Composition in existing target/config tests | Preset/block/system precedence; atomic login replacement; lists replace; omission versus empty; forbidden null/types/keys/duplicates; missing identity; valid/invalid preset revision; bounds at and above limits |
| #101 | Canonical manifest and consumers | Legacy byte/digest/render regression; complete install roundtrip; key-order invariance; changed settings/revision change digest; direct-config validation; old-parser refusal; inspect/evidence use effective values |
| #101 | Failure and capability boundaries | Rejected overwritten values; profile mismatch; no login/multi-profile refusal; unsupported renderer settings invoke no subprocess; safe errors with malicious field/value fixtures; two systems offline |
| #102 | Rocky renderer and shared RHEL path | Exact selected directives/package lines; syntax injection refusals; mandatory minimal group and guards retained; unchanged legacy Rocky/RHEL bytes; rendered size/digest recomputed |
| #103 | Ubuntu renderer and offline scope | JSON roundtrip for allowed values; in-target settings step first in `late-commands`, before the marker, carrying exactly the effective values; nonempty packages refused; no extra package/mirror/refresh keys; size/digest recomputed; unchanged legacy user data |
| #102/#103 | Customized install and installed-disk boot | Matching-build canonical evidence binds console/access/capture/disk hashes; inspect installed timezone/locale/keyboard and Rocky extras; existing guards, completion and unprivileged login; separate QEMU/native limits |

Implementation adds focused unittest cases in the matching existing behavior classes and proves
new tests detect controlled faults. Each implementation PR runs applicable guardrails and records
its first real runtime proof, or explicitly keeps missing proof outstanding. No runtime suite or
media operation belongs to this contract-only change. Settings observations supplement existing
canonical evidence; a green offline validation is not package availability or installation proof.

## Failure model

- **Actors and deployments:** local operators on macOS arm64 or x86_64 Linux composing private
  inputs for ppc64le POWER9; CI exercises parsing/rendering; existing inspect/evidence consumers.
- **Invariants and assets:** exact identity and sources, no silent ignored settings, deterministic
  binding, private identifiers, blank disks, completion and privilege boundaries.
- **Accepted failure classes:** offline grammar validation cannot establish Rocky package
  availability; installer failure remains visible without a completion marker. An Ubuntu
  in-target settings step failure aborts the install the same way (ADR 0033). Old consumers
  reject opt-in formats; old input forms stay compatible. Neither class implies successful media.
- **Covered elsewhere:** implementation/tests #101; renderer and QEMU install proof #102/#103;
  source-policy expansion/additional catalogs operator/separate scope; native PowerVM proof
  operator/native validation workflow. Existing FTP evidence gap #77 is outside this design.

Threat boundary: untrusted JSON values become installer input and public error text. Strict field
sets, bounded reads, finite scalar allowlists and package grammar prevent directives/paths/options
from crossing that boundary; existing renderer encoding protects login values. ADR 0033's
script is a constant; allowlisted timezone/locale values reach it only as positional arguments.
No new secret storage, endpoint, service, privilege or dependency is introduced.
