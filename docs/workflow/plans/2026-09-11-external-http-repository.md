# Plan: external HTTP(S) repository validation

1. Extend manifest source validation to accept canonical `https://` origins
   while retaining `http://` for local/test use; add tests for both schemes and
   forbidden credentials/query/fragment forms.
2. Add a bounded read-only `validate-external-source` implementation using the
   standard library, with strict response status, redirect, size, and digest
   checks and JSON output.
3. Add deterministic server tests and an opt-in environment-gated mirror test.
4. Document external preparation, network/TLS requirements, canonical manifest
   examples, the command, and the access-log evidence boundary.
5. Run repository checks, then execute the command in the ppc64le VM against an
   explicitly supplied mirror when available; otherwise record the skipped
   external arm while still running the local deterministic proof.
