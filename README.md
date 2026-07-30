# FlareBisect 🔥

[![PyPI](https://img.shields.io/pypi/v/flarebisect.svg)](https://pypi.org/project/flarebisect/)
[![CI](https://github.com/kaorii-ako/FlareBisect/actions/workflows/ci.yml/badge.svg)](https://github.com/kaorii-ako/FlareBisect/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

FlareBisect finds the commit that made something flaky, not just the one that
broke it: it bisects on failure-rate drift instead of pass/fail, then flares
the culprit with an AI-written root cause.

`git bisect` gives you confidently wrong answers when the thing you're
bisecting on is flaky — it treats every run as a clean pass/fail signal, so a
test that was already unstable *before* you started bisecting can point
straight at an innocent commit.

`flarebisect` bisects on **failure rate**, not pass/fail. It runs each
candidate commit's command N times in parallel, computes a failure rate, and
finds the commit where that rate jumps — then asks an LLM to explain, in plain
English, whether the commit broke things cleanly or just made them flakier.

**It is not a Python tool.** The command is anything a shell can run — `npm
test`, `go test ./...`, `cargo test`, `mvn test`, a deploy smoke check, a bare
shell script. FlareBisect detects your toolchain, builds each candidate
worktree before measuring it, and clusters the failure output it captures.

```
detected: node-npm
command:  npm test  (default for this toolchain)
setup:    npm ci || npm install  (inferred — override with --setup)

3 commits in range · 20 runs per commit · parallel worktrees (12 workers)

commit   flake rate                                  result  status
2bb16f8                                               20/20  good
b3ce802                                               20/20  stable
bfbef57  ████████████████                             12/20  flare
6fcf28e  ██████████████████                           11/20  bad

1 distinct way it failed

8x  ██████████████████  Expected values to be strictly equal:

+------------------------------------------------------------------------+
|  * culprit found · commit bfbef57  flakiness regression                 |
|                                                                         |
|  failure rate jumped 0% -> 40% at this commit                           |
|  "counter: drop mutex in bump() for speed"                              |
|                                                                         |
|   ! likely cause — bump() reads this.value, awaits, then writes it back |
|   without holding the mutex, so concurrent bumps lose updates.          |
+------------------------------------------------------------------------+
⏱ 2.2s    ⚡ 4 checked    ⚙ 12 parallel workers
```

## Install

```bash
pip install flarebisect
```

For local development:

```bash
pip install -e ".[dev]"
pytest -q                      # unit suite
bash scripts/selftest.sh       # end-to-end, incl. FlareBisect on its own repo
```

`scripts/selftest.sh` drives the real CLI against generated fixtures: toolchain
detection, diagnose mode, the guard rails, bisection accuracy against scripted
failure rates, and the Python/Node demo repos. Its last section plants a flaky
bug in a copy of this repo and has FlareBisect bisect its own history to find
it. Sections needing a toolchain you don't have are skipped, not failed; add
`--quick` to skip the slow language fixtures.

Works on Linux, macOS, and Windows — the only external dependency is `git` on
your `PATH`. Every candidate commit runs in its own `git worktree` under a temp
directory; your actual working tree and index are never touched.

## Usage

Point it at a range. Everything else is inferred:

```bash
flarebisect run --good <known-good-sha> --bad <known-bad-sha>
```

Or say exactly what to run:

```bash
flarebisect run \
  --repo /path/to/repo \
  --good v1.4.0 \
  --bad HEAD \
  --cmd "go test -race ./internal/queue" \
  --setup "go mod download" \
  --runs 20 \
  --threshold 0.3 \
  --timeout 60
```

- `--cmd` — the command whose failure rate is measured. Defaults to the
  detected toolchain's test command. (`--test` still works as an alias.)
- `--setup` — one-time prep per worktree, before the runs. Defaults to the
  detected toolchain's. `--no-setup` skips it.
- `--runs` — executions per commit (default 20), run in parallel (capped at
  your core count). Lower counts are faster but noisier — a low sample can
  misattribute the culprit near the threshold boundary.
- `--threshold` — failure-rate jump (0-1) over the `good` baseline required to
  call a commit the culprit (default 0.3).
- `--timeout` — seconds before a single run counts as hung. The process group
  is killed, so servers the command spawned don't survive to block the next run.
- `--workers` — how many runs execute at once (default: your core count).
- `--no-explain` — skip the LLM root-cause call entirely (fully offline).

**Concurrency caveat:** the N runs of a commit share one worktree. A suite that
binds a fixed port, writes a shared scratch file, or uses a single test
database will trip over itself and measure its own contention rather than your
bug. Pass `--workers 1` for those; it's slower but honest.

### Languages and toolchains

`flarebisect detect` shows what it found and what it would run:

```
$ flarebisect detect
inspecting /home/you/project

→ node-npm
    command: npm test
    setup:   npm ci || npm install
    shared cache: npm_config_cache
```

Detected from marker files: **Node** (npm/yarn/pnpm/bun), **Go**, **Rust**,
**Python** (pip/poetry/uv), **Java** (Maven/Gradle), **Ruby**, **.NET**,
**Elixir**, **PHP**, **Swift**, **CMake**, and plain **Make**. The command
itself is also evidence — `--cmd "cargo test"` means Rust whether or not
`Cargo.toml` is where FlareBisect looked.

Anything not on that list works fine; just pass `--cmd` and `--setup`
yourself. Explicit flags always beat detection.

**Why setup matters:** a fresh `git worktree` is a bare checkout with no
`node_modules`, no `target/`, no compiled binaries. Without a setup step every
commit fails identically for reasons unrelated to your bug. Package-manager
caches are pointed at one shared directory (`--no-share-cache` to opt out), so
a 12-commit bisection downloads its dependencies once, not twelve times.

### Diagnose mode — no commit range needed

Bisection assumes you know a commit where things were healthy. Often you
don't: the flake has been there forever, or only happens on your machine, or
isn't even in a git repo. `diagnose` skips history entirely — it runs the
command N times where it stands, clusters the distinct failure modes, and
explains them.

```bash
flarebisect diagnose --cmd ./deploy-check.sh --runs 30
```

```
30 runs in the working tree · parallel (12 workers)

failure rate                            result  verdict
█████████████████                        16/30  flaky — multiple failure modes

2 distinct ways it failed

8x  ██████████  Error: connection refused connecting to db:5432
6x  ████████    FATAL: upstream health probe timed out after 5s
```

Two clusters means two problems, not one intermittent race — worth knowing
before you go hunting for a single root cause. Add `--ref <sha>` to measure an
isolated worktree at a specific commit instead of your working tree.

### When it won't guess

FlareBisect exists to avoid confidently wrong answers, so it refuses to
produce one:

- If the command fails on **every** run at the known-good commit, there's no
  baseline to bisect against — it stops and shows you the failure instead of
  blaming the last commit.
- If **no** commit's rate ever crosses the threshold, it reports
  `inconclusive`, tells you the largest move it did see, and suggests a
  threshold that would catch it. It does not nominate a culprit, and it does
  not ask the LLM to explain one.
- If a commit's **setup** fails, that commit is marked `setup` rather than
  silently counted as 100% failing.

## AI provider setup

The root-cause explanation step works with Claude, OpenAI, Gemini, or a local
model — anything speaking an OpenAI-compatible chat API (Ollama, LM Studio,
llama.cpp server, vLLM, and similar all qualify).

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

`flarebisect config show` lists the active provider and stored settings (keys
are masked). Config lives in a JSON file under the OS config dir
(`~/.config/flarebisect/config.json` on Linux/macOS, `%APPDATA%` on Windows),
written with owner-only permissions.

Per-run overrides skip the config file entirely:

```bash
flarebisect run ... --provider openai --model gpt-4o-mini --api-key sk-...
flarebisect run ... --provider ollama --base-url http://localhost:11434/v1
```

Env vars (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`) work too, as
a fallback under whatever's in the config file.

The model sees the culprit's diff **and** the captured failure output, so the
explanation is grounded in the actual error rather than the diff alone.

## Demo

See [`demo/`](demo/) for two self-contained repos with seeded flaky bugs — one
Python, one Node — that you can bisect against with no network access required
for the bisection itself.

## How it works

1. Detect the toolchain; resolve the command and setup step (flags win).
2. Measure the failure rate at `good` and `bad` as baselines.
3. Binary-search the commit range between them.
4. At each candidate, create an isolated worktree, run the setup step once,
   then run the command `N` times and compute `failed / N`.
5. The culprit is the first commit whose rate jumps by `>= threshold` over the
   `good` baseline.
6. Verdict: **clean break** (~0% → ~100%), **flakiness regression** (~0% → in
   between), or **build break** (the tree stopped building here).
7. Failure output is normalized — addresses, PIDs, timings, temp paths and
   timestamps masked — and grouped into distinct failure modes.
8. The configured LLM gets the diff, the rate evidence, and the real error
   text, and returns a short root-cause read.

Binary search assumes the failure rate is roughly monotonic across the range,
same as ordinary `git bisect` assumes pass/fail is. At low `--runs` counts a
noisy sample can occasionally violate that near the threshold boundary — bump
`--runs` if a result looks off.

## Releasing

Version is single-sourced from `src/flarebisect/__init__.py`. Bump it, commit,
tag (`vX.Y.Z`), and cut a GitHub Release — `.github/workflows/publish.yml`
builds and publishes to PyPI via trusted publishing (OIDC, no stored token).

## License

MIT
