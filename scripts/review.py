#!/usr/bin/env python3
"""Export bounded public evidence or compare two independent review passes."""
import argparse
import sys
from common import appid, decode, encode, read, require, validate_plan
from curator import normalize_type, verified_choice


def evidence(plan, ids):
    pending = set(plan["review_queue"])
    require(len(set(ids)) == len(ids) and 0 < len(ids) <= 10 and set(ids) < {
        int(a) for a in plan["records"]} and set(ids) <= pending,
        "Select 1–10 pending AppIDs without exposing the complete library")
    return [{"appid": a, "type": normalize_type(plan["records"][str(a)].get("type"))} for a in ids]


def compare(left, right, groups, pending):
    require(type(left) is dict and type(right) is dict and set(left) | set(right) <= pending,
            "Review contains invalid or out-of-scope AppIDs")
    agree, disputed = {}, []
    for aid in sorted(left.keys() | right.keys(), key=int):
        choices = [verified_choice(x[aid], groups) if x.get(aid) is not None else None for x in (left, right)]
        if choices[0] and choices[0] == choices[1]:
            primary, extra = choices[0]
            agree[aid] = {"primary": primary, "extra": extra}
        else:
            disputed.append(aid)
    return {"agreements_for_player_review": agree, "disputed": disputed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--appid", action="append", type=appid)
    mode.add_argument("--compare", nargs=2, metavar=("PASS_A", "PASS_B"))
    args = parser.parse_args()
    plan = decode(read(args.plan))
    groups = validate_plan(plan)
    if args.appid:
        result = evidence(plan, args.appid)
    else:
        left, right = [decode(read(path)) for path in args.compare]
        result = compare(left, right, groups, {str(a) for a in plan["review_queue"]})
    print(encode(result).decode(), end="")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, TypeError, AttributeError, OSError, RecursionError):
        sys.exit("Refused: invalid review scope or decisions")
