# Classification and review

## Local inputs

Use UTF-8 HTML or CSV. A CSV needs AppID and name. Recognized headers include `AppID`, `App ID`, `应用ID`, `Name`, `Game Name` and `游戏名称`. Optional type headers include `App Type`, `Type` and `类型`. HTML requires static application table rows. App links or `tr[data-appid]` identify rows. Use `--table-id` when the export includes several tables. The checked fixture uses a SteamDB-style table with public titles. Authenticated or JavaScript-only variants require separate validation.

`--metadata` accepts an object keyed by canonical AppID. Values may include `type`, `tags` (a list or vote-count map), `genres`, an explicit `franchise`, `free` and `store_status`. Missing evidence stays unknown.

```json
{"620":{"type":"game","tags":{"Puzzle":100,"Puzzle-Platformer":80},"genres":["Adventure"],"free":false,"store_status":"available"}}
```

App types supported by the local schema include game, DLC, Demo, Playtest, soundtrack, tool and launcher. Explicit status distinguishes delisted from missing or unknown. A provider timeout or missing result is insufficient evidence of delisting or a Playtest. The template groups auxiliary types under numbered categories while retaining the specific type on each record.

Use `--previous` with the plan the player approved. Version 1 plans are accepted as classification baselines. Legacy `--baseline` CSV columns include `appid,category,collections,confidence,needs_review`, with `target` as an alternate display label. Conflicting confirmed baselines enter review. Types and narrow tags drive routing. Tag votes normalize relative to the strongest tag. Generic tags contribute weak evidence. The best match leads and at most two other matching tags contribute a quarter of their weight. A score below 4 or lead below 1.5 stays pending. Each template may alter weights and independent evidence requirements. Gameplay presets map fine categories into stable parent categories. Exact franchise evidence supports series assignments.

## Optional public lookups

Use a single private cache across runs. Preview a manually selected set of 1–10 pending AppIDs.

```sh
python scripts/metadata.py --plan /path/to/private/plan.json --cache /path/to/private/cache.json --appid 620
```

Review the displayed IDs and hosts. If the player agrees, add `--fetch --expect <preview_digest>` and confirm in the terminal. Then run the planner with `--metadata /path/to/private/cache.json`. SteamCMD API supplies type evidence and SteamSpy supplies tag votes. Lookup failures leave records eligible for review. A cache hit bypasses the network. The command checks cumulative disclosures for the current library against the cache ledger. Different caches, deletion of the cache or different exports can change what the ledger can verify. Network use is optional.

## Independent review

Extract public AppID and known type for a small player-selected subset via `review.py --plan <plan> --appid <id>`. Keep export titles and provider prose out of review prompts. A reviewer can consult public facts about these apps. Reviewer B uses the same facts and current taxonomy with fresh context and without Reviewer A’s decisions. For example, each creates a local JSON object keyed by AppID with `primary` and optional `extra` codes. Use `review.py --plan <plan> --compare <pass-a.json> <pass-b.json>` to find agreement and disagreement. The player may also review directly, including single-app libraries.

After the player approves the decisions, pass **only** those decisions to the planner with `--decisions`. For example, `{"620":{"primary":"29","extra":[],"type":"game"}}`. Reasons, unresolved entries and overlaps remain in the private plan. Output plans contain personal library data and should stay local.
