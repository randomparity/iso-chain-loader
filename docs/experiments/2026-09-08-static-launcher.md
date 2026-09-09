# Static Launcher VM Experiment

Date: 2026-09-08

## Result

The final five-arm ppc64le QEMU matrix passed. Two ISOs shared one kernel/initramfs payload and
embedded distinct canonical manifests. Both configured defaults and an explicitly selected
alternate GRUB profile reached the launcher terminal target after exactly one static IPv4 HTTP
probe each. Missing and duplicate adapter cases failed before transmitting any packet.

Native PowerVM was not run. These results prove the emulator path only; they do not establish
native LPAR optical behavior, HMC/VIOS mapping behavior, firmware policy, or Secure Boot compatibility.
Installer downloads and the kexec transition remain outside this static-launcher experiment.

## Environment and preparation

An x86_64 host ran QEMU 10.2.2 with TCG, pSeries, POWER9, two CPUs and 4 GiB RAM. A disposable
Fedora 43 ppc64le guest prepared the initramfs using dracut 107-8.fc43 and kernel
6.17.1-300.fc43.ppc64le. Python 3.14.5, systemd, iproute 6.14.0 and curl 8.15.0 were already
installed. The source checkout's launcher assets were copied into snapshot state; source hashes
and the returned payload digest matched. Image inspection confirmed the corrected launcher
units, required runtime tools and no networking dracut module or DHCP client.

Host GRUB 2.12, matching `powerpc-ieee1275` modules and xorriso 1.5.8.pl02 built both ISOs.
`inspect` returned exactly the expected canonical manifest for each. The anonymous configurations
`sys-r1` and `sys-r2` differed in static address, default profile, source path and configuration
digest. The VM tooling checkout and backing disk remained unchanged; all guest writes used
disposable snapshot state.

## Final acceptance matrix

Each successful arm was observed for 60 seconds after reaching the explicit terminal target.
The negative arms were observed for 60 seconds after their fixed adapter failure. No arm selected
a fallback profile or issued another probe.

| Arm | Configuration and selection | HTTP probes | Captures | Result |
| --- | --- | ---: | ---: | --- |
| First matched default; lifecycle gate | `sys-r1`, default `fedora` | 1 | 1 | Passed |
| Second matched default | `sys-r2`, default `rhel` | 1 | 1 | Passed |
| First ISO manual selection | `sys-r1`, console-selected `rhel` | 1 | 1 | Passed |
| Missing adapter | `sys-r1`, fixed adapter failure | 0 | 1 | Passed; capture empty |
| Duplicate adapter | `sys-r1`, fixed adapter failure | 0 | 2 | Passed; both captures empty |

The first default boot passed before any remaining arm started. The manual arm sent Down and
Enter through the GRUB console, then verified `rhel` explicitly against the unchanged first
manifest digest. Each successful console had exactly one ordered set of configuration, adapter,
profile and HTTP pass markers, followed by terminal-target completion and no later failure.

The private HTTP server recorded exactly three requests, one to the expected source path in each
successful arm and none from the two negatives. Every netdev had its own fresh capture. All six
captures passed the bounded, captured `tcpdump -nn -r PATH -c 1` check with the filter
`ip6 or (udp and (port 67 or port 68))`; each verifier returned:

```text
dhcp-ipv6: absent
```

The three negative-arm captures also contained no packets when inspected without a protocol filter.
No packet contents or private configuration values are reproduced here.

## Reproduction and evidence limits

Use the [README preparation, build and verification commands](../../README.md#static-launcher).
Serve a one-byte HTTP response from a private host endpoint and use separate private output paths
for every configuration, ISO, boot log and netdev capture. Run the table's five arms in order;
require the first lifecycle gate before continuing. Verify the explicit selected profile for each
successful boot and account for HTTP requests separately for every arm.

Two earlier diagnostic attempts are excluded from the final acceptance matrix. The first exposed
missing system initialization dependencies; the second reached the terminal target but kept
launcher output only in the journal. The target now requires system initialization and the service
routes both output streams to the journal and console. A private harness was also corrected to
remove console ANSI formatting before detecting terminal completion. After final review tightened
the runtime's directly connected gateway check and literal route parsing, the complete matrix was
repeated with a newly prepared payload containing the current launcher and service corrections.
The results above are from that fresh evidence set.

The VM and HTTP server were stopped after the matrix. Logs, pcaps, manifests, payloads and media
remain in ignored private storage for review. This report contains only anonymous identities,
tool versions, counts and fixed outcomes. Native PowerVM and firmware/security evidence still
require a separately authorized native run.
