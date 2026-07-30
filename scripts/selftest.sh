#!/usr/bin/env bash
# FlareBisect self-test.
#
# Exercises the whole tool end to end, including a section where FlareBisect
# bisects a seeded flaky bug planted in a copy of its own repo — the tool
# testing itself on its own history.
#
#   bash scripts/selftest.sh            # everything
#   bash scripts/selftest.sh --quick    # skip the slow language fixtures
#
# Exits non-zero if any check fails. Sections needing a toolchain that isn't
# installed are skipped, not failed.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="${TMPDIR:-/tmp}/flarebisect-selftest.$$"
QUICK=0
[ "${1:-}" = "--quick" ] && QUICK=1

PASS=0; FAIL=0; SKIP=0
FAILED_LABELS=()

if [ -t 1 ]; then
  G=$'\033[32m'; R=$'\033[31m'; Y=$'\033[33m'; B=$'\033[1m'; D=$'\033[2m'; N=$'\033[0m'
else
  G=""; R=""; Y=""; B=""; D=""; N=""
fi

section() { printf '\n%s%s%s\n' "$B" "$1" "$N"; }
ok()   { printf '  %s✓%s %s\n' "$G" "$N" "$1"; PASS=$((PASS+1)); }
no()   { printf '  %s✗%s %s\n' "$R" "$N" "$1"; [ -n "${2:-}" ] && printf '      %s%s%s\n' "$D" "$2" "$N"; FAIL=$((FAIL+1)); FAILED_LABELS+=("$1"); }
skipit(){ printf '  %s–%s %s %s(%s)%s\n' "$Y" "$N" "$1" "$D" "$2" "$N"; SKIP=$((SKIP+1)); }

cleanup() { rm -rf "$WORK"; }
trap cleanup EXIT

# --- how do we invoke flarebisect? -----------------------------------------
if [ -x "$ROOT/.venv/bin/flarebisect" ]; then
  FB=("$ROOT/.venv/bin/flarebisect")
  PY="$ROOT/.venv/bin/python"
elif [ -x "$ROOT/.venv/bin/python" ]; then
  FB=("$ROOT/.venv/bin/python" -m flarebisect.cli)
  PY="$ROOT/.venv/bin/python"
elif command -v flarebisect >/dev/null 2>&1; then
  FB=(flarebisect)
  PY="$(command -v python3 || command -v python)"
else
  FB=(python3 -m flarebisect.cli)
  PY="$(command -v python3 || command -v python)"
fi

# Run flarebisect and capture combined output.
fb() { ( cd "$ROOT" && "${FB[@]}" "$@" 2>&1 ); }

# expect_contains <label> <needle> <flarebisect args...>
expect_contains() {
  local label="$1" needle="$2"; shift 2
  local out; out="$(fb "$@")"
  if printf '%s' "$out" | grep -qF -- "$needle"; then
    ok "$label"
  else
    no "$label" "expected to find \"$needle\" in output; got: $(printf '%s' "$out" | tr '\n' ' ' | cut -c1-160)"
  fi
}

# expect_missing <label> <needle> <flarebisect args...>
expect_missing() {
  local label="$1" needle="$2"; shift 2
  local out; out="$(fb "$@")"
  if printf '%s' "$out" | grep -qF -- "$needle"; then
    no "$label" "did not expect \"$needle\" in output"
  else
    ok "$label"
  fi
}

mkdir -p "$WORK"

# Preflight: fail loudly rather than reporting a wall of confusing check
# failures because flarebisect isn't importable from here.
if ! VERSION_OUT="$(fb version)"; then
  printf '%serror:%s cannot run flarebisect via: %s\n' "$R" "$N" "${FB[*]}" >&2
  printf '  from repo root: %s\n' "$ROOT" >&2
  printf '  %s\n' "$(printf '%s' "$VERSION_OUT" | head -3 | tr '\n' ' ')" >&2
  printf '  try: pip install -e ".[dev]"\n' >&2
  exit 2
fi
if [ ! -f "$ROOT/pyproject.toml" ] || [ ! -d "$ROOT/src/flarebisect" ]; then
  printf '%serror:%s %s does not look like the FlareBisect repo\n' "$R" "$N" "$ROOT" >&2
  printf '  run this script from inside a checkout: bash scripts/selftest.sh\n' >&2
  exit 2
fi

printf '%sFlareBisect self-test%s  %sv%s via %s%s\n' "$B" "$N" "$D" "$VERSION_OUT" "${FB[*]}" "$N"

# ===========================================================================
section "1. unit suite"
# ===========================================================================
if "$PY" -c "import pytest" >/dev/null 2>&1; then
  if ( cd "$ROOT" && "$PY" -m pytest -q >"$WORK/pytest.log" 2>&1 ); then
    ok "pytest ($(grep -oE '[0-9]+ passed' "$WORK/pytest.log" | tail -1))"
  else
    no "pytest" "$(tail -3 "$WORK/pytest.log" | tr '\n' ' ')"
  fi
else
  skipit "pytest" "pytest not installed"
fi

# ===========================================================================
section "2. CLI surface"
# ===========================================================================
expect_contains "version prints a version"      "." version
expect_contains "run has --cmd"                 "--cmd"      run --help
expect_contains "run keeps the --test alias"    "--test"     run --help
expect_contains "run has --setup"               "--setup"    run --help
expect_contains "run has --workers"             "--workers"  run --help
expect_contains "run has --timeout"             "--timeout"  run --help
expect_contains "diagnose is present"           "diagnose"   --help
expect_contains "detect is present"             "detect"     --help

expect_contains "rejects --runs 0"       "not in the range" run --good x --bad y --cmd true --runs 0
expect_contains "rejects --threshold 5"  "not in the range" run --good x --bad y --cmd true --threshold 5
expect_contains "rejects --workers 0"    "not in the range" run --good x --bad y --cmd true --workers 0

# ===========================================================================
section "3. toolchain detection"
# ===========================================================================
det() { # det <label> <marker-file> <expected-toolchain>
  local label="$1" marker="$2" want="$3"
  local d="$WORK/detect-$want"; mkdir -p "$d"; : > "$d/$marker"
  local out; out="$(fb detect --path "$d")"
  if printf '%s' "$out" | grep -qF -- "$want"; then ok "$label"; else
    no "$label" "$(printf '%s' "$out" | tr '\n' ' ' | cut -c1-120)"; fi
}
det "package.json  -> node-npm" package.json  node-npm
det "go.mod        -> go"       go.mod        go
det "Cargo.toml    -> rust"     Cargo.toml    rust
det "pom.xml       -> maven"    pom.xml       maven
det "Gemfile       -> ruby"     Gemfile       ruby
det "Makefile      -> make"     Makefile      make

mkdir -p "$WORK/detect-empty"
expect_contains "empty dir -> no toolchain" "no toolchain detected" detect --path "$WORK/detect-empty"

# ===========================================================================
section "4. diagnose mode (no git, no toolchain)"
# ===========================================================================
DIAG="$WORK/diag"; mkdir -p "$DIAG"
cat > "$DIAG/two-bugs.sh" <<'EOF'
#!/bin/sh
until mkdir .lock 2>/dev/null; do :; done
n=$(cat counter 2>/dev/null || echo 0)
echo $(( (n+1) % 4 )) > counter
rmdir .lock
if [ $((n % 4)) -eq 0 ]; then echo 'Error: connection refused to db:5432' >&2; exit 1; fi
if [ $((n % 4)) -eq 1 ]; then echo 'FATAL: health probe timed out after 5s' >&2; exit 1; fi
echo ok
EOF
chmod +x "$DIAG/two-bugs.sh"

expect_contains "separates two failure modes" "2 distinct ways it failed" \
  diagnose --path "$DIAG" --cmd ./two-bugs.sh --runs 12 --no-explain
expect_contains "reports a mid-range flake rate" "flaky" \
  diagnose --path "$DIAG" --cmd ./two-bugs.sh --runs 12 --no-explain
rm -f "$DIAG/counter"
expect_contains "clean command reproduces nothing" "no failures" \
  diagnose --path "$DIAG" --cmd true --runs 5 --no-explain
expect_contains "always-failing is deterministic" "deterministic failure" \
  diagnose --path "$DIAG" --cmd "exit 1" --runs 5 --no-explain
expect_contains "--workers 1 serialises" "1 worker)" \
  diagnose --path "$DIAG" --cmd true --runs 4 --workers 1 --no-explain

# a command that leaves a background process must not hang the run
START=$(date +%s)
fb diagnose --path "$DIAG" --cmd "(sleep 25 &) ; true" --runs 2 --no-explain >/dev/null
ELAPSED=$(( $(date +%s) - START ))
if [ "$ELAPSED" -lt 15 ]; then ok "orphaned background process does not hang the run (${ELAPSED}s)"
else no "orphaned background process does not hang the run" "took ${ELAPSED}s"; fi

# ===========================================================================
section "5. guard rails (refusing to guess)"
# ===========================================================================
GUARD="$WORK/guard"
mkdir -p "$GUARD" && ( cd "$GUARD" && git init -q && git config user.email s@t.u && git config user.name s )
for i in 0 1 2; do
  echo "rev $i" > "$GUARD/file.txt"
  ( cd "$GUARD" && git add -A && git commit -q -m "commit $i" && git tag "c$i" )
done

expect_contains "refuses a 100%-failing baseline" "no working baseline" \
  run --repo "$GUARD" --good c0 --bad c2 --cmd "exit 1" --runs 4 --no-explain
expect_contains "reports inconclusive when nothing jumps" "inconclusive" \
  run --repo "$GUARD" --good c0 --bad c2 --cmd true --runs 4 --no-explain
expect_missing  "names no culprit when inconclusive" "culprit found" \
  run --repo "$GUARD" --good c0 --bad c2 --cmd true --runs 4 --no-explain
expect_contains "rejects an empty commit range" "no commits between" \
  run --repo "$GUARD" --good c2 --bad c2 --cmd true --runs 2 --no-explain
expect_contains "explains a missing toolchain" "no toolchain detected" \
  run --repo "$GUARD" --good c0 --bad c2 --runs 2 --no-explain

# brackets in a command must survive Rich markup rendering
expect_contains "shows a bracketed command verbatim" 'test[1]' \
  run --repo "$GUARD" --good c0 --bad c2 --cmd 'true # test[1] [/] [bold red]' --runs 2 --no-explain

if [ -z "$(cd "$GUARD" && git worktree list | tail -n +2)" ]; then
  ok "leaves no worktrees behind"
else
  no "leaves no worktrees behind" "$(cd "$GUARD" && git worktree list | tail -n +2 | tr '\n' ' ')"
fi

# ===========================================================================
section "6. bisection accuracy (scripted failure rates)"
# ===========================================================================
RATES="$WORK/rates"
mkdir -p "$RATES" && ( cd "$RATES" && git init -q && git config user.email s@t.u && git config user.name s )
mkrate() { # mkrate <index> <failures-per-20>
  cat > "$RATES/flake.sh" <<EOF
#!/bin/sh
# revision $1
until mkdir .lock 2>/dev/null; do :; done
n=\$(cat counter 2>/dev/null || echo 0)
echo \$(( (n+1) % 20 )) > counter
rmdir .lock
if [ \$((n % 20)) -lt $2 ]; then echo 'AssertionError: lost an update' >&2; exit 1; fi
EOF
  chmod +x "$RATES/flake.sh"
  ( cd "$RATES" && git add -A && git commit -q -m "commit $1" && git tag "r$1" )
}
mkrate 0 0; mkrate 1 0; mkrate 2 16; mkrate 3 16

expect_contains "finds the commit where the rate jumps" "commit 2" \
  run --repo "$RATES" --good r0 --bad r3 --cmd ./flake.sh --runs 20 --threshold 0.3 --no-explain
expect_contains "labels it a flakiness regression" "flakiness regression" \
  run --repo "$RATES" --good r0 --bad r3 --cmd ./flake.sh --runs 20 --threshold 0.3 --no-explain
expect_contains "captures the real error text" "lost an update" \
  run --repo "$RATES" --good r0 --bad r3 --cmd ./flake.sh --runs 20 --threshold 0.3 --no-explain
expect_contains "a setup step runs in each worktree" "commit 2" \
  run --repo "$RATES" --good r0 --bad r3 --cmd "test -f prepared && ./flake.sh" \
      --setup "touch prepared" --runs 20 --threshold 0.3 --no-explain

# ===========================================================================
section "7. dogfood — FlareBisect bisects its own repo"
# ===========================================================================
# A copy of this repo's source with a genuinely flaky test planted partway
# through its history. FlareBisect runs the real pytest suite at each commit
# and has to land on the commit that planted it.
DOG="$WORK/dogfood"
mkdir -p "$DOG"
cp -r "$ROOT/src" "$ROOT/tests" "$ROOT/pyproject.toml" "$ROOT/README.md" "$DOG/" 2>/dev/null
rm -rf "$DOG/tests/__pycache__" "$DOG/src/flarebisect/__pycache__"
(
  cd "$DOG" && git init -q && git config user.email s@t.u && git config user.name s

  # The test exists and passes from the very first commit — otherwise the good
  # baseline fails for a missing file and there is nothing to bisect against.
  cat > tests/_seeded_counter.py <<'EOF'
"""Seeded fixture for scripts/selftest.sh. Not part of the real package."""


def bump(state):
    state["value"] = state["value"] + 1
EOF
  cat > tests/test_seeded_flake.py <<'EOF'
"""Seeded flaky test used by scripts/selftest.sh. Not a real test."""
from _seeded_counter import bump

BUMPS = 4


def test_all_bumps_land():
    state = {"value": 0}
    for _ in range(BUMPS):
        bump(state)
    assert state["value"] == BUMPS, "seeded flake: lost an update"
EOF
  git add -A && git commit -q -m "flarebisect: initial import" && git tag d0

  echo "# housekeeping" >> README.md
  git add -A && git commit -q -m "docs: tidy readme" && git tag d1

  # the culprit: bump() starts dropping updates, so the test goes flaky
  cat > tests/_seeded_counter.py <<'EOF'
"""Seeded fixture for scripts/selftest.sh. Not part of the real package."""
import random


def bump(state):
    current = state["value"]
    if random.random() < 0.25:
        return  # "optimization": skip the write when it looks redundant
    state["value"] = current + 1
EOF
  git add -A && git commit -q -m "counter: skip redundant writes in bump()" && git tag d2

  echo "# more notes" >> README.md
  git add -A && git commit -q -m "docs: more notes" && git tag d3
) >/dev/null 2>&1

if "$PY" -c "import pytest" >/dev/null 2>&1; then
  DOGCMD="$PY -m pytest tests/test_seeded_flake.py -q"
  expect_contains "finds the commit that made the test flaky" \
    "counter: skip redundant writes in bump()" \
    run --repo "$DOG" --good d0 --bad d3 --cmd "$DOGCMD" --runs 20 --threshold 0.3 --no-explain
  expect_contains "grounds it in the real assertion message" "seeded flake" \
    run --repo "$DOG" --good d0 --bad d3 --cmd "$DOGCMD" --runs 20 --threshold 0.3 --no-explain
  expect_contains "diagnoses the same flake with no commit range" "flaky" \
    diagnose --path "$DOG" --ref d2 --cmd "$DOGCMD" --runs 20 --no-explain
else
  skipit "dogfood bisection" "pytest not installed"
fi

# ===========================================================================
section "8. language fixtures"
# ===========================================================================
if [ "$QUICK" = "1" ]; then
  skipit "language fixtures" "--quick"
else
  # --- Python demo ---
  if "$PY" -c "import pytest" >/dev/null 2>&1; then
    bash "$ROOT/demo/setup_demo_repo.sh" >/dev/null 2>&1
    expect_contains "python demo finds the lock-drop commit" "drop lock in bump()" \
      run --repo "$ROOT/demo/flaky-counter" --good good --bad bad \
          --cmd "$PY -m pytest test_counter.py -q" --runs 20 --no-explain
  else
    skipit "python demo" "pytest not installed"
  fi

  # --- Node demo: auto-detection + setup step do the work ---
  if command -v npm >/dev/null 2>&1; then
    bash "$ROOT/demo/setup_node_demo.sh" >/dev/null 2>&1
    expect_contains "node demo auto-detects the toolchain" "node-npm" \
      run --repo "$ROOT/demo/flaky-node-counter" --good good --bad bad --runs 20 --no-explain
    expect_contains "node demo finds the mutex-drop commit" "drop mutex in bump()" \
      run --repo "$ROOT/demo/flaky-node-counter" --good good --bad bad --runs 20 --no-explain
    expect_contains "node demo refuses to guess without setup" "no working baseline" \
      run --repo "$ROOT/demo/flaky-node-counter" --good good --bad bad --no-setup --runs 4 --no-explain
  else
    skipit "node demo" "npm not installed"
  fi
fi

# ===========================================================================
printf '\n%s─────────────────────────────────────%s\n' "$D" "$N"
printf '%s%d passed%s' "$G" "$PASS" "$N"
[ "$FAIL" -gt 0 ] && printf ', %s%d failed%s' "$R" "$FAIL" "$N"
[ "$SKIP" -gt 0 ] && printf ', %s%d skipped%s' "$Y" "$SKIP" "$N"
printf '\n'

if [ "$FAIL" -gt 0 ]; then
  printf '\n%sfailed:%s\n' "$R" "$N"
  for label in "${FAILED_LABELS[@]}"; do printf '  • %s\n' "$label"; done
  exit 1
fi
exit 0
