#!/usr/bin/env python3
"""Offline collection planning from local SteamDB exports."""
import argparse
from collections import defaultdict
import csv
from datetime import datetime, timezone
from html.parser import HTMLParser
import io
from itertools import combinations
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

from common import appid, decode, encode, label, label_key, private_json_output, read, require, sha, validate_plan, write_local

ROOT = Path(__file__).resolve().parents[1]
FIELDS = {
    "appid": {"appid", "app id", "steam appid", "steam app id", "应用id", "应用 id", "应用程序 id"},
    "name": {"name", "title", "app name", "game", "game name", "游戏名称", "名称"},
    "type": {"app type", "type", "类型", "应用类型"},
}
TYPES = {
    "game": "game", "游戏": "game", "dlc": "dlc", "demo": "demo", "试玩": "demo",
    "playtest": "playtest", "play test": "playtest", "soundtrack": "soundtrack",
    "music": "soundtrack", "application": "tool", "software": "tool", "tool": "tool",
    "工具": "tool", "launcher": "launcher", "standalone launcher": "launcher",
}
ATTACHMENTS = {"dlc", "demo", "playtest", "soundtrack"}
PROFILES = ("compact", "balanced", "detailed")
MANUAL_EN = ["Playing", "Recently Played", "Plan to Play", "Completed", "Dropped",
             "Plan to Replay", "Free Acquisitions and Low-Value Games", "Gacha and Library Clutter"]


def normalize_type(value):
    return TYPES.get(label_key(str(value or "")), "unknown")


def app_link(href):
    try:
        url = urlsplit(href)
        if (url.netloc and (url.scheme != "https" or url.netloc.casefold() not in
                            {"steamdb.info", "store.steampowered.com"})) or (not url.netloc and url.scheme):
            return None
        match = re.fullmatch(r"/app/([0-9]+)(?:/[^?#]*)?", url.path)
        return match[1] if match else None
    except ValueError:
        return None


class SteamHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self.table = self.row = self.cell = self.anchor = None
        self.ignored = []
        self.table_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "template", "noscript", "svg"}:
            self.ignored.append(tag)
        if self.ignored:
            return
        attrs = dict(attrs)
        if tag == "table":
            self.table_depth += 1
            if self.table_depth == 1:
                self.table = {"id": attrs.get("id"), "rows": [], "headers": []}
                self.tables.append(self.table)
        if self.table_depth > 1:
            return
        if tag == "tr":
            self.row = {"attr": attrs.get("data-appid"), "links": [], "cells": [], "headers": []}
            self.cell = self.anchor = None
        if self.row is None:
            return
        if tag in {"td", "th"}:
            self.cell = []
            self.row["cells" if tag == "td" else "headers"].append(self.cell)
        if tag == "a":
            aid = app_link(attrs.get("href") or "")
            if aid:
                self.anchor = []
                self.row["links"].append((aid, self.anchor))

    def handle_data(self, data):
        if not self.ignored and self.table_depth <= 1:
            if self.cell is not None:
                self.cell.append(data)
            if self.anchor is not None:
                self.anchor.append(data)

    def handle_endtag(self, tag):
        if self.ignored:
            if tag == self.ignored[-1]:
                self.ignored.pop()
            return
        if tag == "table" and self.table_depth:
            self.table_depth -= 1
            if self.table_depth == 0:
                self.table = self.row = self.cell = self.anchor = None
            return
        if self.table_depth > 1:
            return
        if tag == "a":
            self.anchor = None
        if tag in {"td", "th"}:
            self.cell = None
        if tag == "tr" and self.row is not None:
            if self.table is not None:
                if self.row["headers"]:
                    self.table["headers"] = ["".join(x) for x in self.row["headers"]]
                elif self.row["cells"]:
                    self.table["rows"].append(self.row)
            self.row = self.anchor = self.cell = None


def columns(headers):
    found = defaultdict(list)
    for index, value in enumerate(headers):
        normalized = label_key(value).strip()
        for alias, choices in FIELDS.items():
            if normalized in choices:
                found[alias].append(index)
    require(all(len(x) == 1 for x in found.values()), "Ambiguous column aliases")
    return {k: v[0] for k, v in found.items()}


def library_rows(data, suffix, table_id):
    source = data.decode("utf-8-sig")
    if suffix == ".csv":
        require(not table_id, "--table-id applies only to HTML")
        reader = csv.reader(io.StringIO(source, newline=""), strict=True)
        header = next(reader, [])
        fields = columns(header)
        require({"appid", "name"} <= fields.keys(), "CSV needs AppID and name columns")
        for row in reader:
            if not row or not any(x.strip() for x in row):
                continue
            require(len(row) == len(header), "CSV row has unexpected column count")
            yield {key: row[index] for key, index in fields.items()}
        return
    require(suffix in (".html", ".htm"), "Use a UTF-8 HTML or CSV export")
    parser = SteamHTML()
    parser.feed(source)
    parser.close()
    tables = [t for t in parser.tables if (not table_id or t["id"] == table_id) and
              any(r["attr"] or r["links"] for r in t["rows"])]
    require(len(tables) == 1, "Select one application table with --table-id or supply CSV")
    table = tables[0]
    fields = columns(table["headers"])
    for row in table["rows"]:
        cells = ["".join(x).strip() for x in row["cells"]]
        ids = [raw for raw, _ in row["links"]]
        if row["attr"] is not None:
            ids.append(row["attr"])
        if "appid" in fields and fields["appid"] < len(cells):
            if cells[fields["appid"]]:
                ids.append(cells[fields["appid"]])
        if not ids:
            continue
        names = ["".join(text).strip() for _, text in row["links"] if "".join(text).strip()]
        values = {field: cells[idx] for field, idx in fields.items() if idx < len(cells)}
        values["appid"] = ids[0]
        values["name"] = values.get("name") or next(iter(names), "")
        values["conflict"] = len(set(ids)) != 1
        yield values


def ingest(data, suffix, table_id=None):
    records, issues = {}, []
    for index, row in enumerate(library_rows(data, suffix, table_id), 1):
        try:
            aid = str(appid(row["appid"]))
        except ValueError:
            issues.append({"row": index, "reason": "invalid_appid"})
            continue
        try:
            name = label(row.get("name", ""), 512)
        except ValueError:
            name = ""
        kind = normalize_type(row.get("type"))
        game = {"name": name, "type": kind, "conflict": bool(row.get("conflict"))}
        if aid in records:
            previous = records[aid]
            if (name and previous["name"] and name != previous["name"]) or (
                    kind != "unknown" and previous["type"] not in ("unknown", kind)):
                previous["conflict"] = True
            previous["conflict"] |= game["conflict"]
            previous["name"] = previous["name"] or name
            if previous["type"] == "unknown":
                previous["type"] = kind
            issues.append({"row": index, "reason": "duplicate_appid"})
        else:
            records[aid] = game
    require(records, "No usable AppIDs in this export")
    return records, issues


def configuration(raw, language, profile, use_experience):
    require(type(raw) is dict and type(raw.get("categories")) is list and type(raw.get("rules")) is list,
            "Invalid taxonomy")
    groups = {}
    for row in raw["categories"]:
        code, kind = row["id"], row["kind"]
        if kind == "overlay":
            kind = {"S": "series", "T": "theme", "E": "experience"}.get(code[:1])
        require(code not in groups, "Duplicate taxonomy ID")
        if code in {"07", "37"}:
            # Legacy franchise and pending buckets were never stable gameplay genres.
            continue
        if kind == "manual":
            name = row.get("manual_en", MANUAL_EN[int(code[-2:]) - 1]) if language == "en" else row["name"]
            display = f"00-{code[1:]} {name}"
        else:
            display = row.get("label_en", row["label"]) if language == "en" else row["label"]
        groups[code] = {"id": code, "label": label(display), "kind": kind, "members": []}
    require(all(f"M{i:02d}" in groups for i in range(1, 9)), "Eight manual definitions are required")
    validate_plan({"schema_version": 2, "records": {}, "review_queue": [], "collections": list(groups.values())})
    mappings = raw.get("profiles", {}).get(profile, {})
    require(all(k in groups and v in groups and groups[k]["kind"] == groups[v]["kind"] == "primary"
                for k, v in mappings.items()), "Invalid profile mapping")
    overlays = raw.get("overlays", {})
    for code, terms in overlays.items():
        require(code in groups and groups[code]["kind"] in {"series", "theme", "experience"}
                and type(terms) is list and all(isinstance(t, str) for t in terms), "Invalid overlay rules")
    for rule in raw["rules"]:
        require(rule["id"] in groups and groups[rule["id"]]["kind"] == "primary"
                and type(rule["tags"]) in (list, dict), "Invalid gameplay rule")
        if type(rule["tags"]) is dict:
            require(all(isinstance(k, str) and type(v) is int and 0 <= v <= 8
                        for k, v in rule["tags"].items()), "Invalid gameplay weight")
    return groups, mappings, overlays


def strengths(meta):
    tags = meta.get("tags", [])
    if type(tags) is list:
        return {label_key(t): 1.0 for t in tags if isinstance(t, str)}
    require(type(tags) is dict, "Invalid tags object")
    tags = {label_key(t): n for t, n in tags.items() if type(n) is int and 0 < n <= 10**12}
    peak = max(tags.values(), default=1)
    return {t: 0.5 + 0.5 * n / peak for t, n in tags.items()}


def classify(game, meta, rules, mapping, overlays, groups, use_experience):
    kind = normalize_type(meta.get("type"))
    conflict = game["conflict"] or (kind != "unknown" and game["type"] not in ("unknown", kind))
    if kind == "unknown":
        kind = game["type"]
    tags = strengths(meta)
    genres = {label_key(t) for t in meta.get("genres", []) if isinstance(t, str)}
    franchise = label_key(str(meta.get("franchise", "")))
    extra = sorted(code for code, terms in overlays.items()
                   if kind == "game" and (groups[code]["kind"] != "experience" or use_experience)
                   and ((groups[code]["kind"] == "series" and franchise in {label_key(t) for t in terms})
                        or (groups[code]["kind"] != "series" and any(label_key(t) in tags for t in terms))))
    scores = {}
    for rule in rules:
        weights = rule["tags"] if isinstance(rule["tags"], dict) else dict.fromkeys(rule["tags"], 5)
        if any(label_key(t) not in tags for t in rule.get("require", [])):
            continue
        hits = sorted((weight * tags.get(label_key(tag), 0.0) for tag, weight in weights.items()), reverse=True)
        score = (hits[0] if hits else 0.0) + 0.25 * sum(hits[1:3])
        score += 2 if any(label_key(g) in genres for g in rule.get("genres", [])) else 0
        code = mapping.get(rule["id"], rule["id"])
        scores[code] = max(score, scores.get(code, 0))
    ranking = sorted(scores, key=lambda code: (-scores[code], code))
    candidate = ranking[0] if ranking and scores[ranking[0]] > 0 else None
    lead = scores[candidate] - (scores[ranking[1]] if len(ranking) > 1 else 0) if candidate else 0
    confident = bool(candidate and scores[candidate] >= 4 and lead >= 1.5)
    if kind in ATTACHMENTS or kind in {"tool", "launcher"}:
        candidate = "36" if kind in ATTACHMENTS else "35"
        confident = candidate in groups
    status = meta.get("store_status", "unknown" if meta else "missing")
    require(status in {"available", "delisted", "unknown", "missing"}, "Invalid store status")
    if candidate not in groups:
        candidate = None
    reason = ("input_conflict" if conflict else "missing_name" if not game["name"] else
              "unknown_type" if kind == "unknown" else "weak_or_conflicting_evidence" if not confident else "")
    return {"primary": candidate, "extra": extra, "type": kind, "store_status": status,
            "free": meta.get("free") if type(meta.get("free")) is bool else None,
            "review": bool(reason), "reason": reason, "source": "rules",
            "top_scores": {code: round(scores[code], 3) for code in ranking[:3] if scores[code] > 0}}


def baseline(paths, groups):
    labels = {label_key(g["label"]): code for code, g in groups.items()}
    result, conflicts = {}, set()
    for path in paths:
        reader = csv.DictReader(io.StringIO(read(path).decode("utf-8-sig"), newline=""), strict=True)
        for row in reader:
            aid = str(appid(row["appid"]))
            code = None
            for raw in (row.get("category") or "", row.get("target") or ""):
                code = raw if raw in groups else labels.get(label_key(raw))
                if not code:
                    matches = [k for k, g in groups.items()
                               if label_key(g["label"].split("｜")[-1]) == label_key(raw)]
                    code = matches[0] if len(matches) == 1 else None
                if code in groups and groups[code]["kind"] == "primary":
                    break
            if code not in groups or groups[code]["kind"] != "primary":
                continue
            extras = [labels.get(label_key(v)) for v in (row.get("collections") or "").split(";")]
            extras = sorted({v for v in extras if v and groups[v]["kind"] not in {"manual", "primary"}})
            if row.get("needs_review") in {"是", "yes", "true", "1"} or row.get("confidence") in {"低", "待核实", "low"}:
                continue
            decision = {"primary": code, "extra": extras}
            if aid in result and result[aid] != decision:
                conflicts.add(aid)
            result[aid] = decision
    return {a: v for a, v in result.items() if a not in conflicts}, conflicts


def previous_plan(doc):
    if doc.get("schema_version") == 2:
        validate_plan(doc)
    else:
        require(doc.get("schema_version") == 1, "Unsupported previous plan")
    queued = {str(appid(a)) for a in doc.get("review_queue", [])}
    archived = doc.get("approved_missing", {}) if doc["schema_version"] == 2 else {}
    require(type(archived) is dict and not (archived.keys() & doc["records"].keys()),
            "Invalid archived decisions")
    previous = {str(appid(a)): {"primary": r["primary"], "extra": r["extra"], "type": r.get("type")}
                for a, r in archived.items()}
    previous.update({str(appid(a)): {"primary": r["primary"], "extra": r["extra"], "type": r.get("type")}
                     for a, r in doc["records"].items() if r["review"] is False and a not in queued})
    return previous


def verified_choice(choice, groups):
    primary = choice["primary"]
    extras = choice.get("extra", [])
    require(primary in groups and groups[primary]["kind"] == "primary" and type(extras) is list
            and len(extras) == len(set(extras)) and all(c in groups and groups[c]["kind"] in
                {"series", "theme", "experience"} for c in extras), "Invalid approved decision")
    return primary, sorted(extras)


def make_plan(games, issues, metadata, raw, language="zh", profile="balanced", experience=False,
              prior=None, conflicts=None, decisions=None):
    groups, mapping, overlays = configuration(raw, language, profile, experience)
    prior, conflicts, decisions = prior or {}, conflicts or set(), decisions or {}
    require(type(decisions) is dict and set(decisions) <= games.keys(), "Decision references unknown AppID")
    records = {}
    for aid, game in sorted(games.items(), key=lambda item: int(item[0])):
        meta = metadata.get(aid, {})
        require(type(meta) is dict, "Invalid metadata record")
        record = classify(game, meta, raw["rules"], mapping, overlays, groups, experience)
        if aid in prior and aid not in decisions:
            known = prior[aid]
            if known["primary"] in groups and all(c in groups for c in known["extra"]):
                record["primary"], record["extra"] = verified_choice(known, groups)
                kind = record["type"]
                if kind == "unknown" and known.get("type") in TYPES.values():
                    kind = record["type"] = known["type"]
                mismatch = ((known.get("type") not in (None, "unknown", kind) and kind != "unknown") or
                            (kind in ATTACHMENTS and record["primary"] != "36") or
                            (kind in {"tool", "launcher"} and record["primary"] != "35"))
                record.update(source="previous", review=mismatch or game["conflict"] or not game["name"],
                              reason="previous_conflict" if mismatch or game["conflict"] or not game["name"] else "")
            else:
                record.update(review=True, reason="previous_category_missing")
        if aid in conflicts and aid not in decisions:
            record.update(review=True, reason="baseline_conflict")
        if aid in decisions:
            decision = decisions[aid]
            record["primary"], record["extra"] = verified_choice(decision, groups)
            if "type" in decision:
                require(normalize_type(decision["type"]) != "unknown", "Invalid approved app type")
                record["type"] = normalize_type(decision["type"])
            record.update(source="player", review=False, reason="")
        records[aid] = {**record, "name": game["name"]}
        if not record["review"]:
            for code in [record["primary"], *record["extra"]]:
                groups[code]["members"].append(int(aid))
    active = [g for g in groups.values() if g["members"] and g["kind"] not in {"manual", "primary"}]
    overlap = []
    for left, right in combinations(active, 2):
        if left["kind"] == right["kind"]:
            a, b = set(left["members"]), set(right["members"])
            index = len(a & b) / len(a | b)
            if index >= 0.45:
                overlap.append({"ids": [left["id"], right["id"]], "jaccard": round(index, 4)})
    plan = {"schema_version": 2, "profile": profile,
            "collections": sorted(groups.values(), key=lambda g: (g["kind"] != "manual", g["id"])),
            "records": records, "review_queue": [int(a) for a, v in records.items() if v["review"]],
            "input_issues": issues, "overlap_warnings": overlap,
            "approved_missing": {a: prior[a] for a in sorted(prior.keys() - games.keys(), key=int)
                                 if a not in conflicts},
            "diff": {"new_appids": sorted(set(games) - prior.keys(), key=int),
                     "retained_appids": sorted(set(games) & prior.keys(), key=int),
                     "missing_appids": sorted(prior.keys() - games.keys(), key=int)}}
    validate_plan(plan)
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?")
    parser.add_argument("--manual-only", action="store_true")
    parser.add_argument("--profile", choices=PROFILES, default="balanced")
    parser.add_argument("--language", choices=("zh", "en"), default="zh")
    parser.add_argument("--table-id")
    parser.add_argument("--baseline", action="append", default=[])
    parser.add_argument("--previous")
    parser.add_argument("--decisions")
    parser.add_argument("--metadata", action="append", default=[])
    parser.add_argument("--taxonomy", default=ROOT / "config" / "taxonomy.json", type=Path)
    parser.add_argument("--experience", action="store_true")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    require(bool(args.input) != args.manual_only, "Specify an export or --manual-only")
    require(not args.manual_only or not (args.previous or args.decisions or args.baseline or args.metadata),
            "Manual-only mode uses only the taxonomy")
    sources = [args.input, args.previous, args.decisions, args.taxonomy, *args.baseline, *args.metadata]
    require(all(args.output.resolve() != Path(x).expanduser().resolve() for x in sources if x),
            "Output cannot replace an input")
    taxonomy = decode(read(args.taxonomy))
    groups, _, _ = configuration(taxonomy, args.language, args.profile, args.experience)
    prior, conflicts = baseline(args.baseline, groups)
    previous = previous_plan(decode(read(args.previous))) if args.previous else {}
    conflicts.update(k for k in previous.keys() & prior.keys()
                     if any(previous[k][field] != prior[k][field] for field in ("primary", "extra")))
    prior.update(previous)
    data = read(args.input) if args.input else b""
    games, issues = ingest(data, Path(args.input).suffix.lower(), args.table_id) if args.input else ({}, [])
    metadata = {}
    for path in args.metadata:
        doc = decode(read(path))
        if doc.get("metadata_schema") == 1:
            now = int(datetime.now(timezone.utc).timestamp())
            doc = {k: v["facts"] for k, v in doc["entries"].items() if v["expires"] >= now}
        metadata.update({str(appid(k)): v for k, v in doc.items()})
    decisions = decode(read(args.decisions)) if args.decisions else {}
    plan = make_plan(games, issues, metadata, taxonomy, args.language, args.profile,
                     args.experience, prior, conflicts, decisions)
    plan.update(input_sha256=sha(data), taxonomy_sha256=sha(encode(taxonomy)))
    write_local(private_json_output(args.output), encode(plan))
    print(f"Planned {len(games)} apps. Pending review: {len(plan['review_queue'])}. Input issues: {len(issues)}.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError, AttributeError, IndexError, csv.Error, RecursionError) as exc:
        sys.exit("Refused: " + (str(exc) if type(exc) is ValueError else "Invalid or inaccessible input"))
