"""A door somebody opens onto nothing, and the ten things that look like one.

The detector is only worth having if it stays quiet about seams. Ten of the
eleven candidates in a real 24-repository measurement were deliberate -- Null
Object sinks, no-op spans, test doubles, a stateless `__init__` -- so most of
this file is about silence, and each test names the shape it is protecting.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

from ghost_buster.deadend import (
    DETECTOR,
    DOCSTRING_ONLY,
    ELLIPSIS,
    PASS,
    RAISES,
    RETURNS_NOTHING,
    body_does_nothing,
    detect_dead_end_calls,
    find_dead_ends,
)
from ghost_buster.schema import Category, Layer, Severity, Status


def _tree(tmp_path: Path, files: dict) -> list:
    for rel, body in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(body))
    return sorted(tmp_path.rglob("*.py"))


# The shape this whole detector exists for: a documented base contract, a
# raising method, nothing subclassing it, and live code calling the name.
ADAPTER = {
    "core.py": '''\
        class UniversalAdapter:
            """Base contract for all domain adapters."""

            def execute(self, request):
                """Translate and run the request."""
                raise NotImplementedError
    ''',
    "runner.py": '''\
        from core import UniversalAdapter


        def run(adapter, request):
            return adapter.execute(request)
    ''',
}


# ------------------------------------------------------------- the shapes

def test_every_empty_shape_is_recognised(tmp_path):
    import ast
    shapes = {
        "def a():\n    pass\n": PASS,
        "def b():\n    ...\n": ELLIPSIS,
        "def c():\n    'doc'\n": DOCSTRING_ONLY,
        "def d():\n    return None\n": RETURNS_NOTHING,
        "def e():\n    return\n": RETURNS_NOTHING,
        "def f():\n    raise NotImplementedError\n": RAISES,
        "def g():\n    raise NotImplementedError('later')\n": RAISES,
    }
    for source, expected in shapes.items():
        assert body_does_nothing(ast.parse(source).body[0]) == expected, source


def test_a_real_body_is_not_an_empty_one(tmp_path):
    import ast
    for source in ("def a():\n    return 1\n",
                   "def b():\n    'doc'\n    return 1\n",
                   "def c():\n    raise ValueError('no')\n",
                   "def d():\n    pass\n    return 1\n"):
        assert body_does_nothing(ast.parse(source).body[0]) is None, source


def test_a_docstring_is_not_an_implementation(tmp_path):
    """The most convincing dead end there is: documented at length,
    implemented not at all."""
    files = _tree(tmp_path, {
        "core.py": '''\
            class Router:
                def dispatch(self, event):
                    """Route the event to the right handler.

                    Chooses a handler by event type and returns its result.
                    """
        ''',
        "app.py": "from core import Router\n\n\ndef go(r, e):\n    return r.dispatch(e)\n",
    })
    found = find_dead_ends(files)
    assert [h.shape for h in found] == [DOCSTRING_ONLY]


# --------------------------------------------------------- the real finding

def test_a_base_contract_nobody_implements_is_reported(tmp_path):
    findings = detect_dead_end_calls(_tree(tmp_path, ADAPTER))
    assert len(findings) == 1
    f = findings[0]
    assert f.detector == DETECTOR
    assert f.category is Category.DEAD_CODE
    assert f.layer is Layer.MECHANICAL
    assert f.status is Status.CONFIRMED
    assert "UniversalAdapter.execute" in f.summary
    assert f.attributes["shape"] == RAISES


def test_the_loud_shape_is_minor_and_the_silent_ones_are_major(tmp_path):
    """A raised NotImplementedError stops and names itself. A `pass` lets the
    caller believe the work happened, which is the difference between `the
    check passed` and `the thing works`."""
    loud = detect_dead_end_calls(_tree(tmp_path, ADAPTER))
    assert loud[0].severity is Severity.MINOR

    quiet = dict(ADAPTER)
    quiet["core.py"] = quiet["core.py"].replace("raise NotImplementedError", "pass")
    silent = detect_dead_end_calls(_tree(tmp_path / "silent", quiet))
    assert silent[0].severity is Severity.MAJOR


def test_the_finding_refuses_to_claim_never(tmp_path):
    f = detect_dead_end_calls(_tree(tmp_path, ADAPTER))[0]
    assert "scan the siblings" in f.detail
    assert "scanned set" in f.detail


# ------------------------------------------------ a seam declares itself

def test_an_abstract_base_is_a_seam(tmp_path):
    files = _tree(tmp_path, {
        "core.py": '''\
            from abc import ABC


            class UniversalAdapter(ABC):
                def execute(self, request):
                    raise NotImplementedError
        ''',
        "runner.py": "def run(a, r):\n    return a.execute(r)\n",
    })
    assert find_dead_ends(files) == []


def test_a_protocol_is_a_seam(tmp_path):
    files = _tree(tmp_path, {
        "core.py": '''\
            from typing import Protocol


            class Adapter(Protocol):
                def execute(self, request):
                    ...
        ''',
        "runner.py": "def run(a, r):\n    return a.execute(r)\n",
    })
    assert find_dead_ends(files) == []


def test_an_abstractmethod_decorator_is_a_seam(tmp_path):
    files = _tree(tmp_path, {
        "core.py": '''\
            from abc import abstractmethod


            class Adapter:
                @abstractmethod
                def execute(self, request):
                    raise NotImplementedError
        ''',
        "runner.py": "def run(a, r):\n    return a.execute(r)\n",
    })
    assert find_dead_ends(files) == []


def test_a_subclass_with_a_real_body_is_a_seam(tmp_path):
    """The seam declared by USE rather than by keyword: no ABC anywhere, but
    something actually implements it, so the empty one is dispatch."""
    files = _tree(tmp_path, {
        **ADAPTER,
        "billing.py": '''\
            from core import UniversalAdapter


            class BillingAdapter(UniversalAdapter):
                def execute(self, request):
                    return {"ok": True, "request": request}
        ''',
    })
    assert find_dead_ends(files) == []


def test_the_implementer_may_be_a_grandchild(tmp_path):
    """Ancestry is walked, not just the immediate base."""
    files = _tree(tmp_path, {
        **ADAPTER,
        "middle.py": "from core import UniversalAdapter\n\n\n"
                     "class RegionalAdapter(UniversalAdapter):\n    pass\n",
        "billing.py": '''\
            from middle import RegionalAdapter


            class BillingAdapter(RegionalAdapter):
                def execute(self, request):
                    return {"ok": True}
        ''',
    })
    assert find_dead_ends(files) == []


def test_a_subclass_that_does_not_override_leaves_it_a_dead_end(tmp_path):
    """Being subclassed is not the same as being implemented."""
    files = _tree(tmp_path, {
        **ADAPTER,
        "regional.py": "from core import UniversalAdapter\n\n\n"
                       "class RegionalAdapter(UniversalAdapter):\n"
                       "    def region(self):\n        return 'eu'\n",
    })
    assert len(find_dead_ends(files)) == 1


def test_a_second_definition_with_a_real_body_is_a_seam(tmp_path):
    """The module-level equivalent: a platform-specific stub beside a real
    implementation of the same name."""
    files = _tree(tmp_path, {
        "posix.py": "def flush_cache():\n    import os\n    return os.sync()\n",
        "windows.py": "def flush_cache():\n    pass\n",
        "app.py": "def go():\n    return flush_cache()\n",
    })
    assert find_dead_ends(files) == []


# ------------------------------------------- an empty body IS the implementation

def test_a_null_object_is_not_a_dead_end(tmp_path):
    """Measured false positive: ANVIL's NullTelemetrySink.record."""
    files = _tree(tmp_path, {
        "sinks.py": '''\
            class NullTelemetrySink:
                def record(self, event):
                    return None
        ''',
        "app.py": "def go(sink, e):\n    return sink.record(e)\n",
    })
    assert find_dead_ends(files) == []


def test_a_no_op_span_is_not_a_dead_end(tmp_path):
    """Measured false positive: OBSERVE and sentinel_os's _NoOpSpan."""
    files = _tree(tmp_path, {
        "tracing.py": "class _NoOpSpan:\n    def set_status(self, status):\n        pass\n",
        "app.py": "def go(span, s):\n    return span.set_status(s)\n",
    })
    assert find_dead_ends(files) == []


def test_a_stateless_init_is_not_a_dead_end(tmp_path):
    """Measured false positive: ATS's AuditReportValidator.__init__.

    `__init__` reaches the `called` set only through an explicit
    `super().__init__()` somewhere, never through construction, so the
    unrelated class below is what makes this test test anything. Its first
    version constructed the validator instead and passed because the name
    was never called at all, which a mutant caught.
    """
    files = _tree(tmp_path, {
        "v.py": "class AuditReportValidator:\n"
                "    def __init__(self):\n        pass\n\n\n"
                "class Unrelated:\n"
                "    def __init__(self):\n        super().__init__()\n",
    })
    assert find_dead_ends(files) == []


def test_a_word_that_merely_starts_with_null_is_still_checked(tmp_path):
    """`nullify_cache` is not a Null object and `stubborn_retry` is not a
    stub. The prefix has to end where a name part ends."""
    files = _tree(tmp_path, {
        "c.py": "def nullify_cache():\n    pass\n\n\ndef stubborn_retry():\n    pass\n",
        "app.py": "def go():\n    nullify_cache()\n    return stubborn_retry()\n",
    })
    assert {h.name for h in find_dead_ends(files)} == {"nullify_cache", "stubborn_retry"}


# --------------------------------------------------------------- test code

def test_a_test_double_is_not_a_dead_end(tmp_path):
    """Measured false positives: _FakeClient.close, _FakeConn.close,
    NoneReturningDecider.safety_check, RangePublishingIndex.add."""
    files = _tree(tmp_path, {
        "tests/test_thing.py": '''\
            class _FakeConn:
                def close(self):
                    pass


            def test_it():
                _FakeConn().close()
        ''',
    })
    assert find_dead_ends(files) == []


def test_a_stub_defined_in_a_test_file_is_not_reported(tmp_path):
    """The definition side of the same rule, with a name the Null Object
    convention does NOT cover, so only the test-directory skip is holding
    it back and this test therefore tests that skip."""
    files = _tree(tmp_path, {
        "tests/test_router.py": "class Recorder:\n"
                                "    def record(self, event):\n        pass\n",
        "app.py": "def go(r, e):\n    return r.record(e)\n",
    })
    assert find_dead_ends(files) == []


def test_a_helper_stub_in_a_test_file_is_not_reported(tmp_path):
    """The same rule for a module-level function. Both halves of the
    definition skip need their own case: a mutant that reports only
    methods, or only functions, survives a suite that covers one."""
    files = _tree(tmp_path, {
        "tests/test_router.py": "def record_event(event):\n    pass\n",
        "app.py": "def go(e):\n    return record_event(e)\n",
    })
    assert find_dead_ends(files) == []


def test_a_stub_called_only_by_a_test_is_not_reported(tmp_path):
    """The call has to come from live code. A stub that only tests reach is
    a fixture, whatever it is named."""
    files = _tree(tmp_path, {
        "core.py": "class Router:\n    def dispatch(self, e):\n        pass\n",
        "tests/test_router.py": "from core import Router\n\n\n"
                                "def test_dispatch():\n    Router().dispatch(1)\n",
    })
    assert find_dead_ends(files) == []


def test_an_uncalled_stub_is_left_to_dead_code(tmp_path):
    """Nobody opens this door, which is the other detector's question. Two
    detectors reporting one thing is how a report doubles its own noise."""
    files = _tree(tmp_path, {
        "core.py": "class Router:\n    def dispatch(self, e):\n        pass\n",
    })
    assert find_dead_ends(files) == []
