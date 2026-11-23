"""Data quality: checks find seeded faults, tools warn the agent, alerts fire once."""
import copy

from solstice import runtime_store
from solstice.config import get_settings
from solstice.data.quality import report, run_checks
from solstice.data.store import _read_csv, get_store
from tests.test_agent_loop import FakeClient, _text, _tool
from solstice.agent.runner import AgentSession


def _rows():
    s = get_settings()
    return [_read_csv(s.path(k)) for k in ("properties_csv", "guests_csv", "inquiries_csv")]


def _fields(issues):
    return {(i.record_id, i.field) for i in issues}


def test_real_data_issues_found():
    f = _fields(get_store().data_issues)
    assert ("SOL-PVD", "base_rate_suite") in f
    assert ("INQ-2004", "rooms_requested") in f


def test_seeded_faults_are_all_caught():
    """Inject one fault of each kind into a copy of the data; every one must be detected."""
    props, res, inq = (copy.deepcopy(x) for x in _rows())
    props[0]["blackout_dates"] = "July 4th week"
    props[1]["max_discount_auto_approve_pct"] = "n/a"
    props[2]["total_rooms"] = "999"
    res[0]["check_out_date"] = res[0]["check_in_date"]
    res[1]["total_nights"] = "9"
    res[2]["property_code"] = "SOL-XXX"
    res[3]["nightly_rate"] = "-10"
    res[4]["reservation_status"] = "Pending??"
    res.append(dict(res[5]))                                   # duplicate reservation id
    inq[0]["nights"] = "7"
    inq[1]["arrival_date"], inq[1]["departure_date"] = "2026-06-01", "2026-06-03"   # before received

    f = _fields(run_checks(props, res, inq))
    for expected in [(props[0]["property_code"], "blackout_dates"), (props[1]["property_code"], "max_discount_auto_approve_pct"),
                     (props[2]["property_code"], "total_rooms"), (res[0]["reservation_id"], "check_out_date"),
                     (res[1]["reservation_id"], "total_nights"), (res[2]["reservation_id"], "property_code"),
                     (res[3]["reservation_id"], "nightly_rate"), (res[4]["reservation_id"], "reservation_status"),
                     (res[5]["reservation_id"], "reservation_id"), (inq[0]["inquiry_id"], "nights"),
                     (inq[1]["inquiry_id"], "arrival_date")]:
        assert expected in f, expected


def test_report_filters_by_property():
    r = report(get_store().data_issues, "SOL-PVD")
    assert r["total"] >= 1 and all(i["property_code"] == "SOL-PVD" for i in r["issues"])


def test_tool_warns_agent_and_raises_one_alert():
    fake = FakeClient([
        [_tool("evaluate_group_block", {"property_code": "SOL-PVD", "arrival": "2026-09-01", "departure": "2026-09-03",
                                        "rooms": 5, "room_type": "Suite"})],
        [_tool("get_property_info", {"property_code": "SOL-PVD"}, "t2")],
        [_text("The suite rate on file is invalid; Sales will confirm.")],
    ])
    r = AgentSession("group_sales", "staff", client=fake).send("price 5 suites at Providence")
    assert r.steps[0].output["data_quality_warnings"][0]["field"] == "base_rate_suite"
    alerts = runtime_store.read_all("alerts")
    assert len(alerts) == 1                                   # deduped within the session
    assert alerts[0]["issue_id"] == "DQ-properties-SOL-PVD-base_rate_suite"


def test_clean_record_has_no_warnings():
    fake = FakeClient([[_tool("get_property_info", {"property_code": "SOL-CHI"})], [_text("ok")]])
    r = AgentSession("concierge", "guest", client=fake).send("tell me about Chicago")
    assert "data_quality_warnings" not in r.steps[0].output
    assert runtime_store.read_all("alerts") == []


def test_report_tool_is_staff_only():
    assert "get_data_quality_report" not in AgentSession("concierge", "guest", client=FakeClient([])).tools
    assert "get_data_quality_report" in AgentSession("concierge", "staff", client=FakeClient([])).tools
