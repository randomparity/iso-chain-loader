# Example configurations

Synthetic structural fixtures: documentation addresses, placeholder digests and placeholder keys.
Adapt them as the [guides](../docs/guides/) describe; none is a verified installer input.

Every `examples/*.json` has one row below. `ExampleConfigurationTests` parses this table, so a new
example adds a row here and nothing else. The test fails on an unindexed file, a link to a missing
file, an unknown form, or a file that fails `validate-config` in its documented form.

The **Form** column is the exact input form:

| Form | Validated as |
| --- | --- |
| `config` | `validate-config --config FILE` (single manifest) |
| `target base=BASE` | `--target FILE --base-config BASE` |
| `target base=BASE block=BLOCK` | `--target FILE --base-config BASE --block-config BLOCK` |
| `base` | Base manifest; must be named by a `base=` |
| `block` | Block for target rows; must be named by a `block=` |

A `base=` may name a `config` row or a `base` row; either supplies its `version`, `source`
and `profiles`.

| File | Distribution | Mode | Form |
| --- | --- | --- | --- |
| [fedora.json](fedora.json) | Fedora 44 | Kickstart fixture | `config` |
| [rocky-interactive.json](rocky-interactive.json) | Rocky 9.8 | Interactive | `config` |
| [rocky-unattended.json](rocky-unattended.json) | Rocky 9.8 | Keyed unattended | `config` |
| [base.json](base.json) | Rocky 9.8 | Base | `base` |
| [target.json](target.json) | Rocky 9.8 | Target/base | `target base=base.json` |
| [preset-block.json](preset-block.json) | Rocky 9.8 | Preset block | `block` |
| [rocky-system-a.json](rocky-system-a.json) | Rocky 9.8 | Preset system A | `target base=rocky-unattended.json block=preset-block.json` |
| [rocky-system-b.json](rocky-system-b.json) | Rocky 9.8 | Preset system B | `target base=rocky-unattended.json block=preset-block.json` |
| [rocky-london-block.json](rocky-london-block.json) | Rocky 9.8 | London block | `block` |
| [rocky-london-system-a.json](rocky-london-system-a.json) | Rocky 9.8 | London system A | `target base=rocky-unattended.json block=rocky-london-block.json` |
| [rocky-london-system-b.json](rocky-london-system-b.json) | Rocky 9.8 | London system B | `target base=rocky-unattended.json block=rocky-london-block.json` |
| [rocky-operator.json](rocky-operator.json) | Rocky 9.8 | Operator Kickstart | `config` |
| [rhel-interactive.json](rhel-interactive.json) | RHEL 9.8 | Interactive | `config` |
| [rhel-unattended.json](rhel-unattended.json) | RHEL 9.8 | Keyed unattended | `config` |
| [rhel-operator.json](rhel-operator.json) | RHEL 9.8 | Operator Kickstart | `config` |
| [ubuntu-interactive.json](ubuntu-interactive.json) | Ubuntu 26.04.1 | Interactive | `config` |
| [ubuntu-unattended.json](ubuntu-unattended.json) | Ubuntu 26.04.1 | Keyed unattended | `config` |
| [ubuntu-block.json](ubuntu-block.json) | Ubuntu 26.04.1 | Preset block | `block` |
| [ubuntu-system-a.json](ubuntu-system-a.json) | Ubuntu 26.04.1 | Preset system A | `target base=ubuntu-unattended.json block=ubuntu-block.json` |
| [ubuntu-system-b.json](ubuntu-system-b.json) | Ubuntu 26.04.1 | Preset system B | `target base=ubuntu-unattended.json block=ubuntu-block.json` |
| [opensuse-interactive.json](opensuse-interactive.json) | openSUSE Leap 15.6 | Interactive | `config` |
