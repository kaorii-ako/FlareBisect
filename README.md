# flarebisect 🔥

[![PyPI](https://img.shields.io/pypi/v/flarebisect.svg)](https://pypi.org/project/flarebisect/)
[![CI](https://github.com/flarebisect/flarebisect/actions/workflows/ci.yml/badge.svg)](https://github.com/flarebisect/flarebisect/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

`git bisect` gives you confidently wrong answers when the test you're
bisecting on is flaky — it treats every run as a clean pass/fail signal, so
a test that was already unstable *before* you started bisecting can point
straight at an innocent commit.

`flarebisect` bisects on **flake rate**, not pass/fail. It runs each
candidate commit's test N times in parallel, computes a failure rate, and
finds the commit where that rate jumps — then asks Claude to explain, in
plain English, whether the commit broke the test cleanly or made it flakier.

## Install

```bash
pip install flarebisect
export ANTHROPIC_API_KEY=sk-...   # only needed for --explain (on by default)
```

For local development:

```bash
pip install -e ".[dev]"
pytest -q
```

## Usage

```bash
flarebisect run \
  --repo /path/to/repo \
  --good <known-good-sha> \
  --bad <known-bad-sha> \
  --test "pytest -k my_flaky_test" \
  --runs 5 \
  --threshold 0.3
```

- `--runs` — test executions per commit (default 5), run in parallel.
- `--threshold` — flake-rate jump (0-1) vs. the `good` baseline required to
  call a commit the culprit (default 0.3).
- `--no-explain` — skip the Claude root-cause call (offline / no API key).

Every candidate commit is checked out into an isolated `git worktree` under a
temp directory — your actual working tree and index are never touched.

## Demo

See [`demo/`](demo/) for a self-contained, seeded-flaky-bug repo you can
bisect against with no network access required.

## How it works

1. Measure the flake rate at `good` and `bad` as baselines.
2. Binary-search the commit range between them.
3. At each candidate, run the test `N` times in an isolated worktree and
   compute `failed / N`.
4. The culprit is the first commit whose flake rate jumps by `>= threshold`
   over the `good` baseline.
5. Verdict: **clean break** (rate goes ~0% → ~100%) vs. **flakiness
   regression** (rate goes ~0% → somewhere in between).
6. Claude gets the culprit's diff + the flake-rate evidence and explains the
   likely root cause (race condition, shared mutable state, timing
   assumption, etc.).

## Releasing

Version is single-sourced from `src/flarebisect/__init__.py`. Bump it, commit,
tag (`vX.Y.Z`), and cut a GitHub Release — `.github/workflows/publish.yml`
builds and publishes to PyPI via trusted publishing (OIDC, no stored token).

## License

MIT
