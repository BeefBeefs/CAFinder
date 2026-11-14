#!/usr/bin/env python3
"""Rebuild settlements.json: hand-curated seed + newly scraped no-proof settlements.

Standard library only. Run from anywhere: python3 scripts/scrape.py

Source: the OpenClassActions no-proof list, then each settlement's own page.
Fails (exit 1, file untouched) if the list page can't be fetched or yields no links,
so a broken scraper shows up as a failed GitHub Action instead of an empty site.
"""
import datetime as dt
import html as htmllib
import json
import re
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://openclassactions.com"
LIST_URL = BASE + "/no-proof-class-action-settlements.php"
UA = "Mozilla/5.0 (compatible; no-receipt-finder/1.0; personal use)"
MONTHS = ("January|February|March|April|May|June|July|August|September|"
          "October|November|December")
DATE_RE = re.compile(r"(%s)\.?\s+(\d{1,2}),?\s+(\d{4})" % MONTHS)
STOP = {"settlement", "class", "action", "claims", "claim", "data", "privacy", "breach"}


def get(url):
    req = Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
    with urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def to_text(h):
    h = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", h)
    h = re.sub(r"(?s)<[^>]+>", "\n", h)
    h = htmllib.unescape(h)
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in h.split("\n")]
    return "\n".join(ln for ln in lines if ln)


def parse_date(s):
    m = DATE_RE.search(s or "")
    if not m:
        return None
    try:
        return dt.datetime.strptime("%s %s %s" % m.groups(), "%B %d %Y").date()
    except ValueError:
        return None


def after_label(text, label):
    """First non-empty line after a label (or the rest of the label's own line)."""
    m = re.search(r"(?im)^\s*" + label + r"\??\s*:?\s*(.*)$", text)
    if not m:
        return None
    if m.group(1).strip():
        return m.group(1).strip()
    rest = text[m.end():].lstrip("\n")
    return rest.split("\n", 1)[0].strip() or None


def find_links(list_html):
    seen, out = set(), []
    for href in re.findall(r'href="((?:https://openclassactions\.com)?/settlements/[^"#?]+\.php)"', list_html):
        url = href if href.startswith("http") else BASE + href
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


def parse_detail(url):
    h = get(url)
    text = to_text(h)
    title = re.search(r"(?is)<h1[^>]*>(.*?)</h1>", h)
    name = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", "", title.group(1)))).strip() if title else None
    deadline = parse_date(after_label(text, r"Claim Deadline") or "")
    proof = after_label(text, r"Proof Required") or ""
    payout = after_label(text, r"(?:Estimated )?Payout") or ""
    who = after_label(text, r"Who Qualifies") or ""
    if not who:
        m = re.search(r'(?i)<meta[^>]+name="description"[^>]+content="([^"]*)"', h)
        who = htmllib.unescape(m.group(1)) if m else ""
    return {"name": name, "deadline": deadline, "proof": proof, "payout": payout, "who": who, "url": url}


def keep(d):
    """Only claims anyone in the class can file on attestation alone."""
    p = d["proof"].lower()
    if not p.startswith("no"):
        return False
    if re.search(r"\b(claim|notice) id\b|\bpin\b|automatic", p) and not p.startswith("no id"):
        return False
    return True


def clean_name(n):
    n = re.sub(r"(?i)\s*(class action )?settlement.*$", "", n or "")
    return re.sub(r"^\$[\d.,]+\s*[MBK]?\s*", "", n).strip()


def words(n):
    return {w for w in re.findall(r"[a-z0-9]{5,}", (n or "").lower())} - STOP


def same(a, b):
    if a.get("u") and a.get("u") == b.get("u"):
        return True
    return a["d"] == b["d"] and bool(words(a["n"]) & words(b["n"]))


def main():
    today = dt.date.today()
    seed = json.loads((ROOT / "data_seed.json").read_text())

    try:
        links = find_links(get(LIST_URL))
    except Exception as e:  # network or HTTP failure
        print("FAILED to fetch list page:", e, file=sys.stderr)
        return 1
    if not links:
        print("FAILED: no settlement links found; the site layout probably changed.", file=sys.stderr)
        return 1
    print("found %d candidate pages" % len(links))

    scraped, skipped = [], 0
    for url in links[:60]:
        try:
            d = parse_detail(url)
        except Exception as e:
            print("  skip", url, e)
            skipped += 1
            continue
        time.sleep(1.0)  # be polite
        if not d["name"] or not d["deadline"] or d["deadline"] < today or not keep(d):
            continue
        scraped.append({
            "n": clean_name(d["name"]),
            "d": d["deadline"].isoformat(),
            "p": d["payout"][:90] or "See site",
            "w": (d["who"][:220] or "See tracker page for who qualifies."),
            "u": d["url"],
            "c": not d["payout"],
        })
    print("kept %d scraped, %d skipped" % (len(scraped), skipped))

    items = list(seed)
    for s in scraped:
        if not any(same(s, x) for x in items):
            items.append(s)
    items = [i for i in items if i["d"] >= today.isoformat()]
    items.sort(key=lambda i: i["d"])

    out = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "scraped_count": len(scraped),
        "items": items,
    }
    (ROOT / "settlements.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print("wrote settlements.json with %d items" % len(items))
    return 0


if __name__ == "__main__":
    sys.exit(main())
