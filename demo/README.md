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

The seeded bug is a genuine race, not a scripted number, so at low sample
counts it can occasionally undersample into a false negative on one
binary-search step. The CLI default of 20 runs is comfortably stable for a
live take; drop `--runs` lower only if you want to see that noise firsthand.

No network access is required for the bisection itself. The root-cause
explanation needs a configured provider — either a cloud key
(`flarebisect config set-key anthropic <key>`, or openai/google) or a local
model via Ollama (`flarebisect config use ollama`, no key needed). Pass
`--no-explain` to demo the bisection with no AI call at all.
