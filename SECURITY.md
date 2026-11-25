# Security policy

Report vulnerabilities privately through GitHub private vulnerability reporting when it is available. Otherwise request a private contact channel from the maintainers before sending details. Avoid posting real Steam data, account IDs, paths, exports, credentials or configuration backups.

The current supported development line is v0.3.0-alpha. Use synthetic fixtures or public apps to describe issues. See [Data and privacy](docs/privacy.md), [writer safety](references/writer.md) and [test results](TEST_REPORT.md).

The writer is an experimental integration with an undocumented client format. Never enable a write while Steam is active. Unsupported formats and unverified process state fail closed. The standard-library CLI relies on normal OS access controls. Keep its inputs and private directory under your control. The writer's checks reduce races but do not guarantee safety against a concurrent process with the same filesystem privileges.
