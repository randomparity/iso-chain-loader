# Fedora Unattended Installation Experiment

Date: 2026-09-10

## Inputs and environment

An x86_64 host ran QEMU 10.2.2 with TCG, pSeries, POWER9 mode, two CPUs, 32 GiB
configured RAM, a fresh standalone 20 GiB sparse qcow2, a 7,200-second install timeout, and a
600-second disk-only boot timeout. The verified Fedora Server 44 compose 1.7 ppc64le DVD was
3,013,869,568 bytes with SHA-256
`d0d11c768e2933a421e81db2606eafd512f9d75a15e0d591277837d2c97c908b`.

The reference Kickstart selected Fedora's `server-product-environment`, masked the unused
`serial-getty@hvc0` unit for an unambiguous evidence console, and had SHA-256
`b30be8bbf1f8563cb8914f76d6bca9dd1781eef80c81297de047c3d419b0b044`. Source preparation
embedded those bytes in an installer initramfs of 1,080,102,584 bytes with SHA-256
`7a270ebe55fc603563c6bed3c1b0c2e83a1bf4baef2de19c1dc710ce74f6a4d1`. The canonical anonymous
manifest digest was `a8410f1428ea04e3f8112d460eb666e6fe9987fb7d88af75aff79362f8e35c4a`.
Raw manifests, network values, console logs, HTTP records, captures, media, boot IDs, disks, and
paths remain in mode-0700 private storage.

`qemu-system-ppc64`, `qemu-img`, xorriso, ppc64le GRUB modules, tcpdump 4.99.6, the source media,
RAM, capture capacity, and disk capacity were available. `ksvalidator` was not installed, so the
Fedora 44 Anaconda parser supplied the live semantic Kickstart check.

## Procedure

The acceptance arm used new `SOURCE`, `MANIFEST`, `ISO`, and `INSTALL` paths below a private
directory. `MANIFEST` was canonical version-3 JSON formed from the emitted `profile.json` and
anonymous network inputs. `LAUNCHER_INITRAMFS` contained the current branch launcher asset, and
`GRUB_MODULES` named the extracted ppc64le `powerpc-ieee1275` modules.
The live acceptance arm was built from implementation commit
`6e3c8294451250ebd31a3b4907b545f5c8fefe30`; all implementation files used by the build matched
that commit. The later documentation-only result update does not alter that build.

```sh
scripts/iso_chain.py prepare-fedora-source --iso Fedora-Server-dvd-ppc64le-44-1.7.iso \
  --iso-sha256 d0d11c768e2933a421e81db2606eafd512f9d75a15e0d591277837d2c97c908b \
  --minimum-memory-mib 8192 --kickstart assets/kickstart/fedora-44-power9.ks \
  --output "$SOURCE"
scripts/iso_chain.py build --config "$MANIFEST" --grub-modules "$GRUB_MODULES" \
  --kernel "$SOURCE/profiles/fedora-44/vmlinuz" --initramfs "$LAUNCHER_INITRAMFS" \
  --output "$ISO"
scripts/iso_chain.py inspect "$ISO"
```

In one terminal the bounded, privacy-safe local server wrote a fresh access log:

```sh
scripts/iso_chain.py serve-fedora-source --directory "$SOURCE" --bind "$BIND" --port "$PORT" \
  --access-log "$PRIVATE/access.jsonl"
```

The installation and disk-only boot then ran as one command. The command accepted no existing disk
input and published `INSTALL` only after both phases and all result checks passed.

```sh
scripts/iso_chain.py install-fedora --iso "$ISO" --config "$MANIFEST" --output "$INSTALL" \
  --disk-size-gib 20 --memory-mib 32768 --install-timeout-seconds 7200 \
  --boot-timeout-seconds 600
```

After the run, tcpdump retained only forbidden IPv6 or DHCP traffic from the raw install capture.
The two digest files came from the canonical process result.

```sh
tcpdump -r "$INSTALL/install.pcap" -w "$PRIVATE/install-forbidden.pcap" \
  'ip6 or (udp and (port 67 or port 68))'
jq -r '.disk_sha256_before' "$INSTALL/result.json" >"$PRIVATE/disk-before.sha256"
jq -r '.disk_sha256_after' "$INSTALL/result.json" >"$PRIVATE/disk-after.sha256"
```

The strict record is reproducible from those nine run-local inputs. Compute each digest and emit
canonical sorted JSON before invoking the verifier:

```sh
sha256sum "$MANIFEST" | awk '{print $1}' >"$PRIVATE/manifest.sha256"
MANIFEST_SHA=$(cat "$PRIVATE/manifest.sha256")
sha256sum "$KICKSTART" | awk '{print $1}' >"$PRIVATE/kickstart.sha256"
sha256sum "$INSTALL/install-console.log" | awk '{print $1}' >"$PRIVATE/install_console.sha256"
sha256sum "$INSTALL/boot-console.log" | awk '{print $1}' >"$PRIVATE/boot_console.sha256"
sha256sum "$PRIVATE/access.jsonl" | awk '{print $1}' >"$PRIVATE/access_log.sha256"
sha256sum "$INSTALL/result.json" | awk '{print $1}' >"$PRIVATE/result.sha256"
sha256sum "$INSTALL/install-forbidden.pcap" | awk '{print $1}' >"$PRIVATE/install_pcap.sha256"
sha256sum "$PRIVATE/disk-before.sha256" | awk '{print $1}' >"$PRIVATE/disk_before.sha256"
sha256sum "$PRIVATE/disk-after.sha256" | awk '{print $1}' >"$PRIVATE/disk_after.sha256"
jq -cnS \
  --arg manifest "$(cat "$PRIVATE/manifest.sha256")" \
  --arg kickstart "$(cat "$PRIVATE/kickstart.sha256")" \
  --arg install_console "$(cat "$PRIVATE/install_console.sha256")" \
  --arg boot_console "$(cat "$PRIVATE/boot_console.sha256")" \
  --arg access_log "$(cat "$PRIVATE/access_log.sha256")" \
  --arg result "$(cat "$PRIVATE/result.sha256")" \
  --arg install_pcap "$(cat "$PRIVATE/install_pcap.sha256")" \
  --arg disk_before "$(cat "$PRIVATE/disk_before.sha256")" \
  --arg disk_after "$(cat "$PRIVATE/disk_after.sha256")" \
  --arg manifest_sha256 "$MANIFEST_SHA" \
  '{version:1,manifest_sha256:$manifest_sha256,profile:"fedora",qemu_memory_mib:32768,disk_label:"fresh-fedora-disk",same_run_collection:true,evidence_sha256:{manifest:$manifest,kickstart:$kickstart,install_console:$install_console,boot_console:$boot_console,access_log:$access_log,result:$result,install_pcap:$install_pcap,disk_before:$disk_before,disk_after:$disk_after}}' \
  >"$PRIVATE/record.json"
```

After checking that every input came from this run, a canonical record bound exactly `manifest`,
`kickstart`, `install_console`, `boot_console`, `access_log`, `result`, `install_pcap`,
`disk_before`, and `disk_after` by SHA-256. The verifier consumed that record and those same nine
files:

```sh
scripts/iso_chain.py verify-fedora-install-evidence --record "$PRIVATE/record.json" \
  --config "$MANIFEST" --kickstart assets/kickstart/fedora-44-power9.ks \
  --install-console-log "$INSTALL/install-console.log" \
  --boot-console-log "$INSTALL/boot-console.log" --access-log "$PRIVATE/access.jsonl" \
  --result "$INSTALL/result.json" --install-pcap "$PRIVATE/install-forbidden.pcap" \
  --disk-hash-before "$PRIVATE/disk-before.sha256" \
  --disk-hash-after "$PRIVATE/disk-after.sha256"
```

## Result

The final arm (attempt 9c) completed with installer and disk-only boot exit status 0. The result
reported 2,492,465,152 disk bytes, with before/after digests
`693313d3d5af9d7c4b7f145b141bb3342d439bfa1a445b5ffd1f1cdef5716476` and
`09cb9ae44a421bb065ea22849bd8dfd1df493ab0d47cb251d8f862974af585b4`. The access log contained
682 successful requests; the first five were kernel, installer initramfs, treeinfo, repomd, and
Kickstart, followed by repository package requests. The disk-only console contained exactly one
installed-boot marker, and the filtered forbidden-traffic capture was empty. The verifier output
was `manifest`, `kickstart`, `network-config`, `http-evidence`, `installation`, `disk-mutation`,
`disk-only-boot`, and `dhcp-ipv6-filter` all passed, followed by `same-run: operator-reviewed`.

## Controlled failures

Supplying `/dev/null` as `--kickstart` returned exit 2 with
`error: Kickstart: must be a regular file` and created no output. An earlier live arm used the
nonexistent `minimal-environment`; Anaconda reported `No match for argument: minimal-environment`,
left Software Selection incomplete, and did not mutate the fresh disk. The local Fedora compose
metadata identified `server-product-environment` as the intended Server edition ID.

Another live arm completed installation, booted the disk without the ISO or a NIC, and powered off,
but its direct `/dev/hvc0` write was not retained as a canonical marker; the command rejected the
run with `error: boot console requires one canonical installed-boot marker`. The corrected service
prints to stdout with systemd `StandardOutput=journal+console` and `StandardError=journal+console`,
matching the repository's earlier working boot-evidence unit.

Automated failure injection also exercised an unreachable Kickstart request, install timeout,
nonzero QEMU status, console and capture ceilings, unchanged disk, and missing or false boot marker.
Each failed at its named boundary and published no successful installation result.

## Boundary and cleanup

The HTTP server was stopped after evidence collection. Failed arms remained private until their
diagnostic value was exhausted; their fresh qcow2 files and captures are disposable. The accepted
disk is also a test artifact, not an input or existing VM image.

No native LPAR, HMC, VIOS, host disk, existing VM image, or physical storage was mutated. Native
PowerVM optical behavior, firmware and Secure Boot policy, VIOS mapping, real-P9 storage, and native
cleanup remain outside this emulator proof and require a separately authorized run.
