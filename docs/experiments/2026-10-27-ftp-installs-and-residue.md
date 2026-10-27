# FTP Launcher Installs and Credential Residue

Date: 2026-10-27

Issue #70, parent #37 Expected item 3. Decision:
[ADR 0016](../adr/0016-assess-authenticated-ftp-sources.md), amended by
[ADR 0027](../adr/0027-accept-plain-ftp-sources-with-userinfo.md). Design:
[FTP installation proof](../workflow/specs/2026-10-27-ftp-install-proof-design.md).

## Result

All four named profiles booted fresh FTP-source media through the current launcher under QEMU
pSeries/POWER9. Fedora, Rocky and Ubuntu installed unattended and passed their matching canonical
installation verifiers. openSUSE reached its interactive readiness point. All three installed
images retain the FTP account and password in installer artifacts; every live hit file is
root-owned mode `0600`. Each per-run FTP account was revoked after its arm.

| Profile | Requested endpoint and observed result | Run time |
| --- | --- | --- |
| Fedora 44 | Installed; disk-only boot marker; canonical verification passed | 47 min 16 s |
| Rocky 9.8 | Installed; ISO-first installed-disk handoff/login; canonical verification passed | 37 min 58 s |
| Ubuntu 26.04.1 | Installed; ISO-first installed-disk handoff/login; canonical verification passed | 29 min 06 s |
| openSUSE Leap 15.6 | YaST Language, Keyboard and License Agreement; operator stopped QEMU | 11 min 44 s |

Times include the arm's throwaway FTP-server startup and exclude its final account shutdown.
Fedora ran first; the other three arms overlapped after checking 48 available CPUs, over 220 GiB
available RAM and over 250 GiB free disk. Each used separate accounts, chroots, ports, disks,
console logs and captures. There was one acceptance run per arm and no QEMU retry.

## Inputs and execution

Runtime/media construction and verification commit: `5ab0bf303d6210f8505d983d6f6dda090431f8d3`.

- An x86_64 Fedora 44 host used QEMU 10.2.2, TCG, pSeries, POWER9 and two guest CPUs.
  Fedora received 32,768 MiB; the other arms received 8,192 MiB. The manifest selected the exact
  MAC and static IPv4 configuration in each separate QEMU user network. Disks were fresh 20 GiB.
- Original signed source anchors were rechecked with `gpgv`, then the current preparation
  commands regenerated the four profiles. Inputs were the Fedora 44 Server compose 1.7 tree
  and netinst ISO, Rocky 9.8 BaseOS/AppStream and boot ISO, Ubuntu 26.04.1 live-server ISO,
  and the Leap 15.6 signed-CHECKSUMS tree. Copied serving bytes matched the selected profile pins.
- A throwaway vsftpd 3.0.5-15.fc44 served each private chroot. Authenticated login succeeded;
  anonymous login and a write attempt were refused before installation. Each fresh password
  carried 192 bits of generated entropy. Accounts disappeared with their ephemeral containers.
- The launcher was regenerated from the build commit. Its embedded shell, service and target
  compared byte for byte with that commit's assets. As in prior experiments, container builds
  disabled SELinux labeling and copied source assets without xattrs. Dracut logged unsupported
  xattr-copy warnings; generation exited zero and the byte comparisons and actual boots passed.
- `install-fedora`, `install-rocky` and `install-ubuntu` performed the complete install/boot
  sequences. Matching `verify-*-install-evidence` commands each passed, including
  `ftp-evidence: passed`, installation, disk mutation and their required boot/network checks.
  Their version-1 canonical records bind the original, untouched standard xferlog.
- Completed FTP transfers: Fedora 682, Rocky 359, Ubuntu 3, openSUSE 34.
  The three installation verifiers accepted their ordered pins, exact sizes and later traffic.
  openSUSE's log separately showed its two ordered launcher pins and selected repository traffic.
- openSUSE ran through `smoke` with a snapshot disk. After the YaST readiness title appeared,
  QEMU received SIGTERM; the backing-disk SHA-256 stayed unchanged. `verify-launcher-log` and
  `verify-pcap` passed. Its bound readiness observation is operator-reviewed;
  `verify-installer-evidence` has no FTP readiness support and was not claimed to pass.
- Filtered install and applicable boot captures contained no DHCP or IPv6. Private collection
  records additionally bind the full captures and final disk images. Raw evidence stays private.

## Installed credential residue

Read-only libguestfs mounted each installed root and any separate boot filesystem. Every
exported regular file was searched, including hidden files and hardlink aliases. Symlinks were
not followed; regular target files within the mounted filesystems were covered. Gzip, xz, bzip2,
zstd streams and persistent journals were decoded. Installed initramfs images began with gzip
or zstd and were included in those decoded scans. There were zero decode errors. Original image
SHA-256 values stayed unchanged across inspection.

| Image | Regular files | Hardlink aliases | Live count of each FTP value | Full raw-disk count of each |
| --- | --- | --- | --- | --- |
| Fedora 44 | 33,725 | 3,656 | 47 | 49 |
| Rocky 9.8 | 19,599 | 1,782 | 748 | 750 |
| Ubuntu 26.04.1 | 86,613 | 120 | 5 | 5 |

Each row below has the same count for the FTP username and password. These are live file paths,
all UID 0/GID 0, mode `0600`. The Ubuntu PID suffix is anonymized consistently; the private
path map preserves its original value.

| Image | Path | Count of each value |
| --- | --- | --- |
| Fedora 44 | `/root/anaconda-ks.cfg` | 1 |
| Fedora 44 | `/var/log/anaconda/journal.log` | 17 |
| Fedora 44 | `/var/log/anaconda/packaging.log` | 12 |
| Fedora 44 | `/var/log/anaconda/syslog` | 17 |
| Rocky 9.8 | `/root/anaconda-ks.cfg` | 2 |
| Rocky 9.8 | `/var/log/anaconda/dnf.librepo.log` | 350 |
| Rocky 9.8 | `/var/log/anaconda/journal.log` | 373 |
| Rocky 9.8 | `/var/log/anaconda/packaging.log` | 15 |
| Rocky 9.8 | `/var/log/anaconda/syslog` | 8 |
| Ubuntu 26.04.1 | `/var/log/installer/installer-journal.txt` | 3 |
| Ubuntu 26.04.1 | `/var/log/installer/subiquity-server-debug.log.<installer-pid-U>` | 2 |

The standalone qcow2 scans matched the full 20 GiB virtual raw-disk counts. Fedora and Rocky
have two more raw occurrences of each value than their live-file totals. Those differences
remain unassociated with a filesystem path; no deleted-file or journal attribution is asserted.
Raw and decoded views are not added together. openSUSE has no installed system in this arm,
so installed-system residue is not applicable, rather than absent.

The accounts and passwords used only unreserved characters, so canonical percent-encoding
is identical to the exact string. Fully escaped `%XX` forms, with upper- and lower-case hex,
were also searched; none occurred in any inspected image or collected console. This does not
establish installer interoperability with percent-escaped userinfo or cover other encodings.

## Console and installed boot arguments

As in the earlier FTP assessment, counts remove ANSI escapes and match literal values;
wrapped lines are not joined, so those fragments are outside these counts.

| Profile | Install/readiness username | Install/readiness password | Installed-boot username/password |
| --- | --- | --- | --- |
| Fedora 44 | 4 | 3 | 0 / 0 |
| Rocky 9.8 | 4 | 3 | 0 / 0 |
| Ubuntu 26.04.1 | 5 | 5 | 0 / 0 |
| openSUSE Leap 15.6 | 24 | 4 | not run |

Ubuntu's installed boot logged one kernel command line, with no `iso-url=`, `ftp://` or FTP
credential occurrence. This confirms the separation after the installer's `---` boundary for
that boot; its copied installer logs still retained the five credential occurrences above.

## Bound evidence identities

Each digest below is SHA-256. Installation records use the existing canonical version-1 format;
openSUSE's record is a canonical operator-readiness observation, not a new verifier format.
Collection records bind the selected same-run proof artifacts, including full captures and the
post-boot image inspected for residue.

- **Fedora 44**
  - manifest: `0a521220b31bfb5d1804672d1c176c82d081200294698b5734547edb8316faca`
  - media: `935349ae8ead5c650c9f6283036b9e36cc3a0cfc1b81a51949f7b32c727f3fcc`
  - record: `8bad3633d3d5037fb6087ce272b027b0b453824627279aa84e3030bbd283bd22`
  - collection: `93330b1a9586d0d345d97115f60a949d5cd60f6ea859d3719c2819b238251ab3`
- **Rocky 9.8**
  - manifest: `604faca6fe8eff1272d1e0fa789ec07db2f9878349e09c4efd5d94676811e794`
  - media: `3c6b30084ef46611884726e9fa857056bed9162aefd4a2a1eb530305f44e5154`
  - record: `94e689d0b91e9b2d504a13c9f5e2a24e101dbf05af37353c3a96c7aae2f2f203`
  - collection: `39cbfb36224d4d65f44c9d21b1e9610970ac09716d48bde1e222689d64fbfc9c`
- **Ubuntu 26.04.1**
  - manifest: `ec47a42b133e36c9d1b66a12c9a94eb77562dd0b651d803ee89293aa12910094`
  - media: `947229895cdb83e92390b178f69ec8c99bde8dfcc261ed4b0c36112d33ed2e9a`
  - record: `c9bca9f00d638f0ddb96f7dfe98c5e2e307dfaf29c79b7e56412cac7b21e587e`
  - collection: `8e282839d05302226c848b2c2a874a0616d25d03dd4543f0039ca83029501acc`
- **openSUSE Leap 15.6**
  - manifest: `6631f9fe930915a66607673488cd88216c651fb3541b6fd4026f8a085626747c`
  - media: `cae665b93b110cb2202d83989b659970ea0f2a855d697de5445255ef90841851`
  - record: `692ed35ac5bdc9f5ca4b150c89db7fefa96602115b543bb37e64d9eab868b0ee`
  - collection: `0f6a9fdad107245a51da33e5964b5a5ebef759950cf5fb8daca83d9d523a7c76`

## Boundary and operator follow-up

This is emulator evidence for these four profiles and inputs. Native PowerVM remains #37/#72;
FTPS, RHEL expansion and openSUSE beyond readiness were excluded. Captures, manifests, media,
keys, account values, source trees and disks remain private.

All three installed images retained root-only plaintext FTP credentials after their accounts
were revoked. The operator owns the decision on sanitizing copied installer artifacts beyond
per-run revocation; remediation is unfiled and was not part of this experiment. The unattributed
raw differences on Fedora and Rocky remain explicit limits of path attribution.
