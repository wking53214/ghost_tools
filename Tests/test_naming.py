"""Names that say where the code came from instead of what it does.

The vestigial check exists because observe-perceive's own cassette commit
recorded the work it was leaving behind:

    The engine's private attributes are still named _patient_kalman,
    _patient_policies, _touch_patient. The VALUES flowing through them come
    from the cassette, so a pump keys correctly today -- these are names,
    not couplings.

That is a defect no test can catch, because the behaviour is right. It is
also the exact thing an author forgets, because the code works.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

from ghost_buster.naming import (
    DISAGREEMENT_DETECTOR,
    MINIMUM_CASSETTES,
    _ORDINARY_ENGLISH,
    detect_name_disagreements,
    detect_placeholder_names,
    detect_vestigial_domain_names,
    domain_vocabularies,
    find_cassettes,
)
from ghost_buster.schema import Category, Layer, Severity, Status


def _tree(tmp_path: Path, files: dict) -> list:
    for rel, body in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(body))
    return sorted(tmp_path.glob("*.py"))


def _two_cassettes(tmp_path: Path, core: str) -> list:
    return _tree(tmp_path, {
        "cassette.py": "REQUIRED = ('subject_id', 'channels')\n",
        # Channel names are BOUND, not quoted: a string literal is not an
        # identifier and the detector reads identifiers, correctly.
        "pediatric_cassette.py":
            "def subject_id(reading):\n"
            "    patient_id = reading['id']\n"
            "    return patient_id\n"
            "oxygen_saturation = 'spo2'\n"
            "respiratory_rate = 'rr'\n",
        "industrial_cassette.py":
            "def subject_id(reading):\n"
            "    asset_tag = reading['id']\n"
            "    return asset_tag\n"
            "vibration_velocity = 'mm_s'\n"
            "bearing_load = 'kn'\n",
        "engine.py": core,
    })


# ----------------------------------------------------------------- abstention

def test_it_abstains_with_fewer_than_two_cassettes(tmp_path):
    """With one domain, every word it uses looks domain-specific and the
    engine's own vocabulary cannot be told apart from it."""
    files = _tree(tmp_path, {
        "cassette.py": "REQUIRED = ('subject_id',)\n",
        # Bound, not quoted, and shared with the engine below: without the
        # guard this WOULD be reported, which is what makes the guard
        # testable at all.
        "pediatric_cassette.py": "oxygen_saturation = 'spo2'\npatient_id = 'id'\n",
        "engine.py": "def track(patient_id):\n    return patient_id\n",
    })
    assert len(find_cassettes(files)[0]) < MINIMUM_CASSETTES
    assert detect_vestigial_domain_names(files) == []


def test_it_abstains_when_there_is_no_seam_at_all(tmp_path):
    files = _tree(tmp_path, {"engine.py": "def track(patient_id):\n    return patient_id\n"})
    assert detect_vestigial_domain_names(files) == []


# ------------------------------------------------------------- the real thing

def test_domain_vocabulary_is_the_words_only_one_cassette_uses(tmp_path):
    files = _two_cassettes(tmp_path, "x = 1\n")
    vocab = domain_vocabularies(*find_cassettes(files))
    assert "oxygen" in vocab["pediatric_cassette"]
    assert "vibration" in vocab["industrial_cassette"]
    # `subject_id` and `reading` are the contract's and everyone's
    assert "subject" not in vocab["pediatric_cassette"]
    assert "reading" not in vocab["industrial_cassette"]


def test_a_core_module_keeping_one_domains_words_is_reported(tmp_path):
    files = _two_cassettes(tmp_path, '''
        class PatientKalmanTracker:
            def __init__(self):
                self._patient_policies = {}
        ''')
    found = detect_vestigial_domain_names(files)
    assert len(found) == 1
    f = found[0]
    assert "pediatric" in f.summary and "engine.py" in f.summary
    assert "PatientKalmanTracker" in f.detail and "_patient_policies" in f.detail


def test_a_core_module_using_only_shared_words_is_not_reported(tmp_path):
    """The check must be silent on an engine that IS domain-agnostic, or it
    reports the success of the refactor as its failure."""
    files = _two_cassettes(tmp_path, '''
        def evaluate(subject_id, reading, channels):
            return {"subject_id": subject_id, "channels": channels}
        ''')
    assert detect_vestigial_domain_names(files) == []


def test_the_cassettes_themselves_are_never_reported(tmp_path):
    """A cassette carrying its own domain's words is the entire point."""
    files = _two_cassettes(tmp_path, "x = 1\n")
    assert all("cassette" not in f.evidence.file for f in detect_vestigial_domain_names(files))


def test_a_finding_is_mechanical_confirmed_and_minor(tmp_path):
    files = _two_cassettes(tmp_path, "def go(patient_id):\n    return patient_id\n")
    f = detect_vestigial_domain_names(files)[0]
    assert f.layer is Layer.MECHANICAL and f.status is Status.CONFIRMED
    assert f.severity is Severity.MINOR
    assert f.category is Category.NAMING


def test_a_generic_python_word_is_not_a_domain_word(tmp_path):
    """`severity` is vocabulary this tool itself uses everywhere. A cassette
    mentioning it does not make it pediatrics, and an engine using it is not
    carrying a domain."""
    # `severity` must appear in exactly ONE cassette for the generic filter
    # to be the thing that excludes it; in neither, it is never a candidate
    # and the test proves nothing.
    files = _tree(tmp_path, {
        "cassette.py": "REQUIRED = ('subject_id',)\n",
        "pediatric_cassette.py": "severity = 'high'\noxygen_saturation = 'spo2'\n",
        "industrial_cassette.py": "vibration_velocity = 'mm_s'\n",
        "engine.py": "def go(severity):\n    return severity\n",
    })
    vocab = domain_vocabularies(*find_cassettes(files))
    assert "oxygen" in vocab["pediatric_cassette"]      # the fixture works
    assert "severity" not in vocab["pediatric_cassette"]  # ...and the filter fires
    assert detect_vestigial_domain_names(files) == []


def test_a_measured_false_positive_stays_excluded(tmp_path):
    """`triggered` reads as industrial only because this tool does not use
    it. The engine's `triggered_rules` is a core concept, not a domain's."""
    files = _tree(tmp_path, {
        "cassette.py": "REQUIRED = ('subject_id',)\n",
        "pediatric_cassette.py": "oxygen_saturation = 'spo2'\n",
        "industrial_cassette.py": "triggered = ()\nvibration_velocity = 'mm_s'\n",
        "engine.py": "def go():\n    triggered_rules = []\n    return triggered_rules\n",
    })
    vocab = domain_vocabularies(*find_cassettes(files))
    assert "triggered" not in vocab["industrial_cassette"]
    assert "vibration" in vocab["industrial_cassette"]
    assert detect_vestigial_domain_names(files) == []


def test_ordinary_english_is_excluded_by_measurement_not_by_guess():
    """Each entry was observed as a false positive. The set is pinned by
    literal so that adding a word costs an edit and a reason."""
    assert "triggered" in _ORDINARY_ENGLISH
    assert "faults" in _ORDINARY_ENGLISH
    # ...and a real domain word is NOT quietly excluded with them
    assert "vibration" not in _ORDINARY_ENGLISH
    assert "patient" not in _ORDINARY_ENGLISH


# --------------------------------------------------------------- placeholders

def test_placeholder_and_versioned_names_are_reported(tmp_path):
    files = _tree(tmp_path, {"m.py": "tmp = 1\ndecision_old = 2\ndecision_new = 3\nhandler_v2 = 4\n"})
    f = detect_placeholder_names(files)[0]
    assert f.severity is Severity.MINOR
    for name in ("tmp", "decision_old", "decision_new", "handler_v2"):
        assert name in f.detail, name


def test_a_measurement_is_never_mistaken_for_a_placeholder(tmp_path):
    """`temp` is a temperature and `bar` is a unit of pressure. A list that
    flags either is worse than no list."""
    files = _tree(tmp_path, {
        # `threshold_old_value` CONTAINS `_old` and does not end with it;
        # a substring match would flag it.
        "m.py": "temp = 37.2\nbar = 4.1\ntemplate = 'x'\nthreshold = 2\n"
                "threshold_old_value = 3\nrenewal_date = 4\n"})
    assert detect_placeholder_names(files) == []


def test_tests_are_left_alone(tmp_path):
    files = _tree(tmp_path, {"test_thing.py": "tmp = 1\n"})
    assert detect_placeholder_names(files) == []


# ------------------------------------------------- one thing under two names

def _pair(tmp_path: Path) -> list:
    """A parameter that only ever receives one variable, and a variable that
    only ever reaches one parameter. The second argument is named the same on
    both sides, so it contributes nothing and the fixture has exactly one
    pair in it."""
    return _tree(tmp_path, {
        "queue.py":
            "def enqueue(recipient_pub, payload):\n"
            "    return (recipient_pub, payload)\n",
        "caller.py":
            "from queue import enqueue\n"
            "def send(cust_pub, payload):\n"
            "    return enqueue(cust_pub, payload)\n",
    })


def test_a_one_to_one_disagreement_is_reported(tmp_path):
    findings = detect_name_disagreements(_pair(tmp_path))
    assert len(findings) == 1
    f = findings[0]
    assert f.detector == DISAGREEMENT_DETECTOR
    assert f.category is Category.NAMING
    assert f.layer is Layer.MECHANICAL
    assert f.severity is Severity.MINOR
    assert f.status is Status.CONFIRMED
    assert "recipient_pub" in f.summary and "cust_pub" in f.summary
    # Both ends: the signature that declares the parameter and the call
    # that passes the variable.
    assert {Path(p).name for p in f.evidence.related_files} == {"queue.py", "caller.py"}


def test_a_keyword_argument_counts(tmp_path):
    files = _tree(tmp_path, {
        "queue.py": "def enqueue(recipient_pub):\n    return recipient_pub\n",
        "caller.py":
            "from queue import enqueue\n"
            "def send(cust_pub):\n"
            "    return enqueue(recipient_pub=cust_pub)\n",
    })
    assert len(detect_name_disagreements(files)) == 1


def test_the_same_name_on_both_sides_is_not_a_disagreement(tmp_path):
    files = _tree(tmp_path, {
        "queue.py": "def enqueue(payload):\n    return payload\n",
        "caller.py":
            "def send(payload):\n"
            "    return enqueue(payload)\n",
    })
    assert detect_name_disagreements(files) == []


def test_a_parameter_taking_several_variables_is_doing_its_job(tmp_path):
    """Not a disagreement. Renaming `dest` after either caller's local would
    be wrong for the other one."""
    files = _tree(tmp_path, {
        "sink.py": "def deliver(dest):\n    return dest\n",
        "caller.py":
            "def one(alpha):\n"
            "    return deliver(alpha)\n"
            "def two(beta):\n"
            "    return deliver(beta)\n",
    })
    assert detect_name_disagreements(files) == []


def test_a_variable_reaching_several_parameters_is_not_renamable(tmp_path):
    """`token` is one name in the caller and two names in the callees.
    Renaming it would have to pick one and collide with the other."""
    files = _tree(tmp_path, {
        "sink.py":
            "def left(dest):\n    return dest\n"
            "def right(origin):\n    return origin\n",
        "caller.py":
            "def send(token):\n"
            "    return (left(token), right(token))\n",
    })
    assert detect_name_disagreements(files) == []


def test_a_function_this_scan_never_saw_is_left_alone(tmp_path):
    """pyparsing's `parseAll` is not ours to reconcile. The genuine pair in
    the same tree is still reported, so this is not vacuous."""
    files = _tree(tmp_path, {
        "queue.py": "def enqueue(recipient_pub):\n    return recipient_pub\n",
        "caller.py":
            "def send(cust_pub, grammar, flag):\n"
            "    grammar.parse_string(flag)\n"
            "    third_party_entry(strict=flag)\n"
            "    return enqueue(cust_pub)\n",
    })
    summaries = [f.summary for f in detect_name_disagreements(files)]
    assert len(summaries) == 1
    assert "cust_pub" in summaries[0]


def test_two_functions_sharing_a_name_decide_nothing(tmp_path):
    """The worst false positive this detector produced, on 2026-09-10:
    `run(cmd)` in one module supplied the parameter names for `run(nodeids)`
    in another, and the two were reported as one value under two names.
    They are not the same function. Ambiguity is a reason to say nothing."""
    files = _tree(tmp_path, {
        "a.py": "def run(nodeids):\n    return nodeids\n",
        "b.py": "def run(other):\n    return other\n",
        "c.py": "def go(cmd):\n    return run(cmd)\n",
    })
    assert detect_name_disagreements(files) == []


def test_two_classes_with_one_method_name_decide_nothing(tmp_path):
    """`self.handle` in a module where two classes define `handle` names one
    of them, and a walk over the syntax tree cannot say which. Picking the
    first is how the parameter names of one class end up describing the
    other's."""
    files = _tree(tmp_path, {
        "a.py":
            "class Alpha:\n"
            "    def handle(self, recipient_pub):\n"
            "        return recipient_pub\n"
            "class Beta:\n"
            "    def handle(self, other_name):\n"
            "        return other_name\n"
            "    def send(self, cust_pub):\n"
            "        return self.handle(cust_pub)\n",
    })
    assert detect_name_disagreements(files) == []


def test_a_call_in_the_same_file_wins_over_a_stranger(tmp_path):
    """Python looks in the module first, and so does this. `enqueue` here is
    the local one, whose parameter is `local_pub` -- not the other file's."""
    files = _tree(tmp_path, {
        "far.py": "def enqueue(recipient_pub):\n    return recipient_pub\n",
        "near.py":
            "def enqueue(local_pub):\n    return local_pub\n"
            "def send(cust_pub):\n    return enqueue(cust_pub)\n",
    })
    findings = detect_name_disagreements(files)
    assert len(findings) == 1
    assert "local_pub" in findings[0].summary
    assert "recipient_pub" not in findings[0].summary


def test_a_method_on_somebody_elses_object_is_not_ours(tmp_path):
    """`subprocess.run(cmd)` is not our `run`. The receiver's type is exactly
    what this layer does not know, so only `self`/`cls` methods count."""
    files = _tree(tmp_path, {
        "a.py": "def run(nodeids):\n    return nodeids\n",
        "b.py":
            "import subprocess\n"
            "def go(cmd):\n    return subprocess.run(cmd)\n",
    })
    assert detect_name_disagreements(files) == []


def test_a_method_reached_through_self_still_counts(tmp_path):
    files = _tree(tmp_path, {
        "a.py":
            "class Sender:\n"
            "    def enqueue(self, recipient_pub):\n"
            "        return recipient_pub\n"
            "    def send(self, cust_pub):\n"
            "        return self.enqueue(cust_pub)\n",
    })
    assert len(detect_name_disagreements(files)) == 1


def test_a_constant_keeps_its_role(tmp_path):
    """INGRESS_GUARDS is not renamed to `dependencies` because it happens to
    be passed as one. The case is a real one, observed 2026-09-10."""
    files = _tree(tmp_path, {
        "app.py":
            "INGRESS_GUARDS = ('a',)\n"
            "def build(dependencies):\n    return dependencies\n"
            "def main():\n    return build(INGRESS_GUARDS)\n",
    })
    assert detect_name_disagreements(files) == []


def test_a_leading_underscore_is_a_statement_that_survives(tmp_path):
    files = _tree(tmp_path, {
        "app.py":
            "def _create():\n    return 1\n"
            "def register(create_fn):\n    return create_fn\n"
            "def main():\n    return register(_create)\n",
    })
    assert detect_name_disagreements(files) == []


def test_camel_case_means_somebody_elses_api(tmp_path):
    files = _tree(tmp_path, {
        "app.py":
            "def load(parse_all):\n    return parse_all\n"
            "def main(parseAll):\n    return load(parseAll)\n",
    })
    assert detect_name_disagreements(files) == []


def test_disagreements_in_tests_are_left_alone(tmp_path):
    files = _tree(tmp_path, {
        "test_queue.py":
            "def enqueue(recipient_pub):\n    return recipient_pub\n"
            "def test_send(cust_pub):\n"
            "    return enqueue(cust_pub)\n",
    })
    assert detect_name_disagreements(files) == []
