#!/usr/bin/env bash
# Builds a tiny throwaway git repo with a deliberately seeded flaky bug,
# for demoing flarebisect without needing network/API access.
set -euo pipefail

DEMO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/flaky-counter"

rm -rf "$DEMO_DIR"
mkdir -p "$DEMO_DIR"
cd "$DEMO_DIR"

git init -q
git config user.email "demo@flarebisect.dev"
git config user.name "flarebisect demo"

# --- commit 1: safe, lock-protected counter -------------------------------
cat > counter.py <<'EOF'
import time
import threading


class Counter:
    def __init__(self):
        self.value = 0
        self._lock = threading.Lock()

    def bump(self):
        with self._lock:
            current = self.value
            time.sleep(0.0005)  # widen the race window on purpose
            self.value = current + 1
EOF

cat > test_counter.py <<'EOF'
import threading

from counter import Counter

THREADS = 2
INCREMENTS_PER_THREAD = 2


def test_concurrent_increments():
    counter = Counter()

    def worker():
        for _ in range(INCREMENTS_PER_THREAD):
            counter.bump()

    threads = [threading.Thread(target=worker) for _ in range(THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert counter.value == THREADS * INCREMENTS_PER_THREAD
EOF

git add -A
git commit -q -m "counter: lock-protected increment"
git tag good

# --- commit 2: unrelated, harmless refactor --------------------------------
cat > counter.py <<'EOF'
import time
import threading


class Counter:
    """Simple thread-safe counter."""

    def __init__(self):
        self.value = 0
        self._lock = threading.Lock()

    def bump(self):
        with self._lock:
            current = self.value
            time.sleep(0.0005)  # widen the race window on purpose
            self.value = current + 1

    def snapshot(self) -> int:
        with self._lock:
            return self.value
EOF

git add -A
git commit -q -m "counter: add snapshot() helper"
git tag before-culprit

# --- commit 3: THE CULPRIT - drops the lock "for performance" --------------
cat > counter.py <<'EOF'
import random
import time
import threading


class Counter:
    """Simple counter."""

    def __init__(self):
        self.value = 0
        self._lock = threading.Lock()  # kept for API compat, no longer used in bump()

    def bump(self):
        # "optimization": skip locking on the hot path
        current = self.value
        if random.random() < 0.35:  # race only lands some of the time
            time.sleep(0.0003)
        self.value = current + 1

    def snapshot(self) -> int:
        with self._lock:
            return self.value
EOF

git add -A
git commit -q -m "counter: drop lock in bump() for speed"
git tag culprit

# --- commit 4: further unrelated change, bug still present -----------------
cat > README.md <<'EOF'
# flaky-counter

Toy project used as a live demo fixture for flarebisect.
EOF

git add -A
git commit -q -m "docs: add README"
git tag bad

echo "Demo repo ready at: $DEMO_DIR"
echo
echo "Try:"
echo "  flarebisect run --repo $DEMO_DIR --good good --bad bad \\"
echo "    --test 'python -m pytest test_counter.py -q'"
echo
echo "(uses the CLI default of 20 runs - the seeded bug is a genuine race,"
echo " so lower sample counts can occasionally undersample it into a false negative)"
