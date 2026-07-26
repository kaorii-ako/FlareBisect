# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.0] - 2026-07-26

### Added
- Core engine: worktree-isolated, parallel N-run test execution per commit.
- Flake-rate binary-search bisection with configurable jump threshold.
- Clean-break vs. flakiness-regression verdict classification.
- Claude-powered plain-English root-cause explanation of the culprit commit.
- `flarebisect run` CLI with `--good`, `--bad`, `--test`, `--runs`, `--threshold`, `--explain` flags.
- Seeded flaky demo repo (`demo/setup_demo_repo.sh`) for offline demoing.
