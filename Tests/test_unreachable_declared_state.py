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


# ------------------------ a state only a test can create is still unreached
#
# This is not a refinement. It is the difference between finding the defect
# and missing it.
#
# The harness defect that motivated this detector -- a phase declared and
# never carried out -- would have gone unreported if a single test had named
# the phase, and a test naming it is the most likely thing in the world. A
# test constructs a state artificially to prove it is HANDLED; that is not
# something producing it.
#
# Weaker evidence, weaker claim: nothing at all producing a member is MINOR,
# a member only tests produce is INFORMATIONAL. Measured, the distinction
# added four true findings across two repositories and not one was
# actionable -- every one was reached from stored data or held unreachable on
# purpose. Reporting those at the same weight as a real gap is how a usable
# detector becomes a noisy one.

LIB = '''
    from enum import Enum

    class Phase(Enum):
        BUILD = "build"
        BETWEEN = "between"

    def build():
        return Phase.BUILD
'''

TEST_PRODUCES = '''
    from lib import Phase

    def test_between_is_handled():
        assert Phase.BETWEEN.value
        return Phase.BETWEEN
'''


def _files(tmp_path, **named):
    import textwrap
    out = []
    for name, body in named.items():
        path = tmp_path / ("%s.py" % name)
        path.write_text(textwrap.dedent(body))
        out.append(path)
    return sorted(out)


def test_a_state_only_a_test_produces_is_still_reported(tmp_path):
    """THE ONE THAT MATTERS. Without this, one test naming the state hides
    the defect entirely."""
    from ghost_buster.mechanical import detect_unreachable_declared_state
    found = detect_unreachable_declared_state(
        _files(tmp_path, lib=LIB, test_phase=TEST_PRODUCES))
    assert [f.attributes['member'] for f in found] == ['BETWEEN']


def test_it_says_the_production_was_a_test(tmp_path):
    from ghost_buster.mechanical import detect_unreachable_declared_state
    found = detect_unreachable_declared_state(
        _files(tmp_path, lib=LIB, test_phase=TEST_PRODUCES))
    assert found[0].attributes['produced_by_tests_only'] == 'yes'
    assert 'only test code' in found[0].summary
    assert 'proves it is handled' in found[0].detail


def test_a_test_producing_it_does_not_buy_a_lower_severity(tmp_path):
    """THE 1.7.7 DEFECT, WRITTEN DOWN SO IT CANNOT COME BACK.

    1.7.7 reported a test-only state at INFORMATIONAL instead of MINOR, on
    the reasoning that somebody constructing the state deliberately is weak
    evidence it was meant to be unreachable.

    The reasoning was wrong in a way that generalises. A test file is the
    cheapest artifact anyone can add to a repository, so grading it measures
    willingness to type, not intent. An adversary looking for a cheap edit
    that changes this tool's verdict was handed one, and the comment next to
    it explained where.

    Evidence that costs nothing to manufacture never lowers a severity here.
    """
    from ghost_buster.mechanical import detect_unreachable_declared_state
    only_tests = detect_unreachable_declared_state(
        _files(tmp_path, lib=LIB, test_phase=TEST_PRODUCES), history=False)
    nothing = detect_unreachable_declared_state(
        _files(tmp_path, lib=LIB), history=False)
    assert only_tests[0].severity is nothing[0].severity
    assert only_tests[0].severity is Severity.MINOR
    # Still recorded, because it is true and a reader may want it. Recorded
    # is not the same as credited.
    assert only_tests[0].attributes["produced_by_tests_only"] == "yes"
    assert nothing[0].attributes["produced_by_tests_only"] == "no"


# ---------------------------------------------------------------------------
# Structural reachability: a member built from a runtime value is reachable
# ---------------------------------------------------------------------------

FROM_DATA = '''
    from enum import Enum

    class Phase(Enum):
        BUILD = "build"
        BETWEEN = "between"

    def build():
        return Phase.BUILD

    def load(record):
        return Phase(record["phase"])
'''

DOCUMENTED = '''
    from enum import Enum

    class Phase(Enum):
        """Phases.

        produced here      BUILD
        arrives from data  BETWEEN
        """
        BUILD = "build"
        BETWEEN = "between"

    def build():
        return Phase.BUILD

    def load(record):
        return Phase(record["phase"])
'''

CLAIMED_ONLY = '''
    from enum import Enum

    class Phase(Enum):
        """Phases.

        produced here      BUILD
        arrives from data  BETWEEN
        """
        BUILD = "build"
        BETWEEN = "between"

    def build():
        return Phase.BUILD
'''


def test_a_member_built_from_a_runtime_value_is_reachable(tmp_path):
    """`Phase(record["phase"])` can produce any member. A detector that only
    looks for `Phase.BETWEEN` calls that member unreachable, which is not a
    near miss but the opposite of the truth.

    This was a live false positive: `Status.CONFIRMED_BY_REVIEW` and
    `Status.REJECTED` in this repository, reported at the top severity this
    detector emitted, while `Finding.from_dict` built either from a stored
    record thirty lines away.
    """
    found = _scan(tmp_path, m=FROM_DATA)
    assert [f.severity for f in found] == [Severity.MINOR]
    assert found[0].attributes["reachable_from_data"] == "yes"


def test_a_documented_data_path_is_silent(tmp_path):
    """Reachable, and the enum says so. Nothing to report."""
    assert _scan(tmp_path, m=DOCUMENTED) == []


def test_an_undocumented_data_path_is_worth_one_line(tmp_path):
    """Reachable but unexplained. The member looks abandoned to a reader, and
    the next person tidying up deletes it and turns reading an old file into
    a crash."""
    found = _scan(tmp_path, m=FROM_DATA)
    assert found[0].attributes["documented_as_from_data"] == "no"
    assert "nothing says so" in found[0].summary


def test_a_claim_the_code_does_not_back_is_critical(tmp_path):
    """PROSE CANNOT BUY A LOWER SEVERITY, AND CAN BUY A HIGHER ONE.

    A docstring saying a member arrives from stored data, with nothing
    building the enum from a value, is worse than silence: an undocumented
    gap is a gap, a documented one is a gap plus an assurance that it is
    fine, and the assurance is what stops the next reader looking.

    CRITICAL is this repository's own definition -- "actively misleading or
    dangerous if acted on" -- applied rather than stretched.
    """
    found = _scan(tmp_path, m=CLAIMED_ONLY)
    assert [f.severity for f in found] == [Severity.CRITICAL]
    assert found[0].attributes["documented_as_from_data"] == "yes"
    assert found[0].attributes["reachable_from_data"] == "no"


def test_a_claim_alone_never_suppresses(tmp_path):
    """The asymmetry stated as a test. Without structure behind it the claim
    does not quiet the finding, it escalates it."""
    claimed = _scan(tmp_path, m=CLAIMED_ONLY)
    assert claimed, "a bare claim must not suppress the finding"
    assert claimed[0].severity is Severity.CRITICAL


def test_a_literal_argument_only_accounts_for_its_own_member(tmp_path):
    """`Phase("middle")` accounts for MIDDLE and says nothing about BETWEEN.
    Treating every construction as a blanket data path would suppress real
    findings wherever anyone wrote one literal."""
    found = _scan(tmp_path, m='''
        from enum import Enum

        class Phase(Enum):
            BUILD = "build"
            MIDDLE = "middle"
            BETWEEN = "between"

        def build():
            return Phase.BUILD

        def middle():
            return Phase("middle")
    ''')
    reach = {f.attributes["member"]: f.attributes["reachable_from_data"]
             for f in found}
    assert reach == {"MIDDLE": "yes", "BETWEEN": "no"}


def test_mentioning_a_member_is_not_a_claim_about_it(tmp_path):
    """A docstring that merely NAMES the member says nothing about how it
    arrives. Treating any line naming a member as a claim would turn every
    documented enum into a CRITICAL, which is how an escalation rule becomes
    a reason to stop writing docstrings."""
    found = _scan(tmp_path, m='''
        from enum import Enum

        class Phase(Enum):
            """Phases.

            BETWEEN is not used yet.
            """
            BUILD = "build"
            BETWEEN = "between"

        def build():
            return Phase.BUILD
    ''')
    assert [f.severity for f in found] == [Severity.MINOR]
    assert found[0].attributes["documented_as_from_data"] == "no"


def test_a_claim_can_cover_the_whole_enum_without_naming_members(tmp_path):
    """"`Finding.from_dict` reconstructs any member from a stored record" is
    how this repository actually states it, and it names nobody. A reader of
    the claim form that only matched named members would miss the commonest
    way the claim is written."""
    found = _scan(tmp_path, m='''
        from enum import Enum

        class Phase(Enum):
            """Phases. `load` reconstructs any member from a stored record."""
            BUILD = "build"
            BETWEEN = "between"

        def build():
            return Phase.BUILD

        def load(record):
            return Phase(record["phase"])
    ''')
    assert found == [], "a blanket claim, backed by a data path, is satisfied"


def test_a_member_name_is_not_matched_inside_a_longer_one(tmp_path):
    """`CONFIRMED` must not be found inside `CONFIRMED_BY_REVIEW`. An
    underscore is a word character, so the boundary does this without a
    special case -- and a mutant dropping the boundaries proves it matters."""
    found = _scan(tmp_path, m='''
        from enum import Enum

        class S(Enum):
            """States.

            arrives from data  CONFIRMED_BY_REVIEW
            """
            CONFIRMED = "c"
            CONFIRMED_BY_REVIEW = "cbr"
            OTHER = "o"

        def f():
            return S.OTHER
    ''')
    claimed = {f.attributes["member"]: f.attributes["documented_as_from_data"]
               for f in found}
    assert claimed["CONFIRMED_BY_REVIEW"] == "yes"
    assert claimed["CONFIRMED"] == "no"


def test_a_state_the_library_produces_is_silent_either_way(tmp_path):
    """The boundary. This must not start reporting live states."""
    from ghost_buster.mechanical import detect_unreachable_declared_state
    assert detect_unreachable_declared_state(_files(tmp_path, lib='''
        from enum import Enum

        class Phase(Enum):
            BUILD = "build"
            BETWEEN = "between"

        def build(x):
            return Phase.BUILD if x else Phase.BETWEEN
    ''', test_phase=TEST_PRODUCES)) == []


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


def test_a_data_path_written_in_a_test_does_not_clear_the_finding(tmp_path):
    """THE SAME HOLE, ONE LEVEL UP.

    Structural evidence clears this finding because faking it means writing a
    real deserialiser. That argument only holds for LIBRARY code. A
    `Phase(record["phase"])` in a test file is barely more typing than naming
    the member, and if it counted, the free lever this version exists to
    remove would be back -- clearing the finding outright rather than merely
    discounting it.
    """
    lib = '''
        from enum import Enum

        class Phase(Enum):
            BUILD = "build"
            BETWEEN = "between"

        def build():
            return Phase.BUILD
    '''
    test = '''
        from lib import Phase

        def test_round_trip(record):
            return Phase(record["phase"])
    '''
    found = detect_unreachable_declared_state(
        _files(tmp_path, lib=lib, test_phase=test), history=False)
    assert [f.attributes["member"] for f in found] == ["BETWEEN"]
    assert found[0].attributes["reachable_from_data"] == "no"
    assert found[0].severity is Severity.MINOR
