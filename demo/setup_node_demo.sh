#!/usr/bin/env bash
# Builds a throwaway Node git repo with a seeded flaky bug, to demo that
# flarebisect is not a Python tool. Needs no network: the one dependency is
# vendored locally and linked in by `npm install`, which is exactly the point —
# a fresh `git worktree` has no node_modules, so without the auto-detected
# setup step every commit would fail with MODULE_NOT_FOUND.
set -euo pipefail

DEMO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/flaky-node-counter"

rm -rf "$DEMO_DIR"
mkdir -p "$DEMO_DIR"
cd "$DEMO_DIR"

git init -q
git config user.email "demo@flarebisect.dev"
git config user.name "flarebisect demo"

# --- a vendored local dependency, so `npm install` has real work to do -------
mkdir -p vendor/tinylock
cat > vendor/tinylock/package.json <<'EOF'
{ "name": "tinylock", "version": "1.0.0", "main": "index.js" }
EOF

cat > vendor/tinylock/index.js <<'EOF'
// A promise-chaining mutex: each run() waits for the previous one to settle.
class Lock {
  constructor() { this.tail = Promise.resolve(); }
  run(fn) {
    const result = this.tail.then(fn);
    this.tail = result.catch(() => {});
    return result;
  }
}
module.exports = { Lock };
EOF

cat > package.json <<'EOF'
{
  "name": "flaky-node-counter",
  "version": "1.0.0",
  "private": true,
  "scripts": { "test": "node --test" },
  "dependencies": { "tinylock": "file:./vendor/tinylock" }
}
EOF

mkdir -p src test

cat > test/counter.test.js <<'EOF'
const test = require('node:test');
const assert = require('node:assert');
const { Counter } = require('../src/counter.js');

// Two racers, so the lost update only lands when the interleaving is unlucky —
// a genuine flake, not a clean break.
const BUMPS = 2;

test('concurrent bumps all land', async () => {
  const counter = new Counter();
  await Promise.all(Array.from({ length: BUMPS }, () => counter.bump()));
  assert.strictEqual(counter.value, BUMPS);
});
EOF

# --- commit 1: safe, lock-protected counter ---------------------------------
cat > src/counter.js <<'EOF'
const { Lock } = require('tinylock');

class Counter {
  constructor() {
    this.value = 0;
    this.lock = new Lock();
  }

  async bump() {
    return this.lock.run(async () => {
      const current = this.value;
      await new Promise((resolve) => setImmediate(resolve));
      this.value = current + 1;
    });
  }
}

module.exports = { Counter };
EOF

git add -A
git commit -q -m "counter: lock-protected async increment"
git tag good

# --- commit 2: unrelated, harmless refactor ---------------------------------
cat > src/counter.js <<'EOF'
const { Lock } = require('tinylock');

/** Async-safe counter. */
class Counter {
  constructor() {
    this.value = 0;
    this.lock = new Lock();
  }

  async bump() {
    return this.lock.run(async () => {
      const current = this.value;
      await new Promise((resolve) => setImmediate(resolve));
      this.value = current + 1;
    });
  }

  snapshot() {
    return this.value;
  }
}

module.exports = { Counter };
EOF

git add -A
git commit -q -m "counter: add snapshot() helper"
git tag before-culprit

# --- commit 3: THE CULPRIT - drops the lock "for performance" ----------------
cat > src/counter.js <<'EOF'
const { Lock } = require('tinylock');

/** Async counter. */
class Counter {
  constructor() {
    this.value = 0;
    this.lock = new Lock(); // kept for API compat, no longer used in bump()
  }

  async bump() {
    // "optimization": skip the mutex on the hot path
    const current = this.value;
    if (Math.random() < 0.4) {
      await new Promise((resolve) => setImmediate(resolve));
    }
    this.value = current + 1;
  }

  snapshot() {
    return this.value;
  }
}

module.exports = { Counter };
EOF

git add -A
git commit -q -m "counter: drop mutex in bump() for speed"
git tag culprit

# --- commit 4: further unrelated change, bug still present ------------------
cat > README.md <<'EOF'
# flaky-node-counter

Toy Node project used as a live demo fixture for flarebisect.
EOF

git add -A
git commit -q -m "docs: add README"
git tag bad

echo "Node demo repo ready at: $DEMO_DIR"
echo
echo "Try (note: no --cmd and no --setup - both are auto-detected):"
echo "  flarebisect run --repo $DEMO_DIR --good good --bad bad"
echo
echo "Or diagnose the flake with no commit range at all:"
echo "  cd $DEMO_DIR && npm install --silent && flarebisect diagnose"
