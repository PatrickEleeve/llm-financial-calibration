"""Minimal SEC EDGAR / XBRL client.

Reads the required User-Agent contact from the SEC_USER_AGENT environment
variable (see .env.example). The contact is never written to disk or logs.
Respects SEC fair-access guidance (<=10 requests/second; we use ~4/s).
"""
import json, os, time
from pathlib import Path
import requests
from dotenv import load_dotenv

load_dotenv()
CACHE = Path(__file__).resolve().parent.parent / "data" / "raw"
CACHE.mkdir(parents=True, exist_ok=True)
_last = 0.0


def _headers():
    ua = os.environ.get("SEC_USER_AGENT", "").strip()
    if not ua or "@" not in ua:
        raise SystemExit(
            "Set SEC_USER_AGENT in .env, e.g. SEC_USER_AGENT=\"Your Name you@example.edu\""
        )
    return {"User-Agent": ua, "Accept-Encoding": "gzip, deflate"}


def _get_json(url, cache_name):
    global _last
    path = CACHE / cache_name
    if path.exists():
        return json.loads(path.read_text())
    wait = 0.25 - (time.time() - _last)
    if wait > 0:
        time.sleep(wait)
    r = requests.get(url, headers=_headers(), timeout=30)
    _last = time.time()
    r.raise_for_status()
    path.write_text(r.text)
    return r.json()


def ticker_map():
    """ticker -> zero-padded 10-digit CIK."""
    d = _get_json("https://www.sec.gov/files/company_tickers.json", "company_tickers.json")
    return {v["ticker"].upper(): str(v["cik_str"]).zfill(10) for v in d.values()}


def company_facts(cik10):
    return _get_json(
        f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json",
        f"facts_{cik10}.json",
    )


def fetch_json(url):
    """Rate-limited GET that does NOT cache to disk (for large files we slim in memory)."""
    global _last
    wait = 0.25 - (time.time() - _last)
    if wait > 0:
        time.sleep(wait)
    r = requests.get(url, headers=_headers(), timeout=60)
    _last = time.time()
    r.raise_for_status()
    return r.json()


if __name__ == "__main__":
    # Self-test: fetch Apple and print the latest few revenue-like facts.
    cik = ticker_map()["AAPL"]
    facts = company_facts(cik)
    gaap = facts["facts"]["us-gaap"]
    for tag in ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "NetIncomeLoss"):
        if tag in gaap:
            rows = gaap[tag]["units"]["USD"][-3:]
            print(tag)
            for r in rows:
                print("  ", r["fy"], r["fp"], r["form"], r["start"] if "start" in r else "", r["end"], r["val"], "filed", r["filed"])
