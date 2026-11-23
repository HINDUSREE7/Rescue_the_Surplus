"""Integration tests covering complete lifecycle scenarios for Rescue the Surplus.
"""
from datetime import datetime, timedelta

from django.test import TestCase
from django.utils import timezone

from core import engine, parser
from core.models import Listing, Org

AT = timezone.make_aware(datetime(2026, 1, 10, 20, 0))


class FullFlowIntegrationTests(TestCase):
    def setUp(self):
        engine.reset_demo()
        self.donor = Org.objects.get(pk=2)  # Function Hall B
        self.receiver = Org.objects.get(pk=7)  # NGO G (near Function Hall B)
        self.volunteer = Org.objects.get(pk=12)  # Volunteer L
        self.sponsor = Org.objects.get(pk=15)

    def test_complete_intake_to_delivery_lifecycle(self):
        # 1. Donor starts natural language intake
        text = "60 kilo biryani migilindi, 11:30 lopu teesukellandi"
        draft = parser.ingest(self.donor, text, channel="chat", at=AT)
        self.assertEqual(draft.parsed["category"], "cooked_rice")
        self.assertEqual(draft.parsed["kg"], 60.0)
        self.assertIn("allergens", draft.missing)

        # 2. Donor answers allergen question
        draft = parser.answer(self.donor, draft.id, "none", at=AT)
        self.assertEqual(draft.missing, [])

        # 3. Donor confirms draft -> becomes active Listing
        listing, clamp_msg = parser.confirm(self.donor, draft.id, at=AT)
        self.assertEqual(listing.status, "posted")
        self.assertEqual(listing.kg, 60.0)
        self.assertTrue(listing.offers.filter(status="pending").exists())

        # Raw intake text must be purged for privacy retention
        draft.refresh_from_db()
        self.assertEqual(draft.raw_text, "")
        self.assertEqual(draft.field_sources, {})

        # 4. Receiver claims the listing
        claimed_listing = engine.claim(self.receiver, listing.id, at=AT + timedelta(minutes=5))
        self.assertEqual(claimed_listing.status, "claimed")
        self.assertEqual(claimed_listing.receiver_id, self.receiver.id)
        self.assertIsNotNone(claimed_listing.volunteer)
        pickup_code = claimed_listing.pickup_otp
        drop_code = claimed_listing.drop_otp

        # 5. Volunteer picks up food from donor with pickup OTP (within OTP_TTL_MINUTES)
        collector = claimed_listing.volunteer or self.receiver
        collected_listing = engine.collect(collector, listing.id, pickup_code, at=AT + timedelta(minutes=9))
        self.assertEqual(collected_listing.status, "collected")
        self.assertIsNotNone(collected_listing.collected_at)

        # 6. Volunteer delivers food to receiver with drop OTP (within OTP_TTL_MINUTES)
        delivered_listing = engine.deliver(collector, listing.id, drop_code, at=AT + timedelta(minutes=13))
        self.assertEqual(delivered_listing.status, "delivered")
        self.assertIsNotNone(delivered_listing.delivered_at)

        # 7. Receiver's last_served is updated
        self.receiver.refresh_from_db()
        self.assertEqual(self.receiver.last_served, AT + timedelta(minutes=13))

        # 8. Impact reflects OTP-verified meals and CO2e abatement
        imp = engine.impact()
        self.assertEqual(imp["delivered_kg"], 60.0)
        self.assertEqual(imp["meals"][1], 150)  # 60 / 0.4
        self.assertEqual(imp["co2e_kg"][1], 150.0)  # 60 * 2.5
        self.assertEqual(imp["rescue_rate"], 1.0)

    def test_sponsor_view_privacy(self):
        # Post a listing
        listing, _ = engine.post(self.donor, "cooked_rice", 30, ["none"], 90, at=AT)
        
        # Donor view includes OTPs and details
        donor_view = engine.view(self.donor)
        self.assertEqual(len(donor_view), 1)
        self.assertIsNotNone(donor_view[0]["pickup_otp"])

        # Sponsor view hides operational listing details for privacy
        sponsor_view = engine.view(self.sponsor)
        self.assertEqual(len(sponsor_view), 0)

        # But sponsor can see macro impact metrics
        imp = engine.impact()
        self.assertIn("delivered_kg", imp)
        self.assertIn("sponsor_value_rs", imp)
