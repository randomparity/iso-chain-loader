# Target-bound media for hmcpctl

hmcpctl builds media after it creates a partition and reads its adapter's MAC
([ADR 0015](../adr/0015-emit-a-target-bound-producer-result.md)). Instead of `--config`, `build`
and `container-build` take a per-partition target request and an operator base manifest:

```json
{
  "format": "iso-chain-target-v1",
  "profile": "rocky-9.8",
  "lpar": "sys-r1",
  "mac": "52:54:00:12:34:56",
  "network": {
    "address": "10.0.2.15/24",
    "routes": [{"destination": "0.0.0.0/0", "gateway": "10.0.2.2"}],
    "dns": ["10.0.2.3"]
  },
  "operation_binding": "00000000000000000000000000000001"
}
```

The base manifest holds exactly `version`, `source`, and `profiles`, as prepared in each
distribution guide's [Prepare the profile](rocky.md#prepare-the-profile) section. `profile` names a
distribution and release and must match exactly one base profile; the ISO carries only that profile,
under its base key, and its embedded manifest records `operation_binding`. `lpar` is a lower-case
identifier of at most 32 characters and becomes the installer hostname.

The request may also carry `ssh_authorized_keys`, 1 to 16 public keys that are each one printable
line of 1 to 8,192 characters, and `login_user`, matching `[a-z_][a-z0-9_-]{0,31}`; they appear
together or not at all, the same bounds hmcpctl applies in built mode. They become top-level fields
of the composed manifest, so its digest binds them, and they never reach the kernel command line
or the result ([ADR 0017](../adr/0017-carry-login-values-in-the-manifest.md)). The Rocky, RHEL
and Ubuntu profiles apply them, as their unattended installs
([Rocky](rocky.md#unattended-installation), [RHEL](rhel.md#unattended-installation),
[Ubuntu](ubuntu.md#unattended-installation)) describe, so `build` and
`container-build` refuse a manifest carrying them unless every profile is Rocky or RHEL, or every
profile is Ubuntu. Requests
and manifests may be up to 2 MiB.

A bound request must be published, and only a bound request may be. The operator configures the
fixed part of the command, and only the request path varies:

```sh
umask 077
scripts/iso_chain.py container-build --kernel LAUNCHER/vmlinuz \
  --initramfs LAUNCHER/initramfs.img --profiles PREPARED --base-config BASE.json \
  --publish-dir PUBLISH-DIR --publish-url https://MEDIA-HOST/iso --target REQUEST.json
```

The ISO is linked, never replaced, as `PUBLISH-DIR/<iso_sha256>.iso`. Its mode is the building
process's: `build` follows its umask, while `container-build` gets the container's default
(world-readable with the pinned image), so control access through the publish directory itself.
The publish URL follows the `source` rules, which forbid `?` and `#` in both URLs. `build` prints
one line of canonical JSON on stdout, and child tools' output goes to stderr:

| Field | Value |
| --- | --- |
| `format` | `iso-chain-media-v1` |
| `iso_sha256`, `iso_size` | the ISO's SHA-256 and byte size |
| `manifest_sha256` | the embedded manifest's SHA-256 |
| `distribution`, `release`, `architecture` | the profile's, and `ppc64le` |
| `mac`, `network` | the request's, `network` without `mac` |
| `operation_binding`, `url` | published media only; `url` is the publish URL plus `/<iso_sha256>.iso` |

An unbound request, or `--config`, with `--output` prints the same result without the last two
fields; that is hmcpctl's prepared mode. A result names one installer, so a `--config` build
whose manifest holds several profiles prints nothing. `inspect --result ISO` prints the result for
an existing one-profile ISO and refuses a published, bound one. `smoke`, the `install-*`, and
the `verify-*` commands take the embedded manifest, which `inspect ISO` recovers. Nothing removes
published media: the operator deletes `PUBLISH-DIR/*.iso` files and any `.iso-chain-*`
directories an interrupted build left.
The build is not byte-reproducible, so every run, an identical retry included, publishes a new ISO.

## Privacy and proof limits

Keep manifests, media, source trees, console logs, access logs, disk hashes and packet captures in
private storage (`umask 077`), using fresh output paths for every run, because they can contain
machine or network identifiers. Local checks and CI do not build or boot media. Emulator results
establish only their recorded QEMU boundary; native PowerVM requires separate proof.
