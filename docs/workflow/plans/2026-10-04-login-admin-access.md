# Login User Administrative Access Implementation Plan

Goal: record that keyed Rocky and Ubuntu media grant the login user no administrative access, and
hold it with tests. Spec: `docs/workflow/specs/2026-10-04-login-admin-access-design.md`;
ADR 0023.

Architecture: no rendering change. `_rocky_kickstart` and `_ubuntu_user_data` already render a
user with no group or password; two unit tests pin that, and the ADRs and README cite ADR 0023.

Tech stack: Python 3.14 standard library, `unittest`.

Expected implementation size: 40–60 changed lines (M) — about 35 unit-test lines and 15 README,
AGENTS.md, and ADR status-note lines in the one task below; the design artifacts are excluded.
The frozen M band came from triage before the decision; the no-grant outcome is smaller.

## Global Constraints

- Standard library only in `scripts/`; ruff line length 100; rumdl line length 100.
- `just check` and `just check-tests` stay green; `.secrets.baseline` covers only `Justfile`, so
  no line-number refresh is needed.
- `scripts/iso_chain.py` and both install-answer assets are not edited; no ISO digest changes.
- Merged ADRs 0019 and 0020 gain only a Status note.

## File map

- `tests/test_iso_chain.py` — `RockyKickstartTests` and `UbuntuUserDataTests` gain one case each;
  `UbuntuUserDataTests.test_rendering_names_no_device_and_no_launcher_failure_text` drops
  `"sudo"` and `"groups"` from its forbidden tuple, which the new Ubuntu case owns.
- `docs/adr/0019-*.md`, `docs/adr/0020-*.md` — Status note citing ADR 0023.
- `README.md` — the Rocky and Ubuntu login-user bullets say "no sudo rule or group (ADR 0023)".
- `AGENTS.md` — ADR count "twenty-three accepted, binding ADRs (0001–0023)" and an ADR 0023 entry.

## Task 1: No-grant tests and document pointers

Files: modify `tests/test_iso_chain.py`, `README.md`, `AGENTS.md`, `docs/adr/0019-*.md`,
`docs/adr/0020-*.md`.

Interfaces: consumes `RockyKickstartTests.render(keys=(KEY,), **changes) -> str` (rendered
Kickstart text), `UbuntuUserDataTests.render(keys=(KEY,), **changes) -> bytes`, and
`UbuntuUserDataTests.document(rendered: bytes) -> dict` (the `autoinstall` mapping); all exist
in `tests/test_iso_chain.py`. Provides nothing to later tasks.

### Verification

- **Rocky no-grant.** Mode: focused-test.
  `RockyKickstartTests.test_grants_the_login_user_no_administrative_access`. Red: add
  `--groups=wheel` to the `user` line in `_rocky_kickstart`, observe the failure, revert. Green:
  `.venv/bin/python -m unittest -v
  tests.test_iso_chain.RockyKickstartTests.test_grants_the_login_user_no_administrative_access`.
- **Ubuntu no-grant.** Mode: focused-test.
  `UbuntuUserDataTests.test_grants_the_login_user_no_administrative_access`. Red: add
  `"groups": "sudo"` to the user entry in `_ubuntu_user_data`, observe the failure, revert. Green:
  `.venv/bin/python -m unittest -v
  tests.test_iso_chain.UbuntuUserDataTests.test_grants_the_login_user_no_administrative_access`.
- **Documents.** Mode: task-test-not-applicable; prose with no executable consumer, held by
  `just check`'s Markdown lint.

### Steps

1. Add to `RockyKickstartTests`:

   ```python
   def test_grants_the_login_user_no_administrative_access(self):
       # ADR 0023: the login user gets no group, password, or sudo rule; root stays locked.
       lines = self.render().splitlines()
       commands = [line for line in lines if line.split(" ")[0] in ("user", "rootpw")]
       self.assertEqual(commands, ["user --name=core", "rootpw --lock"])
       rendered = "\n".join(lines)
       grants = ("wheel", "sudo", "admin", "usermod", "gpasswd", "--groups", "--password")
       for grant in (*grants, "--iscrypted"):
           self.assertNotIn(grant, rendered)
   ```

2. Add to `UbuntuUserDataTests`, and drop `"sudo"` and `"groups"` from the forbidden tuple of
   `test_rendering_names_no_device_and_no_launcher_failure_text`:

   ```python
   def test_grants_the_login_user_no_administrative_access(self):
       # ADR 0023: one locked, groupless user with keys only, root disabled, no identity.
       rendered = self.render()
       autoinstall = self.document(rendered)
       [user] = autoinstall["user-data"]["users"]
       self.assertEqual(set(user), {"name", "lock_passwd", "shell", "ssh_authorized_keys"})
       self.assertIs(user["lock_passwd"], True)
       self.assertIs(autoinstall["user-data"]["disable_root"], True)
       self.assertNotIn("identity", autoinstall)
       for grant in ("wheel", "sudo", "admin", "usermod", "gpasswd", "groups", "chpasswd"):
           self.assertNotIn(grant, rendered.decode())
   ```

3. Run both focused commands above; expect `OK`. Make each red fault, expect `FAIL`, revert.
4. Apply the document edits in the file map.
5. Run `just check-tests` and `just check`; expect exit 0. Commit
   `test: hold that keyed media grants the login user nothing`.
