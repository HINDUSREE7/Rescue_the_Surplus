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
