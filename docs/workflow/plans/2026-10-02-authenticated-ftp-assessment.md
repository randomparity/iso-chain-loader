# Authenticated FTP Assessment Plan

**Goal:** Give the launcher and the four installer profiles an observed authenticated-FTP outcome,
and record them with ADR 0016's credential-delivery decision.

**Architecture:** No repository code changes. A loopback FTP server with a disposable account
serves local copies of vendor trees to QEMU pSeries/POWER9 guests that boot each installer's
pinned kernel and initrd directly. A console driver types the credential where an installer asks
for one. One experiment record holds the outcomes.

**Tech stack:** QEMU 10.2.2 TCG, `pyftpdlib` 2.2.0 and `pyOpenSSL` 26.4.0 in a throwaway virtual
environment, Python 3.14 stdlib driver, `gpgv`, `podman`.

Expected implementation size: 170–230 changed lines (M) — the experiment record of about 150
lines, plus about 10 lines of README and AGENTS.md references, plus `.secrets.baseline` updates.

## Global Constraints

- Spec: `docs/workflow/specs/2026-10-02-authenticated-ftp-assessment-design.md`; ADR 0016.
- No change to `scripts/`, `assets/`, `tests/`, or any manifest grammar (charter exclusion a).
- `PRIVATE` is an operator-chosen directory outside the repository, created with `umask 077`.
  Every server, credential, media, console, and log file lives under it and is never committed.
  The record names files by role and SHA-256, never by host path.
- The credential is generated per run, never typed into a repository file or a shell argument,
  and deleted after its run's evidence is recorded.
- Guests use `-netdev user,id=n0,ipv6=off,restrict=on` plus one `guestfwd` per server port, so
  they reach only the loopback FTP server: no public mirror, no DNS, no HTTP.
- Every kernel, initrd, and ISO must match the size and SHA-256 recorded in the 2026-10-01 and
  2026-10-02 experiment records before it is booted. Unpinned trees (stage2, metadata) are the
  accepted ADR 0011 class.
- Guardrails: `just check` before each commit. Refresh `.secrets.baseline` line numbers if a
  covered file shifts.

## Shared harness (built in Task 1, used by Tasks 2–5)

- `PRIVATE/venv`: `uv venv --python 3.14 PRIVATE/venv` then
  `uv pip install --python PRIVATE/venv/bin/python pyftpdlib==2.2.0 pyopenssl==26.4.0`.
- `PRIVATE/ftpd.py`: reads `PRIVATE/cred` (two lines, user then password), serves `PRIVATE/tree`
  read-only (`perm="elr"`) for that one user, binds `127.0.0.1:2121`, sets
  `passive_ports=range(60000, 60010)` and `masquerade_address="10.0.2.2"`, logs to
  `PRIVATE/run/ftpd.log`, and uses `TLS_FTPHandler` with `PRIVATE/cert.pem` when given `--tls`
  (with `tls_control_required` and `tls_data_required` false so plain FTP is a separate run).
- `PRIVATE/drive.py`: connects to the QEMU console socket, appends every byte to
  `PRIVATE/run/console.log`, and runs a step file of `expect <regex>` / `send <text>` lines, where
  `send` replaces `@USER@` and `@PASSWORD@` from `PRIVATE/cred` so neither appears in a step file.
- Network arguments: `-netdev user,id=n0,ipv6=off,restrict=on,guestfwd=tcp:10.0.2.2:2121-tcp:127.0.0.1:2121`
  with one more `guestfwd` per passive port 60000–60009, and
  `-device virtio-net-pci,netdev=n0,mac=52:54:00:12:34:56`.
- QEMU base: `qemu-system-ppc64 -machine pseries,accel=tcg -cpu power9 -smp 2 -m 8192M
  -display none -monitor none -serial unix:PRIVATE/run/console.sock,server=on,wait=on
  -kernel K -initrd I -append "ARGS"`.
- Leak check after each run: `grep -c -F -f PRIVATE/cred PRIVATE/run/console.log` prints the
  number of console lines carrying the user name or password.

## Task 1: Harness and bootstrap arm

**Interfaces.** Provides the shared harness above. Consumes nothing.

**Verification.**

- Harness. Mode: `focused-test`. Contract: the server rejects anonymous login and accepts the
  generated account. Red: before `PRIVATE/cred` exists, `ftpd.py` exits non-zero. Green:
  `curl -s ftp://anonymous:x@127.0.0.1:2121/` exits 67, and
  `curl -s --netrc-file PRIVATE/netrc ftp://127.0.0.1:2121/` lists the tree, where
  `PRIVATE/netrc` is written from `PRIVATE/cred`.
- Bootstrap observation. Mode: `task-test-not-applicable`. Surface: an observation of existing
  behaviour. Reason: no code changes; the outcome is the recorded command output.

Steps:

1. Create `PRIVATE`, the venv, `ftpd.py`, `drive.py`, and a self-signed `cert.pem`
   (`openssl req -x509 -newkey rsa:3072 -nodes -days 2 -subj /CN=10.0.2.2`).
2. Generate the account, two `secrets.token_urlsafe(18)` lines, with
   `python3 -c 'import secrets; [print(secrets.token_urlsafe(18)) for _ in "up"]' > PRIVATE/cred`.
3. Run the two `curl` checks above; expect exit 67 and a listing.
4. Run `podman run --rm --platform linux/ppc64le localhost/iso-chain-initramfs:44 curl --version`;
   expect `ftp` and `ftps` in `Protocols:`.
5. Run `.venv/bin/python -c` that calls `scripts.iso_chain._validate_source` on
   `ftp://10.0.2.2:2121` and `ftps://10.0.2.2:2121`; expect a `ValidationError` naming `source`
   for both.

## Task 2: Fedora 44 (Anaconda)

**Interfaces.** Consumes the shared harness. Provides the Fedora outcome row.

**Verification.** Fedora outcome. Mode: `task-test-not-applicable`. Surface: an emulator
observation. Reason: the run's console log and server log are the evidence; nothing executable
consumes the outcome.

Steps:

1. Fetch the Fedora 44 Everything ppc64le netinst ISO and `CHECKSUM` from
   `dl.fedoraproject.org/pub/fedora-secondary/releases/44/Everything/ppc64le/iso/`, run
   `gpgv --keyring <dearmored RPM-GPG-KEY-fedora-44-primary> CHECKSUM`, and check the ISO.
2. Copy the ISO's `.treeinfo`, `images/install.img`, `ppc/ppc64/vmlinuz`, and `ppc/ppc64/initrd.img`
   into `PRIVATE/tree/fedora/` with `xorriso -osirrox on -indev ISO -extract`, and fetch the
   `os/repodata/` directory; check kernel 66,211,760 bytes `daf5a8fd…a454` and initrd 224,712,048
   bytes `f9adcc0c…617a` as recorded on 2026-10-01.
3. Arm T: start `ftpd.py`, boot with `-append "inst.text rd.neednet=1
   ifname=iso0:52:54:00:12:34:56 ip=10.0.2.15::10.0.2.2:255.255.255.0:ftp-test:iso0:none
   inst.repo=ftp://@USER@:@PASSWORD@@10.0.2.2:2121/fedora console=hvc0 ipv6.disable=1"`, the
   placeholders filled in a `0600` arguments file read by the shell. Drive to the hub; record
   whether the hub shows the source and `ftpd.log` shows `RETR` of `install.img` and `repomd.xml`.
   Repeat with `ftps://` and `--tls`.
4. Arm C: boot with the netinst ISO attached as a cdrom and `inst.stage2=cdrom` instead of
   `inst.repo`. In Installation Source choose Network, select FTP, type
   `@USER@:@PASSWORD@@10.0.2.2:2121/fedora`, and drive to the hub.
5. Run the leak check for each run; record the outcome class.

## Task 3: Rocky 9.8 (Anaconda)

**Interfaces.** Consumes the shared harness. Provides the Rocky outcome row.

**Verification.** Rocky outcome. Mode: `task-test-not-applicable`. Surface: an emulator
observation. Reason: the run's console log and server log are the evidence; nothing executable
consumes the outcome.

Steps:

1. Fetch `Rocky-9.8-ppc64le-boot.iso` and check 1,467,269,120 bytes, SHA-256 `bd0db737…5a70`.
2. Extract `.treeinfo`, `images/install.img`, `ppc/ppc64/vmlinuz` (47,225,925 bytes), and
   `ppc/ppc64/initrd.img` (209,438,548 bytes) into `PRIVATE/tree/rocky/BaseOS/ppc64le/os/`, and
   fetch BaseOS's and AppStream's `repodata/`.
3. Arm T: the Task 2 arm T arguments with `inst.repo=ftp://@USER@:@PASSWORD@@10.0.2.2:2121/rocky/BaseOS/ppc64le/os`;
   drive to the hub; repeat with `ftps://` and `--tls`.
4. Arm C: the Rocky boot ISO as cdrom with `inst.stage2=cdrom`; in Installation Source choose
   Network, select FTP, type `@USER@:@PASSWORD@@10.0.2.2:2121/rocky/BaseOS/ppc64le/os`, drive to
   the hub.
5. Run the leak check for each run; record the outcome class.

## Task 4: openSUSE Leap 15.6 (linuxrc)

**Interfaces.** Consumes the shared harness. Provides the openSUSE outcome row.

**Verification.** openSUSE outcome. Mode: `task-test-not-applicable`. Surface: an emulator
observation. Reason: the run's console log and server log are the evidence; nothing executable
consumes the outcome.

Steps:

1. Fetch the tree subset listed in the 2026-10-02 openSUSE record under
   `PRIVATE/tree/opensuse/`, `gpgv`-check `CHECKSUMS` with key `AD485664…9B700A4`, and check
   `boot/ppc64le/linux` (50,387,704 bytes) and `initrd` (198,543,156 bytes).
2. Arm T: boot with `-append "ifcfg=52:54:00:12:34:56=10.0.2.15/24,10.0.2.2 hostname=ftp-test
   install=ftp://@USER@:@PASSWORD@@10.0.2.2:2121/opensuse textmode=1 self_update=0 console=hvc0
   ipv6.disable=1"`; drive to the license screen; repeat with `ftps://` and `--tls`.
3. Arm C: the same arguments with `manual=1` and no `install=`. In linuxrc choose Start
   Installation, Installation, Network, FTP; enter `10.0.2.2:2121` and `/opensuse`; answer No to
   anonymous FTP; type `@USER@` and `@PASSWORD@`; drive to the license screen.
4. Run the leak check for each run; record the outcome class.

## Task 5: Ubuntu 26.04.1 (casper)

**Interfaces.** Consumes the shared harness. Provides the Ubuntu outcome row.

**Verification.** Ubuntu outcome. Mode: `task-test-not-applicable`. Surface: an emulator
observation and a source reading. Reason: the console log, server log, and casper script lines
are the evidence; nothing executable consumes the outcome.

Steps:

1. Fetch `ubuntu-26.04.1-live-server-ppc64el.iso` and check 1,647,902,720 bytes, SHA-256
   `3eb24626…4826`; copy it to `PRIVATE/tree/ubuntu/`. Extract `casper/vmlinux` and
   `casper/initrd` and check them against the 2026-10-02 Ubuntu record's pins.
2. Arm C: unpack the initrd and search casper's scripts for any prompt that reads a URL or
   credential (`grep -rn "read \|iso-url\|wget\|curl"`); record the lines, or that none exist.
3. Arm T: boot with `-append "ip=10.0.2.15::10.0.2.2:255.255.255.0:ftp-test::off
   BOOTIF=01-52-54-00-12-34-56 iso-url=ftp://@USER@:@PASSWORD@@10.0.2.2:2121/ubuntu/ubuntu-26.04.1-live-server-ppc64el.iso
   console=hvc0 ipv6.disable=1"`; drive to the subiquity network screen or the first casper
   error; repeat with `ftps://` and `--tls`.
4. Run the leak check for each run; record the outcome class.

## Task 6: Experiment record and references

**Interfaces.** Consumes the outcome rows from Tasks 1–5.

**Verification.** Record. Mode: `task-test-not-applicable`. Surface: Markdown. Reason: no
executable consumer reads it; `just check-markdown` checks its form only.

Steps:

1. Write `docs/experiments/2026-10-02-authenticated-ftp-sources.md`: result table (subject, arm T
   plain/FTPS, arm C, leak count, outcome class, exact blocker), inputs by size and SHA-256,
   boundaries (emulator only, console-only leak check, loopback server), and the proposed
   follow-up for operator approval.
2. Add the record and ADR 0016 to `AGENTS.md` (overview, ADR count, Important Files) and a short
   README note that FTP sources are unsupported, citing ADR 0016.
3. Delete `PRIVATE/cred`; stop the server. Run `just check`; expect exit 0. Commit.
