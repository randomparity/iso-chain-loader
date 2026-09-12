set shell := ["sh", "-eu", "-c"]

setup:
    #!/bin/sh
    set -eu
    if ! command -v uv >/dev/null 2>&1; then
        echo "error: uv 0.12.12 or a compatible release is required" >&2
        echo "       install it from https://docs.astral.sh/uv/" >&2
        exit 1
    fi
    uv venv --allow-existing --python 3.14 .venv
    uv pip install --require-hashes --python .venv/bin/python -r requirements-dev.lock
    hook_path=$(git rev-parse --git-path hooks/pre-commit)
    if [ -e "$hook_path" ] && ! cmp -s .githooks/pre-commit "$hook_path"; then
        echo "error: refusing to replace existing hook at $hook_path" >&2
        exit 1
    fi
    install -m 0755 .githooks/pre-commit "$hook_path"

build-image:
    docker build --file Containerfile --tag iso-chain-builder:44 .

check: check-justfile check-whitespace check-python-lint check-python-format check-tests check-markdown check-secrets

check-justfile:
    just --fmt --check

check-whitespace:
    #!/bin/sh
    if git grep -n -I -E '[[:blank:]]+$' -- .; then
        exit 1
    else
        status=$?
    fi
    if [ "$status" -eq 1 ]; then
        exit 0
    fi
    exit "$status"

check-python-lint:
    .venv/bin/ruff check --no-cache .

check-python-format:
    .venv/bin/ruff format --check --no-cache .

check-markdown:
    .venv/bin/rumdl check --config pyproject.toml --no-code-block-tools \
        --no-cache --deny-config-warnings .

check-secrets:
    #!/bin/sh
    set -eu
    paths=$(mktemp)
    baseline=$(mktemp)
    trap 'rm -f "$paths" "$baseline"' EXIT HUP INT TERM
    git ls-files -z > "$paths"
    cp .secrets.baseline "$baseline"
    xargs -0 -x -n 2147483647 .venv/bin/detect-secrets-hook --json \
        --exclude-files '^\.secrets\.baseline$' --baseline "$baseline" -- < "$paths"

fix:
    .venv/bin/ruff check --fix .
    .venv/bin/ruff format .
    .venv/bin/rumdl fmt --config pyproject.toml --no-code-block-tools \
        --no-cache --deny-config-warnings .
    just check

check-tests:
    bash tests/test_iso_chain_launch.sh
    .venv/bin/python -m unittest discover -s tests -v
