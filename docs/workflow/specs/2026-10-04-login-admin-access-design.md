# Login User Administrative Access Design

Issue: #48. Decision: [ADR 0023](../../adr/0023-grant-the-login-user-no-administrative-access.md),
settling the question ADR 0019 left open and ADR 0020 matched.

## Problem

Keyed Rocky and Ubuntu media create the manifest's login user with keys, no password, and no
group, and keep root locked. No accepted decision says whether that is the intended end state,
and no test stops the Rocky Kickstart template from adding a grant.

## Scope

- **Decision.** ADR 0023: built media grants the login user no administrative access. The
  consumer evidence is hmc-mcp ADR 0191 Decision 7: hmcpctl never uses the keys or login user and
  ends at `boot_started`.
- **Tests.** One `RockyKickstartTests` case and one `UbuntuUserDataTests` case assert the rendered
  answers grant nothing. The Ubuntu `sudo` and `groups` exclusions move from
  `test_rendering_names_no_device_and_no_launcher_failure_text` into the new Ubuntu case.
- **Documents.** A Status note on ADR 0019 and ADR 0020 pointing to ADR 0023, README's two
  login-user bullets, and AGENTS.md's ADR count and list.
- No change to `scripts/iso_chain.py`, `assets/kickstart/rocky-9.8-unattended.ks`, or
  `assets/autoinstall/ubuntu-26.04.1.json`, and no experiment record: the rendered media is
  unchanged and both QEMU records already observed the installed account.

## Failure model

1. **Actors and deployments**
   - A local operator running `build` on a Linux or macOS host.
   - hmcpctl's built mode booting keyed Rocky or Ubuntu media on a PowerVM partition
     (hmc-mcp ADR 0191).
   - A holder of a manifest SSH key logging in to an installed guest.
2. **Invariants and assets at stake**
   - The rendered Rocky Kickstart and Ubuntu user data give the login user no group, no password,
     no sudoers rule, and keep root locked.
   - Keyed media digests stay unchanged by this change.
3. **Accepted failure classes**
   - The installed guest has no remote administrative path; the consumer contract leaves guest
     use to the user (ADR 0023 Consequences).
   - A grant written outside the rendered answers, such as a distribution default applied after
     first boot, is not observable by these tests; both QEMU sessions observed none.
4. **Covered elsewhere**
   - Root password and root SSH: out of scope by operator decision.
   - Credential carriage in manifests: ADR 0017; FTP credentials: #37.
   - Fedora and openSUSE profiles, and post-install configuration management: out of scope by
     operator decision.

## Success

1. The rendered keyed Rocky Kickstart's only `user` command is `user --name=<login_user>`, its
   only `rootpw` command is `rootpw --lock`, and it contains none of `wheel`, `sudo`, `admin`,
   `usermod`, `gpasswd`, `--groups`, `--password`, or `--iscrypted`.
2. The rendered keyed Ubuntu user data's `user-data.users` is one entry with exactly the keys
   `name`, `lock_passwd` (true), `shell`, and `ssh_authorized_keys`; `disable_root` is true; the
   autoinstall has no `identity`; and the rendered text contains none of `wheel`, `sudo`, `admin`,
   `usermod`, `gpasswd`, `groups`, or `chpasswd`.
3. ADR 0023 is accepted, and ADR 0019 and ADR 0020 carry a Status note pointing to it.

## Validation

- **Rocky no-grant (Success 1).** Mode: focused-test.
  `RockyKickstartTests.test_grants_the_login_user_no_administrative_access`. Red: a temporary
  `--groups=wheel` on the rendered `user` line fails it; reverted.
- **Ubuntu no-grant (Success 2).** Mode: focused-test.
  `UbuntuUserDataTests.test_grants_the_login_user_no_administrative_access`. Red: a temporary
  `"groups": "sudo"` in the rendered user entry fails it; reverted.
- **Documents (Success 3).** Mode: task-test-not-applicable; ADR and README prose has no
  executable consumer, and `just check`'s Markdown lint holds its form.
