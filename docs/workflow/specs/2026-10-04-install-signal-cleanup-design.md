# Install Signal Cleanup Design

Issue: #50. No ADR: the change applies the existing context-manager cleanup to two more exits and
adopts the shell's `128 + signal` exit convention; it sets no new public contract.

## Problem

`install-fedora`, `install-rocky`, and `install-ubuntu` stage their result in a private
`.iso-chain-install-*` directory from `tempfile.TemporaryDirectory`, which is removed only when
Python unwinds normally or through an exception. The CLI installs no signal handler, so SIGHUP or
SIGTERM kills the interpreter at once: the staging directory, its multi-gigabyte `disk.qcow2`, and
any running `qemu-system-ppc64` survive, and QEMU keeps writing to an orphaned disk.

## Scope

In scope:

- `Terminated(BaseException)` carrying `signum`, raised by a handler that the context manager
  `_terminating_signals()` installs for SIGHUP and SIGTERM and restores on exit. A signal the
  process inherited as ignored (`nohup`) keeps its ignore and is not translated. On its first
  call the handler sets both signals to `SIG_IGN`, then raises, so a second signal cannot abort
  the unwinding cleanup. It derives from `BaseException`, as `KeyboardInterrupt` does, so no
  `except Exception` or `except OSError` clause on the install path can swallow it.
- `main()` runs only the three install commands inside `_terminating_signals()`. It catches
  `Terminated`, prints `error: interrupted by <SIGNAME>` to stderr, and returns `128 + signum`
  (129 for SIGHUP, 143 for SIGTERM).
- `_stop_process(process) -> int` terminates a process, waits 10 seconds, then kills and reaps
  it; `_run_qemu_phase` uses it on its existing stop path and in its `finally`, which now stops a
  QEMU that is still running and joins the reader threads (10 seconds each) before unlinking the
  FIFO. `TemporaryDirectory` then removes staging after QEMU is reaped and no reader writes into
  it. This `finally` runs for every exception, `KeyboardInterrupt` included; SIGINT's disposition
  is unchanged.
- `qemu-img` needs no change: `subprocess.run` kills and reaps its child on any exception.
- README: the signal behaviour and the manual removal of `.iso-chain-install-*` directories that
  SIGKILL or a crash leaves, in the unattended installation proof section.

Out of scope (approved exclusions): SIGINT behaviour; signal handling for any other command;
SIGKILL or crash cleanup; HMC/VIOS orchestration (#6).

Alternatives considered:

- **Clean up inside the signal handler.** judgment: the handler would need the staging path and
  QEMU handle as globals and would race the main thread's own teardown.
- **Raise `SystemExit(128 + signum)`.** judgment: equivalent unwinding, but `main()` could not
  print the actionable message, and in-process tests would see the interpreter's exit path.
- **Re-deliver the signal with `SIG_DFL` after cleanup.** judgment: callers then observe a
  signal death rather than an exit status; `main()` returns an integer everywhere else.

## Failure model

1. Actors and deployments:
   - a local operator, or a supervising script, on the Linux or macOS host running an install
     command under QEMU; the signal comes from that operator, a closing terminal, or a supervisor.
     An operator who started the command with a signal ignored (`nohup`) keeps that choice.
2. Invariants and assets at stake:
   - a published install result (`--output`) is never removed: `_publish_install` renames the
     staged directory out of the temporary root, so a later unwinding removes only the empty root.
   - QEMU is reaped before staging removal, so no process writes the disk after cleanup.
   - private evidence stays in the 0700 staging directory until it is removed.
3. Accepted failure classes:
   - a signal after publication still exits `128 + signum` with the result in place; the result
     is complete and verified, and the message names the signal.
   - a signal inside the few bytecodes between `Popen` returning and the process being recorded,
     or inside `Popen`'s own fork and exec, can orphan that one QEMU; the window is a few
     instructions per phase.
   - a signal before QEMU opens its capture FIFO leaves the capture reader blocked in `open`;
     cleanup waits its 10-second join, then removes staging; the daemon thread ends with the
     process.
   - a first signal that lands while `TemporaryDirectory` is already removing staging after
     another error interrupts that removal; the window is the length of one `rmtree`.
4. Covered elsewhere:
   - SIGINT, SIGKILL, crashes, and non-install commands: the approved exclusions.
   - removal of `.iso-chain-install-*` directories SIGKILL or a crash left: the README note this
     change adds.

## Success

1. SIGHUP or SIGTERM delivered to `install-fedora` while QEMU runs leaves no
   `.iso-chain-install-*` directory and no output in the output parent, leaves the fake QEMU
   process gone, prints `error: interrupted by <SIGNAME>`, and exits `128 + signum`.
2. SIGTERM delivered while `qemu-img` runs leaves no staging directory and no live `qemu-img`.
3. A `Terminated` raised immediately after `_publish_directory` leaves the published output with
   its `result.json`.
4. After the first terminating signal, both signals are ignored until `_terminating_signals()`
   exits, and the prior handlers are restored on exit; a signal ignored on entry stays ignored.
5. `main()` translates the signals for `install-fedora`, `install-rocky`, and `install-ubuntu`
   and for no other command.
6. Every existing test passes; the only edit to one moves the successful-install test's fakes
   into shared `InstallTests` methods with identical bodies.

## Validation

- Success 1 and 2: `InstallTests` runs the real CLI in a child Python (with
  `MAX_INSTALL_CAPTURE_BYTES` lowered so the capacity check fits any host, and SIGHUP and SIGTERM
  reset to their defaults so the runner's own dispositions cannot decide the result) against fake
  `qemu-img` and `qemu-system-ppc64` on `PATH`; each fake records its PID and blocks. The test
  signals the CLI, then asserts the exit status, stderr, the parent's listing, and that
  `os.kill(pid, 0)` raises `ProcessLookupError`.
- Success 3: `InstallTests` drives `install_fedora` with the existing mocks and a
  `_publish_directory` wrapper that publishes, then raises `Terminated`.
- Success 4: an in-process test raises SIGHUP with `signal.raise_signal` inside
  `_terminating_signals()`, then repeats with SIGHUP ignored on entry.
- Success 5: an in-process test patches each command's function and records the SIGTERM handler
  `main()` installed.
- Success 6: `just check-tests`.
