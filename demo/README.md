# Demo fixture

`setup_demo_repo.sh` generates `flaky-counter/`, a throwaway git repo (git
history only, not committed as a submodule — regenerate it any time) with 4
tagged commits:

| tag             | what it is                                      |
|-----------------|--------------------------------------------------|
| `good`          | lock-protected counter, test passes 100%         |
| `before-culprit`| harmless refactor, still 100% passing            |
| `culprit`       | drops the lock in `bump()` — test goes flaky     |
| `bad`           | later unrelated commit, bug still present        |

Run:

```bash
bash setup_demo_repo.sh
flarebisect run --repo ./flaky-counter --good good --bad bad \
  --test "python -m pytest test_counter.py -q"
```

No network access is required for the bisection itself — only the final
`--explain` step calls the Anthropic API. Pass `--no-explain` to demo fully
offline.
