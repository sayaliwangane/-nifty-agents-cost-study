"""Collect the full local dataset for the NIFTY 50 multi-agent study.

usage: python collect_all.py prices|index|results|news
Window: 1 Oct 2025 - 30 Sep 2026 (exactly 12 months). Everything is saved under data/.
"""
import csv, gzip, io, json, re, subprocess, sys, time, zipfile, html, urllib.parse
from datetime import date, datetime, timedelta
from pathlib import Path

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124 Safari/537.36"
DATA = Path(__file__).parent / "data"
START, END = date(2025, 10, 1), date(2026, 9, 30)


def curl(url, timeout=90):
    r = subprocess.run(["curl", "-s", "-m", str(timeout), "-A", UA, "-w", "%{http_code}", "-o", "-", url],
                       capture_output=True)
    return r.stdout[:-3], r.stdout[-3:].decode(errors="ignore")


def nifty50():
    body, _ = curl("https://nsearchives.nseindia.com/content/indices/ind_nifty50list.csv")
    rows = list(csv.DictReader(io.StringIO(body.decode())))
    assert len(rows) == 50, len(rows)
    return rows


def weekdays():
    d = START
    while d <= END:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def fetch_zip(url, tries=4):
    """Download a zip and confirm it opens; retry on truncated/corrupt files. None = not published (holiday)."""
    for attempt in range(tries):
        body, s = curl(url, 180)
        if s == "404":
            return None
        if s == "200" and body[:2] == b"PK":
            try:
                with zipfile.ZipFile(io.BytesIO(body)) as z:
                    if z.testzip() is None:
                        return body
            except zipfile.BadZipFile:
                pass
        print(f"  retry {attempt + 1} for {url.rsplit('/', 1)[-1]} (HTTP {s}, {len(body)} bytes)", flush=True)
        time.sleep(10 * (attempt + 1))
    raise RuntimeError(f"could not download a valid zip: {url}")


def zip_rows(b):
    with zipfile.ZipFile(io.BytesIO(b)) as z, z.open(z.namelist()[0]) as f:
        yield from csv.DictReader(io.TextIOWrapper(f, encoding="utf-8", errors="replace"))


# ---------------------------------------------------------------- prices
def prices():
    n50 = {r["Symbol"] for r in nifty50()} | {"NIFTY"}
    out_cm, out_fo = DATA / "cm_bhavcopy_12m.csv.gz", DATA / "fo_nifty50_12m.csv.gz"
    tmp_cm, tmp_fo = out_cm.with_suffix(".tmp"), out_fo.with_suffix(".tmp")
    cm_f, fo_f = gzip.open(tmp_cm, "wt", newline=""), gzip.open(tmp_fo, "wt", newline="")
    cm_w = fo_w = None; cm_n = fo_n = 0; days = []; holidays = []
    for d in weekdays():
        ds = d.strftime("%Y%m%d")
        cm = fetch_zip(f"https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{ds}_F_0000.csv.zip")
        if cm is None:
            holidays.append(ds); time.sleep(0.5); continue
        fo = fetch_zip(f"https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{ds}_F_0000.csv.zip")
        assert fo is not None, f"{ds}: cash file present but F&O missing"
        for r in zip_rows(cm):
            if cm_w is None: cm_w = csv.DictWriter(cm_f, fieldnames=list(r)); cm_w.writeheader()
            cm_w.writerow(r); cm_n += 1
        for r in zip_rows(fo):
            if r["TckrSymb"] in n50:
                if fo_w is None: fo_w = csv.DictWriter(fo_f, fieldnames=list(r)); fo_w.writeheader()
                fo_w.writerow(r); fo_n += 1
        days.append(ds); print(f"prices {ds} cm={cm_n:,} fo={fo_n:,}", flush=True); time.sleep(0.6)
    cm_f.close(); fo_f.close()
    tmp_cm.replace(out_cm); tmp_fo.replace(out_fo)          # only replace old files once the new ones are complete
    (DATA / "N50_symbols.txt").write_text("\n".join(sorted(n50)))
    (DATA / "trading_days.txt").write_text("\n".join(days))
    print(f"PRICES DONE days={len(days)} holidays={holidays} cm={cm_n:,} fo={fo_n:,}")


# ---------------------------------------------------------------- index closes
def index():
    days = (DATA / "trading_days.txt").read_text().split() if (DATA / "trading_days.txt").exists() \
        else [d.strftime("%Y%m%d") for d in weekdays()]
    out = gzip.open(DATA / "indices_close_12m.csv.gz", "wt", newline="")
    w = None; n = 0; missing = []
    for ds in days:
        dmy = ds[6:8] + ds[4:6] + ds[0:4]
        body, s = curl(f"https://nsearchives.nseindia.com/content/indices/ind_close_all_{dmy}.csv")
        if s != "200" or not body.startswith(b"Index Name"):
            missing.append(ds); continue
        for r in csv.DictReader(io.StringIO(body.decode(errors="replace"))):
            if w is None: w = csv.DictWriter(out, fieldnames=list(r)); w.writeheader()
            w.writerow(r); n += 1
        time.sleep(0.4)
    out.close()
    print(f"INDEX DONE rows={n:,} days={len(days) - len(missing)} missing={missing}")


# ---------------------------------------------------------------- quarterly results
JAR = "/tmp/nse_cookies.txt"


def nse_api(url):
    """NSE JSON API with a session cookie (primed from the home page) and retries."""
    for attempt in range(4):
        if attempt == 0 or attempt == 2:
            subprocess.run(["curl", "-s", "-m", "20", "-A", UA, "-c", JAR, "-o", "/dev/null", "https://www.nseindia.com/"])
        r = subprocess.run(["curl", "-s", "-m", "40", "-A", UA, "-b", JAR, "-H", "Referer: https://www.nseindia.com/", url],
                           capture_output=True, text=True)
        try:
            return json.loads(r.stdout)
        except ValueError:
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"NSE API failed: {url}")


def results():
    """Integrated Filing (Financials): SEBI's format for quarterly results since early 2025."""
    meta_dir, xbrl_dir = DATA / "results_meta", DATA / "results_xbrl"
    meta_dir.mkdir(exist_ok=True); xbrl_dir.mkdir(exist_ok=True)
    for old in meta_dir.glob("*.json"):              # drop metadata from the outdated pre-2025 endpoint
        old.unlink()
    lo, hi = datetime(2025, 7, 1), datetime(2026, 9, 30, 23, 59)   # results released just before + during window
    filings = xbrls = 0; failed = []
    for row in nifty50():
        sym = row["Symbol"]
        base = ("https://www.nseindia.com/api/integrated-filing-results?index=equities&period=Quarterly&symbol="
                + urllib.parse.quote(sym))
        try:
            first = nse_api(base)
            items, total, page = list(first.get("data", [])), first.get("totalCount", 0), 1
            while len(items) < total and page < 20:
                page += 1
                more = nse_api(f"{base}&page={page}").get("data", [])
                if not more:
                    break
                items += more
        except RuntimeError:
            failed.append(sym); continue
        (meta_dir / f"{sym}.json").write_text(json.dumps(items, indent=1))
        filings += len(items)
        for it in items:
            if "Financials" not in (it.get("type") or ""):
                continue
            try:
                bd = datetime.strptime((it.get("broadcast_Date") or "")[:20].strip(), "%d-%b-%Y %H:%M:%S")
            except ValueError:
                continue
            if not (lo <= bd <= hi) or not (it.get("xbrl") or "").endswith(".xml"):
                continue
            kind = "C" if (it.get("consolidated") or "").startswith("Cons") else "S"
            name = f"{sym}_{it.get('qe_Date')}_{kind}_{it.get('type_Sub') or 'Original'}.xml"
            if (xbrl_dir / name).exists():
                continue
            x, s2 = curl(it["xbrl"])
            if s2 == "200" and b"xbrl" in x[:3000]:
                (xbrl_dir / name).write_bytes(x); xbrls += 1
            time.sleep(0.5)
        print(f"results {sym}: {len(items)} filings, xbrl so far {xbrls}", flush=True); time.sleep(1)
    print(f"RESULTS DONE companies={50 - len(failed)} filings={filings:,} xbrl_files={xbrls} failed={failed}")


# ---------------------------------------------------------------- news
def short_name(n):
    n = re.sub(r"\s+(Ltd\.?|Limited)$", "", n.strip())
    return n.replace(" and Special Economic Zone", "")


def rss(query):
    url = ("https://news.google.com/rss/search?q=" + urllib.parse.quote(query)
           + "&hl=en-IN&gl=IN&ceid=IN:en")
    for attempt in range(4):
        body, s = curl(url, 30)
        if s == "200":
            break
        time.sleep(30 * (attempt + 1))
    else:
        raise RuntimeError(f"RSS failed after retries: {query} ({s})")
    out = []
    for item in re.findall(rb"<item>(.*?)</item>", body, re.S):
        g = lambda tag: html.unescape((re.search(rb"<" + tag + rb"[^>]*>(.*?)</" + tag + rb">", item, re.S)
                                        or [b"", b""])[1].decode(errors="replace")).strip()
        out.append({"title": g(b"title"), "link": g(b"link"), "pubDate": g(b"pubDate"), "source": g(b"source")})
    return out


def news():
    out = gzip.open(DATA / "news_headlines_12m.csv.gz", "wt", newline="")
    w = csv.DictWriter(out, fieldnames=["symbol", "company", "window_start", "window_end", "pubDate", "title",
                                        "source", "link"])
    w.writeheader()
    total = 0
    for row in nifty50():
        sym, name = row["Symbol"], short_name(row["Company Name"])
        seen = set(); n_sym = 0
        wk = START - timedelta(days=START.weekday())
        while wk <= END:
            windows = [(wk, wk + timedelta(days=7))]
            items = rss(f'"{name}" stock after:{windows[0][0]} before:{windows[0][1]}'); time.sleep(1.2)
            if len(items) >= 100:                       # hit Google's cap: re-ask one day at a time
                items, windows = [], [(wk + timedelta(days=i), wk + timedelta(days=i + 1)) for i in range(7)]
                for a, b in windows:
                    items += [dict(it, _a=a, _b=b) for it in rss(f'"{name}" stock after:{a} before:{b}')]
                    time.sleep(1.2)
            for it in items:
                if it["link"] in seen:
                    continue
                seen.add(it["link"])
                a, b = it.pop("_a", windows[0][0]), it.pop("_b", windows[0][1])
                w.writerow({"symbol": sym, "company": name, "window_start": a, "window_end": b, **it}); n_sym += 1
            wk += timedelta(days=7)
        total += n_sym; out.flush()
        print(f"news {sym:12s} ({name}): {n_sym:,} headlines | total {total:,}", flush=True)
    out.close()
    print(f"NEWS DONE headlines={total:,}")


if __name__ == "__main__":
    {"prices": prices, "index": index, "results": results, "news": news}[sys.argv[1]]()
