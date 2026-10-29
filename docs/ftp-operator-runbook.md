# FTP-source operator runbook

Use this lifecycle alongside the README's [profile preparation and build sequences](../README.md#choose-a-task)
and [target-bound publication](guides/target-bound-media.md). It implements the
operator mitigations of accepted [ADR 0016](adr/0016-assess-authenticated-ftp-sources.md), as amended
by [ADR 0027](adr/0027-accept-plain-ftp-sources-with-userinfo.md). Account provisioning and VIOS
commands depend on the lab and remain operator procedures; this CLI does not provision accounts,
run an FTP server, detach media or delete VIOS repository objects.

## Before granting access

Obtain the lab owner's **written acceptance of cleartext FTP credentials** for the run's network
and retain it privately. ADR 0027 records the original acceptance by date; do not assume it covers
another lab. `ftp://` is plaintext, including login and installer content. `ftps://` is refused;
there is no FTPS, anonymous FTP or HTTP fallback. An on-path observer can steal the credential or
substitute unpinned installer content while the run is active. Revocation bounds account access,
not installer substitution, and digest checks cover only the artifacts they actually pin.

Start a fresh private run directory outside the checkout, before writing any account material:

```sh
umask 077
PRIVATE=$(mktemp -d)
```

Keep that directory owner-only. Apply equivalent restrictions on every machine collecting or
serving private artifacts; a local umask does not control a remote FTP server, VIOS or HMC.
Record privately the run, account, source tree, media digest, publication path, VIOS object and
mapping, evidence paths and person responsible for revocation. Arrange a cleanup owner who can
revoke access even if the build shell, guest, console session or connection is interrupted.

Using the lab's supported FTP administration procedure:

1. Create a fresh tree containing only the verified release content needed by the selected
   profile. Preserve the distribution guide's signature checks, profile paths and exact pinned bytes.
   Restrict the tree to its operator and serving process; do not expose other runs or private
   manifests, media, account records or evidence through it.
2. Create a unique account for this run, rooted/confined to that tree. Grant only read/list access;
   deny uploads, creation, modification, deletion, rename, traversal outside the tree and unrelated
   login services. Keep the tree unwritable by the account, including its confinement root.
3. Generate a fresh high-entropy password. For the proven path, use unreserved URL characters
   (`A-Z`, `a-z`, digits, `.`, `_`, `~`, `-`) and a printable ASCII username without whitespace.
   Keep the encoded `user:password` within 128 bytes. The CLI admits canonical percent-escapes,
   but installer interoperability with escaped userinfo has not been proven.
4. Before booting, check authenticated downloads of the selected files and refusal of anonymous
   login, writes and access outside this tree. Configure a fresh private standard xferlog for
   that account when collecting installation evidence; follow the verification guide's
   [FTP transfer-log requirements](guides/verification.md#unattended-installation-proof).

Provisioning is complete only when these restrictions are verified. Do not reuse an account or
credential across runs, including a retry after revocation.

## Prepare this run's manifest and media

Copy the applicable prepared manifest or base manifest into private run storage and edit it
there, using a private editor. Its top-level `source` has this placeholder form:

```text
ftp://<FTP-USER>:<FTP-PASSWORD>@<FTP-HOST>[:<FTP-PORT>]/<TREE-PATH>
```

Replace the placeholders and omit the bracketed port when using the default. The URL path is
relative to the account's login directory; align it with the prepared profile paths and the
server's chroot namespace. Keep credentials out of command arguments, shell history, environment
variables, issue reports and the checkout. Supply them through the manifest file rather than
pasting a credential-bearing URL into a shell command. Queries and fragments are refused.

For direct manifest input, adapt the matching guide sequence using this run's private file:

```sh
python scripts/iso_chain.py validate-config --config "$PRIVATE/manifest.json"
python scripts/iso_chain.py validate-external-source --config "$PRIVATE/manifest.json"
```

These commands require the prepared file to exist. Offline validation does not contact the
source; external validation downloads the pinned files and proves neither a boot nor an install.
Follow the existing build sequence with the same `--config` path, prepared profile directory and
launcher payload, and a fresh private ISO output path.

For `--target`, put this run's source in a fresh private **base manifest**, containing exactly
`version`, `source` and `profiles`. The target request supplies the machine/network and operation
binding; it has **no source override**. For example, after preparing both private files:

```sh
python scripts/iso_chain.py validate-config \
  --target "$PRIVATE/target.json" --base-config "$PRIVATE/base.json"
```

Follow the target-bound media guide's `build` or `container-build` command with those same files
(and `--block-config` for a target-v2 request using a block). Point hmcpctl's fixed build entry
at this fresh base for each FTP run; it must not keep a previous account's base. Retain the
composed manifest privately for evidence verification; `inspect` prints its credentials, so
redirect its output only to private storage.

Use an access-controlled `--publish-dir` and media-serving endpoint. `--publish-url` remains a
credential-free HTTP(S) URL; the secret is inside the ISO it serves. A private directory alone
does not authorize clients at that endpoint: restrict downloads to the intended operator/VIOS.
`container-build` uses its container's umask and may produce world-readable files even when the
host uses `umask 077`; restrict the publication directory and every subsequent copy. Track the
exact `<iso_sha256>.iso` from the producer result, plus any local ISO hardlink or copied media.
Treat `inspect` output and media metadata privately too; manifest digests and volume labels
allow offline password guesses when the remaining manifest is known.

## Run and retain private evidence

Use the verification guide's matching [smoke](guides/verification.md#installer-smoke-proof) or
[installation](guides/verification.md#unattended-installation-proof) sequence with fresh output paths and
the commit that built the media. Preserve the exact selected MAC/static IPv4 configuration and
no-DHCP/no-IPv6 rules. Never switch protocol or source to rescue a failed FTP run.

Treat the manifest/base, ISO and VIOS copy, console/vterm output, access/transfer logs, packet
captures, installer logs, disk images and canonical evidence records as secret-bearing private
evidence. Keep files owner-only and directories owner-only, including copies and backups; never
commit or attach raw evidence to public issues. Collect access logs privately at the server;
retain their original bytes and review the same-run set before asserting `same_run_collection`.
For Fedora, Rocky and Ubuntu installation verification, pass the untouched standard xferlog
through the existing `--access-log` option and bind it in the existing record's
`evidence_sha256.access_log`. Do not convert it to HTTP records. `verify-installer-evidence`
does not support FTP readiness evidence.

The [recorded experiment](experiments/2026-10-27-ftp-installs-and-residue.md) proves QEMU
pSeries/POWER9 Fedora, Rocky and Ubuntu installs and openSUSE readiness for its stated inputs.
Native PowerVM remains unproven. All three installed systems retained plaintext FTP account
values in root-owned mode `0600` installer files, even when the installed boot command line
contained none. Under the operator-approved
[2026-10-27 retention amendment to ADR 0016](adr/0016-assess-authenticated-ftp-sources.md#status),
accept this observed root-only installer history after immediately revoking the per-run account
and terminating authenticated sessions as specified below. Keep installed disks, backups and other
copies private under the lab's retention policy. No automated guest-file deletion is required;
mandatory media cleanup still applies to normal, failed and interrupted runs.

This acceptance covers only the observed Fedora 44, Rocky 9.8 and Ubuntu 26.04.1 QEMU history.
It does not establish installed RHEL or openSUSE residue, escaped-userinfo interoperability or
native PowerVM proof (#37/#72). Root-only permissions restrict ordinary local access; privileged
readers can still recover the retained values. Fedora and Rocky also had unattributed raw-disk
occurrences. Revocation bounds account access; deleting media or guest files would not establish
historical-byte erasure. This policy supplies no safety claim or authorization for disk release.
The operator/lab owner sets retention durations and disclosure/release policy; secure erasure of
disks, snapshots, backups and underlying storage remains the operator/storage owner's work.
Runtime sanitization, installer hooks and verification tooling require separately authorized
operator work. Never report residue absent solely from a clean boot command line.

## Complete or interrupt the run

Perform this cleanup after a normal run, a failed build/boot/install, or an interruption:

1. **Revoke the per-run account first**, using the server's administration procedure. Terminate
   existing authenticated sessions as well as disabling future logins; confirm the old credential
   cannot download and no serving session remains. Do this immediately on interruption, even
   when the guest or VIOS cannot be reached. Never delay revocation for evidence analysis.
2. Stop the guest's use of the media through the lab's safe shutdown/detachment procedure.
   In the exclusive VIOS mapping window, confirm the exact run's optical mapping is safely
   detached/unloaded and no partition still uses that repository object. Do not delete mapped
   media or a shared repository object; resolve ownership before proceeding.
3. Delete this run's exact digest-named `PUBLISH-DIR/<iso_sha256>.iso` and its VIOS media repository
   copy after safe detachment. Remove any separately retained local ISO or other media copy under
   the lab's retention policy. Removing one hardlink does not remove the other published name.
   Check both publication and VIOS inventories; deleting a local file does not delete the VIOS
   copy. Do not use a wildcard or infer the digest from another run.
4. Retire the per-run source tree/account configuration when no longer needed. Retain required
   manifests, logs, captures, disks and evidence only in the private evidence store under the
   lab's retention policy; remove transient credential files and surplus copies. Revocation
   remains necessary even when copies cannot all be removed. Unlinking a file is not proof of
   secure erasure from disk blocks, snapshots or backups.
5. Record revocation, session termination, safe detachment and removal results privately. If
   detachment or deletion is blocked, record the exact remaining artifact and cleanup owner,
   keep access restricted and complete that work when safe. The revoked account is the backstop
   for an interrupted run's remaining copies; cleanup is not complete until they are accounted for.
