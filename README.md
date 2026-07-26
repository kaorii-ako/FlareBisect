# FlareBisect 🔥

[![PyPI](https://img.shields.io/pypi/v/flarebisect.svg)](https://pypi.org/project/flarebisect/)
[![CI](https://github.com/kaorii-ako/FlareBisect/actions/workflows/ci.yml/badge.svg)](https://github.com/kaorii-ako/FlareBisect/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

FlareBisect finds the commit that made your tests flaky, not just the one
that broke them: it bisects on flake-rate drift instead of pass/fail, then
flares the culprit with an AI-written root cause.

`git bisect` gives you confidently wrong answers when the test you're
bisecting on is flaky — it treats every run as a clean pass/fail signal, so
a test that was already unstable *before* you started bisecting can point
straight at an innocent commit.

`flarebisect` bisects on **flake rate**, not pass/fail. It runs each
candidate commit's test N times in parallel, computes a failure rate, and
finds the commit where that rate jumps — then asks an LLM to explain, in
plain English, whether the commit broke the test cleanly or made it flakier.

```
$ flarebisect run --good a1b2c3 --bad HEAD --test "npm test -- counter"

12 commits in range · 5 runs per commit · parallel worktrees

commit   flake rate                                  result  status
a1b2c3                                                  5/5  good
4f9e21                                                  5/5  stable
7d3aa0   ███████                                        4/5  wobbling
9c1f88   ████████████████████████████                   1/5  flare
HEAD     ████████████████████████████                   1/5  bad

╭────────────────────────────────────────────────────────────────╮
│ ✦ culprit found · commit 9c1f88                                    │
│                                                                        │
│ flake rate jumped 20% → 80% at this commit                             │
│ "add request counter for rate limiting"                                │
│                                                                        │
│   💡 likely cause — shared counter incremented without a lock.        │
│   concurrent test workers race on the same variable.                   │
╰────────────────────────────────────────────────────────────────╯
⏱ 8.4s    ⚡ 5 checked    ⚙ 4 parallel workers
```

## Install

```bash
pip install flarebisect
```

For local development:

```bash
pip install -e ".[dev]"
pytest -q
```

Works on Linux, macOS, and Windows — the only external dependency is `git`
on your `PATH`. Every candidate commit runs in its own `git worktree` under a
temp directory; your actual working tree and index are never touched.

## AI provider setup

The root-cause explanation step works with Claude, OpenAI, Gemini, or a
local model — anything speaking an OpenAI-compatible chat API (Ollama, LM
Studio, llama.cpp server, vLLM, and similar all qualify).

```bash
# cloud
flarebisect config set-key anthropic sk-ant-...
flarebisect config set-key openai sk-...
flarebisect config set-key google AI...

# local, no key needed - just have Ollama running
flarebisect config use ollama
flarebisect config set-model ollama llama3.1

# or let flarebisect pick a model sized to your GPU and pull it for you
flarebisect models detect   # shows detected GPU/VRAM + recommended model
flarebisect models pull     # downloads it and sets it active (run with no args)

# any other OpenAI-compatible endpoint
flarebisect config use custom
flarebisect config set-base-url custom http://localhost:8080/v1
flarebisect config set-key custom sk-local
```

Run `flarebisect config` with no arguments for a guided setup wizard — for
Ollama it detects your GPU/VRAM, prefills a right-sized model, and offers to
pull it on the spot.

`flarebisect config show` lists the active provider and stored settings
(keys are masked). Config lives in a JSON file under the OS config dir
(`~/.config/flarebisect/config.json` on Linux/macOS, `%APPDATA%` on Windows),
written with owner-only permissions.

Per-run overrides skip the config file entirely:

```bash
flarebisect run ... --provider openai --model gpt-4o-mini --api-key sk-...
flarebisect run ... --provider ollama --base-url http://localhost:11434/v1
```

Env vars (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`) work too,
as a fallback under whatever's in the config file.

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

- `--runs` — test executions per commit (default 5), run in parallel
  (capped at your core count so it doesn't oversubscribe).
- `--threshold` — flake-rate jump (0-1) vs. the `good` baseline required to
  call a commit the culprit (default 0.3).
- `--no-explain` — skip the LLM root-cause call entirely (fully offline).

## Demo

See [`demo/`](demo/) for a self-contained, seeded-flaky-bug repo you can
bisect against with no network access required for the bisection itself.

## How it works

1. Measure the flake rate at `good` and `bad` as baselines.
2. Binary-search the commit range between them.
3. At each candidate, run the test `N` times in an isolated worktree and
   compute `failed / N`.
4. The culprit is the first commit whose flake rate jumps by `>= threshold`
   over the `good` baseline.
5. Verdict: **clean break** (rate goes ~0% → ~100%) vs. **flakiness
   regression** (rate goes ~0% → somewhere in between).
6. The configured LLM gets the culprit's diff + the flake-rate evidence and
   returns a short root-cause read (race condition, shared mutable state,
   timing assumption, etc.).

Binary search assumes the flake rate is roughly monotonic across the range,
same as ordinary `git bisect` assumes pass/fail is. At low `--runs` counts
a noisy sample can occasionally violate that near the threshold boundary —
bump `--runs` if a result looks off.

## Releasing

Version is single-sourced from `src/flarebisect/__init__.py`. Bump it, commit,
tag (`vX.Y.Z`), and cut a GitHub Release — `.github/workflows/publish.yml`
builds and publishes to PyPI via trusted publishing (OIDC, no stored token).

## License

MIT
