# Installer Kickstart Label Evidence — Implementation Plan

**Goal:** `verify_launcher_log` rejects a console log unless the post-kexec installer kernel
command line carries exactly one `inst.ks=cdrom:LABEL=<volume ID>:<Kickstart path>`.

**Architecture:** generalize the launcher command-line parser in `scripts/iso_chain.py` and call
it a second time on the log after `kexec-exec: started`. The two Fedora verifiers already call
`verify_launcher_log`.

**Tech stack:** Python 3.14 stdlib, `unittest`. Spec:
`docs/workflow/specs/2026-10-02-installer-kickstart-label-evidence-design.md`.

Expected implementation size: 70–100 changed lines (S) — about 25 in `iso_chain.py` (parser
signature, one call site, the new check) and 60 in tests (helper, three fixtures, new cases).

## Global Constraints

- Standard library only; ruff line length 100; annotate every function.
- `ValidationError` messages never contain the digest, label, Kickstart path, or log text.
- The launcher's existing error messages stay byte-identical.
- Guardrails: `just check-tests`, `just check`.

## Task 1: Installer `inst.ks` evidence

Files: modify `scripts/iso_chain.py`, `tests/test_iso_chain.py`.

**Interfaces:** consumes `_volume_id(digest: str) -> str`, `Manifest.profile(name) ->
InstallerProfile` (`.kickstart.path`), `_kernel_arguments(manifest, digest, profile)`. Produces
`_kernel_command_line(lines: list[str], first: int, end: int, prefixes: tuple[str, ...] | None,
subject: str) -> tuple[int, list[str]]` and test helper
`installer_command_line(manifest, digest, kickstart_argument: str | None = None) -> str`.

**Verification:**

- Contract: installer `inst.ks` assertion. Mode: focused-test.
  `EvidenceTests.test_requires_one_exact_installer_kickstart_label`; red: the bad variants
  verify without raising; green:
  `.venv/bin/python -m unittest -v tests.test_iso_chain.EvidenceTests`.
- Contract: both Fedora verifiers inherit it. Mode: focused-test.
  `FedoraEvidenceTests.test_rejects_installer_kickstart_from_another_label` and
  `FedoraInstallEvidenceTests.test_rejects_installer_kickstart_from_another_label`; red: no
  error; green: `.venv/bin/python -m unittest -v tests.test_iso_chain.FedoraEvidenceTests
  tests.test_iso_chain.FedoraInstallEvidenceTests`.

Steps:

1. Add the module test helper beside `valid_log()`:

   ```python
   def installer_command_line(manifest, digest, kickstart_argument=None):
       if kickstart_argument is None:
           path = manifest.profile("fedora").kickstart.path
           kickstart_argument = f"inst.ks=cdrom:LABEL={iso_chain._volume_id(digest)}:{path}"
       return (
           "[    1.000000] Kernel command line: inst.text rd.neednet=1 "
           f"{kickstart_argument} console=hvc0 ipv6.disable=1"
       )
   ```

2. Append `installer_command_line(...)` after `"kexec-exec: started"` in `EvidenceTests.content`
   (use `self.manifest`, `self.digest`; `fedora` and `rescue` share the Kickstart path
   `/profiles/fedora-44/ks.cfg` in `manifest_data()`), the `FedoraEvidenceTests` console, and the
   `FedoraInstallEvidenceTests` install console.
   Replace the hard-coded `inst.text console=hvc0` line in
   `test_accepts_wrapped_launcher_and_second_kernel_command_lines` with a wrapped installer line.
   In `test_rejects_reordered_replayed_spoofed_or_failed_evidence`, replace the
   `good.rsplit("\n", 1)[0]` variant with `good.replace("\nkexec-exec: started", "")` so it still
   drops that marker rather than the new last line.
3. Add `test_requires_one_exact_installer_kickstart_label`: for each variant — installer line
   removed; `inst.ks` argument removed; different label; different path; argument repeated;
   extra `ks=cdrom:/ks.cfg`; installer line moved before `kexec-exec: started`; a second installer
   command line appended non-contiguously; a final installer fragment ending in a backslash; two
   adjacent unwrapped installer lines — assert `ValidationError` and that neither `self.digest`
   nor the label appears in the message. The `inst.ks` variants match `installer Kickstart
   evidence`; the others match `installer kernel command line`. Add one assertion that a log
   without the launcher line raises `one contiguous launcher kernel command line`. Add the two
   Fedora rejection tests (rewrite the console with a different label, refresh the console digest
   in the record). Run; expect red.
4. In `scripts/iso_chain.py`, rename `_launcher_command_line` to `_kernel_command_line` with the
   signature above: iterate `range(first, end)`; select a line when `prefixes is None` or an
   argument starts with one of `prefixes`; format messages with `subject`. Update the launcher call
   to `_kernel_command_line(lines, 0, start, ("iso_chain.", "ipv6.", "rd.systemd.unit="),
   "launcher")`.
5. In `verify_launcher_log`, keep the computed digest in `digest`, and after the final marker loop:

   ```python
   _, installer = _kernel_command_line(lines, launcher_end, len(lines), None, "installer")
   kickstart = manifest.profile(expected_profile).kickstart.path
   expected_kickstart = f"inst.ks=cdrom:LABEL={_volume_id(digest)}:{kickstart}"
   if [a for a in installer if a.split("=", 1)[0] in ("inst.ks", "ks")] != [expected_kickstart]:
       raise ValidationError("installer Kickstart evidence is missing, repeated, or different")
   ```

6. Run both focused commands; expect `OK`. Run `just check`; expect exit 0. Commit
   `fix: require installer evidence to bind the inst.ks volume label`.

Acceptance: spec Success 1–4 each map to a variant above; launcher messages unchanged.
