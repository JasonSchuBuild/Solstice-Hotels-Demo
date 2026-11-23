# Tool definitions

Generated from the code by `docs/build_tools_doc.py`; don't edit by hand.

Each tool is a JSON schema the model sees plus a Python handler that does the work. Which tools a session gets is decided in code by agent and mode (`tools_for` in `backend/solstice/tools/registry.py`), so nothing typed in a chat can unlock a tool.

## Access by mode

| Tool | Guest | Front desk | Group sales |
|---|---|---|---|
| `check_cancellation_terms` | ✅ | ✅ |  |
| `check_comp_authority` |  | ✅ |  |
| `check_service_recovery_eligibility` | ✅ | ✅ |  |
| `create_group_proposal` |  |  | ✅ |
| `escalate_to_staff` | ✅ | ✅ | ✅ |
| `evaluate_group_block` |  |  | ✅ |
| `find_alternative_properties` |  |  | ✅ |
| `get_data_quality_report` |  | ✅ | ✅ |
| `get_group_inquiry` |  |  | ✅ |
| `get_property_info` | ✅ | ✅ | ✅ |
| `list_group_inquiries` |  |  | ✅ |
| `list_reservations` |  | ✅ |  |
| `lookup_reservation` |  | ✅ |  |
| `request_late_checkout` | ✅ | ✅ |  |
| `search_guests` |  | ✅ |  |
| `submit_service_request` | ✅ | ✅ |  |
| `verify_guest` | ✅ | ✅ |  |

## Definitions

### `check_cancellation_terms`

Exact cancellation terms for a reservation right now (free-cancel deadline, penalty, or non-refundable). Use instead of calculating dates yourself.

**Agents:** concierge · **Modes:** guest, staff · **Code:** `backend/solstice/tools/concierge_tools.py`

| Parameter | Type | Required | Description |
|---|---|---|---|
| `reservation_id` | string | yes | Reservation / confirmation number, e.g. R55001 |

### `check_comp_authority`

Whether a set of comps for one stay is inside front-desk authority ($50 total, Policy 7) or needs AGM/GM.

**Agents:** concierge · **Modes:** staff · **Code:** `backend/solstice/tools/concierge_tools.py`

| Parameter | Type | Required | Description |
|---|---|---|---|
| `amounts_usd` | array of number | yes |  |
| `includes_full_night` | boolean |  |  |

### `check_service_recovery_eligibility`

Whether a complaint about a stay is inside the 72-hour service-recovery window (Policy 5).

**Agents:** concierge · **Modes:** guest, staff · **Code:** `backend/solstice/tools/concierge_tools.py`

| Parameter | Type | Required | Description |
|---|---|---|---|
| `reservation_id` | string | yes | Reservation / confirmation number, e.g. R55001 |
| `reported_during_stay` | boolean |  | True if the guest says they told staff during the stay. |

### `create_group_proposal`

Save a structured proposal for Sales. The rules engine re-runs here, so the status is set by the rules, not by you: inside the rules it is a DRAFT ready to send; anything flagged goes to PENDING_HUMAN_APPROVAL.

**Agents:** group_sales · **Modes:** guest, staff · **Code:** `backend/solstice/tools/group_tools.py`

| Parameter | Type | Required | Description |
|---|---|---|---|
| `property_code` | string | yes |  |
| `arrival` | string | yes | YYYY-MM-DD |
| `departure` | string | yes | YYYY-MM-DD |
| `rooms` | integer | yes |  |
| `room_type` | string (one of: Standard King, Standard Double, Deluxe King, Suite, Accessible King) | yes |  |
| `requested_discount_pct` | integer |  |  |
| `budget_per_night` | integer |  |  |
| `meeting_capacity_needed` | integer |  |  |
| `event_type` | string |  |  |
| `inquiry_id` | string | yes |  |
| `cover_note` | string | yes | Short client-facing summary of the offer |

### `escalate_to_staff`

Hand the conversation to a human with full context. Use for anything outside the agent's authority: refunds/comps over limits, disputes, anything medical, legal or safety-related, media, policy gaps or conflicts, or an upset guest. The transcript and reservation are attached automatically.

**Agents:** concierge, group_sales · **Modes:** guest, staff · **Code:** `backend/solstice/tools/escalation.py`

| Parameter | Type | Required | Description |
|---|---|---|---|
| `category` | string (one of: refund_or_comp_over_authority, billing_dispute, outside_policy_window, safety_or_security, medical, legal, media_inquiry, vip_arrival, policy_gap_or_conflict, guest_upset, other) | yes |  |
| `summary` | string | yes | 2-4 sentences: what happened and what the guest wants |
| `what_agent_already_did` | string |  |  |
| `recommended_next_step` | string | yes |  |
| `policy_refs` | array of string |  | e.g. ['Policy 5', 'Policy 7'] |
| `reservation_id` | string |  | If known |

### `evaluate_group_block`

Run Solstice group rules for a block at one property: blackout dates, room limit, discount ceiling (incl. seasonal caps), inventory, meeting space, property-specific rules, and pricing. Returns a decision (READY_TO_SEND / NEEDS_HUMAN_APPROVAL / CANNOT_ACCOMMODATE / NEEDS_CLARIFICATION) with every check and its source.

**Agents:** group_sales · **Modes:** guest, staff · **Code:** `backend/solstice/tools/group_tools.py`

| Parameter | Type | Required | Description |
|---|---|---|---|
| `property_code` | string | yes |  |
| `arrival` | string | yes | YYYY-MM-DD |
| `departure` | string | yes | YYYY-MM-DD |
| `rooms` | integer | yes |  |
| `room_type` | string (one of: Standard King, Standard Double, Deluxe King, Suite, Accessible King) | yes |  |
| `requested_discount_pct` | integer |  |  |
| `budget_per_night` | integer |  |  |
| `meeting_capacity_needed` | integer |  |  |
| `event_type` | string |  |  |

### `find_alternative_properties`

Evaluate the same block at every other Solstice property and return the best options: workable ones first, nearest first (same city, same state, other state), then by price. Use when the preferred property can't accommodate, or the client said alternates are OK.

**Agents:** group_sales · **Modes:** guest, staff · **Code:** `backend/solstice/tools/group_tools.py`

| Parameter | Type | Required | Description |
|---|---|---|---|
| `property_code` | string | yes |  |
| `arrival` | string | yes | YYYY-MM-DD |
| `departure` | string | yes | YYYY-MM-DD |
| `rooms` | integer | yes |  |
| `room_type` | string (one of: Standard King, Standard Double, Deluxe King, Suite, Accessible King) | yes |  |
| `requested_discount_pct` | integer |  |  |
| `budget_per_night` | integer |  |  |
| `meeting_capacity_needed` | integer |  |  |
| `event_type` | string |  |  |

### `get_data_quality_report`

Staff/Sales only: list known problems in the source data (invalid rates, inconsistent dates, incomplete inquiries), with severity and how the agent handles each, plus alerts raised when the agent hit bad data.

**Agents:** concierge, group_sales · **Modes:** staff · **Code:** `backend/solstice/tools/data_quality_tools.py`

| Parameter | Type | Required | Description |
|---|---|---|---|
| `property_code` | string |  | Optional, e.g. SOL-PVD. Omit for all properties. |

### `get_group_inquiry`

Full details of one group inquiry (contact details masked).

**Agents:** group_sales · **Modes:** guest, staff · **Code:** `backend/solstice/tools/group_tools.py`

| Parameter | Type | Required | Description |
|---|---|---|---|
| `inquiry_id` | string | yes |  |

### `get_property_info`

Facts about a Solstice property: location, room types and counts, published base rates, meeting space, GM and notes. Does NOT include parking, amenities or live availability.

**Agents:** concierge, group_sales · **Modes:** guest, staff · **Code:** `backend/solstice/tools/concierge_tools.py`

| Parameter | Type | Required | Description |
|---|---|---|---|
| `property_code` | string | yes | e.g. SOL-CHI |

### `list_group_inquiries`

List inbound group inquiries (id, company, property, dates, rooms).

**Agents:** group_sales · **Modes:** guest, staff · **Code:** `backend/solstice/tools/group_tools.py`

No parameters.

### `list_reservations`

Staff only: a short, scoped list of reservations to see who is in focus. Scope it with a property and a focus: 'arriving' (upcoming arrivals, soonest first), 'in_house' (staying tonight) or 'recent' (most recent past arrivals, newest first). Capped at 25 rows; compact fields only (use lookup_reservation for details). Show the result as a markdown table with reservation_id as the first column.

**Agents:** concierge · **Modes:** staff · **Code:** `backend/solstice/tools/concierge_tools.py`

| Parameter | Type | Required | Description |
|---|---|---|---|
| `property_code` | string |  | Optional, e.g. SOL-CHI. Omit for all properties. |
| `focus` | string (one of: arriving, in_house, recent) |  | Default 'arriving'. |
| `status` | string |  | Optional exact status filter, e.g. Confirmed, Checked-in, Cancelled. |
| `limit` | integer |  | Rows to return, default 10, max 25. |

### `lookup_reservation`

Staff only: look up any reservation by confirmation number (masked).

**Agents:** concierge · **Modes:** staff · **Code:** `backend/solstice/tools/concierge_tools.py`

| Parameter | Type | Required | Description |
|---|---|---|---|
| `reservation_id` | string | yes | Reservation / confirmation number, e.g. R55001 |

### `request_late_checkout`

Request late checkout. Platinum is confirmed automatically (2 PM, guaranteed); everyone else is submitted to the front desk as a pending request.

**Agents:** concierge · **Modes:** guest, staff · **Code:** `backend/solstice/tools/concierge_tools.py`

| Parameter | Type | Required | Description |
|---|---|---|---|
| `reservation_id` | string | yes | Reservation / confirmation number, e.g. R55001 |

### `search_guests`

Staff only: find reservations by guest last name. Several guests can share a name — confirm with the confirmation number.

**Agents:** concierge · **Modes:** staff · **Code:** `backend/solstice/tools/concierge_tools.py`

| Parameter | Type | Required | Description |
|---|---|---|---|
| `last_name` | string | yes |  |

### `submit_service_request`

Send a request (early check-in, rollaway, bedding, room location, amenity booking, etc.) to the property's front desk queue. Requests are PENDING until the property confirms — never tell the guest it is guaranteed.

**Agents:** concierge · **Modes:** guest, staff · **Code:** `backend/solstice/tools/concierge_tools.py`

| Parameter | Type | Required | Description |
|---|---|---|---|
| `reservation_id` | string | yes | Reservation / confirmation number, e.g. R55001 |
| `request_type` | string (one of: early_check_in, rollaway_bed, bedding_or_pillows, room_location, connecting_rooms, celebration_or_turndown, accessibility, amenity_booking, other) | yes |  |
| `details` | string | yes | What the guest asked for, in plain words |

### `verify_guest`

Verify a guest's identity with their confirmation number and last name. Required before sharing any reservation details in guest mode. Returns all of the guest's reservations on success.

**Agents:** concierge · **Modes:** guest, staff · **Code:** `backend/solstice/tools/concierge_tools.py`

| Parameter | Type | Required | Description |
|---|---|---|---|
| `reservation_id` | string | yes | Reservation / confirmation number, e.g. R55001 |
| `last_name` | string | yes |  |
