# Installer Kickstart Label Evidence — Design

Issue: #31. Governing decision: ADR 0011 (Anaconda reads the Kickstart with
`inst.ks=cdrom:LABEL=<volume ID>:<path>`).

## Problem

The launcher passes Anaconda `inst.ks=cdrom:LABEL=<volume ID>:<path>` (`fedora_command_line` in
`assets/dracut/iso-chain-launch.sh`), but `verify_launcher_log` reads only the launcher's own
kernel command line. A console log whose installer took its Kickstart from another device still
passes `verify-launcher-log`, `verify-fedora-evidence`, and `verify-fedora-install-evidence`.

The installer kernel command line is in that console: the launcher appends `console=hvc0` to it,
the kexeced kernel prints `Kernel command line:` like the first kernel, and the 2026-10-01
PowerVM experiment record reports the installer kernel command line from its console.

## Design

`verify_launcher_log` gains one check, so all three verifiers inherit it.

- **Parser.** `_launcher_command_line(lines, end)` becomes
  `_kernel_command_line(lines, first, end, prefixes, subject)`. It keeps the current fragment
  rules: timestamped `Kernel command line:` lines in `lines[first:end]`, selected when an
  argument starts with one of `prefixes` (`None` selects every such line), contiguous, and
  joined where a fragment ends in `\`. Error text names `subject`; the launcher call passes
  `"launcher"`, so its messages are unchanged.
- **Installer region.** After every launcher marker passes, parse the installer command line from
  the line after `kexec-exec: started` to the end of the log with `prefixes=None`. Exactly one
  contiguous command line must appear there.
- **Assertion.** Collect the installer arguments whose key (text before the first `=`) is
  `inst.ks` or Anaconda's legacy alias `ks`. That list must equal
  `[f"inst.ks=cdrom:LABEL={_volume_id(digest)}:{profile.kickstart.path}"]` for the manifest
  digest and the verified profile. Otherwise raise
  `ValidationError("installer Kickstart evidence is missing, repeated, or different")`.
- **No echo.** Neither message contains the digest, label, path, or any log text.

No new CLI surface, output line, or manifest field. `verify-launcher-log` therefore now requires
a log that continues past `kexec-exec: started` into the installer kernel; the README's smoke
procedure already captures the console until the text installer is shown.

Rejected: checking only in the two Fedora verifiers (`verify-launcher-log` would keep passing the
gap); a substring search for the label (would accept it inside another argument or a non-kernel
line).

## Failure model

1. **Actors and deployments**
   - Local operator running the verifiers on console logs from QEMU pSeries or PowerVM runs.
   - The console log is untrusted evidence text.
2. **Invariants and assets**
   - A passing verdict implies Anaconda was told to read the Kickstart from the volume labelled
     with this manifest's digest, at the selected profile's path.
   - Error messages never echo manifest or log values.
3. **Accepted failure classes**
   - A forged log that prints the expected line: the verifiers bind digests of operator-collected
     evidence, not authenticity of the guest, as for every other console check.
   - Anaconda reading a different device despite the argument: the launcher's `blkid` uniqueness
     check and ADR 0011 hold that; the console cannot show it.
4. **Covered elsewhere**
   - Launcher argument construction and volume-ID derivation: #26 / ADR 0011.
   - QEMU end-to-end proof: #27. Live PowerVM proof: #28.

## Success

1. A log with the expected installer argument once, after `kexec-exec: started`, passes all three
   verifiers.
2. A missing `inst.ks`, a different label, a different path, a repeated value, or a second
   Kickstart argument (`ks=`) fails with the Kickstart message above. A missing, non-contiguous,
   or truncated installer command line fails with the parser's installer-subject message.
   Neither message contains the digest or the label.
3. An installer command line that appears only before `kexec-exec: started` fails.
4. A wrapped installer command line is accepted.

## Validation

Focused tests in `EvidenceTests` and `FedoraEvidenceTests`; then `just check`.
