"""Build checks for YoMama eBay scheduled-listing CSVs.

Every rule here comes from a past eBay rejection or a listing miss (see the
project memory file ebay-build-checks.md). A batch is only delivered when this
script exits 0.

  python tools/listing/check_listing_csv.py FILE.csv [FILE2.csv ...]
        [--check-urls] [--allow-blank-illustrator SKU,SKU] [--now 2026-11-20T18:00:00Z]

Exit code 1 on any FAIL. WARN lines and the blank-field dump are for the
check list in the reply, not failures.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import re
import sys
import unicodedata

INFO_LINE = "Info,Version=1.0.0,Template=fx_category_template_EBAY_US"
BANNER = "https://raw.githubusercontent.com/yomamacollects/yomama-photos/main/brand/yomama-why-buy-from-us.png"
PHOTO_BASE = "https://raw.githubusercontent.com/yomamacollects/yomama-photos/main/"
DESC_LINES = (
    "Thank you for choosing YoMama Collectibles! Every order comes with a FREE GIFT!",
    "Please see photos for condition and feel free to ask any questions!",
)
CONDITION_COL = "CD:Card Condition - (ID: 40001)"
CARD_CONDITIONS = {
    "183454": {"400010", "400015", "400016", "400017"},
    "183050": {"400010", "400011", "400012", "400013"},
    "261328": {"400010", "400011"},
}
SINGLE_CARD_CATS = {"183454", "183050", "261328"}
CARD_CATS_AGE = {"183454", "183050"}
NO_GAME_CATS = {"183050", "261328"}
BANNED_TITLE_WORDS = {
    "lot", "lots", "bundle", "bulk", "pair", "pairs", "cards", "stickers", "packs",
    "assorted", "multiple", "pick", "choose", "mixed",
}
MULTI_VALUE_OK = {"C:Character", "C:Features"}
SHIPPING = {"$1 Shipping", "US Only Shipping Buyer Pays"}
SKU_RE = re.compile(r"^YMC-\d{8}-\d{2,}$")
COLLECTED_ARTISTS = [  # Christian's list (project memory ebay-illustrator-check); add names here
    "Yuka Morii", "Mitsuhiro Arita", "Ken Sugimori", "Kagemaru Himeno", "Atsuko Nishida",
    "Tomokazu Komiya", "Naoki Saito", "Shinji Kanda", "Kouki Saitou", "Akira Komayama",
    "sowsow", "Taiga Kayama",
]
NO_ARTIST_MAKERS = ("topps", "merlin", "artbox", "panini", "amada", "bandai carddass")


def norm(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


class Report:
    def __init__(self):
        self.fails, self.warns, self.info = [], [], []

    def fail(self, where, msg):
        self.fails.append(f"FAIL {where}: {msg}")

    def warn(self, where, msg):
        self.warns.append(f"WARN {where}: {msg}")


def check_file(path: str, rep: Report, now: dt.datetime, allow_blank_ill: set[str], urls: list[str]) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    name = path.rsplit("/", 1)[-1]
    if not rows or ",".join(c for c in rows[0] if c) != INFO_LINE:
        rep.fail(name, f"row 1 must be `{INFO_LINE}` (padded); got `{','.join(rows[0])[:80] if rows else ''}`")
        return []
    header = rows[1]
    width = len(header)
    if len(rows[0]) != width:
        rep.fail(name, f"Info row has {len(rows[0])} cells, header has {width}")
    if not header[0].startswith("*Action(SiteID=US"):
        rep.fail(name, "header must start with the classic *Action(SiteID=US|...) column")
    out = []
    for i, r in enumerate(rows[2:], start=3):
        if not any(r):
            continue
        if len(r) != width:
            rep.fail(f"{name} line {i}", f"{len(r)} cells, header has {width}")
        out.append({h: (r[k] if k < len(r) else "") for k, h in enumerate(header)})
    seen = set()
    for row in out:
        check_row(row, rep, now, allow_blank_ill, urls, seen)
    return out


def check_row(row: dict, rep: Report, now, allow_blank_ill, urls, seen):
    sku = row.get("CustomLabel", "")
    w = sku or "(no SKU)"
    cat = row.get("*Category", "")
    title = row.get("*Title", "")
    g = lambda k: row.get(k, "").strip()  # noqa: E731

    if not SKU_RE.match(sku):
        rep.fail(w, "CustomLabel must look like YMC-YYYYMMDD-NN")
    if sku in seen:
        rep.fail(w, "duplicate SKU")
    seen.add(sku)

    # fixed values
    if g(next((k for k in row if k.startswith("*Action")), "")) != "Add":
        rep.fail(w, "Action must be Add")
    for col, val in (("*Quantity", "1"), ("*Format", "FixedPrice"), ("*Duration", "GTC"), ("PostalCode", "33166"),
                     ("ReturnProfileName", "No Returns"), ("PaymentProfileName", "Payment")):
        if col in row and g(col) != val:
            rep.fail(w, f"{col} must be `{val}`, is `{g(col)}`")
    if g("ShippingProfileName") not in SHIPPING:
        rep.fail(w, f"ShippingProfileName `{g('ShippingProfileName')}` is not one of {sorted(SHIPPING)}")
    if g("BestOfferEnabled") != "1":
        rep.fail(w, "BestOfferEnabled must be 1")
    if g("BestOfferAutoAcceptPrice") or g("MinimumBestOfferPrice"):
        rep.fail(w, "Best Offer auto-accept/decline must be blank")
    if "Location" in row and g("Location"):
        rep.warn(w, "Location column should be left out")

    # title
    try:
        title.encode("ascii")
    except UnicodeEncodeError:
        rep.warn(w, "title has non-ASCII characters (eBay counts them as more than one)")
    if len(title) > 80:
        rep.fail(w, f"title is {len(title)} chars (max 80)")
    elif len(title) < 60:
        rep.warn(w, f"title is only {len(title)} chars: unused keyword space")
    if cat in SINGLE_CARD_CATS:
        toks = [t.lower() for t in re.split(r"[^A-Za-z0-9]+", title) if t]
        bad = [t for t in toks if t in BANNED_TITLE_WORDS or re.fullmatch(r"x\d+|\d+x", t)]
        if bad:
            rep.fail(w, f"single-card title has lot words {bad} (error 240)")
        if "complete set" in title.lower():
            rep.fail(w, "single-card title says 'complete set'")

    # price
    try:
        price = float(g("*StartPrice"))
        if price < 2.75:
            rep.fail(w, f"StartPrice {price} is under the $2.75 floor")
    except ValueError:
        rep.fail(w, f"StartPrice `{g('*StartPrice')}` is not a number")

    # schedule
    try:
        st = dt.datetime.strptime(g("ScheduleTime"), "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc)
        if st <= now:
            rep.fail(w, f"ScheduleTime {g('ScheduleTime')} GMT is already past")
        elif st > now + dt.timedelta(days=21):
            rep.fail(w, "ScheduleTime is more than 21 days out")
        if st.minute or st.second:
            rep.warn(w, "ScheduleTime is not on a full hour")
    except ValueError:
        rep.fail(w, f"ScheduleTime `{g('ScheduleTime')}` must be YYYY-MM-DD HH:MM:SS (GMT)")

    # photos
    pics = [p for p in g("PicURL").split("|") if p]
    if not pics or pics[-1] != BANNER:
        rep.fail(w, "PicURL must end with the brand banner")
    for p in pics[:-1]:
        if not p.startswith(PHOTO_BASE):
            rep.fail(w, f"photo not hosted in yomama-photos main: {p}")
        elif sku and f"/{sku}_" not in p:
            rep.warn(w, f"photo name doesn't match the SKU: {p.rsplit('/', 1)[-1]}")
    if len(pics) < 2:
        rep.fail(w, "no item photo before the banner")
    urls.extend(pics)

    # description
    d = g("*Description")
    if not d.startswith("<p><b>") or any(x not in d for x in DESC_LINES):
        rep.fail(w, "description must open with a bold summary and contain both thank-you lines")

    # condition
    if cat in CARD_CONDITIONS:
        if g("*ConditionID") != "4000":
            rep.warn(w, f"ConditionID {g('*ConditionID')} (ungraded cards use 4000)")
        if g("*ConditionID") == "4000" and g(CONDITION_COL) not in CARD_CONDITIONS[cat]:
            rep.fail(w, f"Card Condition `{g(CONDITION_COL)}` not valid for category {cat} "
                        f"(allowed {sorted(CARD_CONDITIONS[cat])})")

    # specifics
    for k, v in row.items():
        if k.startswith("C:") and k not in MULTI_VALUE_OK and "|" in v:
            rep.fail(w, f"{k} has more than one value `{v}` (single-value field)")
    if "/" in g("C:Card Name"):
        rep.fail(w, f"Card Name `{g('C:Card Name')}` joins names with '/'")
    for col in ("C:Manufacturer", "C:Year Manufactured", "C:Country/Region of Manufacture"):
        if col not in row or not g(col):
            rep.fail(w, f"{col} is blank")
    if cat not in NO_GAME_CATS and "C:Game" in row and not g("C:Game"):
        rep.fail(w, "Game is blank")
    if cat in CARD_CATS_AGE and "C:Age Level" in row and g("C:Age Level") != "6+":
        rep.fail(w, f"Age Level must be 6+, is `{g('C:Age Level')}`")

    # illustrator
    maker = norm(g("C:Manufacturer"))
    game = norm(g("C:Game"))
    basic_energy = "energy" in norm(g("C:Card Type")) and "basic" in norm(title + " " + g("C:Card Name"))
    needs_artist = (cat == "183454" and "C:Illustrator" in row and not any(m in maker for m in NO_ARTIST_MAKERS)
                    and "yu-gi-oh" not in game and "mezastar" not in norm(title) and "ga-ole" not in norm(title)
                    and not basic_energy)
    ill = g("C:Illustrator")
    if needs_artist and not ill and sku not in allow_blank_ill:
        rep.fail(w, "Illustrator is blank; read the Illus. line (or pass --allow-blank-illustrator with a reason)")
    for a in COLLECTED_ARTISTS:
        if norm(a) in norm(ill):
            surname = norm(a.split()[-1])
            if surname not in norm(title):
                rep.fail(w, f"collected artist {a} is in Illustrator but not in the title")

    # English WOTC Base Set
    if g("C:Set") == "Base Set" and "/102" in g("C:Card Number") + title and "english" in norm(g("C:Language") or "english"):
        ed = [x for x in ("shadowless", "1st edition", "unlimited") if x in norm(title)]
        if not ed:
            rep.fail(w, "Base Set title needs Shadowless, 1st Edition or Unlimited")
        elif not any(x in norm(g("C:Features")) for x in ed):
            rep.fail(w, f"Base Set: Features doesn't match the title ({ed[0]})")

    # completeness dump
    blanks = [k[2:] for k, v in row.items() if k.startswith("C:") and not v.strip()]
    if blanks:
        rep.info.append(f"{w} blank: {', '.join(blanks)}")


def check_urls(urls: list[str], rep: Report):
    import concurrent.futures as cf

    import requests

    def one(u):
        try:
            r = requests.get(u, timeout=30, stream=True)
            ok = r.status_code == 200 and r.headers.get("content-type", "").startswith("image/")
            r.close()
            return u, ok, f"{r.status_code} {r.headers.get('content-type', '')}"
        except Exception as e:  # noqa: BLE001
            return u, False, str(e)[:80]

    with cf.ThreadPoolExecutor(16) as ex:
        for u, ok, why in ex.map(one, sorted(set(urls))):
            if not ok:
                rep.fail(u.rsplit("/", 1)[-1], f"photo link doesn't load as an image ({why})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--check-urls", action="store_true")
    ap.add_argument("--allow-blank-illustrator", default="", help="comma-separated SKUs with no printed artist")
    ap.add_argument("--now", help="pretend time (UTC ISO) for re-checking old files")
    a = ap.parse_args()
    now = dt.datetime.fromisoformat(a.now.replace("Z", "+00:00")) if a.now else dt.datetime.now(dt.timezone.utc)
    allow = {s.strip() for s in a.allow_blank_illustrator.split(",") if s.strip()}
    rep, urls, n = Report(), [], 0
    for f in a.files:
        n += len(check_file(f, rep, now, allow, urls))
    if a.check_urls:
        check_urls(urls, rep)
    for line in rep.info:
        print("BLANK", line)
    for line in rep.warns + rep.fails:
        print(line)
    print(f"\n{n} rows, {len(rep.fails)} failures, {len(rep.warns)} warnings")
    sys.exit(1 if rep.fails else 0)


if __name__ == "__main__":
    main()
