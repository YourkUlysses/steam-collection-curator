# Data and privacy

The planner reads only the export, configuration and optional local metadata, baseline and decisions you select. It retains AppIDs, names and classification evidence in a plan. Spreadsheet data is read as text. HTML is parsed as inert text and linked resources are ignored. Plans and preview data use JSON. Keep plan files, logs and Steam backups on your machine and out of chat or issue attachments.

The optional metadata command sends the approved public AppIDs to SteamCMD API and SteamSpy over HTTPS. It does not send an export file, private titles, account identity, session state or telemetry. The providers can log request addresses and IDs. Keep a consistent local cache and review each proposed lookup. Reviewers receive only selected public facts.

The writer is offline and needs access only to the explicitly selected account's collection store and its local writer state. It does not need Steam credentials, browser data or elevated privileges. Backup directories contain private configuration. Use a local user-owned directory and keep OS permissions restrictive.

Uninstalling the skill leaves local data separate. Delete the data only when you no longer need the plans or backups. For a stuck metadata lookup lock after an interruption, first confirm there is no active lookup and keep the cache and disclosure ledger intact.
