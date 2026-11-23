"""Synthetic 10x data: schema matches the sample, labels are exact, and the engine agrees with them.

The generator labels every fault it seeds and the decision each group inquiry was designed to get.
These tests hold the data-quality checks and the rules engine to those labels at 10x the sample size.
"""
import csv
from pathlib import Path

import pytest

from solstice.config import REPO_ROOT, get_settings
from solstice.data import store as store_mod
from solstice.data.quality import run_checks
from solstice.data.store import _read_csv, build_store
from solstice.data.synthetic import FILES, RAW, generate
from solstice.rules.group_rules import GroupRequest, evaluate


@pytest.fixture(scope="module")
def synth(tmp_path_factory):
    out = tmp_path_factory.mktemp("synthetic")
    manifest = generate(out, scale=10, seed=7)
    rows = {k: _read_csv(out / f) for k, f in FILES.items()}
    labels = {n: _read_csv(out / "labels" / f"{n}.csv") for n in ("expected_issues", "inquiry_scenarios")}
    return out, manifest, rows, labels


def test_scale_and_schema_match_the_sample(synth):
    out, manifest, rows, _ = synth
    assert manifest["rows"]["properties"] == 100 and manifest["rows"]["inquiries"] == 100
    assert manifest["rows"]["reservations"] >= 250
    for f in FILES.values():
        with open(RAW / f, encoding="utf-8-sig") as a, open(out / f, encoding="utf-8") as b:
            assert next(csv.reader(a)) == next(csv.reader(b)), f


def test_quality_checks_find_exactly_the_labeled_issues(synth):
    """Every seeded fault is caught, and clean rows raise nothing (no false alarms at 10x)."""
    _, _, rows, labels = synth
    found = {(i.dataset, i.record_id, i.field) for i in run_checks(rows["properties"], rows["reservations"], rows["inquiries"])}
    expected = {(e["dataset"], e["record_id"], e["field"]) for e in labels["expected_issues"]}
    assert found - expected == set(), "issues on rows the generator left clean"
    assert expected - found == set(), "seeded faults the checks missed"


def test_every_fault_kind_is_seeded(synth):
    from solstice.data.synthetic import INQUIRY_FAULTS, PROPERTY_FAULTS, RESERVATION_FAULTS
    kinds = {e["kind"] for e in synth[3]["expected_issues"] if e["source"] == "fault"}
    assert set(PROPERTY_FAULTS + RESERVATION_FAULTS + INQUIRY_FAULTS) <= kinds


def test_rules_engine_reaches_every_designed_decision(synth):
    _, _, rows, labels = synth
    s = build_store(rows["properties"], rows["reservations"], rows["inquiries"])
    checked, wrong = 0, []
    for lab in labels["inquiry_scenarios"]:
        if lab["scenario"].startswith("faulted:"):
            continue
        q = s.inquiries[lab["inquiry_id"]]
        ev = evaluate(s, GroupRequest(q.preferred_property, q.arrival, q.departure, q.rooms_requested, q.room_type,
                                      q.requested_discount_pct, q.budget_per_night, q.meeting_capacity_needed, q.event_type))
        flags = {c.rule for c in ev.checks if c.status in ("flag", "block")}
        want = set(filter(None, lab["expected_flags"].split(";")))
        if ev.decision != lab["expected_decision"] or not want <= flags:
            wrong.append((lab["inquiry_id"], lab["scenario"], ev.decision, sorted(flags)))
        checked += 1
    assert checked >= 90 and not wrong, wrong


def test_same_seed_same_files(tmp_path, synth):
    out, *_ = synth
    generate(tmp_path, scale=10, seed=7)
    for f in [*FILES.values(), "labels/expected_issues.csv", "labels/inquiry_scenarios.csv"]:
        assert (tmp_path / f).read_bytes() == (out / f).read_bytes(), f


def test_checked_in_copy_is_current(synth):
    """data/synthetic/ must match a fresh run, so its labels never go stale (e.g. after the demo date changes).
    Fix: python -m solstice.data.synthetic"""
    out, *_ = synth
    committed = REPO_ROOT / "data" / "synthetic"
    for f in [*FILES.values(), "labels/expected_issues.csv", "labels/inquiry_scenarios.csv"]:
        assert (committed / f).read_bytes() == (out / f).read_bytes(), f"{f} is stale: regenerate data/synthetic"


def test_people_are_fictional(synth):
    _, _, rows, _ = synth
    for r in rows["reservations"]:
        assert r["email"].endswith("@example.com") and "-555-01" in r["phone"]
    for q in rows["inquiries"]:
        assert q["contact_email"].endswith("@example.com")
        assert q["contact_phone"] == "" or "-555-01" in q["contact_phone"]


def test_app_can_load_synthetic_data(monkeypatch):
    monkeypatch.setenv("SOLSTICE_DATA_DIR", "data/synthetic")
    assert get_settings().path("properties_csv") == REPO_ROOT / "data" / "synthetic" / "properties.csv"
    assert get_settings().path("policy_doc") == REPO_ROOT / "data" / "policies" / "front_desk_policy.md"
    store_mod.get_store.cache_clear()
    try:
        s = store_mod.get_store()
        assert len(s.properties) == 100 and "SYN-001" in s.properties
    finally:
        store_mod.get_store.cache_clear()
