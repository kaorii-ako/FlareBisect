# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
