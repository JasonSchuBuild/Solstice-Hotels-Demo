import json

from solstice.data.masking import mask_email, mask_phone, scrub_free_text
from solstice.data.store import get_store, reservation_view


def test_mask_email_and_phone():
    assert mask_email("laura.bennett@example.com") == "l***@example.com"
    assert mask_phone("312-555-0148") == "***-***-0148"


def test_scrub_card_numbers_in_free_text():
    assert "4111" not in scrub_free_text("guest read me card 4111 1111 1111 1111 over the phone")


def test_no_view_ever_contains_payment_last4_or_raw_contact():
    """Every reservation view, guest or staff, is free of payment digits and raw email/phone."""
    s = get_store()
    for res in s.reservations:
        for audience in ("guest", "staff"):
            blob = json.dumps(reservation_view(res, audience))
            assert res.email not in blob
            assert res.phone not in blob
            assert f'"{res.payment_last4}"' not in blob
            assert "payment" not in blob.lower()


def test_guest_verification_requires_both_fields():
    s = get_store()
    assert s.verify_guest("R55001", "Bennett")
    assert s.verify_guest("R55001", "Okoye") is None
    assert s.verify_guest("R99999", "Bennett") is None
