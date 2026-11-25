# Contributing

Use Python 3.11 or newer. Run `python -B -m unittest discover -s tests -v` from the repository root. Test using synthetic Steam configuration and synthetic or public app facts. Keep real exports, local paths, identifiers, secrets, caches and Steam backups out of Git.

For changes to the writer, explain the affected format or state transition and include a regression test. Preserve users' manual collections, static and dynamic entries, and unmatched IDs. Keep input and metadata handling offline by default. Cite the exact commit and applicable license for external design references or reuse.

For a release, inspect `git diff --cached`, check the Git author identity and run the tracked-file and package audit. Update the test report with observed results and verification gaps.
