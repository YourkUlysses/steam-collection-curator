"""Audit the Git index and build a standalone skill from an explicit manifest."""
import argparse
import hashlib
from pathlib import Path
import re
import stat
import subprocess
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
SKILL = (
    "LICENSE", "SKILL.md", "config/taxonomy.json",
    "references/classification.md", "references/organization.md", "references/writer.md",
    "scripts/common.py", "scripts/curator.py", "scripts/metadata.py", "scripts/review.py",
    "scripts/write_steam.py",
)
REPOSITORY = SKILL + (
    ".gitattributes", ".gitignore", ".github/ISSUE_TEMPLATE/bug_report.md",
    ".github/ISSUE_TEMPLATE/feature_request.md", ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/workflows/ci.yml", "README.md", "CHANGELOG.md", "CONTRIBUTING.md",
    "SECURITY.md", "TEST_REPORT.md", "THIRD_PARTY_NOTICES.md",
    "docs/RELEASE_NOTES.md", "docs/privacy.md", "docs/writer.md", "docs/zh-CN.md",
    "tests/fixtures/library.csv", "tests/fixtures/steamdb-table.html",
    "tests/release_check.py", "tests/test_curator.py", "tests/test_writer.py",
)
FIXTURES = {
    "tests/fixtures/steamdb-table.html": "39b37eb419f07bc34294794e0013adef3e1c1e92d6e7abd7ee520274eea6873d",
    "tests/fixtures/library.csv": "0aa4216381649e8307a71cae6c813b15c7a8ea3a5d8365328b666fb384693de1",
}
SIGNALS = {
    "email": re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b"),
    "account": re.compile(r"\b7656119\d{10}\b"),
    "absolute-private-path": re.compile(r"(?i)\b[A-Z]:[\\/](?:Users|Documents and Settings)[\\/]|/(?:home|Users)/[\w.-]+/"),
    "credential": re.compile(r"(?i)\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|sk-(?:proj-)?[A-Za-z0-9_-]{30,})\b"),
    "private-key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "credential-assignment": re.compile(r"(?i)\b(?:cookie|api[_-]?key|access[_-]?token)\s*[:=]\s*[\'\x22][\w/%+=-]{16,}"),
}
IGNORED_SAMPLES = ("input/library.html", "output/plan.json", "private/cache.json", "dist/archive.zip",
                   "test.csv", "test.html", "logs/run.log", "profile.sqlite3",
                   "cloud-storage-namespace-1.json", ".curator-backup-test/manifest.json",
                   ".curator-transaction.json", "local_config.json", ".env.local")


def run_git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def validate_payload(name, raw):
    if b"\0" in raw:
        raise ValueError("Binary content: " + name)
    content = raw.decode("utf-8")
    if name in FIXTURES:
        checksum = hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()
        if checksum != FIXTURES[name]:
            raise ValueError("Fixture changed. Review it and update its checksum: " + name)
    for rule, pattern in SIGNALS.items():
        candidate = content
        if rule == "account" and name == "scripts/write_steam.py":
            candidate = candidate.replace("STEAM64 = " + str(0x0110000100000000), "")
        if pattern.search(candidate):
            raise ValueError(f"Privacy pattern {rule} in {name}")
    if name == "SKILL.md":
        blocks = content.split("---\n", 2)
        if len(blocks) != 3 or blocks[0]:
            raise ValueError("Missing Skill frontmatter")
        fields = dict(line.split(": ", 1) for line in blocks[1].splitlines())
        if set(fields) != {"name", "description"} or fields["name"] != "steam-collection-curator" or not (
                0 < len(fields["description"]) <= 1024):
            raise ValueError("Invalid Skill metadata")
        for target in re.findall(r"\]\(([^)]+)\)", blocks[2]):
            if target not in SKILL:
                raise ValueError("Skill reference absent from package: " + target)


def audit():
    indexed = {}
    for raw in run_git("ls-files", "--stage", "-z").split(b"\0"):
        if raw:
            header, name = raw.decode().split("\t", 1)
            mode, oid, stage = header.split()
            if mode not in {"100644", "100755"} or stage != "0":
                raise ValueError("Non-file or unmerged Git entry")
            indexed[name] = oid
    if set(indexed) != set(REPOSITORY):
        raise ValueError("Index differs from release manifest. Missing: " +
                         ", ".join(sorted(set(REPOSITORY) - indexed.keys())) +
                         f". Unexpected file count: {len(indexed.keys() - set(REPOSITORY))}.")
    payload = {}
    for name, oid in indexed.items():
        raw = run_git("cat-file", "blob", oid)
        validate_payload(name, raw)
        payload[name] = raw
    ignored = set(run_git("check-ignore", "--", *IGNORED_SAMPLES).decode().splitlines())
    if ignored != set(IGNORED_SAMPLES):
        raise ValueError("One or more private artifact examples are not ignored")
    return payload


def package(payload):
    dist = ROOT / "dist"
    if not dist.is_dir() or dist.is_symlink() or getattr(dist.lstat(), "st_file_attributes", 0) & 0x400:
        raise ValueError("Expected a local release output directory")
    destination = dist / "steam-collection-curator-v0.3.0-alpha.zip"
    with destination.open("xb") as file, ZipFile(file, "w", compression=ZIP_DEFLATED) as archive:
        for name in sorted(SKILL):
            item = ZipInfo("steam-collection-curator/" + name, (2026, 11, 25, 0, 0, 0))
            item.create_system = 3
            item.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(item, payload[name], compress_type=ZIP_DEFLATED)
    with ZipFile(destination) as archive:
        expected = {"steam-collection-curator/" + n for n in SKILL}
        if set(archive.namelist()) != expected or archive.testzip() is not None:
            raise ValueError("Package verification failed")
        for name in SKILL:
            if archive.read("steam-collection-curator/" + name) != payload[name]:
                raise ValueError("Packaged bytes do not match the index")
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", action="store_true")
    args = parser.parse_args()
    payload = audit()
    print(f"Audited {len(payload)} tracked files. Verified {len(SKILL)} standalone package paths.")
    if args.package:
        output = package(payload)
        print(output.name + " SHA256 " + hashlib.sha256(output.read_bytes()).hexdigest())
