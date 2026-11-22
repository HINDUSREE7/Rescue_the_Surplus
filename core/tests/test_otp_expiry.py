from datetime import datetime, timedelta

from django.test import TestCase
from django.utils import timezone

from core import engine
from core.engine import Err, OTP_TTL_MINUTES
from core.models import Listing, Org

# Fixed clock, same as test_core.py: 20:00 local on 10 Jan 2026 (Asia/Kolkata).
AT = timezone.make_aware(datetime(2026, 1, 10, 20, 0))


class OtpExpiryTests(TestCase):
    def setUp(self):
        self.donor = Org.objects.create(role="donor", name="Hall (test)", lat=16.3067,
                                        lng=80.4365)
        self.r1 = Org.objects.create(role="receiver", name="NGO 1 (test)", lat=16.3100,
                                     lng=80.4500, capacity=100, need=0.8)

    def claimed_listing(self):
        listing, _ = engine.post(self.donor, "cooked_rice", 20, ["none"], 90, at=AT)
        engine.claim(self.r1, listing.id, at=AT + timedelta(minutes=10))
        listing.refresh_from_db()
        return listing

    def test_otp_within_ttl_succeeds(self):
        listing = self.claimed_listing()
        # claimed at AT+10 min, so the code is 1 min old at AT+11 min (within OTP_TTL_MINUTES)
        result = engine.collect(self.r1, listing.id, listing.pickup_otp, at=AT + timedelta(minutes=11))
        self.assertEqual(result.status, "collected")
        listing.refresh_from_db()
        self.assertEqual(listing.status, "collected")

    def test_otp_older_than_ttl_rejected_without_attempt_increment(self):
        listing = self.claimed_listing()
        handoff_at = AT + timedelta(minutes=20)
        # Code issued OTP_TTL_MINUTES + 1 minutes before the handoff attempt.
        listing.otp_issued_at = handoff_at - timedelta(minutes=OTP_TTL_MINUTES + 1)
        listing.save(update_fields=["otp_issued_at"])
        wrong = "0000" if listing.pickup_otp != "0000" else "1111"
        with self.assertRaises(Err) as ctx:
            engine.collect(self.r1, listing.id, wrong, at=handoff_at)
        self.assertEqual(ctx.exception.status, 409)
        self.assertIn("OTP expired", ctx.exception.msg)
        listing.refresh_from_db()
        self.assertEqual(listing.pickup_attempts, 0)
        self.assertEqual(listing.status, "claimed")
