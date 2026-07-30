"""Group raw failure output into distinct failure modes.

Twenty failed runs of a flaky command are rarely twenty different bugs — they
are usually two or three, plus noise. Clustering them tells you whether you're
chasing one intermittent race or several unrelated problems, and gives the LLM
the actual error text instead of only a diff.

Grouping is done on a *normalized* signature: run-to-run noise (addresses,
PIDs, timings, temp paths, timestamps) is masked out so the same underlying
error collapses into one cluster.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")

# Substitutions applied in order; each masks a source of run-to-run variance.
NOISE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"0x[0-9a-fA-F]+"), "0xADDR"),
    (re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"), "UUID"),
    (re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\b"), "TIMESTAMP"),
    (re.compile(r"\b\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\b"), "TIME"),
    (re.compile(r"\b\d+(?:\.\d+)?\s?(?:ms|s|sec|secs|seconds|us|ns)\b"), "DURATION"),
    (re.compile(r"flarebisect-[0-9a-zA-Z_]+"), "WORKTREE"),
    (re.compile(r"(?:/tmp|/var/folders|C:\\\\Users\\\\[^\\\\]+\\\\AppData)[^\s'\"]*"), "TMPPATH"),
    (re.compile(r"\b(?:pid|PID|process)[= ]\d+"), "PID"),
    (re.compile(r"\b\d+\b"), "N"),
)

# Lines that look like the actual point of failure. Ordered by how much they
# tell you: a line naming the assertion that blew up beats a bare "FAIL", which
# every runner prints and which names nothing.
ERROR_MARKERS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bpanic:|\bthread '.*' panicked", re.I),
    re.compile(r"\b(?:Segmentation fault|SIGSEGV|SIGABRT|core dumped)\b", re.I),
    re.compile(r"\b\w*(?:Error|Exception)\b\s*[:(]"),
    re.compile(r"\bassert(?:ion)?\b.*\b(?:failed|error)\b", re.I),
    re.compile(r"\b(?:expected|but (?:got|was|received))\b", re.I),
    re.compile(r"\b(?:timed out|timeout|deadlock|deadline exceeded)\b", re.I),
    re.compile(r"\b(?:undefined|null) is not a\b", re.I),
    re.compile(r"^\s*(?:error|fatal)\b", re.I),
    re.compile(r"^\s*(?:E\s+|not ok\b|✗|✕|×)", re.I),
    re.compile(r"^\s*FAILED?\b", re.I),  # weakest: matches every runner's summary
)

# Structured metadata keys emitted by TAP/YAML-style runners (node --test, tap).
# `expected: 2` is a field, not a message — the message is elsewhere.
META_KEYS = (
    "duration_ms|type|location|failureType|exitCode|signal|code|name|expected"
    "|actual|operator|stack|severity|generatedMessage|tap|version"
)

# Lines that are almost never the interesting part, even when they match above:
# stack frames, separators, metadata fields, and the tallies runners end with.
BORING_RE = re.compile(
    rf"""^\s*(?:
          at\ |File\ "|\|\s|-{{3,}}|={{3,}}|\.{{3,}}\s*$
        | Traceback\ \(most\ recent
        | \d+\ (?:passing|failing|tests?)\b
        | \d+\.\.\d+\s*$                  # TAP plan line, e.g. `1..1`
        | E\s+\+                          # pytest's `E  +  where ...` follow-ups
        | (?:FAILED|ERROR)\s+\S+::        # pytest's short summary, which it truncates itself
        | (?:{META_KEYS}):\s
        | exit\ status\ \d+\s*$
        | (?:FAIL|FAILED|PASS|ok)\s*$
        | FAIL\s+\S+\s*$                  # go's `FAIL<TAB>pkg`, jest's `FAIL file`
        | (?:FAIL|ok)\s+\S+\s+[\d.]+s\s*$
    )""",
    re.X,
)


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def normalize(text: str) -> str:
    out = strip_ansi(text)
    for pattern, replacement in NOISE_PATTERNS:
        out = pattern.sub(replacement, out)
    return " ".join(out.split())


def headline(output: str) -> str:
    """The single line most likely to name what went wrong.

    Scans bottom-up because test runners print the summary last, and the last
    error is usually the one that decided the exit code. Low-value lines are
    skipped on the first pass but allowed on the second, so a run configured to
    print only a summary still gets a headline instead of a line count.
    """
    lines = [line.rstrip() for line in strip_ansi(output).splitlines() if line.strip()]
    if not lines:
        return "(no output)"

    for skip_boring in (True, False):
        for pattern in ERROR_MARKERS:
            for line in reversed(lines):
                if skip_boring and BORING_RE.match(line):
                    continue
                if pattern.search(line):
                    return line.strip()[:200]

    return lines[-1].strip()[:200]


def signature(output: str) -> str:
    return normalize(headline(output))


@dataclass
class FailureMode:
    headline: str
    count: int
    signature: str
    sample: str  # full captured output of one representative failure

    def share(self, total: int) -> float:
        return self.count / total if total else 0.0

    def excerpt(self, before: int = 3, after: int = 9) -> str:
        """A window of the sample around the headline.

        Not the tail: TAP and JUnit runners end with a pass/fail tally that says
        nothing about the failure, so the last lines are the wrong ones to show.
        """
        lines = [line.rstrip() for line in strip_ansi(self.sample).splitlines()]
        if not lines:
            return ""

        target = self.headline.strip()
        index = next((i for i, line in enumerate(lines) if line.strip() == target), None)
        if index is None:
            window = lines[-(before + after) :]
        else:
            window = lines[max(0, index - before) : index + after + 1]

        while window and not window[0].strip():
            window.pop(0)
        while window and not window[-1].strip():
            window.pop()
        return "\n".join(window)


def cluster(outputs: list[str]) -> list[FailureMode]:
    """Group failure outputs by normalized signature, most frequent first."""
    if not outputs:
        return []

    counts: Counter[str] = Counter()
    first_seen: dict[str, tuple[str, str]] = {}

    for output in outputs:
        sig = signature(output)
        counts[sig] += 1
        if sig not in first_seen:
            first_seen[sig] = (headline(output), output)

    modes = [
        FailureMode(headline=first_seen[sig][0], count=count, signature=sig, sample=first_seen[sig][1])
        for sig, count in counts.items()
    ]
    modes.sort(key=lambda m: (-m.count, m.headline))
    return modes
