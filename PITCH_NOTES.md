# PITCH NOTES: Rescue the Surplus

- **Live Deployment:** [https://rescue-the-surplus.vercel.app/](https://rescue-the-surplus.vercel.app/)

## Architecture (one line)
Every listing is created by one writer, core/engine.py post(); all other paths (form and chat confirm) call it, so safety rules are enforced in one place.

## Demo script with timings (PRD section 17, 4 minutes)

| Step | Time | What the judge sees |
|------|------|---------------------|
| 1. Story | 15 s | Narrate: "11:40 pm, a wedding in Guntur, 60 kg of biryani, safe window 4 hours." |
| 2. Speak | 25 s | Donor speaks into the mic, or uses the "Pitch via chat" button (message #1 pre-filled). |
| 3. Understand | 25 s | Bot asks allergens only; tap "none"; confirmation card shows conversion and confidence strip; press Confirm. |
| 4. Match | 30 s | Listing appears with spoilage bar and safety card; offers show a four-segment score bar and ETA. |
| 5. Escalation | 40 s | Decline on NGO; tier widens and new receivers appear; clock runs at 120x. |
| 6. Pickup | 40 s | NGO claims; volunteer assigned; both OTPs shown; pickup and delivery confirmed. |
| 7. Trust | 25 s | Injection attempt and rejected input shown; safe window unchanged. |
| 8. Impact and business | 20 s | Impact strip with ranges; assumptions drawer opened. |

- Keep a text-input fallback ready if speech or Wi-Fi fails.
- The scripted browser check (scripts/demo_run.py) covers steps 1-4 and 7; steps 5-6 are manual.

## Unit economics (illustrative, from code constants)

| Factor | Low | Mid | High |
|--------|-----|-----|------|
| Meals per kg | 2.0 | 2.5 | 3.3 |
| CO2e per kg of food | 1.9 kg | 2.5 kg | 3.3 kg |

- Meals per kg are 1/0.5, 1/0.4 and 1/0.3 from MEALS_PER_KG in core/engine.py (3.3 is rounded from 3.33).
- CO2e per kg comes from CO2E_PER_KG in core/engine.py.
- Sponsor value per meal: Rs 4 (RS_PER_MEAL in core/engine.py).
- Example, 60 kg delivered: 120 / 150 / 200 meals; CO2e 114 / 150 / 198 kg; mid sponsor value Rs 600 (150 meals x Rs 4).
- All factors are ILLUSTRATIVE placeholders in the code. Cite a source before any external use.
- Do not present these as measured figures.

## Limitations (say these to judges; from PRD section 19, quoted in substance)
- Real WhatsApp API not built.
- IVR not built.
- Dialects beyond standard Telugu not supported.
- Photo-based quantity estimation not built.
- Delivery photo proof not built.
- Partial claims (splitting one listing) not built.
- Real phone-OTP auth deferred to hardening.
- PostGIS not used; distance is Haversine.
- Simulated clock is per process and for demo only.
- No accuracy figure from real donors. The parser eval is on a SYNTHETIC set (38 items, see EVAL.md) and has not been reviewed by a native Telugu speaker.
- Roadmap v1.1: WhatsApp Business channel, recurring-event templates, delivery photos, partial claims.
- Roadmap v2: IVR, more languages, demand forecasting, route batching, sponsor billing.

## Safety statements
- The platform does not certify food safety.
- Allergens are as declared by the donor, and are never assumed.
- Safe windows are illustrative demo defaults, not clinical guidance.
- Impact is counted only on OTP-confirmed deliveries.
