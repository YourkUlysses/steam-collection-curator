#!/usr/bin/env python3
"""Offline Steam CloudStorage writer. Preview is the default."""
import argparse
import base64
import csv
from contextlib import contextmanager
import ctypes
import hashlib
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time

from common import (appid, decode, encode, file_info, label_key, path_for, read, require,
                    sha, stage, sync_dir, validate_plan, write_local)

MAIN = "cloud-storage-namespace-1.json"
MODIFIED = "cloud-storage-namespace-1.modified.json"
VERSIONS = "cloud-storage-namespaces.json"
REGISTRY = ".curator-registry.json"
JOURNAL = ".curator-transaction.json"
PREFIX = "user-collections."
FILES = (MAIN, VERSIONS, MODIFIED, REGISTRY)
STEAM64 = 76561197960265728
MAX_VERSION = 2**64 - 1
STATIC_KEYS = {"id", "name", "added", "removed"}


def account32(value):
    require(re.fullmatch(r"[1-9][0-9]{0,19}", value), "Invalid Steam account ID")
    number = int(value)
    if number > STEAM64:
        number -= STEAM64
    require(0 < number <= 2**32 - 1, "Expected a public individual SteamID32 or SteamID64")
    return str(number)


def target_dir(value, account):
    require(sys.platform in {"win32", "darwin", "linux"}, "Unsupported writer platform")
    target = path_for(value)
    require(tuple(p.name for p in (target, *target.parents[:4])) ==
            (MAIN, "cloudstorage", "config", account, "userdata"), "Target does not match the selected account")
    if sys.platform == "win32":
        require(ctypes.windll.kernel32.GetDriveTypeW(str(target.anchor)) == 3, "Expected a fixed local drive")
    else:
        require(target.parent.stat().st_uid == os.geteuid(), "CloudStorage belongs to a different OS user")
    if sys.platform == "linux":
        platform = os.uname().release.casefold()
        parts = {part.casefold() for part in target.parts}
        require("microsoft" not in platform and not Path("/.dockerenv").exists()
                and not Path("/run/.containerenv").exists() and not
                (parts & {"com.valvesoftware.steam", ".wine", "snap"}),
                "Expected native desktop Steam and its process namespace")
    return target.parent


def system_tasklist():
    buffer = ctypes.create_unicode_buffer(32768)
    size = ctypes.windll.kernel32.GetSystemDirectoryW(buffer, len(buffer))
    require(0 < size < len(buffer), "Cannot locate Windows system tools")
    return str(Path(buffer.value) / "tasklist.exe")


def steam_stopped():
    try:
        if sys.platform == "win32":
            command = [system_tasklist(), "/FO", "CSV", "/NH"]
        elif sys.platform in {"linux", "darwin"}:
            command = ["/bin/ps", "-A", "-o", "comm="]
        else:
            return False
        result = subprocess.run(command, capture_output=True, text=True, errors="strict",
                                timeout=10, check=True)
        if sys.platform == "win32":
            rows = list(csv.reader(result.stdout.splitlines(), strict=True))
            require(rows and all(len(r) >= 4 and r[1].isdigit() for r in rows), "Unknown process listing")
            names = [r[0] for r in rows]
        else:
            names = [s.strip() for s in result.stdout.splitlines() if s.strip()]
            require(bool(names), "Unknown process listing")
        blocked = {"steam", "steam.exe", "steam_osx", "steam.sh", "steamservice", "steamservice.exe",
                   "gameoverlayui", "gameoverlayui.exe", "steamloader", "steam-runtime-launch-client",
                   "steam-runtime-launcher-service", "steam-runtime-l", "steam-runtime-la", "steamwebhelper.exe"}
        for name in names:
            basename = name.replace("\\", "/").rsplit("/", 1)[-1].casefold()
            if basename in blocked or basename.startswith("steamwebhelper"):
                return False
        return True
    except (ValueError, OSError, csv.Error, subprocess.SubprocessError):
        return False


def collection_key(code):
    raw = hashlib.sha256(("steam-collection-curator:v1:" + code).encode()).digest()[:9]
    return PREFIX + "uc-" + base64.b64encode(raw).decode("ascii")


def version(value):
    require(type(value) in (int, str) and re.fullmatch(r"[0-9]{1,20}", str(value))
            and int(value) <= MAX_VERSION, "Invalid namespace version")
    return int(value)


def appset(items):
    require(type(items) is list, "Invalid Steam member list")
    return {appid(a) for a in items}


def snapshot(directory):
    result = {}
    for name in FILES:
        path = path_for(directory / name, missing=name == REGISTRY)
        result[name] = read(path) if name != REGISTRY or path.exists() else None
    return result


def hashes(files):
    return {name: sha(data) if data is not None else None for name, data in files.items()}


def namespace(files, account):
    pairs, versions, modified = (decode(files[n]) for n in (MAIN, VERSIONS, MODIFIED))
    registry = decode(files[REGISTRY]) if files[REGISTRY] is not None else {
        "schema": 1, "account": account, "groups": {}}
    require(type(registry) is dict and registry.get("schema") == 1 and
            registry.get("account") == account and type(registry.get("groups")) is dict,
            "Invalid or foreign ownership registry")
    require(type(pairs) is list and type(versions) is list and type(modified) is list
            and all(isinstance(x, str) and x for x in modified), "Unsupported CloudStorage layout")
    existing, payloads, names, counters = {}, {}, {}, {}
    for row in versions:
        require(type(row) is list and len(row) == 2 and type(row[0]) in (int, str)
                and re.fullmatch(r"[0-9]{1,10}", str(row[0])) and int(row[0]) not in counters,
                "Invalid namespace counters")
        counters[int(row[0])] = version(row[1])
    require(1 in counters, "Missing namespace 1 counter")
    highest = counters[1]
    for row in pairs:
        require(type(row) is list and len(row) == 2, "Invalid CloudStorage pair")
        key, entry = row
        require(type(key) is str and key not in existing and type(entry) is dict
                and entry.get("key") == key, "Invalid or duplicate CloudStorage key")
        existing[key] = entry
        highest = max(highest, version(entry.get("version")))
        if key.startswith(PREFIX) and entry.get("is_deleted") is not True:
            require(isinstance(entry.get("value"), str), "Unknown collection envelope")
            body = decode(entry["value"])
            require(type(body) is dict and isinstance(body.get("name"), str),
                    "Unknown collection payload")
            payloads[key] = body
            names.setdefault(label_key(body["name"]), set()).add(key)
    for code, entry in registry["groups"].items():
        require(type(entry) is dict and entry.get("key") == collection_key(code)
                and entry.get("kind") in {"manual", "primary", "series", "theme", "experience"},
                "Invalid managed entry")
        appset(entry["owned"])
        appset(entry["suppressed"])
    return existing, payloads, names, versions, modified, registry, highest


def static(entry, key, body):
    return (body is not None and set(body) == STATIC_KEYS and body["id"] == key[len(PREFIX):]
            and entry.get("conflictResolutionMethod") == "custom"
            and entry.get("strMethodId") == "union-collections"
            and set(entry) == {"key", "timestamp", "version", "value", "conflictResolutionMethod", "strMethodId"})


def explicit_actions(document, groups):
    require(type(document) is list, "Expected a list of membership operations")
    seen, operations = set(), []
    for item in document:
        require(type(item) is dict and set(item) in ({"appid", "from"}, {"appid", "from", "to"}),
                "Invalid membership operation")
        aid, source, dest = appid(item["appid"]), item["from"], item.get("to")
        require(source in groups and groups[source]["kind"] != "manual"
                and (dest is None or (dest != source and dest in groups
                                      and groups[dest]["kind"] == groups[source]["kind"] == "primary"))
                and (source, aid) not in seen, "Invalid or duplicate move/removal")
        seen.add((source, aid))
        operations.append((aid, source, dest))
    return operations


def propose(files, account, plan, actions, now):
    groups = validate_plan(plan)
    existing, bodies, names, versions, modified, registry, counter = namespace(files, account)
    operations = explicit_actions(actions, groups)
    ledger = registry["groups"]
    eligible, live, removed = {}, {}, {}
    report = []
    for code, group in groups.items():
        key = collection_key(code)
        previous = ledger.get(code)
        if previous is not None:
            require(previous["kind"] == group["kind"], "Managed collection kind changed")
        if group["kind"] == "manual" and previous is not None:
            report.append({"id": code, "label": group["label"], "action": "preserve_manual"})
        elif previous is not None and static(existing.get(key, {}), key, bodies.get(key)):
            eligible[code] = group
            live[code], removed[code] = appset(bodies[key]["added"]), appset(bodies[key]["removed"])
        elif previous is not None or key in existing or label_key(group["label"]) in names:
            report.append({"id": code, "label": group["label"], "action": "protected_or_collision"})
        else:
            eligible[code], live[code], removed[code] = group, set(), set()

    owned, suppressed, primary = {}, {}, {}
    for code, entry in ledger.items():
        body = bodies.get(entry["key"])
        if entry["kind"] == "primary" and body is not None and isinstance(body.get("added"), list):
            for aid in appset(body["added"]):
                primary.setdefault(aid, set()).add(code)
        if code in eligible:
            old_owned = appset(entry["owned"])
            suppressed[code] = appset(entry["suppressed"]) | (old_owned - live[code]) | removed[code]
            owned[code] = old_owned & live[code] - removed[code]
    dropped = {code: set() for code in eligible}
    moved_to = set()
    for aid, source, dest in operations:
        require(source in eligible and aid in owned.get(source, set()), "Removal requires tool-owned membership")
        if dest is not None:
            require(dest in eligible and aid in appset(groups[dest]["members"])
                    and aid not in suppressed.get(dest, set()) and primary.get(aid) == {source}
                    and (dest, aid) not in moved_to, "Move conflicts with an existing primary or plan")
            moved_to.add((dest, aid))
            primary[aid].remove(source)
        dropped[source].add(aid)

    changed = []
    for code, group in eligible.items():
        key, previous = collection_key(code), ledger.get(code)
        wanted = appset(group["members"])
        add = set()
        blocked = set()
        for aid in wanted - live[code]:
            if aid in suppressed.get(code, set()) or aid in dropped[code] or (
                    group["kind"] == "primary" and primary.get(aid, set()) - {code}):
                blocked.add(aid)
            else:
                add.add(aid)
        if blocked:
            report.append({"id": code, "label": group["label"], "action": "preserve_existing_decision",
                           "skipped": sorted(blocked)})
        if not add and not dropped[code] and (previous or group["kind"] != "manual"):
            continue
        counter += 1
        require(counter <= MAX_VERSION, "CloudStorage version overflow")
        if previous:
            body = dict(bodies[key])
            entry = dict(existing[key])
        else:
            body = {"id": key[len(PREFIX):], "name": group["label"]}
            entry = {"key": key, "conflictResolutionMethod": "custom", "strMethodId": "union-collections"}
        body["added"] = sorted((live[code] | add) - dropped[code])
        body["removed"] = sorted(removed[code] | dropped[code])
        entry.update(timestamp=now, value=encode(body).decode().strip(), version=str(counter))
        existing[key] = entry
        ledger[code] = {"key": key, "kind": group["kind"],
                        "owned": sorted((owned.get(code, set()) | add) - dropped[code]),
                        "suppressed": sorted(suppressed.get(code, set()) | dropped[code])}
        changed.append(key)
        report.append({"id": code, "label": body["name"], "action": "update" if previous else "create",
                       "add": sorted(add), "remove": sorted(dropped[code])})
    require(all(aid in appset(decode(existing[collection_key(dest)]["value"])["added"])
                for dest, aid in moved_to), "Move destination would not contain the app")
    if not changed:
        return files, report
    new_versions = [[key, str(counter) if int(key) == 1 else value] for key, value in versions]
    pending = set(modified)
    new_modified = [*modified, *(key for key in changed if key not in pending)]
    return {MAIN: encode(list(existing.items())), VERSIONS: encode(new_versions),
            MODIFIED: encode(new_modified), REGISTRY: encode(registry)}, report


@contextmanager
def lock(directory):
    path = path_for(directory / ".curator-lock", missing=True)
    if path.exists():
        file_info(path)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    with os.fdopen(os.open(path, flags, 0o600), "r+b") as handle:
        require(os.path.samestat(os.fstat(handle.fileno()), file_info(path_for(path))), "Lock file changed")
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def backup_path(directory, txid):
    require(re.fullmatch(r"[a-f0-9]{64}", txid), "Invalid transaction ID")
    return directory / (".curator-backup-" + txid)


def save_backup(directory, txid, before, after):
    backup = backup_path(directory, txid)
    path_for(backup, missing=True).mkdir(mode=0o700)
    sync_dir(directory)
    for name, data in before.items():
        if data is not None:
            write_local(backup / name, data, acl_from=directory / name)
    manifest = {"id": txid, "before": hashes(before), "after": hashes(after)}
    write_local(backup / "manifest.json", encode(manifest), acl_from=directory / MAIN)
    return manifest


def load_backup(directory, txid):
    backup = backup_path(directory, txid)
    doc = decode(read(backup / "manifest.json"))
    require(doc["id"] == txid and set(doc["before"]) == set(doc["after"]) == set(FILES),
            "Invalid backup manifest")
    before = {name: read(backup / name) if doc["before"][name] is not None else None for name in FILES}
    require(hashes(before) == doc["before"], "Backup checksum mismatch")
    return doc, before


def apply_files(directory, old, new):
    staged = {}
    try:
        for name in FILES:
            if old[name] != new[name] and new[name] is not None:
                target = directory / name
                mode = stat.S_IMODE(file_info(target).st_mode) if old[name] is not None else 0o600
                staged[name] = stage(target, new[name], mode, acl_from=target if old[name] is not None else directory / MAIN)
        expected = hashes(old)
        for name in FILES:
            if old[name] == new[name]:
                continue
            require(steam_stopped() and hashes(snapshot(directory)) == expected,
                    "Steam restarted or a file changed during the transaction")
            target = path_for(directory / name, missing=name == REGISTRY)
            if new[name] is None:
                target.unlink()
            else:
                os.replace(staged[name], target)
            expected[name] = sha(new[name]) if new[name] is not None else None
            sync_dir(directory)
        require(hashes(snapshot(directory)) == hashes(new), "Post-write verification failed")
    finally:
        for tmp in staged.values():
            tmp.unlink(missing_ok=True)


def transact(directory, txid, old, new):
    require(steam_stopped() and hashes(snapshot(directory)) == hashes(old), "Steam active or preview stale")
    save_backup(directory, txid, old, new)
    journal = directory / JOURNAL
    write_local(journal, encode({"id": txid}))
    try:
        apply_files(directory, old, new)
    except (OSError, ValueError):
        try:
            current = snapshot(directory)
            a, b = hashes(old), hashes(new)
            require(all(h in (a[name], b[name]) for name, h in hashes(current).items()),
                    "Concurrent external change")
            apply_files(directory, current, old)
        except (OSError, ValueError):
            raise ValueError("Recovery required. Close Steam and preview --recover.") from None
        journal.unlink()
        sync_dir(directory)
        raise
    journal.unlink()
    sync_dir(directory)


def approval(word):
    require(sys.stdin.isatty() and input(f"Type {word} to continue: ") == word,
            "Interactive confirmation required")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    parser.add_argument("--account", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan")
    mode.add_argument("--rollback", metavar="TRANSACTION")
    mode.add_argument("--recover", action="store_true")
    parser.add_argument("--changes", help="Reviewed JSON operations using appid, from and optional to")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expect")
    args = parser.parse_args()
    require(not args.changes or args.plan, "--changes requires --plan")
    account = account32(args.account)
    directory = target_dir(args.target, account)
    journal = path_for(directory / JOURNAL, missing=True)
    require(journal.exists() == args.recover, "Interrupted write requires --recover, or no recovery is pending")
    old = snapshot(directory)
    now = int(time.time())
    plan_data = read(args.plan) if args.plan else b""
    action_data = read(args.changes) if args.changes else b"[]"
    if args.plan:
        new, report = propose(old, account, decode(plan_data), decode(action_data), now)
        operation = "apply"
    else:
        txid = decode(read(journal))["id"] if args.recover else args.rollback
        manifest, new = load_backup(directory, txid)
        namespace(new, account)
        if args.recover:
            require(all(h in (manifest["before"][n], manifest["after"][n]) for n, h in hashes(old).items()),
                    "External changes prevent safe recovery")
        else:
            require(hashes(old) == manifest["after"], "Steam files changed since the transaction")
        operation = "recover" if args.recover else "rollback"
        report = [{"action": operation, "transaction": txid,
                   "files": [name for name in FILES if old[name] != new[name]]}]
    preview = sha(encode([str(directory), account, operation, hashes(old), sha(plan_data), sha(action_data),
                          report, hashes(new) if not args.plan else None]))
    print(encode({"preview_digest": preview, "changes": report, "steam_stopped": steam_stopped(),
                  "local_pending_keys": len(decode(old[MODIFIED])),
                  "cloud_state": "unknown offline"}).decode(), end="")
    if not args.apply:
        return
    require(args.expect == preview and steam_stopped(), "Preview mismatch or Steam not confirmed stopped")
    if old == new and not args.recover:
        return
    approval(operation.upper())
    if not args.plan or args.changes and decode(action_data):
        approval("CONFIRM REMOVAL")
    with lock(directory):
        require(steam_stopped() and hashes(snapshot(directory)) == hashes(old)
                and journal.exists() == args.recover, "Target changed after preview")
        if args.recover:
            require(decode(read(journal))["id"] == txid, "Recovery journal changed")
            apply_files(directory, old, new)
            journal.unlink()
            sync_dir(directory)
        else:
            transaction = sha(encode([preview, time.time_ns()]))
            transact(directory, transaction, old, new)
            print("Transaction " + transaction)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError, AttributeError, RecursionError, EOFError) as exc:
        message = str(exc) if type(exc) is ValueError else "Unsafe, inaccessible or unsupported input"
        sys.exit("Refused: " + message)
