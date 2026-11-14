#!/usr/bin/env bash
# Check a release tag before anything is built (section "Release" of
# docs/adr/0011-container-and-ci.md).
#
# Usage (from any directory inside the repository):
#   scripts/ci/check-release-tag.sh <tag>
#   e.g. scripts/ci/check-release-tag.sh v1.0.0-rc.1
#
# Arguments:
#   <tag>  Name of a tag in the local repository, without "refs/tags/"
#          (GITHUB_REF_NAME in CI). Lightweight and annotated tags are both
#          accepted; the tagged commit is "refs/tags/<tag>^{commit}".
#
# Checks, in this order; the first failing check ends the script:
#   1. Format: <tag> is "v" followed by a SemVer 2.0.0 version without build
#      metadata: MAJOR.MINOR.PATCH, each 0 or a number without leading zero,
#      optionally followed by "-<pre-release>". Build metadata ("+...") is
#      rejected because image tags cannot contain "+". Rejected examples:
#      v1, vtest, 1.0.0, v1.0, v01.0.0, v1.0.0+build.5.
#   2. Pre-release: when present, <pre-release> is exactly "<label>" or
#      "<label>.<n>", <label> one of alpha, a, beta, b, rc (lowercase), <n> 0
#      or a number without leading zero. Any other pre-release (e.g. "foo",
#      "rc.1.2", "dev.1") has no PEP 440 equivalent and is rejected.
#   3. Version: the tag version maps to the PEP 440 version
#      MAJOR.MINOR.PATCH[{a|b|rc}<n>] (alpha -> a, beta -> b, a missing <n> is
#      0). project.version from pyproject.toml at the tagged commit, read with
#      Python's tomllib (`git show <commit>:pyproject.toml`, not the working
#      tree), is normalized per PEP 440 (case-insensitive; optional leading
#      "v"; leading zeros of numbers dropped; optional "-", "_" or "." before
#      the pre-release label; pre-release aliases alpha -> a, beta -> b,
#      c/pre/preview -> rc; a missing pre-release number is 0). The two
#      normalized strings must be equal. A project.version with a release
#      segment of other than three numbers, or with an epoch, post, dev or
#      local segment, never matches. Examples: v1.0.0 matches 1.0.0;
#      v1.0.0-rc.1 matches 1.0.0rc1 and 1.0.0-rc.1; v1.0.0 does not match
#      1.0.1 or 1.0.
#   4. Branch: the tagged commit is RELEASE_MAIN_REF or one of its ancestors
#      (`git merge-base --is-ancestor`).
#
# Environment:
#   RELEASE_MAIN_REF  Optional. Ref of the main branch; default origin/main.
#   GITHUB_OUTPUT     Optional. When set and every check passed, the two
#                     key=value lines of stdout are also appended to this file
#                     (GitHub Actions step outputs).
#
# Output:
#   stdout, only when every check passed, exactly two lines in this order:
#     version=<tag without the leading "v">   e.g. version=1.0.0-rc.1
#     revision=<full 40-character SHA of the tagged commit>
#   stderr: one line per failed check naming the check and the values
#   compared, or a usage error. Nothing is written to GITHUB_OUTPUT on failure.
#   No other side effects; the working tree, the index and the refs are not
#   changed.
#
# Exit codes:
#   0  every check passed
#   1  the tag is rejected (format, pre-release, version or branch check)
#   2  usage error, unknown tag, unknown RELEASE_MAIN_REF, or pyproject.toml
#      missing at the tagged commit or without a string project.version
#
# Prerequisites: git, python3 >= 3.11 (tomllib) on PATH, and the history of
# the tag and of RELEASE_MAIN_REF available locally (actions/checkout with
# fetch-depth: 0 in CI).
set -euo pipefail

echo "not implemented" >&2
exit 1
