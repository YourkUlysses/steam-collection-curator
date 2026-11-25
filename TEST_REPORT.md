# v0.3.0-alpha verification

## Local results

Windows and Python 3.12.14 on 2026-11-25. Ran `python -B -m unittest discover -s tests -v` with **46 passed and 2 skipped**. The Windows sandbox did not allow creation of live hard links or symbolic links. An independent test exercised the CloudStorage reparse rejection path with synthetic file metadata.

The suite covers offline planning, representative SteamDB HTML and localized CSV, incremental and restored approvals, weighted classification, metadata failures, untrusted review data, protected collections, stable IDs, versions and sidecars, no-write previews, stale hashes, concurrent Curator operations, transaction interruption, backup and recovery. An independent forward test confirmed the previous classification survived a preset change and an existing populated manual group survived the writer preview.

The previous v0.2 baseline passed 21 archived tests. Version 0.3 tests use synthetic Steam configuration and public or synthetic app facts.

## Verification limits

- The SteamDB fixture reconstructs a static table from the supported row structure and public game facts. Authenticated, alternate and JavaScript-only export variants require separate verification.
- Windows, macOS and Linux CI jobs are configured. Hosted results require the approved private push. Hardware and live-client acceptance require a separate authorized session.
- Empty folder display, Steam restart persistence, production metadata endpoint interaction and cloud reconciliation remain pending. Process and interruption tests inject known states. Windows copies preserve a source DACL before staging bytes, and back up the primary data separately for recovery. These tests do not establish guarantees for unusual Windows ACL or filesystem configurations.
- The writer expects Steam to stay closed. Hash checks and its local lock mitigate concurrent writes, within the limitations of an undocumented, multi-file store.
