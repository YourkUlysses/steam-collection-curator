# v0.3.0-alpha release notes

Steam Collection Curator organizes a local SteamDB HTML or CSV export. The standalone Codex skill provides a reviewable classification plan and eight player-managed collections. The offline writer now supports incremental membership changes in registered collections, CloudStorage version and pending keys, and hash-verified local rollback.

**Install** by extracting the standalone ZIP to a Codex `.agents/skills` directory. See the [English README](../README.md) and [中文指南](zh-CN.md). License is MIT.

**Upgrade** by reusing an approved v0.2 plan as a classification baseline. Collections created by the old writer without a registry remain user-managed. Build a fresh v2 plan before previewing writes.

**Verification** uses synthetic Steam files and public app facts. Availability of real-client collections, Steam Deck hardware, empty-folder display and cloud reconciliation require separate acceptance. See the [test report](../TEST_REPORT.md).
