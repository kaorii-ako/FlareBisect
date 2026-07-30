# Demo fixtures

Two throwaway git repos with the same seeded bug — a counter that loses
updates once its lock is dropped — in two different languages. Neither is
committed as a submodule; regenerate them any time.

Both scripts build 4 tagged commits:

| tag             | what it is                                      |
|-----------------|-------------------------------------------------|
| `good`          | lock-protected counter, passes 100%             |
| `before-culprit`| harmless refactor, still 100% passing           |
| `culprit`       | drops the lock in `bump()` — goes flaky         |
| `bad`           | later unrelated commit, bug still present       |

## Python

```bash
bash setup_demo_repo.sh
flarebisect run --repo ./flaky-counter --good good --bad bad \
  --cmd "python -m pytest test_counter.py -q"
```

## Node

Shows off the toolchain detection: pass neither `--cmd` nor `--setup` and
FlareBisect finds `package.json`, infers `npm test`, and runs `npm ci ||
npm install` in each worktree first.

```bash
bash setup_node_demo.sh
flarebisect run --repo ./flaky-node-counter --good good --bad bad
```

That setup step is not decoration. A fresh `git worktree` has no
`node_modules`, and this repo's one dependency is vendored locally — so
without it, every commit fails identically with `MODULE_NOT_FOUND` and the
bisection is meaningless. Try `--no-setup` to watch FlareBisect refuse to
guess: it stops at the good baseline rather than blaming an innocent commit.

You can also skip history entirely:

```bash
cd flaky-node-counter && git checkout culprit && npm install
flarebisect diagnose
```

## Notes

The seeded bug is a genuine race, not a scripted number, so at low sample
counts it can occasionally undersample into a false negative on one
binary-search step. The CLI default of 20 runs is comfortably stable for a
live take; drop `--runs` lower only if you want to see that noise firsthand.

No network access is required for either bisection. The root-cause
explanation needs a configured provider — either a cloud key
(`flarebisect config set-key anthropic <key>`, or openai/google) or a local
model via Ollama (`flarebisect config use ollama`, no key needed). Pass
`--no-explain` to demo the bisection with no AI call at all.
