# Security Policy

## Reporting a vulnerability

Report privately through
[GitHub Security Advisories](https://github.com/ChelseaKR/ca-tariff-parse/security/advisories/new).
Please do not open a public issue for a security report.

Expect an acknowledgement within 7 days.

## Supported versions

The most recent release on `main` is supported. This project is pre-1.0 and
carries no backport commitment.

## What counts as a vulnerability here

This tool has a small attack surface: it is a local command line program with
no server, no account, no credentials and no telemetry. The findings that
matter most are:

- **A wrong or uncited value.** The parser emitting a price, window or
  condition that the cited document does not contain, or emitting anything at
  all without provenance. This is treated with the same seriousness as a
  memory-safety bug, because someone could rely on the number.
- **Silent loss.** Content the parser drops without reporting it as unparsed.
- **Digest bypass.** Anything that lets a document be parsed under a manifest
  id whose SHA-256 it does not match.
- Untrusted input handling in the PDF reading path, including via
  `pdfplumber`.
- Supply-chain issues in the locked dependency set.

## Scope notes

- Parsing is offline. `fetch` is the only command that makes a network request,
  and it verifies what it downloaded against the pinned digest.
- Source documents are fetched from their publishers, not redistributed here.
  A concern about a document's contents belongs with its publisher.
- This project is not affiliated with any utility, and a security report about
  a utility's own systems should go to that utility.
