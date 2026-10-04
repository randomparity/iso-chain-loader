# ADR 0023: Grant the Login User No Administrative Access

## Status

Accepted

## Context

Keyed media installs Rocky from a build-derived Kickstart (ADR 0019) and Ubuntu from ISO-root user
data (ADR 0020). Both create the manifest's login user with the manifest's SSH keys, no password,
and no group, and keep root locked. ADR 0019 left open whether that user should get administrative
access. The media's one consumer is hmcpctl's built mode. hmc-mcp ADR 0191 (Decision 7 and
Consequences) ends its provisioning at `boot_started`, makes the keys and login user opaque inputs
it never uses, and holds no guest credential; the hmc-mcp#1215 epic narrows guest readiness and
authenticated SSH to the user's or consumer's concern. Manifests carry no password or other
credential (ADR 0017).

## Decision

- **No grant.** Built media gives the login user no administrative access. On Rocky the rendered
  Kickstart holds one `user --name=<login_user>` line with no `--groups` or password option, and
  `rootpw --lock`. On Ubuntu the user data's one user entry holds only `name`, `lock_passwd: true`,
  `shell`, and `ssh_authorized_keys`, with `disable_root: true` and no `identity` section. Neither
  install answer writes a sudoers rule or adds the user to `wheel`, `sudo`, `admin`, or any other
  group.
- **Tests hold it.** `RockyKickstartTests` and `UbuntuUserDataTests` each assert the rendered
  answers grant nothing, so a later grant has to change a test and this decision together.

## Consequences

- The installed system has key-based login and no remote administrative path. Root is locked and
  the login user has no password, so `sudo` refuses, as both QEMU sessions recorded
  ([Rocky](../experiments/2026-10-02-rocky-unattended-install.md),
  [Ubuntu](../experiments/2026-10-03-ubuntu-unattended-install.md)).
- Administering the guest is left to whoever holds the partition console or can attach new
  media; this decision provides no path itself.
- No rendered install answer changes, so no keyed Rocky or Ubuntu ISO digest changes.
- Granting access later needs a new decision, and a password-bearing grant would also reopen
  ADR 0017's credential-free manifest.

## Considered & rejected

- **Passwordless sudo for the login user.** judgment: fit; no consumer uses the account
  (hmc-mcp ADR 0191), and it would make every key holder root on every installed guest.
- **`wheel` or `sudo` group with no password.** judgment: fit; the distributions' sudo rules for
  those groups ask for the user's password, which the account does not have, so membership would
  grant nothing yet leave a grant one later password change completes.
- **Group membership with a password carried in the manifest.** judgment: fit; ADR 0017 keeps
  credentials out of the manifest, and that carriage is outside this decision.
- **An opt-in manifest field that selects a grant.** judgment: cost; a new manifest field and
  rendering branch that no consumer requests.
- **Do nothing.** judgment: fit; ADR 0019 leaves the question open and no test forbids a Rocky
  grant.
