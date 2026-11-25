# Steam Collection Curator

**v0.3.0-alpha** · Python 3.11+ · MIT · [中文使用指南](docs/zh-CN.md)

Organize a Steam library from an HTML or CSV export you already have. Curator proposes one gameplay collection per classified game, with optional series, theme and experience collections. Eight empty manual collections give frequently used lists a place near the top. The player decides what to play, finish, revisit or set aside.

## Install and remove

For Codex, unpack the standalone Skill ZIP so its `steam-collection-curator` directory sits inside `.agents/skills` in your project or home directory. The directory contains `SKILL.md`, scripts, local configuration and references. Restart Codex if the skill does not appear, then invoke `$steam-collection-curator`. A source checkout works as a standalone CLI. Python's standard library is sufficient.

Uninstall by removing the installed skill directory. Plans, caches and Steam backups are stored separately. Decide independently whether to keep them and which collections to manage from Steam.

## Plan offline

In the skill directory, create an output directory outside the skill and repository. Replace the paths below with your own paths.

```sh
python scripts/curator.py /path/to/export.csv --output /path/to/private/plan.json
python scripts/curator.py /path/to/export.html --previous /path/to/private/approved.json --profile compact --output /path/to/private/next.json
python scripts/curator.py --manual-only --language en --output /path/to/private/manual.json
```

Use a saved SteamDB application table, or a UTF-8 CSV with AppID and game name columns. Use `--table-id` if the HTML has several application tables. Supply `--metadata` for local public facts, `--baseline` for legacy classification CSV, or `--decisions` for reviewed player choices. Choose `compact`, `balanced` (default) or `detailed`. Add `--experience` to propose experience collections. For manual names, copy the taxonomy to your private directory and edit the manual entries, keeping the codes. See [classification and review](references/classification.md) for input shapes.

The planner validates AppIDs, reconciles duplicate rows, applies typed and weighted rules, and carries forward previous classifications. The plan includes issues, notable overlap, additions and pending review. Missing rows are reported for inspection. Free-to-play status is a public fact and manual collections stay player-managed.

## Preview an optional Steam write

Use an existing CloudStorage configuration for the account you select. Preview is the default and the writer runs offline.

```sh
python scripts/write_steam.py --target /path/to/Steam/userdata/42/config/cloudstorage/cloud-storage-namespace-1.json --account 42 --plan /path/to/private/plan.json
```

On review, close Steam fully and repeat with `--apply --expect <preview_digest>` in an interactive terminal. Read the [writer and recovery guide](references/writer.md) for explicit removals, backups and recovery.

| Environment | Planner | Writer scope |
| --- | --- | --- |
| Windows | Python CLI | Native client, fixed local drive, supported JSON triplet |
| macOS | Python CLI | Native client, physical paths, supported JSON triplet |
| Linux and Steam Deck desktop | Python CLI | Native desktop process namespace, physical paths, supported JSON triplet |

The alpha writer is designed for these scopes. Synthetic tests and actual client verification are tracked separately in [test results](TEST_REPORT.md). Valve does not document this collection storage protocol as a public integration. Empty collections may be filtered, and Steam can apply newer cloud state. Restore is local and requires matching snapshots. Use CSV when an HTML variant needs JavaScript to build its rows or the structure is unsupported.

## Data and privacy

Curator takes user-provided files and has zero Steam credential requirements. Planning, review comparisons and writing are local. The optional lookup command transmits only manually selected public AppIDs to fixed public providers, with a local cumulative limit. The providers can retain request infrastructure information and the queried IDs. Keep the same private cache across runs for that limit to apply. Read the [privacy policy](docs/privacy.md).

## Design references

Curator combines incremental baselines, independent review and observable CloudStorage changes with an explicit local ownership registry. Inputs are user exports, and the planner and offline writer are separate commands. See [upstream snapshots and reuse scope](THIRD_PARTY_NOTICES.md) and the [organization principles](references/organization.md).

## FAQ

**No games were classified.** Check the pending reasons. Supply known public facts or approve a decision for selected titles. Known app type and evidence for a main gameplay category are separate inputs.

**A collection already exists.** Its name or stable ID can block automatic creation. Previously unregistered entries remain user-managed. See the writer guide before changing any existing collection.

**Steam shows an old result.** Check the intended account and local backup. Steam may synchronize from another device. Collect the transaction ID and local preview before deciding on recovery. Keep the configuration and personal data out of public issues.

**How do I report a security issue?** Follow [SECURITY.md](SECURITY.md).
