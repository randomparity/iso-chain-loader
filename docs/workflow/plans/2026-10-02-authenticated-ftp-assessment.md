# Authenticated FTP Assessment Plan

**Goal:** Give the launcher and the four installer profiles an observed authenticated-FTP outcome,
and record them with ADR 0016's credential-delivery decision.

**Architecture:** No repository code changes. A loopback FTP server with a disposable account
serves local copies of vendor trees to QEMU pSeries/POWER9 guests. Each guest boots its installer's
pinned kernel with the pinned initrd plus an appended cpio holding the source file, as ADR 0016's
launcher handoff would. One experiment record holds the outcomes.

**Tech stack:** QEMU 10.2.2 TCG, `pyftpdlib` 2.2.0 and `pyOpenSSL` 26.4.0 in a throwaway virtual
environment, Python 3.14 stdlib helpers, `cpio`, `tcpdump`, `gpgv`, `podman`, `ssh`.

Expected implementation size: 170–230 changed lines (M) — the experiment record of about 150
lines, plus about 10 lines of README and AGENTS.md references, plus `.secrets.baseline` updates.

## Global Constraints

- Spec: `docs/workflow/specs/2026-10-02-authenticated-ftp-assessment-design.md`; ADR 0016.
- No change to `scripts/`, `assets/`, `tests/`, or any manifest grammar (charter exclusion a).
- `PRIVATE` is an operator-chosen directory outside the repository, created with `umask 077`.
  Server, credential, media, console, capture, and log files live under it and are never
  committed. The record names files by role and SHA-256, never by host path.
- The FTP credential reaches a guest only inside an appended cpio (arm I) or, for Ubuntu's arm T,
  on the command line; it never appears in a repository file.
- Every kernel, initrd, and ISO must match the size and SHA-256 recorded in the 2026-10-01 and
  2026-10-02 experiment records before it is booted. Unpinned trees (stage2, metadata) are the
  accepted ADR 0011 class.
- Guardrails: `just check` before each commit. Refresh `.secrets.baseline` line numbers if a
  covered file shifts.

## Shared harness (built in Task 1, used by Tasks 2–5)

- `PRIVATE/venv` with `pyftpdlib==2.2.0` and `pyopenssl==26.4.0`, installed by `uv pip install`.
- `PRIVATE/cred`: two lines, user name then password, each `secrets.token_urlsafe(18)`.
  `PRIVATE/sshpw`: one line, the separate SSH password. `PRIVATE/netrc` for host-side `curl`.
- `PRIVATE/ftpd.py`: serves `PRIVATE/tree` read-only (`perm="elr"`) for the one user, binds
  `127.0.0.1:2121`, `passive_ports=range(60000, 60010)`, `masquerade_address="10.0.2.2"`, logs to
  `PRIVATE/run/ftpd.log`; `--tls` selects `TLS_FTPHandler` with `PRIVATE/cert.pem`.
- `PRIVATE/run.sh NAME KERNEL INITRD ARGSFILE PROBE [--tls]`: sets `umask 077`; starts `ftpd.py`
  and installs `trap` to stop it on exit; runs the positive control
  `curl --netrc-file PRIVATE/netrc [--ssl-reqd -k] ftp://127.0.0.1:2121/PROBE -o /dev/null`
  and exits 3 if it fails; then runs `qemu-system-ppc64 -machine pseries,accel=tcg -cpu power9
  -smp 2 -m 8192M -display none -monitor none
  -chardev socket,id=con,path=PRIVATE/run/NAME.sock,server=on,wait=off,logfile=PRIVATE/run/NAME.console
  -serial chardev:con -netdev user,id=n0,ipv6=off,hostfwd=tcp:127.0.0.1:2222-:22
  -device virtio-net-pci,netdev=n0,mac=52:54:00:12:34:56
  -object filter-dump,id=d0,netdev=n0,file=PRIVATE/run/NAME.pcap
  -kernel KERNEL -initrd INITRD -append "$(cat ARGSFILE)"` in the foreground until killed.
- `PRIVATE/send.py SOCK TEXT`: types `TEXT` into the console socket, one byte every 80 ms.
- `PRIVATE/leak.py CONSOLE`: prints the user name and password counts in the console log, raw and
  with ANSI escapes stripped.
- `PRIVATE/peers.sh PCAP`: `tcpdump -nn -r PCAP 'ip and (tcp or udp)' | awk` listing guest
  destination addresses; a valid run lists only `10.0.2.2`.
- `PRIVATE/inspect.sh`: over `ssh -p 2222 root@127.0.0.1` (password from `PRIVATE/sshpw`), runs
  `grep -rlF -f /dev/stdin /tmp /var/log /run /etc` and `journalctl -b | grep -cF -f /dev/stdin`,
  feeding only the FTP password on standard input, and prints the paths and the count.
- `mkcpio NAME FILE`: `(cd DIR && printf '%s\n' FILE | cpio -o -H newc) > PRIVATE/run/NAME.cpio`,
  then `cat PINNED_INITRD PRIVATE/run/NAME.cpio > PRIVATE/run/NAME.initrd`.
- Common network arguments: Anaconda `inst.text rd.neednet=1 ifname=iso0:52:54:00:12:34:56
  ip=10.0.2.15::10.0.2.2:255.255.255.0:ftp-test:iso0:none console=hvc0 ipv6.disable=1`; linuxrc
  `ifcfg=52:54:00:12:34:56=10.0.2.15/24,10.0.2.2 hostname=ftp-test textmode=1 self_update=0
  console=hvc0 ipv6.disable=1`.

## Task 1: Harness and bootstrap arm

**Interfaces.** Provides the shared harness above. Consumes nothing.

**Verification.**

- Harness. Mode: `focused-test`. Contract: the server rejects anonymous login and accepts the
  account. Red: `ftpd.py` exits non-zero while `PRIVATE/cred` is absent. Green:
  `curl -s ftp://anonymous:x@127.0.0.1:2121/` exits 67, and the `netrc` fetch of a probe file
  exits 0, with the server started by hand.
- Bootstrap observation. Mode: `task-test-not-applicable`. Surface: an observation of existing
  behaviour. Reason: no code changes; the outcome is the recorded command output.

Steps:

1. Create `PRIVATE`, the venv, every harness file, and `cert.pem`
   (`openssl req -x509 -newkey rsa:3072 -nodes -days 2 -subj /CN=10.0.2.2`).
2. Write `cred`, `sshpw`, and `netrc` with `python3` and `secrets`; check mode `0600`.
3. Run the two `curl` checks above; expect exit 67, then exit 0.
4. Run `podman run --rm --platform linux/ppc64le localhost/iso-chain-initramfs:44 curl --version`;
   expect `ftp` and `ftps` in `Protocols:`.
5. Call `scripts.iso_chain._validate_source` from `.venv/bin/python` on `ftp://10.0.2.2:2121` and
   `ftps://10.0.2.2:2121`; expect `ValidationError` naming `source` for both. Outcome: blocked,
   needing excluded implementation.

## Task 2: Fedora 44 (Anaconda, arm I)

**Interfaces.** Consumes the shared harness. Provides the Fedora outcome row.

**Verification.** Fedora outcome. Mode: `task-test-not-applicable`. Surface: an emulator
observation. Reason: the console log, server log, capture, and inspection output are the evidence.

Steps:

1. Fetch the Fedora 44 Everything ppc64le netinst ISO and `CHECKSUM`, `gpgv` the `CHECKSUM` with
   the dearmored `RPM-GPG-KEY-fedora-44-primary`, and check the ISO digest.
2. Extract `images/install.img`, `ppc/ppc64/vmlinuz`, and `ppc/ppc64/initrd.img` with `xorriso
   -osirrox on` into `PRIVATE/tree/fedora/`; fetch `os/.treeinfo` and `os/repodata/`. Check kernel
   66,211,760 bytes `daf5a8fd…a454` and initrd 224,712,048 bytes `f9adcc0c…617a`.
3. Write `ftp-source.ks` with `url --url=ftp://<user>:<password>@10.0.2.2:2121/fedora` and
   `sshpw --username=root --plaintext SSHPW`, with `<user>`, `<password>`, and `SSHPW` filled
   from `cred` and `sshpw` by a Python one-liner; build the cpio and initrd. Arguments: the
   Anaconda network arguments plus `inst.ks=file:/ftp-source.ks inst.sshd`.
4. `run.sh fedora-ftp … images/install.img`; watch the console log, answering Anaconda's text-mode
   prompt with `send.py`, until the hub shows the installation source. Run `inspect.sh`, then stop.
5. Repeat steps 3–4 with `ftps://` and `--tls` as `fedora-ftps`.
6. For each run: `leak.py`, `peers.sh`, and the `RETR` lines of `ftpd.log`; record the outcome.

## Task 3: Rocky 9.8 (Anaconda, arm I)

**Interfaces.** Consumes the shared harness. Provides the Rocky outcome row.

**Verification.** Rocky outcome. Mode: `task-test-not-applicable`. Surface: an emulator
observation. Reason: the console log, server log, capture, and inspection output are the evidence.

Steps:

1. Fetch `Rocky-9.8-ppc64le-boot.iso` and check 1,467,269,120 bytes, SHA-256 `bd0db737…5a70`.
2. Extract `images/install.img`, `ppc/ppc64/vmlinuz` (47,225,925 bytes), and `ppc/ppc64/initrd.img`
   (209,438,548 bytes) into `PRIVATE/tree/rocky/BaseOS/ppc64le/os/`; fetch BaseOS's `.treeinfo`
   and `repodata/`, and AppStream's `repodata/` into `PRIVATE/tree/rocky/AppStream/ppc64le/os/`.
3. Write `ftp-source.ks` with
   `url --url=ftp://<user>:<password>@10.0.2.2:2121/rocky/BaseOS/ppc64le/os` and the `sshpw` line;
   build the cpio and initrd. Arguments: the Anaconda network arguments plus
   `inst.ks=file:/ftp-source.ks inst.sshd`.
4. `run.sh rocky-ftp …`; drive to the hub; run `inspect.sh`; stop. Repeat with `ftps://` and
   `--tls` as `rocky-ftps`.
5. For each run: `leak.py`, `peers.sh`, and `ftpd.log`; record the outcome.

## Task 4: openSUSE Leap 15.6 (linuxrc, arm I)

**Interfaces.** Consumes the shared harness. Provides the openSUSE outcome row.

**Verification.** openSUSE outcome. Mode: `task-test-not-applicable`. Surface: an emulator
observation. Reason: the console log, server log, capture, and inspection output are the evidence.

Steps:

1. Fetch the tree subset listed in the 2026-10-02 openSUSE record into `PRIVATE/tree/opensuse/`,
   `gpgv` `CHECKSUMS` (`7cde59a3…cd9c`) with key `AD485664…9B700A4`, check every fetched file
   `CHECKSUMS` lists, and check `boot/ppc64le/linux` (50,387,704 bytes) and `initrd`
   (198,543,156 bytes).
2. Write `ftp-source.info` with `install: ftp://<user>:<password>@10.0.2.2:2121/opensuse`; build the
   cpio and initrd. Arguments: the linuxrc network arguments plus
   `info=file:/ftp-source.info sshd=1 sshpassword=SSHPW` from an argument file.
3. `run.sh opensuse-ftp … boot/ppc64le/root`; drive to the license screen; run `inspect.sh`;
   stop. Repeat with `ftps://` and `--tls` as `opensuse-ftps`.
4. For each run: `leak.py`, `peers.sh`, and `ftpd.log`; record the outcome.

## Task 5: Ubuntu 26.04.1 (casper, arm T)

**Interfaces.** Consumes the shared harness. Provides the Ubuntu outcome row.

**Verification.** Ubuntu outcome. Mode: `task-test-not-applicable`. Surface: an emulator
observation and a source reading. Reason: the casper script lines and run logs are the evidence.

Steps:

1. Fetch `ubuntu-26.04.1-live-server-ppc64el.iso`, check 1,647,902,720 bytes, SHA-256
   `3eb24626…4826`, copy it to `PRIVATE/tree/ubuntu/`, and extract `casper/vmlinux` and
   `casper/initrd`; check them against the 2026-10-02 Ubuntu record's pins.
2. Unpack the initrd and quote the casper lines that set the ISO URL and fetch it
   (`grep -rn "iso-url\|wget\|curl" scripts/`). If the URL comes only from `/proc/cmdline`, the
   delivery outcome is unsupported: no file-based source input.
3. Arm T: arguments `ip=10.0.2.15::10.0.2.2:255.255.255.0:ftp-test::off
   BOOTIF=01-52-54-00-12-34-56 iso-url=ftp://<user>:<password>@10.0.2.2:2121/ubuntu/ubuntu-26.04.1-live-server-ppc64el.iso
   console=hvc0 ipv6.disable=1` in an argument file; `run.sh ubuntu-ftp …`; drive to the subiquity
   network screen or the first casper error; repeat with `ftps://` and `--tls`.
4. For each run: `peers.sh` and `ftpd.log`; record the transport result beside the outcome.

## Task 6: Experiment record and references

**Interfaces.** Consumes the outcome rows from Tasks 1–5.

**Verification.** Record. Mode: `task-test-not-applicable`. Surface: Markdown. Reason: no
executable consumer reads it; `just check-markdown` checks its form only.

Steps:

1. Write `docs/experiments/2026-10-02-authenticated-ftp-sources.md`: a result table (subject, arm,
   scheme, readiness, console and log leak counts, valid capture, outcome class, exact blocker),
   inputs by size and SHA-256, boundaries (emulator only, readiness window, loopback server), and
   the follow-up proposal for operator approval.
2. Add the record and ADR 0016 to `AGENTS.md` (overview, ADR count, Important Files) and one README
   note that FTP sources are unsupported, citing ADR 0016.
3. Scan the changed files: `git diff main --name-only | xargs grep -lF -f PRIVATE/cred`, and the
   same for the private storage path and the host name; expect no output.
4. Delete `PRIVATE/cred`, `PRIVATE/sshpw`, `PRIVATE/netrc`, and the argument and cpio files. Run
   `just check`; expect exit 0. Commit.
