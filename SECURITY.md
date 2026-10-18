# Security Policy

## Supported versions

matrixark is pre-1.0. Security fixes target the latest `main` and the most recent
published `0.x` release.

## Reporting a vulnerability

Please report suspected vulnerabilities **privately** via GitHub Security Advisories
— use **"Report a vulnerability"** on the Security tab of
<https://github.com/matrixarkai/matrixark/security/advisories/new> — rather than
opening a public issue or pull request.

Include, if possible:

- a description of the issue and its impact,
- the affected version or commit,
- steps to reproduce or a proof of concept.

We aim to acknowledge reports within a few business days and will coordinate a fix
and a disclosure timeline with you.

## Scope

Because matrixark ingests and retrieves context on behalf of callers, **defects that
cross a boundary between callers are treated as security issues, not merely bugs**:
retrieval that returns another tenant's or another session's records, a scope or
filter that admits everything when it was asked to admit one thing, ingested content
that is acted on as an instruction rather than stored as data, or a hook that
forwards more of a conversation than the caller asked it to. Credential handling
belongs here too: a key, token or endpoint that reaches a log, a report or a stored
record is in scope whether or not it was ever transmitted.

Defects in a deployment's own operating decisions are out of scope, but a
configuration this project ships as a **default** is in scope: if a default is
unsafe, the default is the bug.
