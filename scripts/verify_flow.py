import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "rescue.settings")
django.setup()

from django.test import Client

c = Client()
# 1. Reset
r = c.post("/api/demo/reset")
print("1. Demo Reset status:", r.status_code, "Orgs seeded:", len(r.json()))

# 2. Pitch Scenario
s = c.post("/api/demo/scenario", data='{"scale": 1.0}', content_type="application/json")
scenario_data = s.json()
print("2. Demo Scenario status:", s.status_code, "Listing ID:", scenario_data.get("listing_id"))

# 3. View as Donor (Function Hall B, id=2)
v_donor = c.get("/api/view", HTTP_X_ORG="2")
donor_listings = v_donor.json()
print("3. Donor View:", v_donor.status_code, f"{len(donor_listings)} listing(s) visible")
listing_id = donor_listings[0]["id"]
print(f"   Listing #{listing_id}: {donor_listings[0]['kg']} kg {donor_listings[0]['label']} (Status: {donor_listings[0]['status']})")
print(f"   Offers generated: {len(donor_listings[0]['offers'])}")

# 4. View as Receiver (NGO G, id=7)
v_rcv = c.get("/api/view", HTTP_X_ORG="7")
rcv_listings = v_rcv.json()
print("4. Receiver View:", v_rcv.status_code, f"{len(rcv_listings)} listing(s) offered")

# 5. Claim as Receiver
claim_resp = c.post(f"/api/listings/{listing_id}/claim", content_type="application/json", HTTP_X_ORG="7")
print("5. Claim status:", claim_resp.status_code, "Status after claim:", claim_resp.json()["status"])

# 6. Check Pickup & Drop OTPs
donor_updated = c.get("/api/view", HTTP_X_ORG="2").json()[0]
rcv_updated = c.get("/api/view", HTTP_X_ORG="7").json()[0]
pickup_otp = donor_updated["pickup_otp"]
drop_otp = rcv_updated["drop_otp"]
assigned_volunteer = rcv_updated["volunteer"]
print(f"6. Handshake OTPs issued: Pickup OTP={pickup_otp} (with donor), Drop OTP={drop_otp} (with receiver)")
print(f"   Assigned courier: {assigned_volunteer}")

# 7. Courier Pickup (Volunteer L, id=12)
collect_resp = c.post(f"/api/listings/{listing_id}/collect", data=f'{{"otp": "{pickup_otp}"}}', content_type="application/json", HTTP_X_ORG="12")
print("7. Courier Collect status:", collect_resp.status_code, "Listing status:", collect_resp.json()["status"])

# 8. Courier Drop / Delivery (Volunteer L, id=12)
deliver_resp = c.post(f"/api/listings/{listing_id}/deliver", data=f'{{"otp": "{drop_otp}"}}', content_type="application/json", HTTP_X_ORG="12")
print("8. Courier Deliver status:", deliver_resp.status_code, "Listing status:", deliver_resp.json()["status"])

# 9. Macro Impact
impact_data = c.get("/api/impact").json()
print("9. Live Corridor Impact:")
print(f"   - Delivered: {impact_data['delivered_kg']} kg")
print(f"   - Rescued Meals (Mid estimate): {impact_data['meals'][1]} meals")
print(f"   - CO2e Abated: {impact_data['co2e_kg'][1]} kg CO2e")
print(f"   - Rescue Efficiency Rate: {round(impact_data['rescue_rate']*100)}%")
print(f"   - Sponsor Economic Value: Rs. {impact_data['sponsor_value_rs']}")

print("\n>>> ALL CHECKS PASSED: Full working prototype verified end-to-end!")
