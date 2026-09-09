# Per-LPAR Static Launcher Design

Issue: [#4](https://github.com/randomparity/iso-chain-loader/issues/4)
Decision: [ADR 0004](../../adr/0004-use-grub-and-dracut-for-launcher.md)

## Scope and guarantees

Build ppc64le ISOs from one reusable Linux payload and distinct, validated per-LPAR manifests. Each
ISO offers a human GRUB menu and selects its configured profile automatically. Before any network
command runs, the launcher requires exactly one interface with the configured MAC. It then applies
only static IPv4 state and performs one bounded HTTP probe. Missing configuration, invalid values,
zero matches, or multiple matches emit a fixed failure and stop with no network packets.

The VM proves emulator behavior, embedded settings, static HTTP reachability, and absence of DHCP.
It does not prove native POWER9 PowerVM, firmware security, HMC, or VIOS behavior. Installer-specific
downloads and the kexec handoff remain issue #5.

## Manifest contract

The UTF-8 JSON object has exactly these fields:

```json
{
  "version": 1,
  "lpar": "sys-R1",
  "network": {
    "mac": "52:54:00:12:34:56",
    "address": "10.0.2.15/24",
    "routes": [{"destination": "0.0.0.0/0", "gateway": "10.0.2.2"}],
    "dns": ["10.0.2.3"]
  },
  "source": "http://10.0.2.2:8000/probe",
  "profiles": ["fedora", "rhel"],
  "selected_profile": "fedora"
}
```

Unknown or missing fields fail. `version` is exactly `1`. `lpar` and profile identifiers match
`[a-z][a-z0-9-]{0,31}`; profiles are unique, contain 1–16 entries, and include the selected value.
The MAC is canonical lower-case unicast Ethernet. Address, destinations, gateways, and up to three
DNS entries are IPv4; routes contain 1–16 unique destinations. Each non-default gateway is reachable
through the configured subnet or an earlier route. `source` is HTTP with an IP literal or DNS name,
optional port, absolute path, and no credentials, query, or fragment. Input is bounded to 64 KiB.

Canonical JSON uses sorted keys, compact separators, UTF-8, and one trailing newline. Its SHA-256 is
the configuration identity. Diagnostics name the field and rule but do not echo input. Actual lab
manifests and their addresses remain private; committed fixtures use anonymous examples.

## Builder and payload

`scripts/iso_chain.py prepare-initramfs --kernel-version VERSION --output FILE` runs only on
ppc64le, checks dracut and the named kernel tree, and invokes dracut without a shell. It uses
`--include` to install `assets/dracut/iso-chain-launch.sh` as an initqueue-settled hook and fixed
`--install`/`--force-drivers` arguments for the shell, `ip`, `curl`, required libraries, and virtio
networking. It includes no DHCP client and publishes without overwriting. Preparation is tested with
dracut 107-8.fc43 in an ephemeral VM session and does not modify the VM tooling repository.

`build --config FILE --grub-modules DIR --kernel FILE --initramfs FILE --output FILE` replaces the
experiment-only build contract. It validates all inputs before invoking `grub2-mkrescue`, embeds the
canonical manifest at `/iso-chain/config.json`, and stages the shared kernel and initramfs. GRUB has
one entry per profile, a five-second visible timeout, and a default matching `selected_profile`.
Each entry passes only validated `iso_chain.*` arguments, the chosen profile, and manifest digest.

`inspect ISO` extracts the embedded manifest with `xorriso`, validates it again, and prints canonical
JSON. It bounds extracted data and leaves no output on failure. Build and preparation use private
temporary directories beside the output and atomic no-replace publication.

## Launcher behavior

The dracut hook waits for udev to settle without starting networking, inventories non-loopback
interfaces, and compares normalized sysfs MAC values. Exactly one match proceeds; zero or multiple
matches enter dracut emergency mode after a fixed `adapter-match: failed` marker. No interface is
brought up on that path.

For one match, the hook assigns the address, brings up that interface, adds routes in manifest order,
writes a private resolver file when DNS is present, and runs `curl` once with failure reporting, no
redirects, a 30-second timeout, and a 1-byte output limit. It accepts only HTTP 200 or 206, discards
the byte, and prints fixed configuration, adapter, profile, and HTTP-pass markers without the URL or
network values. Any command failure enters emergency mode and never selects another profile.

## Threat model

The local operator controls manifests, payload paths, and build tools. Added boundaries are JSON into
the builder, manifest-derived values into GRUB/kernel arguments, sysfs interface data into the hook,
the HTTP response into curl, ISO bytes into the inspector, and console/packet captures into evidence
verification. Controls are strict schemas and bounds, argument vectors without a shell, restricted
tokens, exact MAC cardinality, no redirects, bounded time/output, regular-file checks, private
temporary state, concise diagnostics, and no-overwrite publication.

The HTTP server is trusted for reachability only; content authenticity is issue #5. Malicious build
tools, kernels, initramfs inputs, local root, DNS infrastructure, and firmware are outside this
change. No credential is accepted or embedded. Native PowerVM isolation and security policy remain
unassessed without an authorized LPAR.

## Verification

Unit tests fault the manifest parser, canonicalization, GRUB generation, dracut invocation, ISO
inspection, no-overwrite behavior, QEMU argument construction, evidence parsing, and fixed-error
redaction. Shell tests run the hook with fake sysfs and command boundaries for unique, missing, and
duplicate adapters; controlled faults prove each test turns red.

The ppc64le VM builds the shared initramfs, then boots two ISOs whose manifests differ in address,
profile, and digest. A fixed QEMU smoke mode supplies matched, missing, or duplicated MAC devices and
captures each netdev with `filter-dump`. A local HTTP server records the two expected probes. The
verifier requires the matching manifest/profile markers and rejects any DHCP UDP 67/68 packet by
examining the bounded pcap through `tcpdump -c 1` without publishing packet contents. Negative boots
must show the adapter failure and empty captures. Raw logs, pcaps, manifests, and generated media stay
private; the published report contains anonymous values and fixed pass/fail results.
