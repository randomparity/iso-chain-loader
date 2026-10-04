# Install Signal Cleanup Implementation Plan

Goal: SIGHUP or SIGTERM ends `install-fedora`, `install-rocky`, or `install-ubuntu` with QEMU
reaped, the `.iso-chain-install-*` staging removed, and exit `128 + signum`. Spec:
`docs/workflow/specs/2026-10-04-install-signal-cleanup-design.md`; issue #50.

Architecture: `main()` wraps the three install commands in `_terminating_signals()`, whose handler
ignores further SIGHUP/SIGTERM and raises `Terminated(BaseException)`; the existing
`TemporaryDirectory` context managers unwind. `_run_qemu_phase`'s `finally` reaps a running QEMU
and joins its reader threads before that unwinding reaches staging removal.

Tech stack: Python 3.14 standard library, `unittest`.

Expected implementation size: 190–240 changed lines (M) — about 50 Python lines in
`scripts/iso_chain.py`, 170 test lines, and 4 README lines across the two tasks below.

## Global Constraints

- Standard library only in `scripts/`; ruff line length 100; annotate every function.
- Only the three install commands change signal disposition, and never one the process inherited
  as ignored (`nohup`). SIGINT's disposition is untouched; the `_run_qemu_phase` `finally` reap
  applies to every exception, `KeyboardInterrupt` included.
- Guardrails: `just check-tests`, `just check`, `git diff --check main...HEAD`.

## Task 1: Translate SIGHUP and SIGTERM for install commands

Files: modify `scripts/iso_chain.py`, `tests/test_iso_chain.py` (`InstallTests`).

Interfaces: produces `iso_chain.Terminated(signum: int)` with attribute `signum`, and
`iso_chain._terminating_signals()`, a context manager; Task 2's test relies on `main()` returning
`128 + signum` and printing `error: interrupted by SIGTERM` / `SIGHUP`.

Verification:

- Contract: handler raises once, then ignores, restores on exit, and keeps an inherited ignore.
  Mode: focused-test. `InstallTests.test_terminating_signals_raise_once_and_keep_an_ignore`; red:
  `AttributeError: ... no attribute '_terminating_signals'`; green:
  `.venv/bin/python -m unittest -v tests.test_iso_chain.InstallTests`.
- Contract: a published result survives a signal after publication. Mode: focused-test.
  `InstallTests.test_signal_after_publication_keeps_the_published_result`; red:
  `AttributeError: ... no attribute 'Terminated'`; green: the same command.
- Contract: `main()` translates for the three install commands only. Mode: focused-test.
  `InstallTests.test_main_translates_signals_only_for_install_commands`; red: `AttributeError: ...
  no attribute '_raise_terminated'`; green: the same command.

Steps:

1. Add `import signal` to the test imports. In `InstallTests`, move the `create_disk` and
   `phase` closures of `test_successful_install_publishes_fresh_disk_logs_capture_and_result`
   into methods `fake_disk(self, command, **kwargs)` and
   `fake_phase(self, command, log, timeout, capture_fifo=None, capture=None)` with identical
   bodies, and patch with `side_effect=self.fake_disk` / `self.fake_phase`. Add:

   ```python
   def test_terminating_signals_raise_once_and_keep_an_ignore(self):
       names = (signal.SIGHUP, signal.SIGTERM)
       for name in names:
           self.addCleanup(signal.signal, name, signal.signal(name, signal.SIG_DFL))
       with iso_chain._terminating_signals():
           with self.assertRaises(iso_chain.Terminated) as raised:
               signal.raise_signal(signal.SIGHUP)
           self.assertEqual(raised.exception.signum, signal.SIGHUP)
           self.assertEqual([signal.getsignal(name) for name in names], [signal.SIG_IGN] * 2)
       self.assertEqual([signal.getsignal(name) for name in names], [signal.SIG_DFL] * 2)
       signal.signal(signal.SIGHUP, signal.SIG_IGN)
       with iso_chain._terminating_signals():
           self.assertIs(signal.getsignal(signal.SIGHUP), signal.SIG_IGN)
           self.assertIs(signal.getsignal(signal.SIGTERM), iso_chain._raise_terminated)
       self.assertIs(signal.getsignal(signal.SIGHUP), signal.SIG_IGN)


   def test_main_translates_signals_only_for_install_commands(self):
       for name in (signal.SIGHUP, signal.SIGTERM):
           self.addCleanup(signal.signal, name, signal.signal(name, signal.SIG_DFL))
       paths = ["--iso", str(self.iso), "--config", str(self.config), "--output", "out"]
       for command, function, arguments, translated in (
           ("install-fedora", "install_fedora", paths, True),
           ("install-rocky", "install_rocky", paths, True),
           ("install-ubuntu", "install_ubuntu", paths, True),
           ("verify-pcap", "verify_pcap", [str(self.iso)], False),
       ):
           seen = []

           def record(*_):
               seen.append(signal.getsignal(signal.SIGTERM))
               return "ok"

           with (
               self.subTest(command=command),
               mock.patch.object(iso_chain, function, side_effect=record),
               mock.patch.object(sys, "argv", ["iso_chain", command, *arguments]),
               mock.patch("sys.stdout"),
           ):
               self.assertEqual(iso_chain.main(), 0)
               self.assertEqual(seen == [iso_chain._raise_terminated], translated)


   def test_signal_after_publication_keeps_the_published_result(self):
       publish = iso_chain._publish_directory

       def publish_then_signal(source, destination):
           publish(source, destination)
           raise iso_chain.Terminated(signal.SIGTERM)

       with (
           mock.patch("scripts.iso_chain.subprocess.run", side_effect=self.fake_disk),
           mock.patch("scripts.iso_chain._run_qemu_phase", side_effect=self.fake_phase),
           mock.patch("scripts.iso_chain._publish_directory", side_effect=publish_then_signal),
           self.assertRaises(iso_chain.Terminated),
       ):
           iso_chain.install_fedora(self.args())
       self.assertTrue((self.output / "result.json").is_file())
       self.assertEqual(list(self.root.glob(".iso-chain-install-*")), [])
   ```

2. Run the green command; expect the first two new tests to error with the stated
   `AttributeError` and the third to fail as stated.
3. In `scripts/iso_chain.py` add `import contextlib`, `import signal`, and
   `from collections.abc import Iterator`. After `ValidationError`, add:

   ```python
   class Terminated(BaseException):
       """SIGHUP or SIGTERM ended an install command; context managers unwind on the way out."""

       def __init__(self, signum: int) -> None:
           super().__init__(signum)
           self.signum = signum
   ```

   Before `main()`, add:

   ```python
   TERMINATING_SIGNALS = (signal.SIGHUP, signal.SIGTERM)


   def _raise_terminated(signum: int, frame: object) -> None:
       for name in TERMINATING_SIGNALS:
           signal.signal(name, signal.SIG_IGN)
       raise Terminated(signum)


   @contextlib.contextmanager
   def _terminating_signals() -> Iterator[None]:
       """Turn the first SIGHUP or SIGTERM into ``Terminated``; keep a signal already ignored."""
       previous = [
           (name, signal.signal(name, _raise_terminated))
           for name in TERMINATING_SIGNALS
           if signal.getsignal(name) is not signal.SIG_IGN
       ]
       try:
           yield
       finally:
           for name, handler in previous:
               signal.signal(name, handler)
   ```

   In `main()`, wrap each of `install_fedora(args)`, `install_rocky(args)`, and
   `install_ubuntu(args)` as `with _terminating_signals():` plus the call, and add before
   `except ValidationError`:

   ```python
   except Terminated as error:
       print(f"error: interrupted by {signal.Signals(error.signum).name}", file=sys.stderr)
       return 128 + error.signum
   ```

4. Run the green command; expect `OK`. Run `just check`; expect exit 0. Commit
   `fix: translate SIGHUP and SIGTERM in install commands`.

Acceptance: the three tests pass.

## Task 2: Reap QEMU before staging removal, and prove it end to end

Files: modify `scripts/iso_chain.py` (`_run_qemu_phase`), `tests/test_iso_chain.py`
(`InstallTests`), `README.md`.

Interfaces: consumes Task 1's `main()` exit status and stderr; produces
`_stop_process(process: subprocess.Popen) -> int`.

Verification:

- Contract: a signalled install reaps QEMU and `qemu-img`, removes staging, exits `128 + signum`.
  Mode: focused-test. `InstallTests.test_signalled_install_stops_children_and_removes_staging`;
  red: the `qemu-system-ppc64` subtests fail at `assertRaises(ProcessLookupError)` because the
  fake QEMU outlives the CLI; green: `.venv/bin/python -m unittest -v
  tests.test_iso_chain.InstallTests`.
- Contract: README operator note. Mode: task-test-not-applicable — prose with no executable
  consumer; `just check-markdown` covers its form only.

Steps:

1. Add module constants to `tests/test_iso_chain.py` after `KEY`:

   ```python
   REPOSITORY = Path(__file__).resolve().parents[1]
   INTERRUPTIBLE_CLI = (
       "import signal, sys; from scripts import iso_chain; iso_chain.MAX_INSTALL_CAPTURE_BYTES = 1; "
       "signal.signal(signal.SIGHUP, signal.SIG_DFL); signal.signal(signal.SIGTERM, signal.SIG_DFL); "
       "raise SystemExit(iso_chain.main())"
   )
   FAKE_INSTALL_TOOL = """#!{python}
   import os, pathlib, sys, time
   name = pathlib.Path(sys.argv[0]).name
   if name == "qemu-img" and os.environ["FAKE_HANG"] != name:
       pathlib.Path(sys.argv[4]).write_bytes(b"fresh")
       sys.exit(0)
   for value in sys.argv:
       if value.startswith("filter-dump,"):
           capture = open(value.rsplit("file=", 1)[1], "wb")
   pid = pathlib.Path(os.environ["FAKE_PIDS"], name + ".tmp")
   pid.write_text(str(os.getpid()))
   pid.replace(pid.with_suffix(""))
   time.sleep(60)
   """
   ```

   In `InstallTests` add:

   ```python
   def test_signalled_install_stops_children_and_removes_staging(self):
       tools, pids = self.root / "tools", self.root / "pids"
       tools.mkdir()
       pids.mkdir()
       for name in ("qemu-img", "qemu-system-ppc64"):
           (tools / name).write_text(FAKE_INSTALL_TOOL.format(python=sys.executable))
           (tools / name).chmod(0o755)
       for hang, signum in (
           ("qemu-system-ppc64", signal.SIGTERM),
           ("qemu-system-ppc64", signal.SIGHUP),
           ("qemu-img", signal.SIGTERM),
       ):
           with self.subTest(hang=hang, signum=signum):
               pid_file = pids / hang
               pid_file.unlink(missing_ok=True)
               environment = dict(
                   os.environ,
                   PATH=f"{tools}{os.pathsep}{os.environ['PATH']}",
                   FAKE_HANG=hang,
                   FAKE_PIDS=str(pids),
               )
               cli = subprocess.Popen(
                   [
                       sys.executable,
                       "-c",
                       INTERRUPTIBLE_CLI,
                       "install-fedora",
                       "--iso",
                       str(self.iso),
                       "--config",
                       str(self.config),
                       "--output",
                       str(self.output),
                       "--disk-size-gib",
                       "20",
                       "--memory-mib",
                       "4096",
                       "--install-timeout-seconds",
                       "60",
                       "--boot-timeout-seconds",
                       "60",
                   ],
                   cwd=REPOSITORY,
                   env=environment,
                   stderr=subprocess.PIPE,
                   text=True,
               )
               self.addCleanup(cli.communicate)
               self.addCleanup(cli.kill)
               deadline = time.monotonic() + 30
               while not pid_file.exists() and time.monotonic() < deadline:
                   if cli.poll() is not None:
                       self.fail(f"install exited early: {cli.communicate()[1]}")
                   time.sleep(0.05)
               child = int(pid_file.read_text())
               os.kill(cli.pid, signum)
               _, stderr = cli.communicate(timeout=60)
               self.assertEqual(cli.returncode, 128 + signum)
               self.assertIn(f"error: interrupted by {signal.Signals(signum).name}", stderr)
               self.assertEqual(list(self.root.glob(".iso-chain-install-*")), [])
               self.assertFalse(self.output.exists())
               with self.assertRaises(ProcessLookupError):
                   os.kill(child, 0)
                   os.kill(child, signal.SIGKILL)
   ```

   Run `ruff format` on the file so the argument list matches the project layout.
2. Run the green command; expect the two `qemu-system-ppc64` subtests to fail as stated and the
   `qemu-img` subtest to pass (`subprocess.run` already reaps it).
3. In `scripts/iso_chain.py`, before `_run_qemu_phase`, add:

   ```python
   def _stop_process(process: subprocess.Popen) -> int:
       """Terminate ``process``, kill it after 10 seconds, and return its reaped status."""
       process.terminate()
       try:
           return process.wait(timeout=10)
       except subprocess.TimeoutExpired:
           process.kill()
           return process.wait()
   ```

   In `_run_qemu_phase`, replace the `if status is None:` block's body with
   `status = _stop_process(process)`, and replace the `finally` body with:

   ```python
   finally:
       # A signal can unwind through here while QEMU runs; reap it and the readers before
       # TemporaryDirectory removes the staging they write into.
       if process_box and process_box[0].poll() is None:
           _stop_process(process_box[0])
       for thread in threads:
           thread.join(timeout=10)
       if capture_fifo is not None:
           capture_fifo.unlink(missing_ok=True)
   ```

4. Run the green command; expect `OK`.
5. README, end of the paragraph beginning "`install-fedora` is separate from": add "SIGHUP or
   SIGTERM stops a running install command's QEMU, removes its private staging directory, and
   exits with 128 plus the signal number, unless the command started with that signal ignored
   (`nohup`); a result already published stays. After SIGKILL or a crash, delete any
   `.iso-chain-install-*` directory left in the output parent."
6. Run `just check-tests` and `just check`; expect exit 0. Commit
   `fix: reap QEMU before install staging removal on a signal`.

Acceptance: spec Success 1, 2, and 6 hold; the README sentence is present.
