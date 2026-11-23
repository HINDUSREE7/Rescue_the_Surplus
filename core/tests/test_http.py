import json

from django.test import TestCase

from core import views as core_views
from core.models import Org


class HttpTests(TestCase):
    def setUp(self):
        # Reset the in-memory per-org rate limiter so hits from earlier tests don't leak in.
        core_views._RATE_HITS.clear()
        self.donor = Org.objects.create(role="donor", name="Hall (http test)", lat=16.3067,
                                        lng=80.4365)

    def test_public_orgs_listing_returns_json(self):
        # views.orgs is auth=False: no X-Org header needed.
        resp = self.client.get("/api/orgs")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp["Content-Type"].startswith("application/json"))
        json.loads(resp.content)

    def test_ingest_malformed_json_body_returns_400(self):
        # views._body raises Err(400, "body must be JSON") for undecodable bodies.
        resp = self.client.post("/api/ingest", data=b"{not json",
                                content_type="application/json",
                                HTTP_X_ORG=str(self.donor.pk))
        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.json())

    def test_ingest_non_object_json_body_returns_400(self):
        # views._body raises Err(400, "body must be a JSON object") for non-dict JSON.
        resp = self.client.post("/api/ingest", data=b"[]",
                                content_type="application/json",
                                HTTP_X_ORG=str(self.donor.pk))
        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.json())

    def test_org_protected_endpoint_without_x_org_returns_401(self):
        # views._org raises Err(401, "missing X-Org header") when the header is absent.
        resp = self.client.get("/api/view")
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["error"], "missing X-Org header")

    def test_method_not_allowed_returns_405(self):
        resp = self.client.get("/api/listings")
        self.assertEqual(resp.status_code, 405)
        self.assertEqual(resp.json()["error"], "method not allowed")

    def test_options_cors_preflight(self):
        resp = self.client.options("/api/listings")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Access-Control-Allow-Origin"], "*")

    def test_meta_endpoint_structure(self):
        resp = self.client.get("/api/meta")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("categories", data)
        self.assertIn("allergens", data)
        self.assertIn("tiers", data)
        self.assertIn("rules", data)
        self.assertIn("disclaimer", data)

    def test_impact_endpoint_structure(self):
        resp = self.client.get("/api/impact")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("delivered_kg", data)
        self.assertIn("expired_kg", data)
        self.assertIn("meals", data)
        self.assertIn("co2e_kg", data)
        self.assertIn("sponsor_value_rs", data)
        self.assertIn("assumptions", data)

    def test_demo_reset_and_speed_endpoints(self):
        reset_resp = self.client.post("/api/demo/reset")
        self.assertEqual(reset_resp.status_code, 200)
        orgs = reset_resp.json()
        self.assertTrue(len(orgs) >= 10)

        speed_resp = self.client.post("/api/demo/speed", data=json.dumps({"scale": 60}),
                                      content_type="application/json")
        self.assertEqual(speed_resp.status_code, 200)
        self.assertEqual(speed_resp.json()["scale"], 60.0)

        bad_speed = self.client.post("/api/demo/speed", data=json.dumps({"scale": "invalid"}),
                                     content_type="application/json")
        self.assertEqual(bad_speed.status_code, 400)

    def test_demo_scenario_endpoint(self):
        scenario_resp = self.client.post("/api/demo/scenario", data=json.dumps({"scale": 1.0}),
                                         content_type="application/json")
        self.assertEqual(scenario_resp.status_code, 200)
        self.assertIn("listing_id", scenario_resp.json())

    def test_listing_post_non_donor_returns_403(self):
        receiver = Org.objects.create(role="receiver", name="Recv (test)", lat=16.3, lng=80.4, capacity=50)
        body = {"category": "cooked_rice", "kg": 20, "pickupInMin": 60, "allergens": ["none"]}
        resp = self.client.post("/api/listings", data=json.dumps(body), content_type="application/json",
                                HTTP_X_ORG=str(receiver.id))
        self.assertEqual(resp.status_code, 403)
        self.assertIn("only donors", resp.json()["error"])

    def test_http_full_dispatch_flow(self):
        # 1. Reset demo data to get standard test orgs
        self.client.post("/api/demo/reset")
        donor_id = "1"  # Wedding Caterer A
        receiver_id = "5"  # Community Kitchen E

        # 2. Donor posts a listing via HTTP
        post_body = {"category": "cooked_rice", "kg": 25, "pickupInMin": 90, "allergens": ["none"]}
        post_resp = self.client.post("/api/listings", data=json.dumps(post_body), content_type="application/json",
                                     HTTP_X_ORG=donor_id)
        self.assertEqual(post_resp.status_code, 200)
        listing_data = post_resp.json()
        listing_id = listing_data["id"]
        self.assertEqual(listing_data["status"], "posted")
        self.assertIsNotNone(listing_data["pickup_otp"])

        # 3. Receiver views and claims via HTTP
        claim_resp = self.client.post(f"/api/listings/{listing_id}/claim", content_type="application/json",
                                      HTTP_X_ORG=receiver_id)
        self.assertEqual(claim_resp.status_code, 200)
        claimed_data = claim_resp.json()
        self.assertEqual(claimed_data["status"], "claimed")
        drop_otp = claimed_data["drop_otp"]
        self.assertIsNotNone(drop_otp)

        # Donor sees the pickup OTP to provide to the courier
        donor_view = self.client.get("/api/view", HTTP_X_ORG=donor_id).json()
        donor_listing = next(l for l in donor_view if l["id"] == listing_id)
        pickup_otp = donor_listing["pickup_otp"]
        self.assertIsNotNone(pickup_otp)

        # Assigned collector (volunteer if assigned, else receiver)
        from core.models import Listing as CoreListing
        db_listing = CoreListing.objects.get(pk=listing_id)
        collector_id = str(db_listing.volunteer_id or db_listing.receiver_id)

        # 4. Collect step via HTTP
        collect_resp = self.client.post(f"/api/listings/{listing_id}/collect", data=json.dumps({"otp": pickup_otp}),
                                        content_type="application/json", HTTP_X_ORG=collector_id)
        self.assertEqual(collect_resp.status_code, 200)
        self.assertEqual(collect_resp.json()["status"], "collected")

        # 5. Deliver step via HTTP
        deliver_resp = self.client.post(f"/api/listings/{listing_id}/deliver", data=json.dumps({"otp": drop_otp}),
                                        content_type="application/json", HTTP_X_ORG=collector_id)
        self.assertEqual(deliver_resp.status_code, 200)
        self.assertEqual(deliver_resp.json()["status"], "delivered")

        # 6. Verify impact reflects the delivery
        impact_resp = self.client.get("/api/impact")
        self.assertEqual(impact_resp.status_code, 200)
        self.assertGreaterEqual(impact_resp.json()["delivered_kg"], 25.0)
