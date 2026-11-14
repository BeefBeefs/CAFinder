#!/usr/bin/env python3
"""Rebuild settlements.json: hand-curated seed + scraped no-proof settlements.

Standard library only. Run: python3 scripts/scrape.py

Each source is isolated: if one site changes layout or is down, the others still run.
The script fails (exit 1, file untouched) only if EVERY source returns nothing, so a
broken scraper shows up as a failed GitHub Action instead of an empty site.
Per-source counts are printed so you can see which parsers are working.
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
UA = "Mozilla/5.0 (compatible; no-receipt-finder/1.0; personal use)"
MONTHS = ("January|February|March|April|May|June|July|August|September|"
          "October|November|December")
LONG_DATE = re.compile(r"(%s)\.?\s+(\d{1,2}),?\s+(\d{4})" % MONTHS)
SHORT_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b")
STOP = {"settlement", "class", "action", "claims", "claim", "the", "and", "for", "inc", "llc",
        "company", "corp", "consumer", "consumers", "lawsuit", "false", "advertising"}
# Settlements where only people on the defendant's notice list can file. Not what this page is for.
NOTICE_ONLY = re.compile(
    r"breach|notified|received (?:a |the )?(?:notice|letter|email)|identified (?:in|by|from)|"
    r"credit union|restitution|claim id|notice id|\bpin\b|employees?\b|wage|overtime|tenants?\b",
    re.I)


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
    s = s or ""
    m = LONG_DATE.search(s)
    try:
        if m:
            return dt.datetime.strptime("%s %s %s" % m.groups(), "%B %d %Y").date()
        m = SHORT_DATE.search(s)
        if m:
            mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return dt.date(y + 2000 if y < 100 else y, mo, d)
    except ValueError:
        pass
    return None


def after_label(text, label):
    """Rest of a label's line, or the next non-empty line if the label stands alone."""
    m = re.search(r"(?im)^\s*" + label + r"\??\s*:?\s*(.*)$", text)
    if not m:
        return None
    if m.group(1).strip():
        return m.group(1).strip()
    rest = text[m.end():].lstrip("\n")
    return rest.split("\n", 1)[0].strip() or None


def h1(h):
    m = re.search(r"(?is)<h1[^>]*>(.*?)</h1>", h)
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", "", m.group(1)))).strip() if m else None


def meta_desc(h):
    m = re.search(r'(?i)<meta[^>]+name="description"[^>]+content="([^"]*)"', h)
    return htmllib.unescape(m.group(1)) if m else ""


def clean_name(n):
    n = re.sub(r"(?i)\s*(class action )?settlement.*$", "", n or "")
    return re.sub(r"^\$[\d.,]+\s*[MBK]?\s*", "", n).strip()


def hrefs(h, pattern):
    seen, out = set(), []
    for href in re.findall(r'href="(%s)"' % pattern, h):
        if href not in seen:
            seen.add(href)
            out.append(href)
    return out


def entry(name, deadline, payout, who, url):
    return {"n": clean_name(name), "d": deadline, "p": (payout or "")[:90] or "See site",
            "w": (who or "")[:220] or "See the tracker page for who qualifies.",
            "u": url, "c": not payout}


# ---------- source 1: OpenClassActions (per-settlement pages) ----------
def src_openclassactions():
    base = "https://openclassactions.com"
    links = [h if h.startswith("http") else base + h for h in
             hrefs(get(base + "/no-proof-class-action-settlements.php"),
                   r"(?:https://openclassactions\.com)?/settlements/[^\"#?]+\.php")]
    out = []
    for url in links[:60]:
        try:
            h = get(url)
        except Exception as e:
            print("   skip", url, e)
            continue
        time.sleep(1.0)
        t = to_text(h)
        proof = (after_label(t, r"Proof Required") or "").lower()
        if not proof.startswith("no") or re.search(r"\b(claim|notice) id\b|\bpin\b|automatic", proof) and not proof.startswith("no id"):
            continue
        d = parse_date(after_label(t, r"Claim Deadline"))
        if d:
            out.append(entry(h1(h), d, after_label(t, r"(?:Estimated )?Payout"),
                             after_label(t, r"Who Qualifies") or meta_desc(h), url))
    return out


# ---------- (disabled) ClassAction.org: its server HTML has no "Proof Required" text (likely filled in by JavaScript), so it is link-only ----------
# source 2: ClassAction.org (cards: title, payout, "Deadline 11/16/26", "Proof Required? No") ----------
def src_classaction_org():
    out = []
    for page in ("https://www.classaction.org/", "https://www.classaction.org/settlements"):
        try:
            lines = to_text(get(page)).split("\n")
        except Exception as e:
            print("   skip", page, e)
            continue
        title = payout = None
        deadline = None
        for i, ln in enumerate(lines):
            if re.search(r"(?i)class action settlement$|^[^|]{3,60} - [^|]{3,60}$", ln) and not ln.lower().startswith(("proof", "deadline", "settlement payout")):
                title, payout, deadline = ln, None, None
            elif ln.lower().startswith("settlement payout"):
                payout = ln.split(None, 2)[-1] if len(ln.split()) > 2 else (lines[i + 1] if i + 1 < len(lines) else None)
            elif ln.lower().startswith("deadline"):
                deadline = parse_date(ln) or parse_date(lines[i + 1] if i + 1 < len(lines) else "")
            elif ln.lower().startswith("proof required"):
                val = ln.split("?", 1)[-1].strip() or (lines[i + 1] if i + 1 < len(lines) else "")
                if title and deadline and val.lower().startswith("no"):
                    out.append(entry(title, deadline, payout, "See ClassAction.org for who qualifies.", page))
                title = payout = deadline = None
        if not out:  # help debug the parser from the Actions log
            hits = [i for i, l in enumerate(lines) if "proof required" in l.lower()]
            print("   [diag] %s: %d text lines, %d 'Proof Required' lines" % (page, len(lines), len(hits)))
            for i in hits[:2]:
                print("   [diag] context:", " | ".join(lines[max(0, i - 6):i + 2]))
    return out


# ---------- source 3: ClaimDepot no-proof list (blocks: title, "Award:", value, "Claim Deadline", date) ----------
def src_claimdepot():
    url = "https://www.claimdepot.com/no-proof-class-action-settlements"
    lines = to_text(get(url)).split("\n")
    out = []
    for i, ln in enumerate(lines):
        if ln.lower().startswith("award") and i > 0:
            title = lines[i - 1].lstrip("# ").strip()
            payout = ln.split(":", 1)[1].strip() if ":" in ln and ln.split(":", 1)[1].strip() else (lines[i + 1] if i + 1 < len(lines) else "")
            d = None
            for j in range(i + 1, min(i + 6, len(lines))):
                if lines[j].lower().startswith("claim deadline"):
                    d = parse_date(lines[j]) or parse_date(lines[j + 1] if j + 1 < len(lines) else "")
                    break
            if title and d:
                out.append(entry(title, d, payout, "See ClaimDepot for who qualifies.", url))
    return out


# ---------- (disabled) Top Class Actions: returns 403 to automated requests, so it is link-only on the page ----------
# Kept for reference; not in SOURCES. Not worth working around a site that blocks bots.
# source 4: Top Class Actions (article pages with "Proof of Purchase Required: No") ----------
def src_topclassactions():
    cat = "https://topclassactions.com/category/lawsuit-settlements/open-lawsuit-settlements/"
    links = hrefs(get(cat), r"https://topclassactions\.com/lawsuit-settlements/open-lawsuit-settlements/[^\"#?]+/")
    out = []
    for url in links[:40]:
        try:
            h = get(url)
        except Exception as e:
            print("   skip", url, e)
            continue
        time.sleep(1.0)
        t = to_text(h)
        proof = (after_label(t, r"Proof of Purchase Required") or "").lower()
        if not proof.startswith("no"):
            continue
        dl = after_label(t, r"(?:Claim )?Deadline")
        d = parse_date(dl)
        if d:
            out.append(entry(h1(h), d, after_label(t, r"Potential Individual Reward"), meta_desc(h), url))
    return out


# ---------- sources 5 & 6: ClaimWatch and FileYourClaim (heading + body chunks) ----------
def chunks(h):
    """Split a page into (heading, body_html) pairs at h2/h3/h4 tags."""
    parts = re.split(r"(?is)<h[234][^>]*>(.*?)</h[234]>", h)
    out = []
    for i in range(1, len(parts) - 1, 2):
        title = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", "", parts[i]))).strip()
        out.append((title, parts[i + 1]))
    return out


def first_link(body_html, page):
    m = re.search(r'href="(https://[^"#]+|/settlements?/[^"#]+)"', body_html)
    if not m:
        return page
    u = m.group(1)
    return u if u.startswith("http") else re.match(r"https?://[^/]+", page).group(0) + u


def diag(label, cs):
    print("   [diag] %s: %d heading chunks" % (label, len(cs)))
    for t, b in cs[:2]:
        print("   [diag] sample:", t[:60], "|", to_text(b).replace("\n", " / ")[:160])


def parse_claimwatch(h, page):
    out, cs = [], chunks(h)
    for title, body in cs:
        t = to_text(body)
        m = re.search(r"(?im)^(.*?)\s*no proof needed", t)
        d = parse_date(m.group(1)) if m else None
        if not d:
            continue
        desc = next((l for l in t.split("\n") if len(l) > 40 and not parse_date(l[:25])), "")
        out.append(entry(title, d, "", desc, first_link(body, page)))
    if not out:
        diag("ClaimWatch", cs)
    return out


def src_claimwatch():
    page = "https://claimwatch.org/settlements/no-proof"
    return parse_claimwatch(get(page), page)


def parse_fileyourclaim(h, page):
    out, cs = [], chunks(h)
    for title, body in cs:
        t = to_text(body)
        if "no proof" not in t.lower():
            continue
        if re.search(r"(?i)proof of purchase[^.]{0,30}required|asks? (?:people )?(?:for|to provide) proof|claim id is required", t):
            continue  # the page itself warns the official form wants proof
        m = re.search(r"(?i)deadline:?\s*([A-Za-z]+ \d{1,2},? \d{4})", t)
        d = parse_date(m.group(1)) if m else None
        if not d:
            continue
        pay = re.search(r"\$\d[\d,.]*(?:\+| ?[MBK])?", t)
        desc = next((l for l in t.split("\n") if len(l) > 40), "")
        out.append(entry(title, d, pay.group(0) if pay else "", desc, first_link(body, page)))
    if not out:
        diag("FileYourClaim", cs)
    return out


def src_fileyourclaim():
    page = "https://fileyourclaim.co/open-class-action-settlements"
    return parse_fileyourclaim(get(page), page)


SOURCES = [
    ("OpenClassActions", src_openclassactions),
    ("ClaimDepot", src_claimdepot),
    ("ClaimWatch", src_claimwatch),
    ("FileYourClaim", src_fileyourclaim),
]


def words(n):
    return {w for w in re.findall(r"[a-z0-9]{3,}", (n or "").lower())} - STOP


def same(a, b):
    if a.get("u") and a.get("u") == b.get("u"):
        return True
    return a["d"] == b["d"] and bool(words(a["n"]) & words(b["n"]))


def main():
    today = dt.date.today()
    seed = json.loads((ROOT / "data_seed.json").read_text())
    scraped, working = [], 0
    for name, fn in SOURCES:
        try:
            got = fn()
        except Exception as e:
            print("[%s] FAILED: %s" % (name, e))
            continue
        got = [g for g in got if g["d"] >= today and not NOTICE_ONLY.search(g["n"] + " " + g["w"])]
        print("[%s] kept %d" % (name, len(got)))
        working += bool(got)
        scraped += [dict(g, d=g["d"].isoformat()) for g in got]

    if not working:
        print("FAILED: no source returned anything; layouts probably changed.", file=sys.stderr)
        return 1

    items = list(seed)
    for s in scraped:
        if not any(same(s, x) for x in items):
            items.append(s)
    items = [i for i in items if i["d"] >= today.isoformat()]
    items.sort(key=lambda i: i["d"])
    out = {"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "scraped_count": len(items) - len(seed), "items": items}
    (ROOT / "settlements.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print("wrote settlements.json with %d items (%d new beyond seed)" % (len(items), len(items) - len(seed)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
