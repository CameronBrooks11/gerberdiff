# Security policy

## Supported versions

Only the latest released minor version is supported.

| Version | Supported |
| ------- | --------- |
| 0.29.x  | Yes       |
| < 0.29  | No        |

## Reporting a vulnerability

**Do not open a public issue for security vulnerabilities.**

Please report them via
[GitHub private security advisories](https://github.com/CameronBrooks11/gerberdiff/security/advisories/new).

Include:

- A description of the vulnerability and its potential impact
- Steps to reproduce or a proof-of-concept
- Affected versions

You will receive an acknowledgement within **5 business days** and a resolution or
mitigation plan within **30 days** where feasible.

## Scope

gerberdiff is a local CLI tool that reads Gerber/Excellon files from disk.  
It does not start network servers, accept remote input, or persist credentials.  
The most relevant attack surface is **malicious Gerber files** that could cause
path traversal, resource exhaustion, or arbitrary code execution through crafted macros.
