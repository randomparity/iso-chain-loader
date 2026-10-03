# Authenticated FTP Sources VM Experiment

Date: 2026-10-02

Issue #10. Decision: [ADR 0016](../adr/0016-assess-authenticated-ftp-sources.md). Design:
[spec](../workflow/specs/2026-10-02-authenticated-ftp-assessment-design.md) and
[plan](../workflow/plans/2026-10-02-authenticated-ftp-assessment.md). Follow-up: #37.

## Result

**No subject is FTP-supported end to end.** The manifest still rejects FTP sources, and nothing
here ran the launcher or PowerVM. #37 owns both.

All four installers fetched their source over plain `ftp://` with the credential as URL userinfo,
the path ADR 0016 chose, and reached the readiness point of their 2026-10-02 HTTP experiments.
None accepted `ftps://`. Each rejected the scheme before contacting the server, so the throwaway
CA was never consulted and no verification-off rerun applied.

| Subject | `ftp://` | `ftps://` | Outcome |
|---|---|---|---|
| Bootstrap (launcher `curl`) | transfer passed; manifest rejects the scheme | needs a CA the launcher lacks; manifest rejects the scheme | blocked (#37) |
| Fedora 44 (Anaconda 44.30-2.fc44) | hub, source and software selected | dracut: invalid `inst.repo` | supported, plain FTP only |
| Rocky 9.8 (Anaconda 34.25.7.14-1.el9.rocky.0.6) | hub, source and software selected | dracut: invalid `inst.repo` | supported, plain FTP only |
| openSUSE Leap 15.6 (linuxrc 7.0.32.7) | YaST license screen | not in linuxrc's scheme table | supported, plain FTP only |
| Ubuntu 26.04.1 (casper, BusyBox 1.37.0) | subiquity network screen | `wget`: not an http or ftp URL | supported, plain FTP only |

"Supported" means installer-side support under the emulator, up to readiness. Every supported row
carries the clear-text constraint: under ADR 0016 plain FTP needs the lab owner's written
acceptance of clear-text credentials, and no installer offers FTPS through its source URL.

## Runs

Each guest run booted the profile's pinned kernel and initrd directly in QEMU, with the launcher's
handoff arguments for that profile and the source URL replaced by
`<scheme>://<user>:<password>@10.0.2.2:2121/<tree>`. Every run had its own account, server, and
packet capture. Every positive control passed. Every capture was valid: all FTP connections went
to `10.0.2.2`, and no packet to another address carried the user name or password.

- **Bootstrap.** In the `iso-chain-initramfs:44` image, the launcher's `curl` 8.18.0, with the
  flags of `download_artifact` and the URL from a `--config` file, fetched the Fedora kernel over
  `ftp://`, exited 0, and its SHA-256 matched the pin. Over `ftps://` it exited 60 with the
  launcher's fixed CA bundle, then exited 0 with the matching digest when given the throwaway CA.
  `_validate_source` rejected both schemes: `manifest source: must use the canonical lower-case
  http:// or https:// scheme`.
- **Fedora, `ftp://`.** dracut logged in and fetched `.treeinfo` and the 851,136,512-byte
  `install.img`. Anaconda's hub listed the installation source and the Fedora Custom Operating
  System software selection after fetching `repomd.xml` and the repository metadata.
- **Fedora and Rocky, `ftps://`.** `dracut-cmdline` and `dracut-initqueue` printed `Warning: Invalid
  value for 'inst.repo': ftps://<user>:<password>@10.0.2.2:2121/…`, and the initqueue then waited
  with no limit. The pinned Rocky initrd's `url-lib.sh` registers its fetch handler for `http
  https ftp tftp` only. The guest opened no server session.
- **Rocky, `ftp://`.** As Fedora, plus the AppStream metadata that Anaconda adds from the BaseOS
  `.treeinfo`. The hub showed the source and Server with GUI.
- **openSUSE, `ftp://`.** linuxrc fetched every installation-system part under `boot/ppc64le/`,
  then YaST read `media.1/` and the signed `repodata/` and showed the Language, Keyboard and
  License Agreement screen.
- **openSUSE, `ftps://`.** linuxrc showed `Please make sure your installation medium is available.
  Choose the URL to retry.` The capture held only ARP from the guest. linuxrc's scheme table in the
  pinned initrd's `/init` is `nfs ftp smb http https tftp cd floppy dvd cdwithnet … relurl`, and
  the binary holds no `ftps` string.
- **Ubuntu, `ftp://`.** casper's `wget` fetched the 1,647,902,720-byte live ISO in 13.4 s. subiquity
  started in basic mode, and its network screen listed `enp0s2` as `static 10.0.2.15/24` with MAC
  `52:54:00:12:34:56`.
- **Ubuntu, `ftps://`.** casper printed `wget: not an http or ftp url: ftps://<user>:<password>@…`,
  then `Unable to find a live file system on the network`, and dropped to the BusyBox shell.

## Where the password appeared

ADR 0016 accepts these exposures for the real path. Counts are occurrences of the run's password in
the console log.

| Run | Password count | Where |
|---|---|---|
| Fedora `ftp://` | 1 | kernel command line; also the hub's source line, wrapped across lines |
| Fedora `ftps://` | 3 | kernel command line and two dracut warnings |
| Rocky `ftp://` | 2 | kernel command line; the hub's source line, wrapped |
| Rocky `ftps://` | 3 | kernel command line and two dracut warnings |
| openSUSE `ftp://` | 2 | kernel command line, and the kernel's list of parameters it does not know; YaST progress lines show the user name only |
| openSUSE `ftps://` | 3 | both kernel lines and the linuxrc retry dialog |
| Ubuntu `ftp://` | 3 | both kernel lines and casper's download line |
| Ubuntu `ftps://` | 4 | both kernel lines, casper's download line, and the `wget` error |

## Constraints for #37

- **No FTPS at any installer.** FTPS here means implicit TLS through an `ftps://` URL, which is the
  only form a source URL can request. Explicit TLS (`AUTH TLS` on an `ftp://` connection) needs a
  client option none of these installers takes from its source argument, so it was not tested.
- **Launcher trust anchor.** The launcher pins `curl --cacert` to the system bundle, which rejected
  the test CA. FTPS at the launcher needs a CA that bundle trusts or a carried anchor.
- **Password characters and length.** Only URL-safe passwords from `secrets.token_urlsafe(18)`
  were tested. Percent-encoding, the characters `_validate_source` and GRUB reject, and the
  command-line budget are untested.
- **Installed-system residue.** Every run stopped at readiness. Whether an installer copies the URL
  onto the installed disk is untested.

## Inputs and environment

- **Host and emulator.** An x86_64 Fedora 44 host ran QEMU 10.2.2 with TCG, pSeries, POWER9 mode,
  two CPUs, and 8 GiB. The guest used QEMU's user-mode network with MAC `52:54:00:12:34:56`.
- **Server.** `pyftpdlib` 2.2.0 with `pyOpenSSL` 26.4.0 in a throwaway virtual environment, bound
  to `127.0.0.1:2121` with passive ports 60000–60009 and masquerade address `10.0.2.2`. It served
  one read-only user and refused anonymous login. FTPS used implicit TLS with a certificate for
  `IP:10.0.2.2` and `IP:127.0.0.1` issued by a throwaway CA. Each run had a fresh 24-character user
  name and password.
- **Fedora.** `Fedora-Everything-netinst-ppc64le-44-1.7.iso`, 1,148,528,640 bytes, SHA-256
  `95e63afad3ea52af38940603a173ac4ea229db717549bcf607c5b7f3ced284ce`; `gpgv` verified its
  `CHECKSUM` with the Fedora 44 primary key. The extracted kernel and initrd matched the
  2026-10-01 pins (`daf5a8fd…a454`, `f9adcc0c…617a`). `.treeinfo` and `repodata/` came from the
  mirror's `os/` tree.
- **Rocky.** `Rocky-9.8-ppc64le-boot.iso` with SHA-256 `bd0db737…5a70`; `gpgv` verified `CHECKSUM`.
  The extracted kernel and initrd matched the 2026-10-02 pins (`fb864a9f…510e`, `fbd8ac41…70e0`).
- **openSUSE.** The 2026-10-02 record's tree subset. `gpgv` verified `CHECKSUMS` (`7cde59a3…cd9c`),
  and every fetched file it lists matched. `boot/ppc64le/linux` was 50,387,704 bytes and `initrd`
  198,543,156 bytes.
- **Ubuntu.** `ubuntu-26.04.1-live-server-ppc64el.iso` with SHA-256 `3eb24626…4826`. The extracted
  `casper/vmlinux` and `casper/initrd` matched the 2026-10-02 pins (`fdbac021…395f`,
  `3181671f…dcd4`).
- **Private evidence.** Console logs, server logs, captures, and credentials remain in private
  storage. Quoted lines here have the user name and password replaced.

## Deviations and boundary

- **Launcher bypassed.** The launcher cannot accept an FTP source without #37's code, so each guest
  run booted the installer directly with the launcher's handoff arguments.
- **No DNS.** The arguments omitted the launcher's DNS servers, so the guest resolved no public
  names. Fedora's run still sent DNS queries to root-server addresses, which carried no
  credential.
- **No Fedora Kickstart.** Fedora ran without its ISO Kickstart, so it stopped at the interactive
  hub, as Rocky does.
- **Emulator only.** No LPAR, HMC, VIOS, or lab FTP server was used. #37 owns the live run.
