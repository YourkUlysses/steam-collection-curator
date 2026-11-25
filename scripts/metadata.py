#!/usr/bin/env python3
"""Optional public metadata lookups for a user-approved selection."""
import argparse
import http.client
from pathlib import Path
import ssl
import sys
import time

from common import appid, decode, encode, path_for, private_json_output, read, require, sha, validate_plan, write_local
from curator import normalize_type

HOSTS = ("api.steamcmd.net", "steamspy.com")
MAX_RESPONSE = 8 * 1024 * 1024
DAY = 86400


def fetch(host, url):
    connection = http.client.HTTPSConnection(host, timeout=8, context=ssl.create_default_context())
    try:
        connection.request("GET", url, headers={"Accept": "application/json",
                                                "User-Agent": "SteamCollectionCurator/0.3"})
        response = connection.getresponse()
        if response.status in {401, 403, 429} or 300 <= response.status < 400:
            raise PermissionError("Provider restricted access. Lookups stopped.")
        if response.status != 200 or response.headers.get_content_type() not in {
                "application/json", "text/json"}:
            return None
        payload = bytearray()
        deadline = time.monotonic() + 12
        while True:
            if time.monotonic() >= deadline:
                return None
            part = response.read1(min(65536, MAX_RESPONSE + 1 - len(payload)))
            if not part:
                return decode(payload)
            payload.extend(part)
            if len(payload) > MAX_RESPONSE:
                return None
    finally:
        connection.close()


def lookup(aid, request=fetch, pause=time.sleep):
    facts = {"store_status": "unknown"}
    try:
        info = request(HOSTS[0], f"/v1/info/{aid}")
        common = info["data"][str(aid)]["common"]
        facts["type"] = normalize_type(common.get("type"))
        if common.get("isfreeapp") in ("0", "1", 0, 1):
            facts["free"] = str(common["isfreeapp"]) == "1"
        if common.get("releasestate") == "released" and common.get("store_asset_mtime"):
            facts["store_status"] = "available"
        if common.get("type", "").casefold() == "beta" and common.get("parent"):
            # A parent alone does not distinguish a Playtest from older betas.
            facts["type"] = "unknown"
    except PermissionError:
        raise
    except (OSError, http.client.HTTPException, ValueError, TypeError, KeyError, AttributeError, RecursionError):
        pass
    pause(1)
    try:
        info = request(HOSTS[1], f"/api.php?request=appdetails&appid={aid}")
        require(appid(info["appid"]) == aid, "Provider returned a different AppID")
        if type(info.get("tags")) is dict:
            facts["tags"] = {tag: votes for tag, votes in list(info["tags"].items())[:100]
                             if isinstance(tag, str) and len(tag) <= 80
                             and tag.isprintable() and type(votes) is int and 0 < votes <= 10**12}
        if isinstance(info.get("genre"), str):
            facts["genres"] = [item.strip() for item in info["genre"][:512].split(",") if item.strip()]
    except PermissionError:
        raise
    except (OSError, http.client.HTTPException, ValueError, TypeError, KeyError, AttributeError, RecursionError):
        pass
    pause(1)
    return facts


def selection(plan, cache, aids, now):
    require(cache["metadata_schema"] == 1 and type(cache["entries"]) is dict
            and type(cache["queried"]) is list, "Invalid metadata cache")
    library = {appid(a) for a in plan["records"]}
    pending = {appid(a) for a in plan["review_queue"]}
    chosen = set(aids)
    require(0 < len(chosen) <= 10 and len(aids) == len(chosen) and chosen <= pending,
            "Choose 1–10 distinct pending AppIDs")
    outstanding = sorted(a for a in chosen if cache["entries"].get(str(a), {}).get("expires", 0) < now)
    previous = {appid(a) for a in cache["queried"]}
    require(not outstanding or not library <= (previous | set(outstanding)),
            "Selection would disclose the entire current library")
    return outstanding


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--cache", required=True, type=Path)
    parser.add_argument("--appid", action="append", required=True, type=appid)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--expect")
    args = parser.parse_args()
    data = read(args.plan)
    plan = decode(data)
    validate_plan(plan)
    path = private_json_output(args.cache)
    require(path != path_for(args.plan), "Cache cannot overwrite the plan")
    empty = encode({"metadata_schema": 1, "entries": {}, "queried": []})
    raw = read(path) if path.exists() else empty
    cache = decode(raw)
    now = int(time.time())
    ids = selection(plan, cache, args.appid, now)
    token = sha(encode([str(path), sha(data), sha(raw), ids, HOSTS]))
    print(encode({"hosts": HOSTS, "selected_public_appids": ids, "preview_digest": token}).decode(), end="")
    if not args.fetch:
        return
    require(args.expect == token, "Lookup preview changed")
    if not ids:
        return
    require(sys.stdin.isatty() and input("Type FETCH to send these AppIDs: ") == "FETCH",
            "Interactive confirmation required")
    lock = path_for(path.with_name(path.name + ".curator-lookup-lock"), missing=True)
    with lock.open("xb"):
        pass
    try:
        require((read(path) if path.exists() else empty) == raw, "Cache changed after preview")
        require(sha(read(args.plan)) == sha(data), "Plan changed after preview")
        for aid in ids:
            cache["queried"] = sorted({*cache["queried"], aid})
            write_local(path, encode(cache))
            facts = lookup(aid)
            if len(facts) > 1:
                days = 30 if facts.get("type") not in (None, "unknown") and facts.get("tags") else 1
                cache["entries"][str(aid)] = {"facts": facts, "expires": now + days * DAY}
                write_local(path, encode(cache))
    finally:
        lock.unlink()
    print("Lookup complete. Unavailable metadata remains eligible for review.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError, AttributeError, EOFError, RecursionError) as exc:
        sys.exit("Refused: " + (str(exc) if type(exc) in (ValueError, PermissionError)
                                 else "Invalid, locked or inaccessible metadata inputs"))
