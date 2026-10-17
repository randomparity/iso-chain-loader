# ADR 0032: Compose Reusable Installation Presets Into the Manifest

## Status

Accepted (2026-10-17) — operator-approved contract; not implemented.

## Context

Issue #100 needs reusable Rocky 9.8 and Ubuntu 26.04.1 policy plus private block/system settings.
The prepared base owns artifact pins and source; target-v1 owns one system request. Manifest v4
and derived installer content already bind effective identity. ADRs 0017, 0019, 0020, 0023 and
0031 govern carriage, rendering and privileges; new policy must preserve those contracts.

## Decision

Use target-v2 plus an optional block-v1 input at the existing composition boundary. Select an
exact bundled preset id/revision, overlay only explicitly allowed leaves, and replace lists.
Require identity per system and treat login values as an atomic pair. Presets contain no pins,
sources or private identity. Null and unknown fields fail, even in overridden values.

Add an optional complete `install` object to manifest v4, including preset identity/revision.
Bind it with existing canonical serialization and derived-content hashes. Existing input forms
and bytes stay unchanged; older readers refuse opt-in fields rather than dropping them.
Require one matching unattended profile for the new object; legacy multi-profile paths remain.

Revision 1 admits bounded timezone/locale/keyboard values and Rocky bare-name extra packages.
Its minimal environment remains mandatory. Ubuntu accepts only an empty extras list because the
existing offline install has no verified arbitrary-package closure. No implicit mirror or source
expansion is authorized. Until a distro renderer is present, nondefault settings fail before
external commands. Safety, completion, sources and privileges remain builder-owned.

The exact grammar, allowlists, examples and consumer obligations are the
[specification](../workflow/specs/2026-10-17-reusable-install-presets-design.md).

## Consequences

Private blocks reduce duplication without making identity inheritable. Preset revisions become
immutable policy contracts; allowlist growth requires a new reviewed revision. New manifests
require supporting tooling, while existing consumers can keep sending target-v1. Offline
validation proves structure/renderability, not package availability or successful installation.
Rocky's existing unpinned repository residual remains; Ubuntu extras need a separate decision.
The design changes no code and supplies no runtime proof; #101–103 implement and verify it.

## Considered & rejected

- **Extend target-v1 in place.** judgment: compatibility; a new format marker makes the new
  inheritance contract explicit while keeping the existing strict consumer contract intact.
- **Manifest v5 and migrate existing manifests.** judgment: cost; an optional field with strict
  old-reader refusal preserves existing artifacts and follows ADR 0017's carriage approach.
- **Resolve policy again at render time.** judgment: fit; the manifest must carry effective
  values so a changed block or catalog cannot silently change the meaning of recorded evidence.
- **Generic recursive merge or arbitrary installer templates.** judgment: complexity and fit;
  neither is needed for the requested bounded settings, and both expand the trusted surface.
- **Allow arbitrary Ubuntu extras from an implicit mirror.** verified: ADR 0020's No alternate
  source decision requires empty candidates and ISO-only installation; this would change it.
- **Do nothing.** judgment: fit; it leaves #99's reusable block policy and bounded overrides absent.
