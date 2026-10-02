# Authenticated FTP Assessment Plan

**Goal:** Give the launcher and the four installer profiles an observed authenticated-FTP outcome
under ADR 0016's userinfo-URL decision, and record it.

**Architecture:** No repository code changes. A loopback FTP server with a disposable account per
run serves local copies of vendor trees. QEMU pSeries/POWER9 guests boot each installer's pinned
kernel and initrd with the launcher's handoff arguments and an `ftp://` or `ftps://` userinfo URL.
One experiment record holds the outcomes.

**Tech stack:** QEMU 10.2.2 TCG, `pyftpdlib` 2.2.0 and `pyOpenSSL` 26.4.0 in a throwaway virtual
environment, `openssl`, `curl`, `tcpdump`, `gpgv`, `xorriso`, `podman`, Python 3.14 stdlib helpers.

Expected implementation size: 150–210 changed lines (M) — the experiment record of about 140
lines, plus about 10 lines of README and AGENTS.md references.

## Global Constraints

- Spec: `docs/workflow/specs/2026-10-02-authenticated-ftp-assessment-design.md`; ADR 0016.
- No change to `scripts/`, `assets/`, `tests/`, or any manifest grammar (charter exclusion a).
- `PRIVATE` is an operator-chosen directory outside the repository, created with `umask 077`.
  Server, credential, media, console, capture, and log files live under it and are never
  committed. The record names files by role and SHA-256, never by host path.
- Every kernel, initrd, and ISO must match the size and SHA-256 recorded in the 2026-10-01 and
  2026-10-02 experiment records before it is booted. Unpinned trees (stage2, metadata) are the
  accepted ADR 0011 class.
- Guardrails: `just check` before each commit (the pre-commit hook runs the same checks). Write
  URL placeholders as `<user>:<password>@`, which `check-secrets` does not flag.

## Shared harness (built in Task 1, used by Tasks 2–5)

- `PRIVATE/venv` with `pyftpdlib==2.2.0` and `pyopenssl==26.4.0`.
- `PRIVATE/ca.pem`, `PRIVATE/cert.pem`: a throwaway CA and a server certificate with
  `subjectAltName=IP:10.0.2.2,IP:127.0.0.1`, both from `openssl req -x509` / `openssl x509 -req`.
- `PRIVATE/ftpd.py`: reads `PRIVATE/cred` (user name line, password line), serves `PRIVATE/tree`
  read-only (`perm="elr"`) for that one user, binds `127.0.0.1:2121`,
  `passive_ports=range(60000, 60010)`, `masquerade_address="10.0.2.2"`, logs to
  `PRIVATE/run/<name>.ftpd.log`; `--tls` selects `TLS_FTPHandler` with `cert.pem`.
- `PRIVATE/run.sh NAME KERNEL INITRD TEMPLATE PROBE [--tls]`, with `umask 077` and `set -eu`:
  1. writes a fresh `PRIVATE/cred` from two `secrets.token_urlsafe(18)` values, and
     `PRIVATE/netrc` for `127.0.0.1`;
  2. fills `@USER@` and `@PASSWORD@` in `TEMPLATE` into `PRIVATE/run/NAME.args`;
  3. starts `ftpd.py` with a `trap` that stops it on exit;
  4. runs the positive control `curl -fsS --netrc-file PRIVATE/netrc [--ssl-reqd --cacert
     PRIVATE/ca.pem] -r 0-1023 -o /dev/null ftp://127.0.0.1:2121/PROBE` and exits 3 on failure;
  5. runs `qemu-system-ppc64 -machine pseries,accel=tcg -cpu power9 -smp 2 -m 8192M -display none
     -monitor none -chardev socket,id=con,path=PRIVATE/run/NAME.sock,server=on,wait=off,logfile=PRIVATE/run/NAME.console
     -serial chardev:con -netdev user,id=n0,ipv6=off -device virtio-net-pci,netdev=n0,mac=52:54:00:12:34:56
     -object filter-dump,id=d0,netdev=n0,file=PRIVATE/run/NAME.pcap -kernel KERNEL -initrd INITRD
     -append "$(cat PRIVATE/run/NAME.args)"` until the operator kills it at readiness or failure.
- `PRIVATE/send.py SOCK TEXT`: types `TEXT` into the console socket, one byte every 80 ms.
- `PRIVATE/leak.py CONSOLE`: prints the user name and password counts in the console log, raw and
  with ANSI escapes stripped.
- `PRIVATE/peers.sh PCAP`: lists destination addresses of packets from `10.0.2.15`; a valid run
  lists only `10.0.2.2`.
- After each run, copy `PRIVATE/cred` to `PRIVATE/run/NAME.cred` so `leak.py` can be rerun; Task 6
  deletes every credential copy.

## Task 1: Harness and bootstrap arm

**Interfaces.** Provides the shared harness. Consumes nothing.

**Verification.**

- Harness. Mode: `focused-test`. Contract: the server rejects anonymous login and accepts the
  account over both schemes. Red: `ftpd.py` exits non-zero while `PRIVATE/cred` is absent. Green:
  `curl -s ftp://anonymous:x@127.0.0.1:2121/` exits 67; the `netrc` fetch exits 0 plain and with
  `--ssl-reqd --cacert PRIVATE/ca.pem`.
- Bootstrap observation. Mode: `task-test-not-applicable`. Surface: an observation of existing
  behaviour. Reason: no code changes; the outcome is the recorded command output.

Steps:

1. Create `PRIVATE`, the venv, the CA, the certificate, and every harness file.
2. Run the three `curl` checks above with a hand-started server; expect exit 67, 0, 0.
3. With Task 2's Fedora tree served, run in
   `podman run --rm --network host --platform linux/ppc64le localhost/iso-chain-initramfs:44`:
   `curl --disable --ipv4 --fail --no-location --cacert /etc/ssl/certs/ca-certificates.crt
   --connect-timeout 30 --max-time 1200 --max-filesize 66211760 --output /tmp/k
   ftp://<user>:<password>@127.0.0.1:2121/fedora/ppc/ppc64/vmlinuz` and `sha256sum /tmp/k`;
   expect `daf5a8fd…a454`. Repeat with `ftps://`: expect a certificate failure (exit 60) with the
   launcher's fixed bundle, then exit 0 and the same digest with the CA mounted as `--cacert`.
4. Call `scripts.iso_chain._validate_source` from `.venv/bin/python` on `ftp://10.0.2.2:2121` and
   `ftps://10.0.2.2:2121`; expect `ValidationError` naming `source`. Outcome: blocked on #37.

## Task 2: Fedora 44 (Anaconda)

**Interfaces.** Consumes the shared harness. Provides the Fedora outcome row.

**Verification.** Fedora outcome. Mode: `task-test-not-applicable`. Surface: an emulator
observation. Reason: the console log, server log, and capture are the evidence.

Steps:

1. `gpgv` the Fedora 44 Everything ppc64le `CHECKSUM` with the dearmored
   `RPM-GPG-KEY-fedora-44-primary` and check the netinst ISO digest.
2. Extract `images/install.img`, `ppc/ppc64/vmlinuz`, and `ppc/ppc64/initrd.img` with `xorriso
   -osirrox on` into `PRIVATE/tree/fedora/`; fetch `os/.treeinfo` and `os/repodata/`. Check kernel
   66,211,760 bytes `daf5a8fd…a454` and initrd 224,712,048 bytes `f9adcc0c…617a`.
3. Template: `inst.text rd.neednet=1 ifname=iso0:52:54:00:12:34:56
   ip=10.0.2.15::10.0.2.2:255.255.255.0:ftp-test:iso0:none
   inst.repo=ftp://@USER@:@PASSWORD@@10.0.2.2:2121/fedora console=hvc0 ipv6.disable=1`.
4. `run.sh fedora-ftp KERNEL INITRD TEMPLATE fedora/images/install.img`; answer Anaconda's text-mode
   prompt with `send.py`; stop at the hub with the source shown, or at the first error.
5. Repeat with `ftps://` and `--tls` as `fedora-ftps`; if it fails before login, rerun once with
   `inst.noverifyssl` as `fedora-ftps-noverify`.
6. For each run: `leak.py`, `peers.sh`, and the login and `RETR` lines of the run's `ftpd.log`.

## Task 3: Rocky 9.8 (Anaconda)

**Interfaces.** Consumes the shared harness. Provides the Rocky outcome row.

**Verification.** Rocky outcome. Mode: `task-test-not-applicable`. Surface: an emulator
observation. Reason: the console log, server log, and capture are the evidence.

Steps:

1. Check `Rocky-9.8-ppc64le-boot.iso`: `gpgv` of `CHECKSUM` with the Rocky 9 release key, then
   1,467,269,120 bytes, SHA-256 `bd0db737…5a70`.
2. Extract `images/install.img`, `ppc/ppc64/vmlinuz` (47,225,925 bytes, `fb864a9f…510e`), and
   `ppc/ppc64/initrd.img` (209,438,548 bytes, `fbd8ac41…70e0`) into
   `PRIVATE/tree/rocky/BaseOS/ppc64le/os/`; fetch BaseOS's `.treeinfo` and `repodata/`, and
   AppStream's `repodata/`.
3. Template: the Task 2 template with
   `inst.repo=ftp://@USER@:@PASSWORD@@10.0.2.2:2121/rocky/BaseOS/ppc64le/os`.
4. `run.sh rocky-ftp KERNEL INITRD TEMPLATE rocky/BaseOS/ppc64le/os/images/install.img`; drive
   to the hub or the first error. Repeat with `ftps://` and `--tls`,
   and once with `inst.noverifyssl` if FTPS fails before login.
5. For each run: `leak.py`, `peers.sh`, and the run's `ftpd.log`.

## Task 4: openSUSE Leap 15.6 (linuxrc)

**Interfaces.** Consumes the shared harness. Provides the openSUSE outcome row.

**Verification.** openSUSE outcome. Mode: `task-test-not-applicable`. Surface: an emulator
observation. Reason: the console log, server log, and capture are the evidence.

Steps:

1. Fetch the tree subset listed in the 2026-10-02 openSUSE record into `PRIVATE/tree/opensuse/`;
   `gpgv` `CHECKSUMS` (`7cde59a3…cd9c`) with key `AD485664…9B700A4`; check every fetched file
   `CHECKSUMS` lists, including `boot/ppc64le/linux` (50,387,704 bytes) and `initrd` (198,543,156
   bytes).
2. Template: `ifcfg=52:54:00:12:34:56=10.0.2.15/24,10.0.2.2 hostname=ftp-test
   install=ftp://@USER@:@PASSWORD@@10.0.2.2:2121/opensuse textmode=1 self_update=0 console=hvc0
   ipv6.disable=1`.
3. `run.sh opensuse-ftp KERNEL INITRD TEMPLATE opensuse/boot/ppc64le/root`; drive to the
   license screen or the first error. Repeat with `ftps://` and `--tls`, and once with
   `ssl.certs=0` if FTPS fails before login.
4. For each run: `leak.py`, `peers.sh`, and the run's `ftpd.log`.

## Task 5: Ubuntu 26.04.1 (casper)

**Interfaces.** Consumes the shared harness. Provides the Ubuntu outcome row.

**Verification.** Ubuntu outcome. Mode: `task-test-not-applicable`. Surface: an emulator
observation. Reason: the console log, server log, and capture are the evidence.

Steps:

1. Check `ubuntu-26.04.1-live-server-ppc64el.iso`: 1,647,902,720 bytes, SHA-256 `3eb24626…4826`;
   link it into `PRIVATE/tree/ubuntu/`; extract `casper/vmlinux` and `casper/initrd` and check them
   against the 2026-10-02 Ubuntu record's pins (`fdbac021…395f`, `3181671f…dcd4`).
2. Template: `ip=10.0.2.15::10.0.2.2:255.255.255.0:ftp-test::off BOOTIF=01-52-54-00-12-34-56
   iso-url=ftp://@USER@:@PASSWORD@@10.0.2.2:2121/ubuntu/ubuntu-26.04.1-live-server-ppc64el.iso
   console=hvc0 ipv6.disable=1`.
3. `run.sh ubuntu-ftp KERNEL INITRD TEMPLATE ubuntu/ubuntu-26.04.1-live-server-ppc64el.iso`;
   drive to the subiquity network screen or the first casper error. Repeat with `ftps://` and
   `--tls`. casper fetches with the initrd's `wget`; quote its error if it
   rejects the scheme.
4. For each run: `leak.py`, `peers.sh`, and the run's `ftpd.log`.

## Task 6: Experiment record and references

**Interfaces.** Consumes the outcome rows from Tasks 1–5.

**Verification.** Record. Mode: `task-test-not-applicable`. Surface: Markdown. Reason: no
executable consumer reads it; `just check-markdown` checks its form only.

Steps:

1. Write `docs/experiments/2026-10-02-authenticated-ftp-sources.md`: a result table (subject,
   scheme, readiness or error, server login, valid capture, console password count, outcome),
   inputs by size and SHA-256, the trust and transport constraints, the boundaries (emulator only,
   readiness window, loopback server), and the statement that no subject is FTP-supported end to
   end until #37.
2. Add the record and ADR 0016 to `AGENTS.md` (overview, ADR count, Important Files), and one
   README note that FTP sources are not yet accepted, citing ADR 0016 and #37.
3. Scan the changed files for every run credential, the private storage path, and the host name:
   `git diff main --name-only | xargs grep -lF -f <list>`; expect no output.
4. Delete every credential copy and `netrc` under `PRIVATE`. Run `just check`; expect exit 0.
   Commit.
