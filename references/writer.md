# Offline writer, backups and rollback

The supported layout on native desktop clients is an existing set of files under `userdata/<SteamID32>/config/cloudstorage`. Provide the physical path to `cloud-storage-namespace-1.json` and the same account as a SteamID32 or public individual SteamID64. The writer requires valid `cloud-storage-namespaces.json` and `cloud-storage-namespace-1.modified.json` sidecars. Unknown layouts and environments such as WSL or Flatpak are outside this alpha scope. On Unix, select a physical directory owned by the current OS user.

The writer checks for Steam and known helpers with the system process listing. Before apply, exit Steam entirely with its normal Quit/Exit command. Check Steam Deck Desktop Mode and other Steam sessions on the same machine. Process checks operate within the current OS process namespace. The writer can report local pending keys and their changes. Remote state and conflicts become visible through the Steam client.

## Preview and apply

```sh
python scripts/write_steam.py --target <collection-json> --account <id> --plan <plan-json>
python scripts/write_steam.py --target <collection-json> --account <id> --plan <plan-json> --apply --expect <preview-digest>
```

Keep the detailed diff local. The player types `APPLY` after comparing the target and changes. The digest covers the account, path, plan, intended operations, registry and all three Steam files. A new preview is required if these change.

The local registry records collection IDs and AppIDs inserted by Curator. Existing manual, dynamic, hidden, favorite and unrelated entries are preserved. A tool-created manual collection retains its members after being renamed or filled in Steam. Unregistered collections are protected even if their IDs match the v0.2 format. If needed the player can migrate an old collection using the client UI. New manual names apply at creation. A primary conflict with a different managed primary requires explicit review.

Use `--changes <private-json>` with the same plan for intentional moves or removals. The file is an array such as `[{"appid":620,"from":"29","to":"02"}]`. Omit `to` to request removal. A move destination must match the reviewed plan, and the source member must have been inserted by this tool. Review the exact diff and provide the additional `CONFIRM REMOVAL` response. This changes collection membership only.

## Backups, rollback and in-progress recovery

Each successful write prints a transaction ID. Its `.curator-backup-<id>` directory contains the prior bytes and before/after hashes of the Steam triplet and the registry. Keep an independent protected copy if needed. A local lock serializes Curator operations. Each file is replaced atomically, and a transaction journal records the multi-file change for recovery. The checks narrow races with other software. Keep Steam closed throughout.

- For rollback, replace `--plan <plan-json>` with `--rollback <transaction-id>`, preview, then add `--apply --expect <preview-digest>` and confirm. It requires all current files to match the transaction’s after-hashes. Restoration may remove tool-created collections from that transaction.
- If a transaction was interrupted and the journal remains, use `--recover` in place of `--plan`. Preview, review and confirm as above. Recovery accepts only the files matching the before or after hashes in the pending transaction.
- If Steam or another process changed files, preserve the current snapshot and backup. Inspect locally and use Steam’s UI for recovery if the matching-hash check fails.

CloudStorage uses version counters plus an upload queue. The tool advances local versions for changed keys and preserves existing pending entries. Steam can still reconcile with newer state from another device. Local rollback cannot reverse remote state. The initial release requires independent real-client verification of empty collections, startup, cloud changes and app visibility.
