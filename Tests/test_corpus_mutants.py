"""The proof that Tests/test_corpus.py is not vacuous.

The mutants that matter loosen the one policy back into the six that
disagreed, or let a shared tree leak to the one caller that mutates.

The working tree is never modified.
"""
from __future__ import annotations

import pytest

from mutant_harness import assert_killed, run_tests_with_mutation

TESTS = "Tests/test_corpus.py"
_C = "ghost_buster/corpus.py"
_M = "ghost_buster/mechanical.py"

MUTANTS = [
    # ---- one policy
    ("a bad byte is decoded with replacement and reasoned about", _C,
     "        text = raw.decode(encoding)", '        text = raw.decode(encoding, errors="replace")'),
    ("the coding cookie is ignored", _C,
     "        encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)",
     '        encoding = "utf-8"'),
    ("a syntax error stops naming its line", _C,
     '        line = f" at line {e.lineno}" if e.lineno else ""', '        line = ""'),
    ("an unreadable file escapes as an exception", _C,
     "    except OSError as e:\n        return Source(path, None, None, f\"{type(e).__name__}: {e}\", stamp)",
     "    except OSError as e:\n        raise"),
    ("the blind-spot list is always empty", _C,
     "        if source.failure is not None:\n            out.append((source.path, source.failure))",
     "        if False:\n            out.append((source.path, source.failure))"),

    # ---- the cache
    ("a changed file is served stale", _C,
     "    if cached is not None and cached.stamp == _stamp(path):",
     "    if cached is not None:"),
    ("nothing is ever served from the cache", _C,
     "    if cached is not None and cached.stamp == _stamp(path):",
     "    if False:"),
    ("reset stops clearing", _C,
     "    _CACHE.clear()\n", "    pass\n"),
    ("run_all inherits the previous scan's cache", _M,
     "    file_list = list(files)\n    corpus.reset()", "    file_list = list(files)"),

    # ---- the contract
    ("the mutation engine is handed the shared tree", _C,
     "    return _read(path).tree", "    return read(path).tree"),
]


@pytest.mark.parametrize("label,rel,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_corpus_mutant_is_killed(label, rel, old, new):
    assert_killed(label, TESTS, run_tests_with_mutation(TESTS, rel, old, new))


def test_corpus_tests_pass_unmutated():
    """A mutant is only judged against a suite that passes as written."""
    result = run_tests_with_mutation(TESTS, _C, 'Stamp = Tuple[int, int]', 'Stamp = Tuple[int, int]')
    assert result.returncode == 0, result.stdout[-2000:]
