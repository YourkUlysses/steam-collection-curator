import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import write_steam as w
from common import decode, encode, read


def wrapper(key, name, members, version=100, extra=None):
    value = {"id": key.removeprefix(w.PREFIX), "name": name, "added": members, "removed": []}
    value.update(extra or {})
    return {"key": key, "timestamp": 12, "value": encode(value).decode().strip(), "version": str(version),
            "conflictResolutionMethod": "custom", "strMethodId": "union-collections"}


def inputs():
    active = {"user-collections.favorite": wrapper("user-collections.favorite", "Favorites", [23]),
              "user-collections.hidden": wrapper("user-collections.hidden", "Hidden", [24]),
              "user-collections.uc-custom": wrapper("user-collections.uc-custom", "User's group", [25]),
              "user-collections.uc-dynamic": wrapper("user-collections.uc-dynamic", "Dynamic", [27],
                                                        extra={"filterSpec": {}}),
              "user-collections.uc-old": {"key": "user-collections.uc-old", "version": "11", "is_deleted": True},
              "LibraryData": {"key": "LibraryData", "version": "12", "value": "{}"}}
    return {w.MAIN: encode(list(active.items())), w.VERSIONS: encode([[3, "88"], [1, "111"]]),
            w.MODIFIED: encode(["LibraryData"]), w.REGISTRY: None}


def plan(records=None):
    records = {"123": "29", "456": None} if records is None else records
    groups = [{"id": f"M{i:02}", "label": f"00-{i:02} Test manual", "kind": "manual", "members": []}
              for i in range(1, 9)]
    for c in ("02", "29"):
        groups.append({"id": c, "label": c + " Test primary", "kind": "primary",
                       "members": [int(a) for a, v in records.items() if v == c]})
    return {"schema_version": 2, "records": {k: {"primary": v, "extra": [], "review": v is None}
                                             for k, v in records.items()},
            "review_queue": [int(k) for k, v in records.items() if v is None], "collections": groups}


def member_data(data, code):
    return decode(dict(decode(data[w.MAIN]))[w.collection_key(code)]["value"])


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.old = inputs()

    def propose(self, original=None, data=None, actions=None):
        return w.propose(original or self.old, "42", plan() if data is None else data, actions or [], 21)

    def test_scope_and_wire_protocol(self):
        result, report = self.propose()
        before, after = dict(decode(self.old[w.MAIN])), dict(decode(result[w.MAIN]))
        self.assertEqual({k: after[k] for k in before}, before)
        self.assertEqual([member_data(result, f"M{i:02}")["added"] for i in range(1, 9)], [[]] * 8)
        self.assertEqual(member_data(result, "29")["added"], [123])
        self.assertEqual(decode(result[w.VERSIONS]), [[3, "88"], [1, "120"]])
        self.assertEqual(decode(result[w.MODIFIED]), ["LibraryData"] + [k for k in after if k not in before])
        self.assertEqual(sum(r["action"] == "create" for r in report), 9)

    def test_idempotence_and_registry_increment(self):
        first, _ = self.propose()
        self.assertEqual(self.propose(first)[0], first)
        second, _ = self.propose(first, plan({"123": "29", "456": "29"}))
        self.assertEqual(member_data(second, "29")["added"], [123, 456])
        self.assertEqual(len(decode(first[w.MAIN])), len(decode(second[w.MAIN])))
        self.assertEqual(self.propose(second, plan({"123": "29", "456": "29"}))[0], second)

    def test_existing_manual_members_and_renames_survive(self):
        first, _ = self.propose()
        pairs = dict(decode(first[w.MAIN]))
        key = w.collection_key("M01")
        pairs[key] = wrapper(key, "User renamed", [987])
        first[w.MAIN] = encode(list(pairs.items()))
        second, _ = self.propose(first, plan({"123": "29", "456": "29"}))
        self.assertEqual(dict(decode(second[w.MAIN]))[key], pairs[key])

    def test_deterministic_id_does_not_grant_ownership(self):
        old = copy.deepcopy(self.old)
        pairs = decode(old[w.MAIN])
        key = w.collection_key("29")
        external = wrapper(key, "29 Test primary", [456])
        pairs.append([key, external])
        old[w.MAIN] = encode(pairs)
        result, _ = self.propose(old)
        self.assertEqual(dict(decode(result[w.MAIN]))[key], external)
        self.assertNotIn("29", decode(result[w.REGISTRY])["groups"])

    def test_unmanaged_name_collision_casefold(self):
        old = copy.deepcopy(self.old)
        pairs = decode(old[w.MAIN])
        key = "user-collections.uc-user"
        pairs.append([key, wrapper(key, "29 TEST PRIMARY", [4])])
        old[w.MAIN] = encode(pairs)
        self.assertNotIn(w.collection_key("29"), dict(decode(self.propose(old)[0][w.MAIN])))

    def test_managed_dynamic_becomes_protected(self):
        first, _ = self.propose()
        pairs = dict(decode(first[w.MAIN]))
        key = w.collection_key("29")
        pairs[key] = wrapper(key, "29 Test primary", [123], extra={"filterSpec": None})
        first[w.MAIN] = encode(list(pairs.items()))
        self.assertEqual(self.propose(first, plan({"123": "29", "456": "29"}))[0], first)

    def test_user_removed_members_are_not_added_back(self):
        first, _ = self.propose()
        pairs = dict(decode(first[w.MAIN]))
        key = w.collection_key("29")
        pairs[key] = wrapper(key, "29 Test primary", [], extra={"removed": [123]})
        first[w.MAIN] = encode(list(pairs.items()))
        second, _ = self.propose(first, plan({"123": "29", "456": "29"}))
        self.assertEqual(member_data(second, "29")["added"], [456])

    def test_move_requires_explicit_operation(self):
        first, _ = self.propose()
        revised = plan({"123": "02"})
        unchanged, _ = self.propose(first, revised)
        self.assertEqual(unchanged, first)
        second, _ = self.propose(first, revised, [{"appid": 123, "from": "29", "to": "02"}])
        self.assertEqual(member_data(second, "29")["removed"], [123])
        self.assertEqual(member_data(second, "02")["added"], [123])

    def test_user_added_member_cannot_be_removed(self):
        first, _ = self.propose()
        pairs = dict(decode(first[w.MAIN]))
        key = w.collection_key("29")
        pairs[key] = wrapper(key, "User renamed", [123, 987])
        first[w.MAIN] = encode(list(pairs.items()))
        with self.assertRaises(ValueError):
            self.propose(first, plan({"123": "29"}), [{"appid": 987, "from": "29"}])

    def test_malformed_formats_and_review_members(self):
        for name, payload in ((w.MAIN, b'[["x",{"key":"y"}]]'), (w.VERSIONS, b'[[3,"1"]]'),
                              (w.MODIFIED, b'{}'), (w.REGISTRY, b'{"account":"43"}')):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.propose({**self.old, name: payload})
        broken = plan()
        broken["collections"][-1]["members"].append(456)
        with self.assertRaises(ValueError):
            self.propose(data=broken)
        with self.assertRaises(ValueError):
            decode(b'{"x":1,"x":2}')

    def test_account_conversion_and_stable_id(self):
        self.assertEqual(w.account32("42"), w.account32(str(w.STEAM64 + 42)))
        self.assertNotEqual(w.collection_key("01"), w.collection_key("M01"))
        for bad in ("0", "01", str(w.STEAM64), str(w.STEAM64 + 2**32)):
            with self.assertRaises(ValueError):
                w.account32(bad)


class TransactionTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name).resolve()
        self.directory = self.root / "userdata/42/config/cloudstorage"
        self.directory.mkdir(parents=True)
        self.old = inputs()
        for name, data in self.old.items():
            if data is not None:
                (self.directory / name).write_bytes(data)
        self.new, _ = w.propose(self.old, "42", plan(), [], 21)
        self.txid = "1" * 64

    def test_preview_real_cli_without_mutation(self):
        plan_path = self.root / "plan.json"
        plan_path.write_bytes(encode(plan()))
        arguments = [sys.executable, "-B", str(ROOT / "scripts/write_steam.py"),
                     "--target", str(self.directory / w.MAIN), "--account", "42", "--plan", str(plan_path)]
        first = subprocess.run(arguments, capture_output=True)
        if sys.platform == "linux" and Path("/.dockerenv").exists():
            self.assertIn(b"native desktop", first.stderr)
            return
        self.assertEqual(first.returncode, 0, first.stderr)
        result = json.loads(first.stdout)
        self.assertTrue(result["changes"])
        self.assertEqual(len(result["preview_digest"]), 64)
        self.assertEqual(w.snapshot(self.directory), self.old)
        self.assertEqual(set(p.name for p in self.directory.iterdir()), set(w.FILES[:3]))
        stale = subprocess.run([*arguments, "--apply", "--expect", "0" * 64], capture_output=True)
        self.assertNotEqual(stale.returncode, 0)
        self.assertEqual(w.snapshot(self.directory), self.old)

    def test_backup_and_restore_exact(self):
        with patch.object(w, "steam_stopped", return_value=True), w.lock(self.directory):
            w.transact(self.directory, self.txid, self.old, self.new)
            doc, backup = w.load_backup(self.directory, self.txid)
            self.assertEqual(w.hashes(w.snapshot(self.directory)), doc["after"])
            w.transact(self.directory, "2" * 64, self.new, backup)
        self.assertEqual(w.snapshot(self.directory), self.old)

    def test_planner_cannot_overwrite_steam(self):
        from common import private_json_output
        original = self.directory / w.MAIN
        with self.assertRaises(ValueError):
            private_json_output(original)
        self.assertEqual(original.read_bytes(), self.old[w.MAIN])

    def test_changed_input_refuses_before_backup(self):
        (self.directory / w.MODIFIED).write_bytes(b'[]')
        with patch.object(w, "steam_stopped", return_value=True), self.assertRaises(ValueError):
            w.transact(self.directory, self.txid, self.old, self.new)
        self.assertFalse(w.backup_path(self.directory, self.txid).exists())

    def test_running_steam_refuses_before_backup(self):
        with patch.object(w, "steam_stopped", return_value=False), self.assertRaises(ValueError):
            w.transact(self.directory, self.txid, self.old, self.new)
        self.assertFalse(w.backup_path(self.directory, self.txid).exists())

    def test_failure_rolls_back_partial_replacement(self):
        real_replace = w.os.replace
        def replace(source, target):
            if target == self.directory / w.VERSIONS:
                raise OSError("simulated interrupted replacement")
            return real_replace(source, target)
        with patch.object(w, "steam_stopped", return_value=True), patch.object(w.os, "replace", replace):
            with self.assertRaises(OSError):
                w.transact(self.directory, self.txid, self.old, self.new)
        self.assertEqual(w.snapshot(self.directory), self.old)
        self.assertFalse((self.directory / w.JOURNAL).exists())

    def test_failed_compensation_leaves_recoverable_journal(self):
        real_replace = w.os.replace
        def replace(source, target):
            if target == self.directory / w.VERSIONS or (
                    target == self.directory / w.MAIN and target.read_bytes() == self.new[w.MAIN]):
                raise OSError("simulated interrupted replacement")
            return real_replace(source, target)
        with patch.object(w, "steam_stopped", return_value=True), patch.object(w.os, "replace", replace):
            with self.assertRaisesRegex(ValueError, "Recovery required"):
                w.transact(self.directory, self.txid, self.old, self.new)
        current = w.snapshot(self.directory)
        self.assertEqual(current[w.MAIN], self.new[w.MAIN])
        backup_id = decode(read(self.directory / w.JOURNAL))["id"]
        _, backup = w.load_backup(self.directory, backup_id)
        with patch.object(w, "steam_stopped", return_value=True):
            w.apply_files(self.directory, current, backup)
        self.assertEqual(w.snapshot(self.directory), self.old)

    def test_lock_conflict(self):
        with w.lock(self.directory), self.assertRaises(OSError):
            with w.lock(self.directory):
                self.fail("Second operation acquired the lock")

    def test_hardlink_refused(self):
        original = self.directory / w.MAIN
        alias = self.directory / "alias"
        try:
            os.link(original, alias)
        except OSError:
            self.skipTest("Hard-link creation unavailable in this sandbox")
        with self.assertRaises(ValueError):
            read(original)

    def test_live_symlink_refused(self):
        original = self.directory / w.MAIN
        alias = self.directory / "alias"
        try:
            alias.symlink_to(original)
        except OSError:
            self.skipTest("Symlink creation unavailable in this sandbox")
        with self.assertRaises(ValueError):
            read(alias)

    def test_wrong_account_and_traversal_refused(self):
        from common import path_for
        with self.assertRaises(ValueError):
            w.target_dir(self.directory / w.MAIN, "43")
        with self.assertRaises(ValueError):
            path_for(self.directory / ".." / "cloudstorage" / w.MAIN)

    def test_reparse_attribute_refused(self):
        from types import SimpleNamespace
        from common import file_info
        import stat
        info = SimpleNamespace(st_mode=stat.S_IFREG, st_nlink=1, st_file_attributes=0x400)
        with patch.object(Path, "lstat", return_value=info), self.assertRaises(ValueError):
            file_info(self.directory / w.MAIN)

    def test_malformed_process_probe_fails_closed(self):
        with patch.object(w.subprocess, "run", side_effect=OSError):
            self.assertFalse(w.steam_stopped())
