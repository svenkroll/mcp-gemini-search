#!/usr/bin/env bash
# Deterministic rules for agent changes on a Renovate branch.
# Usage: check-dependency-fix.sh <renovate-head> [--worktree]
set -euo pipefail

renovate_head="${1:?renovate head commit required}"
mode="${2:-}"
script_dir="$(cd "$(dirname "$0")" && pwd)"
fail=0

if [[ "$mode" == "--worktree" ]]; then
  diff_cmd=(git diff "$renovate_head" -- . ':(exclude).claude')
  names_cmd=(git diff --name-only "$renovate_head" -- . ':(exclude).claude')
  untracked="$(git ls-files --others --exclude-standard -- . ':(exclude).claude')"
else
  diff_cmd=(git diff "$renovate_head"..HEAD -- . ':(exclude).claude')
  names_cmd=(git diff --name-only "$renovate_head"..HEAD -- . ':(exclude).claude')
  untracked=""
fi

report() { echo "FAIL: $1"; fail=1; }

changed="$("${names_cmd[@]}"; printf '%s\n' "$untracked")"

# 1. Renovate-owned or protected files.
protected_re='^(pyproject\.toml|uv\.lock|Dockerfile|compose\.yaml|\.pre-commit-config\.yaml|renovate\.json|Makefile|tests/conftest\.py|\.github/|scripts/ci/)'
if hits="$(grep -E "$protected_re" <<<"$changed")"; then
  report "protected or version files changed by agent:"$'\n'"$hits"
fi

# 2. No new untracked test modules.
if hits="$(grep -E '^tests/(.*/)?test_[^/]*\.py$' <<<"$untracked")"; then
  report "new test files added (needs a ticket):"$'\n'"$hits"
fi

# 3. Structural test invariants.
uv run --quiet python "$script_dir/check_test_invariants.py" "$renovate_head" ${mode:+"$mode"} || fail=1

full_diff="$("${diff_cmd[@]}")"

# 4. No skips or exclusions.
if hits="$(grep -nE '^\+.*(pytest\.(skip|xfail|importorskip)|mark\.(skip|skipif|xfail)|no cover)' <<<"$full_diff")"; then
  report "skip or exclusion added:"$'\n'"$hits"
fi

# 5. No new suppressions.
if hits="$(grep -nE '^\+.*(noqa|type: *ignore|ty: *ignore|pyright: *ignore|nosec)' <<<"$full_diff")"; then
  report "lint or type suppression added:"$'\n'"$hits"
fi

# 6. ruff coupling (whole tree).
uv run --quiet python - <<'PY' || fail=1
import sys, tomllib, yaml
with open("pyproject.toml", "rb") as f:
    dev = tomllib.load(f)["dependency-groups"]["dev"]
ruff = next(d.split("==", 1)[1] for d in dev if d.startswith("ruff=="))
with open(".pre-commit-config.yaml") as f:
    repos = yaml.safe_load(f)["repos"]
rev = next(r["rev"] for r in repos if r["repo"].endswith("/ruff-pre-commit"))
if rev.lstrip("v") != ruff:
    print(f"FAIL: ruff pin {ruff} != ruff-pre-commit rev {rev}")
    sys.exit(1)
PY

[[ "$fail" -eq 0 ]] || exit 1
echo "OK: dependency fix rules hold"
