"""Synthetic test data: about 10x the sample exports, same schema, seeded and labeled.

    cd backend
    .\\.venv\\Scripts\\python.exe -m solstice.data.synthetic                 # 10x, seed 7 -> data/synthetic/
    .\\.venv\\Scripts\\python.exe -m solstice.data.synthetic --scale 14      # ~140 properties, Solstice's real size
    $env:SOLSTICE_DATA_DIR = "data/synthetic"                              # run the app or evals on it

Writes the three source CSVs with exactly the columns of data/raw/, plus labels:
  labels/expected_issues.csv     every data-quality issue the checks should find, and why (seeded fault or scenario)
  labels/inquiry_scenarios.csv   each group inquiry's designed scenario, expected decision and expected flags
  labels/manifest.json           seed, scale, fault rate, demo date and row counts

Why a script and not an LLM: the numbers have to be consistent (room types sum to the total, rates fit
the rate plan, nights match the dates) and the labels have to be exact, so the tests can demand that the
quality checks find every seeded fault and nothing else. Same seed, same demo date -> same files.

All people are fictional: names from small lists, emails at example.com, phones in the 555-01xx range,
random card last-4s. IDs are marked synthetic (SYN-###, G9####, R9####, INQ-9###) so they can't be
mistaken for the sample data.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
from datetime import date, timedelta
from pathlib import Path

from solstice.config import REPO_ROOT, get_settings
from solstice.data.store import RATE_FOR_TYPE, ROOM_TYPES

RAW = REPO_ROOT / "data" / "raw"
FILES = {"properties": "properties.csv", "reservations": "guest_profiles.csv", "inquiries": "group_inquiries.csv"}

CITIES = [("Atlanta", "GA"), ("Boston", "MA"), ("Dallas", "TX"), ("Houston", "TX"), ("San Antonio", "TX"),
          ("Seattle", "WA"), ("Portland", "OR"), ("Salt Lake City", "UT"), ("Las Vegas", "NV"), ("San Diego", "CA"),
          ("Sacramento", "CA"), ("Phoenix", "AZ"), ("Tucson", "AZ"), ("Albuquerque", "NM"), ("Kansas City", "MO"),
          ("St. Louis", "MO"), ("Minneapolis", "MN"), ("Milwaukee", "WI"), ("Detroit", "MI"), ("Indianapolis", "IN"),
          ("Cincinnati", "OH"), ("Pittsburgh", "PA"), ("Philadelphia", "PA"), ("Baltimore", "MD"), ("Richmond", "VA"),
          ("Raleigh", "NC"), ("Charleston", "SC"), ("Savannah", "GA"), ("Orlando", "FL"), ("Miami", "FL"),
          ("New Orleans", "LA"), ("Memphis", "TN"), ("Louisville", "KY"), ("Omaha", "NE"), ("Boise", "ID")]
SUFFIXES = ["Downtown", "Airport", "Convention Center", "Riverfront", "Midtown", "Old Town", "Harbor", "Uptown",
            "Medical District", "University", "Waterfront", "Lakeside"]
FIRST = ["Avery", "Jordan", "Priya", "Mateo", "Hannah", "Kwame", "Sofia", "Liam", "Mei", "Noah", "Amara", "Diego",
         "Elena", "Omar", "Grace", "Ravi", "Chloe", "Tomas", "Nadia", "Ethan", "Yuki", "Isaac", "Leila", "Marcus",
         "Fatima", "Owen", "Zara", "Caleb", "Ingrid", "Samuel"]
LAST = ["Alvarez", "Brennan", "Castillo", "Dubois", "Eriksen", "Fofana", "Garber", "Haddad", "Iverson", "Jaramillo",
        "Kowalski", "Lindqvist", "Mbeki", "Nakamura", "Okonkwo", "Petrov", "Quintana", "Rasmussen", "Sato", "Thornton",
        "Ueda", "Vasquez", "Whitfield", "Xu", "Yilmaz", "Zielinski", "Abernathy", "Bello", "Chowdhury", "Delacroix"]
COMPANIES = ["Northwind Analytics", "Bluepeak Robotics", "Cedar & Finch Law", "Harborlight Health", "Summit Youth Soccer",
             "Ironwood Engineering", "Maple Street Church", "Brightline Logistics", "Oakridge Alumni Assoc.",
             "Silverleaf Insurance", "Crescent Dance Academy", "Tidewater Marine Supply", "Granite State Robotics Club",
             "Juniper Software", "Redfern Family Reunion", "Lumen Pharmaceuticals"]
EVENTS = ["Conference", "Corporate Retreat", "Reunion", "Wedding Block", "Youth Group Travel", "Youth Sports Travel"]
REQUESTS = ["High floor if available", "Early check-in requested", "Quiet room away from elevator",
            "Traveling with an infant, requests a crib", "Celebrating a birthday", "Prefers feather-free bedding"]
# Ordinary, rule-free notes. The agent reads property notes, so they must not say "synthetic" or "test":
# an early eval run showed the agent (rightly) refusing to quote a property described that way.
PROPERTY_NOTES = ["Steady business-travel demand on weekdays.", "Popular for weddings on summer weekends.",
                  "Ballroom divides into three breakout rooms.", "Recently renovated meeting level.",
                  "Free airport shuttle every 30 minutes.", ""]
GROUP_REQUESTS = ["Rooms on the same floor if possible", "Need a registration table in the lobby",
                  "Coffee service for the morning session", "Late arrival on day one", ""]

TIERS = [("None", 0.40), ("Silver", 0.25), ("Gold", 0.20), ("Platinum", 0.15)]
POINTS = {"None": (0, 0), "Silver": (1000, 12000), "Gold": (12000, 40000), "Platinum": (40000, 120000)}
PLANS = {"Best Available Rate": 1.0, "Advance Purchase": 0.85, "Corporate Negotiated": 0.9, "Loyalty Redemption": 0.0}
GROUP_ROOM_TYPES = ["Standard King", "Standard Double", "Deluxe King"]

SCENARIOS = [  # (name, share, expected decision, flags the engine must raise)
    ("within_rules", 0.30, "READY_TO_SEND", []),
    ("over_block_limit", 0.15, "NEEDS_HUMAN_APPROVAL", ["block_size"]),
    ("over_discount", 0.15, "NEEDS_HUMAN_APPROVAL", ["discount"]),
    ("blackout", 0.10, "CANNOT_ACCOMMODATE", ["blackout_dates"]),
    ("meeting_too_big", 0.10, "CANNOT_ACCOMMODATE", ["meeting_capacity"]),
    ("not_enough_rooms", 0.10, "CANNOT_ACCOMMODATE", ["inventory"]),
    ("needs_clarification", 0.10, "NEEDS_CLARIFICATION", []),
]
PROPERTY_FAULTS = ["negative_rate", "non_numeric_rate", "room_total_mismatch", "threshold_missing", "blackout_unparseable"]
RESERVATION_FAULTS = ["invalid_stay_dates", "nights_mismatch", "unknown_property", "bad_nightly_rate", "unknown_status",
                      "unknown_room_type", "duplicate_reservation_id", "guest_id_conflict"]
INQUIRY_FAULTS = ["unknown_property", "nights_mismatch", "arrival_before_received", "no_phone"]


def _header(name: str) -> list[str]:
    with open(RAW / FILES[name], newline="", encoding="utf-8-sig") as f:
        return next(csv.reader(f))


def _person(rng: random.Random) -> tuple[str, str]:
    return rng.choice(FIRST), rng.choice(LAST)


def _phone(rng: random.Random) -> str:
    return f"{rng.randint(201, 989)}-555-01{rng.randint(0, 99):02d}"


def _blackouts(p: dict) -> list[tuple[date, date]]:
    out = []
    for chunk in p["blackout_dates"].split(";"):
        if " to " in chunk:
            a, b = chunk.split(" to ")
            out.append((date.fromisoformat(a.strip()), date.fromisoformat(b.strip())))
    return out


def _overlaps(p: dict, a: date, d: date) -> bool:
    return any(a <= e and s < d for s, e in _blackouts(p))   # same test as the rules engine (nights a..d-1)


class Generator:
    def __init__(self, scale: int, seed: int, fault_rate: float, today: date):
        self.rng, self.scale, self.fault_rate, self.today = random.Random(seed), scale, fault_rate, today
        self.issues: list[dict] = []       # labels/expected_issues.csv
        self.scenarios: list[dict] = []    # labels/inquiry_scenarios.csv

    def expect(self, dataset, record_id, field, kind, source, original="", seeded=""):
        self.issues.append({"dataset": dataset, "record_id": record_id, "field": field, "kind": kind,
                            "source": source, "original_value": original, "seeded_value": seeded})

    # ------------------------------------------------------------ properties
    def properties(self) -> list[dict]:
        rng, out = self.rng, []
        for i in range(1, 10 * self.scale + 1):
            city, state = rng.choice(CITIES)
            total = rng.randrange(120, 330, 10)
            sk, sd, dk, su = (round(total * f) for f in (0.40, 0.28, 0.18, 0.09))
            acc = total - sk - sd - dk - su
            std = rng.randrange(139, 265, 5)
            dlx = std + rng.randrange(30, 75, 5)
            sqft = rng.randrange(2000, 12500, 500)
            n_bo = rng.choices([0, 1, 2], [0.3, 0.5, 0.2])[0]
            starts = sorted(self.today + timedelta(days=rng.randint(20, 420)) for _ in range(n_bo))
            bo = "; ".join(f"{s} to {s + timedelta(days=rng.randint(3, 9))}" for s in starts) or "none scheduled"
            gm = " ".join(_person(rng))
            out.append({
                "property_code": f"SYN-{i:03d}", "property_name": f"Solstice {city} {rng.choice(SUFFIXES)}",
                "city": city, "state": state, "market_type": rng.choice(["Urban", "Urban", "Resort"]),
                "total_rooms": total, "standard_king_rooms": sk, "standard_double_rooms": sd,
                "deluxe_king_rooms": dk, "suite_rooms": su, "accessible_rooms": acc,
                "base_rate_standard": std, "base_rate_deluxe": dlx, "base_rate_suite": dlx + rng.randrange(80, 170, 10),
                "meeting_space_sqft": sqft, "max_meeting_capacity": sqft // 300 * 10,
                "group_block_auto_approve_max_rooms": rng.choice([15, 20, 25, 30, 35, 40]),
                "max_discount_auto_approve_pct": rng.choice([8, 10, 12, 15]),
                "blackout_dates": bo, "general_manager": gm,
                "notes": PROPERTY_NOTES[i % len(PROPERTY_NOTES)],   # by index, not rng: keeps every other value stable
            })
        return out

    def fault_properties(self, props: list[dict]) -> set[str]:
        faulted = set()
        for p, kind in self._pick(props, PROPERTY_FAULTS):
            code = p["property_code"]
            if kind in ("negative_rate", "non_numeric_rate"):
                col = self.rng.choice(["base_rate_standard", "base_rate_deluxe", "base_rate_suite"])
                new = f"-{p[col]}" if kind == "negative_rate" else "TBD"
            elif kind == "room_total_mismatch":
                col, new = "total_rooms", p["total_rooms"] + self.rng.randint(5, 40)
            elif kind == "threshold_missing":
                col = self.rng.choice(["group_block_auto_approve_max_rooms", "max_discount_auto_approve_pct", "max_meeting_capacity"])
                new = self.rng.choice(["", "n/a"])
            else:
                col, new = "blackout_dates", self.rng.choice(["Labor Day week", "TBD (city marathon)", "late Oct"])
            self.expect("properties", code, col, kind, "fault", p[col], new)
            p[col] = new
            faulted.add(code)
        return faulted

    # ------------------------------------------------------------ reservations
    def reservations(self, props: list[dict]) -> list[dict]:
        rng, out, guests = self.rng, [], []
        for i in range(1, 25 * self.scale + 1):
            if guests and rng.random() < 0.15:
                g = rng.choice(guests)                      # repeat guest: identical identity fields
            else:
                first, last = _person(rng)
                tier = rng.choices([t for t, _ in TIERS], [w for _, w in TIERS])[0]
                lo, hi = POINTS[tier]
                g = {"guest_id": f"G9{len(guests) + 1:04d}", "first_name": first, "last_name": last,
                     "email": f"{first}.{last}.{len(guests) + 1}@example.com".lower(), "phone": _phone(rng),
                     "loyalty_tier": tier, "loyalty_points": rng.randrange(lo, hi + 1, 100) if hi else 0,
                     "member_since": str(rng.randint(2012, 2025)) if tier != "None" else ""}
                guests.append(g)
            p = rng.choice(props)
            room = rng.choices(list(ROOM_TYPES), [0.38, 0.27, 0.2, 0.08, 0.07])[0]
            plans = list(PLANS) if g["loyalty_tier"] in ("Gold", "Platinum") else list(PLANS)[:3]
            plan = rng.choice(plans)
            base = int(str(p[RATE_FOR_TYPE[room]]).lstrip("-")) if str(p[RATE_FOR_TYPE[room]]).lstrip("-").isdigit() else 199
            ci = self.today + timedelta(days=rng.randint(-40, 120))
            nights = rng.randint(1, 6)
            co = ci + timedelta(days=nights)
            if co <= self.today:
                status = rng.choices(["Checked-out", "No-show", "Cancelled"], [0.9, 0.05, 0.05])[0]
            elif ci <= self.today:
                status = "Checked-in"
            else:
                status = rng.choices(["Confirmed", "Cancelled"], [0.92, 0.08])[0]
            out.append({**g, "reservation_id": f"R9{i:04d}", "property_code": p["property_code"],
                        "check_in_date": ci.isoformat(), "check_out_date": co.isoformat(), "room_type": room,
                        "rate_plan": plan, "nightly_rate": round(base * PLANS[plan]), "total_nights": nights,
                        "reservation_status": status, "payment_method_last4": f"{rng.randint(0, 9999):04d}",
                        "marketing_opt_in": rng.choice("YN"),
                        "special_requests": rng.choice(REQUESTS) if rng.random() < 0.35 else "",
                        "internal_notes": ""})
        return out

    def fault_reservations(self, res: list[dict]) -> None:
        extra = []
        next_id = len(res) + 1
        for r, kind in self._pick(res, RESERVATION_FAULTS):
            rid = r["reservation_id"]
            if kind == "invalid_stay_dates":
                col, new = "check_out_date", r["check_in_date"]
                self.expect("reservations", rid, col, kind, "fault", r[col], new)
            elif kind == "nights_mismatch":
                col, new = "total_nights", r["total_nights"] + self.rng.randint(1, 3)
                self.expect("reservations", rid, col, kind, "fault", r[col], new)
            elif kind == "unknown_property":
                col, new = "property_code", "SYN-999"
                self.expect("reservations", rid, col, kind, "fault", r[col], new)
            elif kind == "bad_nightly_rate":
                col = "nightly_rate"
                if r["rate_plan"] == "Loyalty Redemption":
                    r["rate_plan"] = "Best Available Rate"
                new = f"-{r[col] or 99}"
                self.expect("reservations", rid, col, kind, "fault", r[col], new)
            elif kind == "unknown_status":
                col, new = "reservation_status", self.rng.choice(["Pending??", "Tentative", "On hold"])
                self.expect("reservations", rid, col, kind, "fault", r[col], new)
            elif kind == "unknown_room_type":
                col, new = "room_type", self.rng.choice(["Penthouse", "Junior Suite", "King"])
                self.expect("reservations", rid, col, kind, "fault", r[col], new)
            elif kind == "duplicate_reservation_id":
                extra.append(dict(r))                     # same id twice: an export that ran twice
                self.expect("reservations", rid, "reservation_id", kind, "fault", rid, rid)
                continue
            else:  # guest_id_conflict: a second booking under the same guest_id with a different email
                twin = dict(r, reservation_id=f"R9{next_id:04d}", email=f"other.{r['email']}")
                next_id += 1
                extra.append(twin)
                self.expect("reservations", r["guest_id"], "guest_id", kind, "fault", r["email"], twin["email"])
                continue
            r[col] = new
        res.extend(extra)

    # ------------------------------------------------------------ inquiries
    def inquiries(self, props: list[dict], res: list[dict], faulted_props: set[str]) -> list[dict]:
        rng, out = self.rng, []
        clean = [p for p in props if p["property_code"] not in faulted_props]
        booked = {}
        for r in res:                                     # every row counts: a safe upper bound on rooms taken
            booked[(r["property_code"], r["room_type"])] = booked.get((r["property_code"], r["room_type"]), 0) + 1
        names = [s for s, *_ in SCENARIOS]
        shares = [w for _, w, *_ in SCENARIOS]
        for i in range(1, 10 * self.scale + 1):
            scen = rng.choices(names, shares)[0]
            for _ in range(200):
                row = self._inquiry(scen, rng.choice(clean), booked, i)
                if row:
                    break
            else:
                raise RuntimeError(f"couldn't build a {scen} inquiry; widen the property ranges")
            out.append(row)
        return out

    def _inquiry(self, scen: str, p: dict, booked: dict, i: int) -> dict | None:
        rng = self.rng
        room = rng.choice(GROUP_ROOM_TYPES)
        type_count = int(p[ROOM_TYPES[room]])
        free = type_count - booked.get((p["property_code"], room), 0)   # rooms certainly free on every night
        limit, ceiling = int(p["group_block_auto_approve_max_rooms"]), int(p["max_discount_auto_approve_pct"])
        cap = int(p["max_meeting_capacity"])
        received = self.today - timedelta(days=rng.randint(0, 30))
        nights = rng.randint(1, 4)
        arrival = self.today + timedelta(days=rng.randint(21, 330))
        rooms, discount = rng.randint(5, max(5, min(limit, free))), rng.randint(0, ceiling)
        need_meeting = rng.random() < 0.5
        meeting = rng.randrange(10, max(11, cap), 5) if need_meeting else 0
        note = ""

        if scen == "blackout":
            bos = [b for b in _blackouts(p) if b[0] > self.today + timedelta(days=2)]
            if not bos:
                return None
            s, e = rng.choice(bos)
            arrival = s + timedelta(days=rng.randint(0, (e - s).days))
            note = f"Stay overlaps the {s} to {e} blackout; expect CANNOT_ACCOMMODATE."
        elif _overlaps(p, arrival, arrival + timedelta(days=nights)):
            return None                                    # keep blackouts out of every other scenario
        if min(limit, free) < 5:
            return None
        if scen == "over_block_limit":
            if free <= limit:
                return None
            rooms = rng.randint(limit + 1, free)
            note = f"{rooms} rooms is over the {limit}-room auto-approve limit; expect a block-size flag."
        elif scen == "over_discount":
            discount = ceiling + rng.randint(1, 8)
            note = f"{discount}% is over the {ceiling}% ceiling; expect a discount flag."
        elif scen == "meeting_too_big":
            need_meeting, meeting = True, cap + rng.randrange(10, 160, 10)
            note = f"Meeting for {meeting} is over the {cap} capacity; expect CANNOT_ACCOMMODATE."
        elif scen == "not_enough_rooms":
            rooms = type_count + rng.randint(1, 25)
            note = f"{rooms} {room} rooms is more than the {type_count} the property has; expect CANNOT_ACCOMMODATE."
        elif scen == "within_rules":
            note = "Within every rule; expect READY_TO_SEND."
        departure = arrival + timedelta(days=nights)
        first, last = _person(rng)
        company = rng.choice(COMPANIES)
        row = {"inquiry_id": f"INQ-9{i:03d}", "date_received": received.isoformat(), "company_name": company,
               "contact_name": f"{first} {last}", "contact_email": f"{first[0]}{last}@example.com".lower(),
               "contact_phone": _phone(rng), "event_type": rng.choice(EVENTS), "preferred_property_code": p["property_code"],
               "alternate_property_ok": rng.choice("YN"), "arrival_date": arrival.isoformat(),
               "departure_date": departure.isoformat(), "nights": nights, "rooms_requested": rooms,
               "room_type_preference": room, "requested_discount_pct": discount,
               "stated_budget_per_night": rng.randrange(120, 320, 5),
               "meeting_space_needed": "Y" if need_meeting else "N", "meeting_capacity_needed": meeting,
               "special_requests": rng.choice(GROUP_REQUESTS), "notes": ""}
        if scen == "needs_clarification":
            gap = rng.choice(["rooms", "dates", "room_type"])
            if gap == "rooms":
                row["rooms_requested"] = f"around {rooms}"
                self.expect("inquiries", row["inquiry_id"], "rooms_requested", "rooms_not_exact", "scenario", rooms, row["rooms_requested"])
            elif gap == "dates":
                row["arrival_date"] = row["departure_date"] = row["nights"] = ""
                self.expect("inquiries", row["inquiry_id"], "arrival_date", "dates_missing", "scenario")
            else:
                row["room_type_preference"] = ""
            note = f"Missing {gap.replace('_', ' ')}; expect clarifying questions and no price."
        row["notes"] = f"Synthetic scenario {scen}. {note}"
        decision, flags = next((d, f) for s, _, d, f in SCENARIOS if s == scen)
        self.scenarios.append({"inquiry_id": row["inquiry_id"], "property_code": p["property_code"], "scenario": scen,
                               "expected_decision": decision, "expected_flags": ";".join(flags)})
        return row

    def fault_inquiries(self, inq: list[dict]) -> None:
        clean = [q for q in inq if not q["notes"].startswith("Synthetic scenario needs_clarification")]
        by_id = {s["inquiry_id"]: s for s in self.scenarios}
        for q, kind in self._pick(clean, INQUIRY_FAULTS):
            qid = q["inquiry_id"]
            if kind == "unknown_property":
                col, new = "preferred_property_code", "SYN-999"
            elif kind == "nights_mismatch":
                col, new = "nights", int(q["nights"]) + 2
            elif kind == "arrival_before_received":
                a = date.fromisoformat(q["date_received"]) - timedelta(days=10)
                q["departure_date"] = (a + timedelta(days=int(q["nights"]))).isoformat()
                col, new = "arrival_date", a.isoformat()
            else:
                col, new = "contact_phone", ""
            self.expect("inquiries", qid, col, kind, "fault", q[col], new)
            q[col] = new
            if kind != "no_phone":                        # a missing phone doesn't change the decision
                by_id[qid].update(scenario=f"faulted:{kind}", expected_decision="", expected_flags="")
                q["notes"] = f"Synthetic fault {kind}: the scenario no longer applies."

    # ------------------------------------------------------------ helpers
    def _pick(self, rows: list[dict], kinds: list[str]):
        """At least one record per fault kind, about fault_rate of the rows overall, no record twice."""
        k = min(len(rows), max(len(kinds), round(self.fault_rate * len(rows))))
        chosen = self.rng.sample(rows, k)
        order = kinds[:] + [self.rng.choice(kinds) for _ in range(k - len(kinds))]
        return list(zip(chosen, order))


def generate(out_dir: Path, scale: int = 10, seed: int = 7, fault_rate: float = 0.06, today: date | None = None) -> dict:
    g = Generator(scale, seed, fault_rate, today or get_settings().today)
    props = g.properties()
    faulted = g.fault_properties(props)
    res = g.reservations(props)
    g.fault_reservations(res)
    inq = g.inquiries(props, res, faulted)
    g.fault_inquiries(inq)

    out_dir = Path(out_dir)
    (out_dir / "labels").mkdir(parents=True, exist_ok=True)
    for name, rows in (("properties", props), ("reservations", res), ("inquiries", inq)):
        cols = _header(name)
        assert set(cols) == set(rows[0]), f"{name}: columns drifted from data/raw"
        with open(out_dir / FILES[name], "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
    for name, rows in (("expected_issues", g.issues), ("inquiry_scenarios", g.scenarios)):
        with open(out_dir / "labels" / f"{name}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    manifest = {"seed": seed, "scale": scale, "fault_rate": fault_rate, "demo_today": g.today.isoformat(),
                "rows": {"properties": len(props), "reservations": len(res), "inquiries": len(inq)},
                "expected_issues": len(g.issues),
                "faults": sum(i["source"] == "fault" for i in g.issues),
                "scenarios": {s: sum(x["scenario"] == s for x in g.scenarios) for s, *_ in SCENARIOS}}
    (out_dir / "labels" / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main():
    ap = argparse.ArgumentParser(prog="python -m solstice.data.synthetic")
    ap.add_argument("--scale", type=int, default=10, help="multiple of the sample data (10 -> 100 properties)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--fault-rate", type=float, default=0.06, help="share of rows per file given a seeded fault")
    ap.add_argument("--out", default="data/synthetic")
    a = ap.parse_args()
    m = generate(REPO_ROOT / a.out, a.scale, a.seed, a.fault_rate)
    print(json.dumps(m, indent=2))
    print(f"wrote {REPO_ROOT / a.out}")


if __name__ == "__main__":
    main()
