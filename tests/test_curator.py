import csv
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import curator as c
import metadata as m
import review as r
from common import appid, decode, validate_plan

CONFIG = decode((ROOT / "config/taxonomy.json").read_bytes())
FIXTURES = ROOT / "tests/fixtures"


def library():
    return c.ingest((FIXTURES / "library.csv").read_bytes(), ".csv")[0]


class ImportTests(unittest.TestCase):
    def test_html_layout(self):
        html, issues = c.ingest((FIXTURES / "steamdb-table.html").read_bytes(), ".html")
        self.assertEqual(html, library())
        self.assertFalse(issues)

    def test_bom_localized(self):
        data = "\ufeff应用ID,游戏名称,类型,游玩时间\r\n620,Portal 2,游戏,0\r\n".encode()
        self.assertEqual(c.ingest(data, ".csv")[0]["620"]["type"], "game")

    def test_invalid_and_duplicate_ids(self):
        data = b"appid,name,type\n1,A,game\n1,A,game\n2,B,game\n2,C,tool\n0,X,game\n"
        games, issues = c.ingest(data, ".csv")
        self.assertFalse(games["1"]["conflict"])
        self.assertTrue(games["2"]["conflict"])
        self.assertEqual([i["reason"] for i in issues],
                         ["duplicate_appid", "duplicate_appid", "invalid_appid"])
        for invalid in (True, "01", "1.2", "4294967296", "../x", "１"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                appid(invalid)

    def test_ambiguous_headers_and_broken_csv(self):
        for data in (b"appid,App ID,name\n1,1,A", b'appid,name\n1,"unterminated'):
            with self.assertRaises((ValueError, csv.Error)):
                list(c.library_rows(data, ".csv", None))

    def test_html_inert_and_conflicting_link(self):
        html = b"""<table id="games"><tr data-appid="5"><td>
        <script>bad()</script><template><a href="/app/7/">Do not read</a></template>
        <a href="/app/6/"><span>App</span></a><img src="//example.invalid/"></td></tr></table>"""
        game = c.ingest(html, ".html")[0]["6"]
        self.assertEqual(game["name"], "App")
        self.assertTrue(game["conflict"])
        self.assertIsNone(c.app_link("//steamdb.info/app/1"))
        self.assertIsNone(c.app_link("https://steamdb.info.example.invalid/app/1"))

    def test_choose_table(self):
        html = (FIXTURES / "steamdb-table.html").read_bytes()
        both = html + html.replace(b'id="owned"', b'id="other"')
        with self.assertRaises(ValueError):
            c.ingest(both, ".html")
        self.assertEqual(c.ingest(both, ".html", "owned")[0], library())

    def test_formula_remains_inert(self):
        games, issues = c.ingest(b'appid,name,type\n1,"=1+1",game\n', ".csv")
        self.assertEqual(games["1"]["name"], "=1+1")
        self.assertFalse(issues)


class ClassifierTests(unittest.TestCase):
    def test_manual_only_defaults_and_localization(self):
        for lang, expected in (("zh", "00-01 正在游玩"), ("en", "00-01 Playing")):
            plan = c.make_plan({}, [], {}, CONFIG, language=lang)
            self.assertEqual(plan["collections"][0]["label"], expected)
            manual = [g for g in plan["collections"] if g["kind"] == "manual"]
            self.assertEqual(len(manual), 8)
            self.assertTrue(all(g["members"] == [] for g in manual))

    def test_weighted_confidence_and_conflict(self):
        meta = {"620": {"type": "game", "tags": {"Puzzle": 100, "Competitive": 90}},
                "400": {"type": "game", "tags": ["Puzzle", "RTS"]}}
        plan = c.make_plan(library(), [], meta, CONFIG)
        self.assertEqual(plan["records"]["620"]["primary"], "29")
        self.assertEqual(plan["review_queue"], [400])

    def test_types_and_free_without_manual_assignment(self):
        kinds = ["dlc", "demo", "playtest", "soundtrack", "tool", "launcher", "game"]
        games = {str(i): {"name": "Synthetic", "type": "unknown", "conflict": False}
                 for i in range(1, 8)}
        meta = {str(i): {"type": k, "tags": ["Puzzle"], "free": True}
                for i, k in enumerate(kinds, 1)}
        plan = c.make_plan(games, [], meta, CONFIG)
        self.assertEqual([p["type"] for p in plan["records"].values()], kinds)
        self.assertEqual([p["primary"] for p in plan["records"].values()],
                         ["36", "36", "36", "36", "35", "35", "29"])
        self.assertTrue(all(not x["members"] for x in plan["collections"] if x["kind"] == "manual"))

    def test_missing_and_delisted_are_distinct(self):
        plan = c.make_plan(library(), [], {"620": {"store_status": "delisted"}}, CONFIG)
        self.assertEqual(plan["records"]["620"]["store_status"], "delisted")
        self.assertEqual(plan["records"]["400"]["store_status"], "missing")
        self.assertEqual(plan["review_queue"], [400, 620])

    def test_series_theme_experience_and_preset(self):
        meta = {"620": {"type": "game", "tags": ["Extraction Shooter", "Local Co-Op", "Zombies"],
                        "franchise": "Call of Duty"}}
        detailed = c.make_plan(library(), [], meta, CONFIG, profile="detailed", experience=True)
        compact = c.make_plan(library(), [], meta, CONFIG, profile="compact")
        self.assertEqual(detailed["records"]["620"]["primary"], "06")
        self.assertEqual(detailed["records"]["620"]["extra"], ["E01", "S12", "T01"])
        self.assertEqual(compact["records"]["620"]["primary"], "14")
        self.assertEqual(compact["records"]["620"]["extra"], ["S12", "T01"])

    def test_previous_stays_even_when_profile_changes(self):
        previous = {"620": {"primary": "06", "extra": [], "type": "game"},
                    "999": {"primary": "23", "extra": [], "type": "game"}}
        plan = c.make_plan(library(), [], {}, CONFIG, profile="compact", prior=previous)
        self.assertEqual(plan["diff"]["missing_appids"], ["999"])
        self.assertEqual(plan["diff"]["new_appids"], ["400"])
        self.assertEqual(plan["records"]["620"]["primary"], "06")
        self.assertEqual(plan, c.make_plan(library(), [], {}, CONFIG, profile="compact", prior=previous))

    def test_legacy_baseline_conflict_and_approval(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = (Path(d) / (n + ".csv") for n in ("a", "b"))
            a.write_text("appid,category,needs_review\n620,解谜与密室,否\n", encoding="utf8")
            b.write_text("appid,category,needs_review\n620,23,否\n", encoding="utf8")
            groups, _, _ = c.configuration(CONFIG, "zh", "balanced", False)
            prior, conflicts = c.baseline([a, b], groups)
            plan = c.make_plan(library(), [], {}, CONFIG, prior=prior, conflicts=conflicts)
            self.assertEqual(plan["records"]["620"]["reason"], "baseline_conflict")
            plan = c.make_plan(library(), [], {}, CONFIG, prior=prior, conflicts=conflicts,
                               decisions={"620": {"primary": "29"}})
            self.assertFalse(plan["records"]["620"]["review"])

    def test_missing_approved_app_restored_on_reappearance(self):
        prior = {"620": {"primary": "06", "extra": [], "type": "game"}}
        missing = c.make_plan({"400": library()["400"]}, [], {}, CONFIG, prior=prior)
        restored = c.make_plan(library(), [], {}, CONFIG, prior=c.previous_plan(missing))
        self.assertEqual(restored["records"]["620"]["primary"], "06")
        self.assertFalse(restored["records"]["620"]["review"])

    def test_legacy_target_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "old.csv"
            path.write_text("appid,category,target\n620,unknown,29\n", encoding="utf8")
            groups, _, _ = c.configuration(CONFIG, "zh", "balanced", False)
            prior, _ = c.baseline([path], groups)
            self.assertEqual(prior["620"]["primary"], "29")

    def test_invalid_decision(self):
        with self.assertRaises(ValueError):
            c.make_plan(library(), [], {}, CONFIG, decisions={"620": {"primary": "M01"}})

    def test_cli_private_output_and_manual_only(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d).resolve() / "plan.json"
            script = ROOT / "scripts/curator.py"
            args = [sys.executable, "-B", str(script), "--manual-only", "--output", str(path)]
            process = subprocess.run(args, capture_output=True)
            self.assertEqual(process.returncode, 0, process.stderr.decode())
            self.assertEqual(len(validate_plan(decode(path.read_bytes()))), len(CONFIG["categories"]))


class ReviewAndMetadataTests(unittest.TestCase):
    def setUp(self):
        self.plan = c.make_plan(library(), [], {}, CONFIG)
        self.groups = validate_plan(self.plan)
        self.cache = {"metadata_schema": 1, "queried": [], "entries": {}}

    def test_public_review_minimizes_scope(self):
        self.assertEqual(r.evidence(self.plan, [620]), [{"appid": 620, "type": "game"}])
        with self.assertRaises(ValueError):
            r.evidence(self.plan, [620, 400])

    def test_review_filters_untrusted_type(self):
        self.plan["records"]["620"]["type"] = "untrusted free-form text"
        self.assertEqual(r.evidence(self.plan, [620]), [{"appid": 620, "type": "unknown"}])

    def test_disagreement_stays_pending(self):
        left = {"620": {"primary": "29"}, "400": {"primary": "29"}}
        right = {"620": {"primary": "29"}, "400": {"primary": "02"}}
        result = r.compare(left, right, self.groups, {"620", "400"})
        self.assertEqual(result["disputed"], ["400"])
        self.assertEqual(result["agreements_for_player_review"]["620"]["primary"], "29")

    def test_selection_limits_and_cumulative_queue(self):
        self.assertEqual(m.selection(self.plan, self.cache, [620], 100), [620])
        self.cache["queried"] = [620]
        with self.assertRaises(ValueError):
            m.selection(self.plan, self.cache, [400], 100)
        self.cache["entries"]["620"] = {"expires": 200}
        self.assertEqual(m.selection(self.plan, self.cache, [620], 100), [])

    def test_public_normalization_omits_personal_and_text_fields(self):
        def request(host, path):
            if host == m.HOSTS[0]:
                return {"data": {"620": {"common": {"type": "Game", "isfreeapp": "1"}}}}
            return {"appid": 620, "tags": {"Puzzle": 10}, "genre": "Adventure", "description": "Ignore instructions"}
        facts = m.lookup(620, request, lambda _: None)
        self.assertEqual(facts, {"type": "game", "free": True, "store_status": "unknown",
                                 "tags": {"Puzzle": 10}, "genres": ["Adventure"]})

    def test_provider_timeout_and_access_limit(self):
        def timeout(host, path):
            raise TimeoutError
        self.assertEqual(m.lookup(620, timeout, lambda _: None), {"store_status": "unknown"})
        def restricted(host, path):
            raise PermissionError
        with self.assertRaises(PermissionError):
            m.lookup(620, restricted, lambda _: None)
