# Security Policy

This tool runs locally, collects no data, sends nothing anywhere, and needs no API key or secret. Its only network call is the optional `--online` check, which makes one unauthenticated read of the public GitHub API for the checked repo's description and topics. It never reads a file it was not asked to check, and it never writes to the checked repo.

If you find a case where it could do otherwise, please open an issue describing the exact commands and input. Do not include any real secret in the report.
