set shell := ["sh", "-eu", "-c"]

setup:
    #!/bin/sh
    set -eu
    python3 -m venv .venv
    .venv/bin/python -m pip install --disable-pip-version-check \
        --require-hashes -r requirements-dev.lock
    hook_path=$(git rev-parse --git-path hooks/pre-commit)
    if [ -e "$hook_path" ] && ! cmp -s .githooks/pre-commit "$hook_path"; then
        echo "error: refusing to replace existing hook at $hook_path" >&2
        exit 1
    fi
    install -m 0755 .githooks/pre-commit "$hook_path"

check: check-justfile check-whitespace

check-justfile:
    just --fmt --check

check-whitespace:
    #!/bin/sh
    if git grep -n -I -E '[[:blank:]]+$' -- . ':!*.md'; then
        exit 1
    else
        status=$?
    fi
    if [ "$status" -eq 1 ]; then
        exit 0
    fi
    exit "$status"
