# ADR 0033: Apply Ubuntu Timezone and Locale Before the Completion Marker

## Status

Accepted (2026-10-26) — operator decision in #103.

## Context

ADR 0032 lets an Ubuntu preset select a timezone, locale and keyboard, rendered as the autoinstall
`timezone`, `locale` and `keyboard` keys. The first matching-build QEMU proof for #103
(`docs/experiments/2026-10-26-ubuntu-preset-install.md`) showed that Subiquity applies only the
keyboard during installation. It hands the timezone and locale to cloud-init on the installed
system's first boot, after the late command has written `iso_chain_installed=1` (ADR 0021). The
harness stops that boot at the login prompt; cloud-init had recorded its once-per-instance locale
step before finishing it, so no later boot applied the locale. A keyed disk could therefore claim
completion without the settings its manifest binds.

## Decision

When the manifest carries `install`, the Ubuntu renderer inserts one fixed late command ahead of
the completion-marker command:

```json
["curtin", "in-target", "--target=/target", "--", "sh", "-c", "<fixed script>", "sh", "TZ", "LOCALE"]
```

The fixed script links `/etc/localtime` to `/usr/share/zoneinfo/TZ`, writes `TZ` to
`/etc/timezone`, runs `locale-gen LOCALE` and `update-locale LANG=LOCALE`, and stops on the first
failure. `TZ` and `LOCALE` are the manifest's effective values, which the existing finite
allowlists bound; they reach the script only as positional arguments, never inside its text.
Subiquity aborts the installation when a late command exits nonzero (autoinstall reference,
*Command lists*), so a failed step leaves no completion marker. The autoinstall `timezone` and
`locale` keys stay, and cloud-init may later apply the same values again. The interim hold on
nondefault Ubuntu values is removed; ADR 0032's revision-1 allowlists apply to Ubuntu as written.

Manifests without `install` keep their legacy user-data bytes. The template, keyboard rendering,
completion marker and every other safety contract are unchanged. No operator-supplied command or
new hook surface is added.

## Consequences

The installed disk holds the selected timezone and locale when the marker is set, including the
defaults when `install` is present. Each opt-in user data grows by one command, still bound by
the existing size, digest and evidence checks. The step depends on `locale-gen`, `update-locale`
and zoneinfo files in the installed image; the QEMU proof for this decision shows they are
present offline. A future allowlist entry must name a timezone and locale that image provides.

## Considered & rejected

- **Keep the interim hold on nondefault values.** judgment: fit; the operator chose to deliver
  the customization in #103, and a hold leaves even the default locale unapplied.
- **Wait for cloud-init in the harness and verifier.** judgment: fit; it changes the evidence
  contract while leaving a real first boot that is interrupted with no locale and a set marker.
- **Use separate argv-only commands with the values in their text.** judgment: complexity; four
  entries and a value-bearing `/etc/timezone` write need a shell anyway, while one fixed script
  with positional values keeps the values out of every script.
- **Reconfigure `tzdata` instead of writing `/etc/timezone`.** judgment: fit; package postinst
  behavior is less direct than writing the two files the inspection reads.
