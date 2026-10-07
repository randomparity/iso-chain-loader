# FTP Source Checks Implementation Plan

Goal: `validate-external-source` checks an `ftp://` source's pinned artifacts, and the evidence
verifiers are proved to accept FTP handoff URLs without echoing the credential. Spec:
`docs/workflow/specs/2026-10-07-ftp-source-checks-design.md`.

Architecture: `_external_opener(source)` picks the opener per scheme; tests mock
`urllib.request.ftpwrapper`, which `FTPHandler.connect_ftp` constructs.
Tech stack: Python 3.14 stdlib (`urllib.request`, `ftplib` in tests), `unittest`.

Expected implementation size: 120–160 changed lines (S) — about 25 Python, 110 test, 10 docs.

## Global Constraints

- Stdlib only in `scripts/`; line length 100; no refusal names any part of the URL.
- detect-secrets flags a literal `scheme://a:b@`; build FTP URLs with `ftp_source()`.
  `.secrets.baseline` covers only `Justfile`.
- Guardrails: `just check-tests`, `just check`.

## File map

- `scripts/iso_chain.py` — `validate_external_source` owner; gains `_external_opener`.
- `tests/test_iso_chain.py` — gains `import contextlib`, `import ftplib`, `DEFAULT_SOURCE` (read
  by `manifest_data`), `external_manifest(source)` (extracted from `ExternalSourceTests.manifest`),
  `ExternalFTPSourceTests`, the `FTPEvidenceSource` mixin, and eight FTP subclasses.
- `README.md`, `AGENTS.md` — FTP sentence for `validate-external-source`.

## Task 1: FTP branch of `validate-external-source`

Interfaces: `_external_opener(source: str) -> urllib.request.OpenerDirector` (new);
`validate_external_source(manifest, profile_name, timeout_seconds)` unchanged.

Verification:

- Mode: focused-test. Contract: success criteria 1–3 of the spec. Test:
  `ExternalFTPSourceTests`. Red: `external source returned a non-200 response` on the success
  cases, the proxy case connecting to the proxy, the UTF-8 case reaching the fake.
  Green: `.venv/bin/python -m unittest -v tests.test_iso_chain.ExternalFTPSourceTests`.

Steps:

1. Extract `external_manifest(source)` returning `ExternalSourceTests.manifest`'s manifest for
   `source`; `ExternalSourceTests.manifest` returns `external_manifest(f"http://127.0.0.1:{port}")`.
2. Write `ExternalFTPSourceTests`: `setUp` patches `urllib.request.ftpwrapper` with a fake class
   (`keepalive = False`; `__init__(self, user, passwd, host, port, dirs, timeout, persistent=True)`
   records the first six and keeps `dirs`; `retrfile(self, file, type)` returns
   `(io.BytesIO(data), len(data))` for `data = files[(tuple(dirs), file)]`; `close(self)` does
   nothing), and patches `socket.gethostbyname` to return `192.0.2.1`. Source:
   `ftp_source("fake-user:fake%2Fpass", "mirror.example:2121/pub")`. Cases: Fedora and Ubuntu
   success (user `fake-user`, password `fake/pass`, dirs relative to login, timeout 5); proxy
   bypass under `mock.patch.dict(os.environ, {"ftp_proxy": "http://127.0.0.1:9"})`; login
   `ftplib.error_perm("530 Login incorrect")` raised by the fake's constructor; a short read
   (one byte fewer); oversize; digest mismatch;
   `ftp_source("fake-user:fake%FF")` refused with no fake constructed; and `main` under
   `sys.argv` with `contextlib.redirect_stdout`/`redirect_stderr` asserting neither output holds
   `fake`.
3. Run the green command; expect the red failures above.
4. Implement in `scripts/iso_chain.py`:

   ```python
   def _external_opener(source: str) -> urllib.request.OpenerDirector:
       if not source.startswith("ftp://"):
           return urllib.request.build_opener(_NoRedirectHandler)
       # urllib decodes FTP userinfo escapes as UTF-8 with replacement; ftplib sends UTF-8.
       try:
           unquote_to_bytes(source.removeprefix("ftp://").partition("@")[0]).decode("utf-8")
       except UnicodeDecodeError:
           message = "ftp:// userinfo escapes must decode as UTF-8 to check the source"
           raise ValidationError(message) from None
       # An ftp_proxy would receive the credential over plain HTTP; FTP connects directly.
       return urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirectHandler)
   ```

   In `validate_external_source`: `opener = _external_opener(manifest.source)`;
   `ftp = manifest.source.startswith("ftp://")`; `if not ftp and response.status != 200:`.
5. Run the green command; expect `OK`. Run `just check-tests`; expect exit 0. Commit
   `feat: check ftp:// sources in validate-external-source`.

## Task 2: Verifiers under an FTP source

Interfaces: `DEFAULT_SOURCE = "http://10.0.2.2:8000"` read by `manifest_data`;
`FTP_EVIDENCE_SOURCE = ftp_source(location="10.0.2.2:2121/pub")`.

Verification:

- Mode: focused-test. Contract: success criterion 4. Test: `FTP*EvidenceTests`. Green on
  arrival; bite: temporarily append `manifest.source` to `verify_launcher_log`'s `kernel
  configuration or profile evidence does not match` message, see the mixin's no-echo assertion
  fail, revert. Green: `.venv/bin/python -m unittest tests.test_iso_chain -k FTP`.

Steps:

1. `manifest_data` uses `"source": DEFAULT_SOURCE`.
2. Add the mixin:

   ```python
   class FTPEvidenceSource:
       """Re-run an evidence class with an FTP source; no refusal names its credential."""

       def setUp(self):
           self.enterContext(mock.patch(f"{__name__}.DEFAULT_SOURCE", FTP_EVIDENCE_SOURCE))
           super().setUp()

       def test_runs_with_an_ftp_source(self):
           self.assertEqual(manifest_data()["source"], FTP_EVIDENCE_SOURCE)

       def assertRaises(self, *args, **kwargs):
           return self._without_credential(super().assertRaises(*args, **kwargs))

       def assertRaisesRegex(self, *args, **kwargs):
           return self._without_credential(super().assertRaisesRegex(*args, **kwargs))

       @contextlib.contextmanager
       def _without_credential(self, context):
           with context as caught:
               yield caught
           for part in FTP_USERINFO.split(":"):
               self.assertNotIn(part, str(caught.exception))
   ```

   and `class FTP<Name>(FTPEvidenceSource, <Name>): pass` for each of the eight classes.
3. Check the callable form is unused in those classes:
   `rg -n "assertRaises(Regex)?\(iso_chain\.ValidationError, [^)]*, " tests/test_iso_chain.py`
   expects no hit inside them.
4. Run the green command, do the bite, run `just check-tests`. Commit
   `test: hold the evidence verifiers under an ftp:// source`.

## Task 3: Docs

Verification: Mode: task-test-not-applicable. Surface: README and AGENTS.md prose; no executable
consumer reads either.

1. README: replace "It does not support an `ftp://` `source` until #69 ... naming the URL." with
   the FTP behaviour: logs in with the decoded user and password, ignores proxy variables, needs
   escapes that decode as UTF-8, and checks the same size and SHA-256; no message names the URL.
2. AGENTS.md: remove "#69 owns `validate-external-source` and the verifiers,"; update the
   test-class count; add the `urllib.request.ftpwrapper` seam to the Mocking bullet.
3. `just check`; expect exit 0. Commit `docs: describe ftp:// checks in validate-external-source`.
