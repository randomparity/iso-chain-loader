# Fedora Installer VM Experiment

Date: 2026-09-09

## Result

A ppc64le QEMU pSeries/POWER9-mode guest booted the optical launcher, configured only the declared
static IPv4 interface, fetched and verified the Fedora Server 44 ppc64le kernel and augmented
initramfs from local HTTP, and entered Anaconda through kexec. The text installer showed all of the
following in the same run:

- the intended local HTTP repository as the installation source;
- Fedora Server Edition as the software selection;
- the statically configured `iso0` interface as connected; and
- the intended virtio test disk as an available installation destination.

The run stopped before beginning installation. QEMU exposed a writable disposable snapshot to the
guest so Anaconda could discover the disk; the qcow2 backing file had the same SHA-256 digest before
and after the run. Native PowerVM was not run, so this proves the emulator path only.

## Inputs and environment

An x86_64 host ran QEMU 10.2.2 with TCG, pSeries, POWER9 mode, two CPUs, and 32 GiB configured RAM.
The guest reported 32,581 MiB `MemTotal`, 32,082 MiB `MemAvailable`, and 6,818,758,656 available
bytes in `/run` at the launcher gate. The verified Fedora Server 44 compose 1.7 DVD was
3,013,869,568 bytes with SHA-256
`d0d11c768e2933a421e81db2606eafd512f9d75a15e0d591277837d2c97c908b`.

Source preparation produced an augmented installer initramfs of 1,080,101,512 bytes with SHA-256
`3fb88548c5e8b76a8eda890721e846f5c73c915324070aaa57a4eb5a41aafc51`. The canonical anonymous
manifest digest was `0dbf9aa21157735d984a026b1f93c03978b5dc4121ebde816c5596b3b907ddde`.
Raw manifests, network values, console logs, HTTP records, captures, media, and disk paths remain in
private storage.

## Evidence

The launcher emitted one ordered sequence of configuration, adapter, profile, memory, artifact,
kexec-load, and kexec-execute markers. The local server then recorded ten successful requests: the
four launcher-bound artifacts followed by Fedora repository metadata requested after kexec. Every
path was within the selected profile or repository, the executable and pinned metadata response
sizes matched the manifest, and the installer UI confirmed the intended source.

The full capture included the expected HTTP transfer and exceeded the verifier's 64 MiB evidence
bound. A same-run derivative retained only IPv6 or DHCP packets using the verifier's protocol
filter. It was a valid empty capture containing only its header, and `verify-pcap` returned:

```text
dhcp-ipv6: absent
```

The canonical run record bound the manifest, console, access log, filtered capture, and both disk
hash files by SHA-256. `verify-fedora-evidence` returned:

```text
manifest: passed
memory: passed
http-evidence: passed
disk-unchanged: passed
dhcp-ipv6: absent
same-run: operator-reviewed
installer-readiness: operator-reviewed
storage-visibility: operator-reviewed
intended-source: operator-reviewed
```

An 8 GiB calibration arm failed before artifact traffic because `/run` lacked space for the
declared initramfs plus the fixed 1 GiB headroom. The 32 GiB arm passed all launcher gates. Earlier
diagnostic runs identified and fixed the missing appended-archive directory, Fedora 44's flattened
runtime layout, an obsolete root-device wait, missing text-mode selection, and disk visibility.
Only the final fresh run is the acceptance evidence.

## Boundary

No native LPAR, HMC, VIOS, or physical storage was mutated. The remaining native gap includes
PowerVM optical behavior, firmware and Secure Boot policy, VIOS mapping behavior, real-P9 storage
visibility, and cleanup after a native mapping window. Those require a separately authorized run.
