# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.1.0] - 2026-07-29

FlareBisect stops being a Python tool. The engine always ran an arbitrary
shell command, but nothing prepared a candidate worktree — so anything needing
a build failed at every commit for reasons unrelated to the bug.

### Added
- **Toolchain detection.** Marker files identify Node (npm/yarn/pnpm/bun), Go,
  Rust, Python (pip/poetry/uv), Maven, Gradle, Ruby, .NET, Elixir, PHP, Swift,
  CMake and Make. `--cmd` and `--setup` are inferred and can be omitted
  entirely; explicit flags always win. The command is evidence too — `--cmd
  "cargo test"` means Rust regardless of what's on disk.
- **Per-worktree setup step** (`--setup`, `--no-setup`), run once before the N
  measured runs, so `npm ci` / `cargo test --no-run` / `go build` happen where
  they need to.
- **Shared dependency caches.** Package-manager cache env vars point at one
  directory, so a 12-commit bisection downloads dependencies once instead of
  twelve times. Opt out with `--no-share-cache`; a cache var you already set is
  left alone.
- **`flarebisect detect`** — shows the detected toolchain and what would run.
- **`flarebisect diagnose`** — no commit range required. Runs a command N times
  in place, clusters the distinct failure modes, and explains them. Works
  outside a git repo entirely; `--ref` measures an isolated worktree instead.
- **Failure output capture and clustering.** Previously only the exit code was
  kept. Output of failing runs is now captured, normalized (addresses, PIDs,
  timings, temp paths, timestamps masked) and grouped into distinct failure
  modes, shown as a breakdown and an excerpt centred on the error.
- **`--timeout`** — a hung run is killed by process group, so servers the
  command spawned don't survive to block the next run. Timeouts are counted
  and reported.
- **`--workers`** — controls how many runs execute at once. The N runs share
  one worktree, so a suite that isn't concurrency-safe (fixed ports, a shared
  scratch file, one test database) needs `--workers 1` or it measures its own
  contention instead of the bug.
- **`build break` verdict** and a `setup` status for commits that stop
  building, instead of silently counting as 100% failing.
- **`scripts/selftest.sh`** — end-to-end self-test covering the CLI surface,
  detection, guard rails, bisection accuracy and the language fixtures,
  including a section where FlareBisect bisects a seeded flaky bug planted in
  a copy of its own repo.

### Changed
- The LLM now receives the captured failure output alongside the diff, so the
  root-cause read is grounded in the actual error rather than the diff alone.
- `--test` is now `--cmd` (`--test` kept as an alias). Output says "failure
  rate" rather than "flake rate" — it is not necessarily a test.

### Fixed
- **A 100%-failing "good" baseline is now refused.** Nothing can jump above a
  baseline already at 100%, so the search fell through and blamed the last
  commit — the confidently-wrong answer FlareBisect exists to avoid. It now
  stops and shows the failure.
- **No commit crossing the threshold now reports `inconclusive`** instead of
  presenting the `bad` endpoint as the culprit. It names the largest move seen,
  suggests a threshold that would catch it, and skips the LLM call rather than
  explaining a commit it hasn't implicated.
- **A command that leaves a background process running no longer hangs the
  run.** Output was collected with `communicate()`, which waits for the pipe to
  reach EOF — and a spawned server inherits that pipe, so a suite that starts
  one blocked for the server's lifetime, forever at the default timeout. Output
  is now drained on a side thread while the wait is on process exit, and the
  orphan is killed so it can't hold the ports the next run needs.
- **Command and failure text containing `[...]` are no longer eaten as terminal
  markup.** `pytest -k "test[1]"` displayed as `pytest -k "test"` — the tool
  showed a command it had not run.
- **A corrupt config file no longer crashes every command** with a raw
  `JSONDecodeError`, which also broke `config set-key` — the command you would
  use to repair it. It now warns, falls back to defaults, and rewrites cleanly
  on the next save.
- `--runs 0`, `--threshold 5` and friends are rejected up front instead of
  silently producing a meaningless "inconclusive" result.
- Failure headlines no longer prefer pytest's short-summary line, which pytest
  truncates itself (`AssertionError: seed...`), over the full message. Output
  with nothing but a summary still yields a headline rather than a test count.
- git output is decoded with replacement, so a commit subject that isn't valid
  in the local encoding can't crash a bisection.

## [1.0.0] - 2026-07-26

### Added
- First public release on PyPI 🎉
- Published via trusted publishing (OIDC) — `pip install flarebisect`

## [0.3.1] - 2026-07-26

### Changed
- Default `--runs` raised from 5 to 20 — low sample counts can misattribute
  the culprit near the threshold boundary; 20 is stable in practice.
- Dropped the redundant echoed `$ flarebisect run ...` line from `run` output.

## [0.3.0] - 2026-07-26

### Added
- `flarebisect models detect` — detects your GPU (NVIDIA/AMD/Apple
  Silicon/Windows WMI fallback) and VRAM, and recommends a right-sized
  Ollama model.
- `flarebisect models pull [MODEL]` — downloads a local model via `ollama
  pull`, auto-sized to your hardware if no model is given, and sets it as
  the active provider.
- Interactive config wizard now auto-detects your GPU/VRAM when you pick
  Ollama, prefills the recommended model, and offers to pull it immediately.

## [0.2.0] - 2026-07-26

### Added
- Multi-provider AI backend: Anthropic, OpenAI, Google (Gemini), Ollama, or
  any OpenAI-compatible endpoint (LM Studio, llama.cpp server, vLLM, etc.).
- `flarebisect config` command group: `set-key`, `set-model`, `set-base-url`,
  `use`, `show` — persisted per-provider settings, keys masked on display.
- Per-run `--provider`/`--api-key`/`--model`/`--base-url` overrides.
- Redesigned terminal report: per-commit flake-rate bars, status labels
  (good/stable/wobbling/flare/bad), elapsed time and worker-count footer.
- Worker pool capped to core count instead of always matching `--runs`.
- Clear error when `git` isn't on `PATH`.

## [0.1.0] - 2026-07-26

### Added
- Core engine: worktree-isolated, parallel N-run test execution per commit.
- Flake-rate binary-search bisection with configurable jump threshold.
- Clean-break vs. flakiness-regression verdict classification.
- Claude-powered plain-English root-cause explanation of the culprit commit.
- `flarebisect run` CLI with `--good`, `--bad`, `--test`, `--runs`, `--threshold`, `--explain` flags.
- Seeded flaky demo repo (`demo/setup_demo_repo.sh`) for offline demoing.
