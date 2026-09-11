---
title: Subprocess evidence stayed empty until the child exited
date: 2026-09-10
tags: [python-buffering, subprocess, evidence-capture]
components: [scripts/iso_chain.py, tests/test_iso_chain.py]
---

## Problem

During a long-running QEMU installation, `install-console.log` stayed at zero bytes even after the
guest had made authenticated HTTP requests. Diagnostics were therefore unavailable until the guest
exited, defeating the purpose of retaining bounded live evidence.

## Root cause

The copy loop crossed two buffering layers. `subprocess.Popen.stdout` is a `BufferedReader`, and
`read(65536)` can wait for the requested byte count or EOF instead of returning the bytes currently
available from a live pipe. After replacing it with `read1(65536)`, the destination created by
`Path.open("xb")` still buffered short writes, so a small diagnostic stream remained invisible on
disk until that file closed.

## Solution

`_copy_bounded_stream` in `scripts/iso_chain.py` now uses `read1` when the source provides it, falls
back to `read` for the raw capture FIFO, and opens the destination with `buffering=0`. The byte limit
and no-replace creation behavior are unchanged.

Two regression tests in `tests/test_iso_chain.py` distinguish the source and destination layers.
One supplies bytes only through `read1`; the other holds the source open and requires the first
block to be visible on disk before EOF. Each test failed against its unfixed layer. `just check`
then passed, and a fresh live guest exposed 1,930 console bytes while QEMU was still
running.

## Prevention

Any bounded collector for a long-lived pipe must test observability before EOF, not only final file
contents after the producer exits. Keep source-read and destination-flush behavior as separate
regression cases so either buffering layer can fail independently.
