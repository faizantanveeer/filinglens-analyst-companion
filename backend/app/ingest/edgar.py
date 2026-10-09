"""Import filings straight from SEC EDGAR by ticker (10-K, 10-Q, 20-F, 40-F). No API key needed."""

import json
import time
import urllib.error
import urllib.request

from ..config import settings

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"

_tickers: dict[str, dict] = {}
_tickers_loaded = 0.0


class EdgarError(Exception):
    pass


def _get(url: str, timeout: int = 30) -> bytes:
    """All requests go to fixed sec.gov hosts (no user-supplied URLs), with the User-Agent the SEC requires."""
    req = urllib.request.Request(url, headers={"User-Agent": settings.sec_user_agent, "Accept-Encoding": "identity"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        hint = " (set SEC_USER_AGENT to 'AppName your@email' in .env)" if exc.code == 403 else ""
        raise EdgarError(f"SEC EDGAR returned HTTP {exc.code}{hint}.") from None
    except Exception as exc:
        raise EdgarError(f"Could not reach SEC EDGAR: {type(exc).__name__}.") from None


def lookup(ticker: str) -> dict:
    """Ticker → {cik, title}. The SEC's ticker map is cached for a day."""
    global _tickers, _tickers_loaded
    if not _tickers or time.time() - _tickers_loaded > 86_400:
        data = json.loads(_get(TICKERS_URL))
        _tickers = {v["ticker"].upper(): {"cik": int(v["cik_str"]), "title": v["title"]} for v in data.values()}
        _tickers_loaded = time.time()
    hit = _tickers.get(ticker.upper().replace(".", "-")) or _tickers.get(ticker.upper())
    if not hit:
        raise EdgarError(f"Ticker {ticker.upper()} not found on SEC EDGAR.")
    return hit


def latest_filing(ticker: str, form: str = "10-K") -> dict:
    """Find the most recent filing of `form` and download its primary (HTML) document."""
    company = lookup(ticker)
    cik = company["cik"]
    recent = json.loads(_get(SUBMISSIONS_URL.format(cik=cik)))["filings"]["recent"]
    try:
        i = recent["form"].index(form)
    except ValueError:
        raise EdgarError(f"No recent {form} found for {ticker.upper()}.") from None
    acc, doc = recent["accessionNumber"][i], recent["primaryDocument"][i]
    url = ARCHIVE_URL.format(cik=cik, acc=acc.replace("-", ""), doc=doc)
    content = _get(url, timeout=120)
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise EdgarError(f"Filing is larger than {settings.max_upload_mb} MB.")
    period = recent.get("reportDate", [""] * (i + 1))[i] or recent["filingDate"][i]
    return {
        "content": content,
        "url": url,
        "filename": f"{ticker.upper()} {form} {period}.html",
        "company": company["title"],
    }
