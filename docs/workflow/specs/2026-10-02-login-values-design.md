# SSH Keys and Login User in Target Requests and Manifest v4

## Problem

hmcpctl's built mode forwards SSH public keys and a login user, but `compose_target_manifest`
accepts only `format`, `profile`, `lpar`, `mac`, `network`, and `operation_binding`, so built mode
cannot serve the unattended Rocky (#25) and Ubuntu (#24) installs. Issue #39. Decision record:
[ADR 0017](../../adr/0017-carry-login-values-in-the-manifest.md).

## Contract

- **Target request.** `iso-chain-target-v1` gains optional `ssh_authorized_keys` and `login_user`.
  `compose_target_manifest` copies each present field unchanged into the composed manifest, which
  `load_manifest_bytes` then validates.
- **Manifest v4.** Root optional fields become `operation_binding`, `ssh_authorized_keys`, and
  `login_user`. `load_manifest_bytes` enforces, in this order, with messages that never contain the
  submitted value:
  - exactly one of the two present: `manifest ssh_authorized_keys/login_user: must appear
    together`;
  - `ssh_authorized_keys` not a JSON array of 1 to 16 entries: `manifest ssh_authorized_keys: must
    hold 1 to 16 keys`;
  - entry `i` not a string of 1 to 8,192 characters for which `str.isprintable()` holds: `manifest
    ssh_authorized_keys[i]: must be one line of 1 to 8192 printable characters`;
  - `login_user` not a string that `re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", value)` accepts:
    `manifest login_user: must match [a-z_][a-z0-9_-]{0,31}`.
- **Model.** `Manifest` gains `ssh_authorized_keys: tuple[str, ...] = ()` and `login_user: str |
  None = None`. `_manifest_data` emits both exactly when `login_user` is not `None`, so serializing
  it with the canonical options reproduces the canonical bytes. `verify_launcher_log` serializes
  with `ensure_ascii=False`, matching `load_manifest_bytes`, so a non-ASCII key recomputes the same
  digest.
- **Bound.** `MAX_MANIFEST_BYTES` becomes 2 MiB; the over-limit message becomes `<label> file:
  exceeds 2 MiB`. The target request, base manifest, `--config` manifest, embedded manifest, and the
  evidence verifier's manifest share it.
- **Build refusal.** `_build_manifest` raises `login_user and ssh_authorized_keys: no installer
  profile applies them yet (ADR 0017)` when the loaded manifest carries them. `build_iso` and
  `container_build_command` both call it first, so neither `grub2-mkrescue` nor a container engine
  runs.
- **Unchanged.** Kernel arguments, GRUB configuration, the launcher, `media_result`, and every
  manifest without the fields keep their bytes.
- **Documentation.** README's target-request section names both fields, their bounds, and the build
  refusal; ADR 0015's consequence line points to ADR 0017; AGENTS.md lists the new optional fields,
  the 2 MiB bound, and seventeen ADRs.

## Failure model

1. **Actors and deployments**
   - hmcpctl's build entry, running `build` or `container-build` with a target request it wrote.
   - A local operator running `build --config`, `inspect`, or the `verify-*` commands.
2. **Invariants and assets at stake**
   - Canonical bytes and digests of existing v4 manifests (published ISO labels, evidence records).
   - The `iso-chain-media-v1` result consumed by hmcpctl.
   - No-fallback rule: a request for keys never yields media that silently omits them.
   - Validation errors never echo request values.
3. **Accepted failure classes**
   - Duplicate keys in the list are accepted; hmcpctl does not reject them and the installer
     renderers own deduplication.
   - Keys are not parsed as OpenSSH key syntax; the consumer's bound is a printable line, and a
     malformed key fails at installation, which #24/#25 prove.
   - A 2 MiB manifest costs at most 2 MiB of memory per read; bounded and stated here.
4. **Covered elsewhere**
   - Rendering into Kickstart or autoinstall and lifting the refusal: #25, #24.
   - Host identity, host-key trust, readiness: hmc-mcp ADR 0191.
   - Access control on published ISOs: ADR 0015 (publish directory).

## Threat model

1. **Boundary inventory.** Widened: the target request file (hmcpctl → `build`) now carries two
   more fields. Widened: the manifest read bound. Added: none.
2. **Actor model.** hmcpctl is trusted to name the partition but not to produce well-formed input;
   the request may carry caller-supplied keys. The operator's base manifest is trusted.
3. **Control per boundary.** Exact field sets (`_manifest_object`), duplicate-key rejection
   (`_object_pairs`), the type, count, length, printable, and pattern checks above, the 2 MiB read
   bound, and messages that name only the field and index.
4. **Out of scope.** Whether a key grants access to the right person (hmcpctl's caller owns
   authorization); confidentiality of published public keys (they are not secrets).

## Success

- Each Contract bullet above has a passing focused test in `tests/test_iso_chain.py`.
- The canonical bytes and digest of `manifest_data()` and every existing fixture are unchanged.
- `just check` passes.
