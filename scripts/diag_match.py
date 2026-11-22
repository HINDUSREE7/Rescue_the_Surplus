import json, urllib.request
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000"

def post(path):
    req = urllib.request.Request(BASE + path, data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status

def get_json(path, org=None):
    headers = {"X-Org": org} if org else {}
    req = urllib.request.Request(BASE + path, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())

print("reset status:", post("/api/demo/reset"))
print("scenario status:", post("/api/demo/scenario"))

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1366, "height": 768})
    page.goto(BASE + "/", wait_until="load")
    page.select_option("#role", "2")
    try:
        page.wait_for_selector("#list .card", timeout=15000)
        print("#list .card rendered: yes")
    except Exception as e:
        print("#list .card rendered: TIMEOUT", type(e).__name__)
    page.wait_for_timeout(1500)
    print("role select value:", page.evaluate("() => document.getElementById('role').value"))

    print("\n== live list (#list) innerText, first 600 chars ==")
    print(repr(page.evaluate("() => document.getElementById('list').innerText.slice(0, 600)")))
    print("#list offsetParent!==null:", page.evaluate("() => document.getElementById('list').offsetParent !== null"))
    print("#list is_visible (playwright):", page.locator("#list").is_visible())

    print("\n== elements under #list whose innerText matches /offer/i ==")
    rows = page.evaluate("""() => Array.from(document.querySelectorAll('#list *'))
        .filter(e => /offer/i.test(e.innerText || '') &&
                     !Array.from(e.children).some(c => /offer/i.test(c.innerText || '')))
        .map(e => ({tag: e.tagName, id: e.id, cls: (typeof e.className === 'string' ? e.className : ''),
                    attached: e.offsetParent !== null, text: (e.innerText || '').slice(0, 120)}))""")
    print("count:", len(rows))
    for m in rows[:25]:
        print(m)

    print("\n== ancestors of .offer elements (details/hidden check) ==")
    anc = page.evaluate("""() => Array.from(document.querySelectorAll('#list .offer')).slice(0, 5).map(e => {
        let chain = []; let x = e;
        while (x && x.tagName !== 'BODY') { chain.push(x.tagName + (x.id ? '#' + x.id : '') + (x.hidden ? '[hidden]' : '') + (x.tagName === 'DETAILS' ? (x.open ? '[open]' : '[closed]') : '')); x = x.parentElement; }
        return {offerVisible: e.offsetParent !== null, chain: chain.join(' < ')};
    })""")
    print("offer elements under #list:", len(anc))
    for a in anc:
        print(a)
    browser.close()

print("\n== GET /api/view with X-Org: 2 ==")
data = get_json("/api/view", org="2")
listings = data if isinstance(data, list) else data.get("listings", data)
print("listings count:", len(listings))
for l in listings:
    offers = l.get("offers") or []
    print(f"id={l.get('id')} label={l.get('label')!r} status={l.get('status')!r} offers={len(offers)}")
