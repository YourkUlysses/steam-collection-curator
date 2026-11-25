# Third-party notices and design references

The listed snapshots were reviewed as source code. All five have an MIT license at the reviewed commit. Curator retains the MIT license of its supplied alpha and uses independent code for the design ideas listed here. The release includes no upstream library or writer source.

| Source snapshot | License | Concepts reviewed and used |
| --- | --- | --- |
| [Smirk1921/steam-collection-skill](https://github.com/Smirk1921/steam-collection-skill/tree/4c7caac76483b9a7fa2dee2afec7a3999e36aa2b) | MIT | AppID-based incremental baseline. This project's inputs replace upstream account and browser acquisition, and local writes use a narrower ownership policy. |
| [xr05shino23/steam-collection-skill-plus](https://github.com/xr05shino23/steam-collection-skill-plus/tree/a31f1f763b35f416ba6e48f2ab1b2504d6e474ba) | MIT | Compare independent reviews and report same-dimension Jaccard overlap. |
| [ozh3272674/steam-collection-skill](https://github.com/ozh3272674/steam-collection-skill/tree/5363c41383003ddd4e95cbae3f158cecaf5cab33) | MIT | Stable collection codes, SteamID32/SteamID64 conversion and versioned baselines. Curator derives IDs from the original Curator namespace and requires a successful local registration. |
| [okabeeer/SteamLibraryOrganizer](https://github.com/okabeeer/SteamLibraryOrganizer/tree/c1760905bf351cfa3529bb23bbb8c7ca131f8a29) | MIT | Three-file CloudStorage protocol, dynamic collection filters, tombstones, version counters, pending keys, weighted gameplay evidence and caching. Curator supports the modern format and requires explicit account selection. VDF and LevelDB stay outside this scope. |
| [FunnyEntity/steam_library_exporter](https://github.com/FunnyEntity/steam_library_exporter/tree/b5995f28c5e75b9650d52c18d7ee3903d8e8bcc0) | MIT | UTF-8 BOM and localized CSV columns, optional public facts and handling missing metadata. Ownership retrieval uses the user's local export. |

Static empty collections use empty member arrays. Display and cloud persistence are client behaviors and remain independent acceptance items. Platform comparisons informed native process checks and explicit physical paths. Steam and SteamDB are separate products. This project is unaffiliated with them.

Public metadata may be queried through [SteamCMD API](https://www.steamcmd.net/) and [SteamSpy](https://steamspy.com/about/). SteamDB provides the export format under the [site’s access rules](https://steamdb.info/faq/#can-i-use-auto-refreshing-plugins-or-automatically-scrape-crawl-steamdb). Fixtures contain synthetic structural data and public app titles. Book titles in the organization reference identify design inspiration.
