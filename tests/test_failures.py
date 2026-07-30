from flarebisect.failures import cluster, headline, normalize, signature, strip_ansi

PYTEST_OUTPUT = """
============================= test session starts ==============================
collected 1 item

tests/test_counter.py F                                                  [100%]

=================================== FAILURES ===================================
______________________________ test_increments ________________________________

    def test_increments():
>       assert counter.value == 10
E       AssertionError: assert 9 == 10

tests/test_counter.py:14: AssertionError
"""

GO_OUTPUT = """
--- FAIL: TestConcurrentWrites (0.03s)
    counter_test.go:41: expected 100, got 97
FAIL
exit status 1
FAIL	example.com/counter	0.312s
"""

RUST_PANIC = """
running 1 test
thread 'tests::race' panicked at src/lib.rs:88:9:
called `Option::unwrap()` on a `None` value
note: run with `RUST_BACKTRACE=1`
"""

JEST_OUTPUT = """
 FAIL  src/queue.test.js
  ● queue drains in order

    expect(received).toBe(expected)

    Expected: 3
    Received: 2
"""


NODE_TAP_OUTPUT = """
not ok 1 - concurrent bumps all land
  ---
  duration_ms: 1.840751
  type: 'test'
  failureType: 'testCodeFailure'
  error: |-
    Expected values to be strictly equal:

    1 !== 2

  code: 'ERR_ASSERTION'
  name: 'AssertionError'
  expected: 2
  actual: 1
  operator: 'strictEqual'
  ...
1..1
"""


PYTEST_ASSERT_BLOCK = """
    def test_concurrent_increments():
        counter = Counter()
>       assert counter.value == THREADS * INCREMENTS_PER_THREAD
E       assert 2 == 4
E        +  where 2 = <counter.Counter object at 0x7647d2cda780>.value

test_counter.py:56: AssertionError
"""


def test_strip_ansi_removes_color_codes():
    assert strip_ansi("\x1b[31mFAILED\x1b[0m") == "FAILED"


def test_headline_finds_python_assertion():
    assert "AssertionError" in headline(PYTEST_OUTPUT)


def test_headline_finds_go_failure():
    assert "expected" in headline(GO_OUTPUT)


def test_headline_finds_rust_panic():
    assert "panicked" in headline(RUST_PANIC)


def test_headline_finds_jest_expectation():
    assert "Received" in headline(JEST_OUTPUT) or "Expected" in headline(JEST_OUTPUT)


PYTEST_WITH_SUMMARY = """
>       assert state["value"] == BUMPS, "seeded flake: lost an update"
E       AssertionError: seeded flake: lost an update
E       assert 3 == 4

tests/test_seeded_flake.py:7: AssertionError
=========================== short test summary info ============================
FAILED tests/test_seeded_flake.py::test_all_bumps_land - AssertionError: seed...
1 failed in 0.01s
"""

SUMMARY_ONLY = """
F
=========================== short test summary info ============================
FAILED tests/test_seeded_flake.py::test_all_bumps_land - AssertionError: seed...
1 failed in 0.01s
"""


def test_headline_prefers_the_full_message_over_pytests_truncated_summary():
    # pytest truncates its own summary line to `AssertionError: seed...`
    line = headline(PYTEST_WITH_SUMMARY)
    assert "seeded flake: lost an update" in line
    assert "seed..." not in line


def test_summary_only_output_still_yields_a_headline():
    # with --tb=no there is nothing but the summary, so use it rather than
    # falling through to the "1 failed in 0.01s" tally
    assert "AssertionError" in headline(SUMMARY_ONLY)


def test_headline_prefers_the_assertion_over_pytest_where_clauses():
    # `E  +  where 2 = <Counter object at 0x...>` explains the assertion; the
    # assertion itself is the headline
    assert headline(PYTEST_ASSERT_BLOCK) == "E       assert 2 == 4"


def test_pytest_where_clause_noise_does_not_split_clusters():
    # the object address differs run to run, so these must be one mode
    other = PYTEST_ASSERT_BLOCK.replace("0x7647d2cda780", "0x7f1122334455")
    assert len(cluster([PYTEST_ASSERT_BLOCK, other])) == 1


def test_headline_prefers_message_over_tap_metadata_fields():
    # `expected: 2` is a YAML field; the assertion message is the real headline
    line = headline(NODE_TAP_OUTPUT)
    assert line != "expected: 2"
    assert "Expected values to be strictly equal" in line


def test_headline_ignores_tap_plan_and_separators():
    assert headline(NODE_TAP_OUTPUT) not in {"1..1", "...", "---"}


def test_headline_on_empty_output():
    assert headline("   \n\n  ") == "(no output)"


def test_headline_falls_back_to_last_line():
    assert headline("nothing structured here\njust a final line") == "just a final line"


def test_normalize_masks_addresses_and_numbers():
    a = normalize("segfault at 0x7ffd4a2b in worker 12 after 3.4s")
    b = normalize("segfault at 0x55e901ff in worker 7 after 11.9s")
    assert a == b


def test_normalize_masks_worktree_paths():
    a = normalize("open /tmp/flarebisect-ab12/9c1f88/data.db failed")
    b = normalize("open /tmp/flarebisect-zz99/4f9e21/data.db failed")
    assert a == b


def test_normalize_masks_timestamps():
    a = normalize("2026-07-29 10:03:11 request failed")
    b = normalize("2026-07-29 22:47:59 request failed")
    assert a == b


def test_same_error_different_values_is_one_cluster():
    modes = cluster([GO_OUTPUT, GO_OUTPUT.replace("got 97", "got 94")])
    assert len(modes) == 1
    assert modes[0].count == 2


def test_different_errors_are_separate_clusters():
    modes = cluster([PYTEST_OUTPUT, RUST_PANIC, PYTEST_OUTPUT])
    assert len(modes) == 2


def test_clusters_are_ordered_by_frequency():
    modes = cluster([RUST_PANIC, PYTEST_OUTPUT, PYTEST_OUTPUT])
    assert modes[0].count == 2
    assert "AssertionError" in modes[0].headline


def test_cluster_of_nothing_is_empty():
    assert cluster([]) == []


def test_mode_share_of_total():
    modes = cluster([GO_OUTPUT, GO_OUTPUT, RUST_PANIC])
    assert modes[0].share(3) == 2 / 3


def test_mode_keeps_a_full_sample():
    modes = cluster([PYTEST_OUTPUT])
    assert "test session starts" in modes[0].sample


def test_excerpt_centres_on_the_error_not_the_tally():
    mode = cluster([NODE_TAP_OUTPUT])[0]
    text = mode.excerpt()
    assert "Expected values to be strictly equal" in text
    # the trailing TAP plan line is the least useful part of the output
    assert "1..1" not in text


def test_excerpt_includes_context_before_the_headline():
    mode = cluster([PYTEST_OUTPUT])[0]
    assert "assert counter.value == 10" in mode.excerpt()


def test_excerpt_falls_back_to_tail_when_headline_not_a_whole_line():
    mode = cluster(["only one line here"])[0]
    assert mode.excerpt() == "only one line here"


def test_excerpt_of_empty_sample_is_empty():
    mode = cluster(["   "])[0]
    assert mode.excerpt() == ""


def test_signature_is_stable_across_runs():
    assert signature(GO_OUTPUT) == signature(GO_OUTPUT.replace("0.03s", "1.44s"))
