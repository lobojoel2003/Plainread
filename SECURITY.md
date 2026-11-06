# Security policy

Plainread handles very private documents, so security and privacy problems are
treated as the highest priority.

## Supported versions

Only the latest release receives fixes. Check yours with `plainread --version`.

## Reporting a problem

Please report security problems **privately** through
[GitHub security advisories](https://github.com/lobojoel2003/Plainread/security/advisories/new).
Do not open a public issue, and never include a real letter.

You can expect a first reply within 7 days.

## Design commitments

- Letters are processed in memory on the user's device and are never written to
  disk, logged or sent over the network.
- The server listens on `127.0.0.1` unless the user explicitly chooses another
  address.
- The optional AI connection is refused for non-local addresses unless
  `PLAINREAD_ALLOW_REMOTE_AI=1` is set.
- The web app loads no external resources and ships with a strict Content
  Security Policy; letter text is always rendered as text, never as HTML.
- Uploads are size-limited and image decompression bombs are rejected.
