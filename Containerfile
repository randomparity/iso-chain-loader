# Build image for the ppc64le launcher ISO: it supplies grub2-mkrescue, xorriso, and the packaged
# powerpc-ieee1275 GRUB modules that macOS hosts cannot install natively.
FROM fedora:44@sha256:43b29f65a41eb9c35e1cd5323e3bdf3b655c2357a9f4f1ff2f9c2798e5045d80

RUN dnf --assumeyes --setopt=install_weak_deps=False install \
        grub2-tools-extra \
        grub2-tools \
        grub2-common \
        grub2-ppc64le-modules \
        xorriso \
        python3.14 \
    && dnf clean all
