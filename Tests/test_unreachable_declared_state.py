"""A state the vocabulary claims and the behaviour does not have.

WHY THIS IS NOT A STYLE COMPLAINT

An enum is a vocabulary of states. A member nothing ever produces is a
distinction that exists in the words and not in the machine, and the damage
is specific: every branch written to handle it is unreachable, anything
dispatching on the enum silently does nothing for it, and a reader believes
the system can be in a state it cannot deliberately enter.

FOUND IN THE WILD, TWICE, ON THE FIRST RUN

An experimental harness declared four phases and its world builder carried
out three. A case declaring the fourth built a world WITHOUT its mutation,
recorded an empty construction history, and was then judged by a check that
adjusted its verdict BECAUSE the phase was declared. The experiment stopped
asking its question and still produced an answer.

And this tool's own `Status.REJECTED` -- "a human looked and said no" --
which nothing produces, whose triage module does not exist, and about which
a test asserts a property.

THE ASYMMETRY IS THE SIGNAL

Reported only when some members of the same enum are produced and others are
not. An enum reconstructed entirely from data -- an HTTP status, a wire
protocol -- is not a defect, and without this rule it would be the entire
output of this detector.
"""
from __future__ import annotations

import textwrap

import pytest

from ghost_buster.mechanical import detect_unreachable_declared_state
from ghost_buster.schema import Severity


def _scan(tmp_path, **files):
    paths = []
    for name, body in files.items():
        path = tmp_path / ("%s.py" % name)
        path.write_text(textwrap.dedent(body))
        paths.append(path)
    return detect_unreachable_declared_state(sorted(paths))


MIXED = '''
    from enum import Enum

    class Phase(Enum):
        BUILD = "build"
        DURING = "during"
        AFTER = "after"
        BETWEEN = "between"

    def run(kind):
        if kind == 1:
            return Phase.BUILD
        if kind == 2:
            return Phase.DURING
        return Phase.AFTER

    def is_temporal(phase):
        return phase in (Phase.DURING, Phase.BETWEEN)
'''


CONSTANTS = '''
    class Limits:
        MAX_RETRIES = 3
        TIMEOUT = 30
        UNUSED_KNOB = 7

    def f():
        return Limits.MAX_RETRIES + Limits.TIMEOUT
'''


# ------------------------------------------------------------- it fires

def test_a_member_nothing_produces_is_reported(tmp_path):
    found = _scan(tmp_path, m=MIXED)
    assert [f.attributes["member"] for f in found] == ["BETWEEN"]


def test_being_compared_against_is_not_being_produced(tmp_path):
    """`phase in (DURING, BETWEEN)` is the whole reason this defect hides.
    Something else has to produce a value for the comparison to ever be
    true, so counting comparisons would make every member look produced by
    the code that checks for it."""
    found = _scan(tmp_path, m=MIXED)
    assert found and found[0].attributes["member"] == "BETWEEN"


def test_the_finding_says_how_many_siblings_are_produced(tmp_path):
    found = _scan(tmp_path, m=MIXED)
    assert found[0].attributes["produced_members"] == "3"
    assert found[0].attributes["declared_members"] == "4"
    assert "3 other member(s)" in found[0].summary


def test_it_points_at_the_declaration(tmp_path):
    found = _scan(tmp_path, m=MIXED)
    assert found[0].evidence.line_start == 8   # the BETWEEN = line


# --------------------------------------------------- it stays quiet

def test_an_enum_where_everything_is_produced_is_silent(tmp_path):
    assert _scan(tmp_path, m='''
        from enum import Enum

        class Colour(Enum):
            RED = "red"
            BLUE = "blue"

        def pick(x):
            return Colour.RED if x else Colour.BLUE
    ''') == []


def test_an_enum_reconstructed_entirely_from_data_is_silent(tmp_path):
    """THE RULE THAT MAKES THIS DETECTOR USABLE.

    An HTTP status, a wire protocol, anything parsed from the outside: no
    member is ever named, every member arrives from data. Flagging those
    would make the whole output noise, and there is nothing wrong with them.
    """
    assert _scan(tmp_path, m='''
        from enum import Enum

        class HttpStatus(Enum):
            OK = 200
            NOT_FOUND = 404
            TEAPOT = 418

        def parse(code):
            return HttpStatus(code)
    ''') == []


def test_a_member_produced_only_in_another_file_is_silent(tmp_path):
    """The scanned set is one corpus. A state produced in the module that
    uses it is produced."""
    assert _scan(
        tmp_path,
        defs='''
            from enum import Enum

            class Phase(Enum):
                A = "a"
                B = "b"

            def first():
                return Phase.A
        ''',
        uses='''
            from defs import Phase

            def second():
                return Phase.B
        ''') == []


def test_an_ordinary_class_of_constants_is_not_an_enum(tmp_path):
    """A settings class is not a state machine.

    `class Limits: MAX_RETRIES = 3` has upper-case class attributes and no
    states. Flagging the one nobody happens to read would be this detector
    wandering into a different job, and the base check is what keeps it out.
    """
    assert _scan(tmp_path, m=CONSTANTS) == []


def test_a_file_with_no_enum_at_all_is_silent(tmp_path):
    assert _scan(tmp_path, m="def f():\n    return 1\n") == []


def test_a_lowercase_class_attribute_is_not_a_member(tmp_path):
    """Enum members are conventionally upper case; an ordinary attribute on
    an enum class is not a state."""
    found = _scan(tmp_path, m='''
        from enum import Enum

        class Phase(Enum):
            A = "a"
            B = "b"
            default = "a"

        def f():
            return Phase.A

        def g():
            return Phase.B
    ''')
    assert found == []


def test_an_unparseable_file_is_skipped_not_guessed_at(tmp_path):
    bad = tmp_path / "broken.py"
    bad.write_text("def f(:\n")
    assert detect_unreachable_declared_state([bad]) == []


# ------------------------------- a lookup table is a comparison in disguise
#
# `AUTHORITATIVE = frozenset({Status.CONFIRMED, Status.CONFIRMED_BY_REVIEW,
# Status.SUPPRESSED})` names three members and produces none of them. The set
# exists to be tested against, exactly like the `in` it is written for.
#
# Counting that as production made this detector miss a state of precisely
# the shape it was built to find: on its own repository it reported
# `Status.REJECTED` and stayed quiet about `Status.CONFIRMED_BY_REVIEW`,
# which is never assigned either. A detector with a blind spot the shape of
# its own subject is worth a test of its own.

TABLE = '''
    from enum import Enum

    class Status(Enum):
        CONFIRMED = "confirmed"
        BY_REVIEW = "by_review"
        SUPPRESSED = "suppressed"
        REJECTED = "rejected"

    AUTHORITATIVE = frozenset({Status.CONFIRMED, Status.BY_REVIEW,
                               Status.SUPPRESSED})

    def scan():
        return Status.CONFIRMED

    def suppress(f):
        f.status = Status.SUPPRESSED

    def authoritative(items):
        return [i for i in items if i.status in AUTHORITATIVE]
'''

# One member produced the ordinary way, one only through a scalar constant.
# Both shapes must read as produced, and the enum must have a live member so
# the asymmetry rule does not skip it and hide the answer.
SCALAR = '''
    from enum import Enum

    class Phase(Enum):
        BUILD = "build"
        OTHER = "other"

    FALLBACK = Phase.OTHER

    def go(x):
        return Phase.BUILD if x else FALLBACK
'''

# A lower-case module-level collection is ordinary code, not a constant
# table. The convention is the only signal available to an AST-only tool,
# and it is the signal the pattern actually uses.
LOWERCASE = '''
    from enum import Enum

    class Phase(Enum):
        BUILD = "build"
        OTHER = "other"

    defaults = [Phase.OTHER]

    def go(x):
        return Phase.BUILD if x else defaults[0]
'''

# Upper-case, a collection, and INSIDE a function. Only module-level
# constants are tables; a collection built in a function body is ordinary
# code and its members are being used.
LOCAL = '''
    from enum import Enum

    class Phase(Enum):
        BUILD = "build"
        OTHER = "other"

    def go(x):
        TABLE = [Phase.OTHER]
        return Phase.BUILD if x else TABLE[0]
'''


def test_membership_of_a_constant_table_is_not_production(tmp_path):
    found = {f.attributes['member'] for f in _scan(tmp_path, m=TABLE)}
    assert found == {'BY_REVIEW', 'REJECTED'}, (
        'a member named only in a lookup table was counted as produced')


def test_a_constant_holding_one_member_is_still_a_production(tmp_path):
    """THE BOUNDARY. `DEFAULT = Phase.BUILD` is not a table: something reads
    that name and uses the value. Only COLLECTIONS are tables."""
    assert _scan(tmp_path, m=SCALAR) == []


def test_a_lower_case_module_collection_is_not_a_table(tmp_path):
    """Convention is the only signal an AST-only tool has, and it is the
    one the pattern actually uses: tables are named in capitals."""
    assert _scan(tmp_path, m=LOWERCASE) == []


def test_a_local_collection_is_not_a_constant_table(tmp_path):
    """Only module-level upper-case names. A collection built inside a
    function is ordinary code and its members are being used."""
    assert _scan(tmp_path, m=LOCAL) == []


# ----------------------------------------------------- what it claims

def test_the_severity_leaves_the_judgement_to_a_human(tmp_path):
    """The right repair is to produce it, handle its arrival, or remove it,
    and which of those is correct is not something an AST can decide."""
    assert _scan(tmp_path, m=MIXED)[0].severity is Severity.MINOR


def test_it_does_not_claim_the_state_is_unreachable(tmp_path):
    """`Phase("between")` reconstructs any member from a string, so a stored
    record can still carry it. That is worse rather than better, and the
    finding has to say so instead of claiming nothing can get there."""
    detail = _scan(tmp_path, m=MIXED)[0].detail
    assert "does not claim the state is unreachable" in detail
    assert "stored record" in detail


def test_it_tells_the_reader_to_check_the_dispatch(tmp_path):
    assert "what that dispatch does" in _scan(tmp_path, m=MIXED)[0].detail


# --------------------------------------------------- the real patients

def test_the_defect_this_was_built_for(tmp_path):
    """The harness shape, reduced: three phases carried out, a fourth
    declared, and a predicate that changes its answer for the fourth."""
    found = _scan(tmp_path, world='''
        from enum import Enum

        class Phase(Enum):
            BUILD = "build"
            DURING_TESTS = "during_tests"
            BETWEEN_RUNS = "between_runs"
            AFTER_BASELINE = "after_baseline"

        def build(genome):
            apply_all(genome, Phase.BUILD)
            apply_all(genome, Phase.DURING_TESTS)
            apply_all(genome, Phase.AFTER_BASELINE)

        def is_temporal(m):
            return m.phase in (Phase.DURING_TESTS, Phase.BETWEEN_RUNS)

        def apply_all(genome, phase):
            pass
    ''')
    assert [f.attributes["member"] for f in found] == ["BETWEEN_RUNS"]
