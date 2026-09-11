# ADR 0010: Portable No-Replace Directory Publication

## Status

Accepted

## Context

`_publish_directory` publishes a prepared Fedora source tree and an installed disk directory by
calling libc `renameat2(..., RENAME_NOREPLACE)` through ctypes, and maps `EEXIST` to "output
appeared during ...". `renameat2` is Linux-only: on macOS the symbol is absent, so every call fails
closed with "no-replace directory publication is unsupported". macOS host support has to decide what
this primitive does there.

## Decision

Add a Darwin branch that calls `renamex_np(from, to, RENAME_EXCL)`, the flag value `0x4`, from the
same ctypes shim and under the same error mapping: `EEXIST` keeps its "output appeared" message, and
`ENOSYS` and `EINVAL` keep the unsupported message. Linux keeps `renameat2`. The guarantee is
unchanged on every host: publication never replaces an existing destination.

## Consequences

- The primitive keeps one semantic on every supported host, so the behavior the focused tests
  observe is the behavior production gets.
- `renamex_np` exists from macOS 10.12, well below the interpreter floor the project already
  requires, so no runtime capability probe is added.
- The Linux path is untouched, so this decision re-verifies no Linux behavior.

## Considered & rejected

- **Skip the publication tests on Darwin.** judgment: it leaves a supported host's primitive
  unexercised and converts a real runtime limitation into an invisible test skip.
- **Check for the destination and then call `os.rename`.** judgment: it reintroduces exactly the
  check-then-act race the primitive exists to close.
- **Publish by hard-linking the tree.** verified: `ln /tmp /tmp/lnprobe` reports
  `hard link not allowed for directory` (macOS 26, 2026-09-11); directories cannot be hard-linked.
- **Keep the Darwin path raising the unsupported error and document the limitation.** judgment: it
  is the same outcome as a skipped test with a louder failure, and the primitive is small enough to
  support properly.
