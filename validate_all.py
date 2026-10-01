"""Validate every local dataset for the NIFTY 50 study and print a PASS/FAIL report."""
import csv, gzip, re
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

D = Path(__file__).parent / "data"
START, END = date(2025, 10, 1), date(2026, 9, 30)
N50 = set((D / "N50_symbols.txt").read_text().split()) - {"NIFTY"}
DAYS = set((D / "trading_days.txt").read_text().split())
iso = lambda ds: f"{ds[:4]}-{ds[4:6]}-{ds[6:]}"
f = lambda x: float(x) if x not in ("", None) else None
problems, total_rows = [], 0


def check(cond, msg):
    if not cond: problems.append(msg)


# ---- cash market
n = dup = bad = 0; keys = set(); days = set(); cover = defaultdict(set); close = {}
with gzip.open(D / "cm_bhavcopy_12m.csv.gz", "rt") as fh:
    for r in csv.DictReader(fh):
        n += 1; k = (r["TradDt"], r["TckrSymb"], r["SctySrs"]); dup += k in keys; keys.add(k); days.add(r["TradDt"])
        if r["SctySrs"] == "EQ":
            o, h, l, c = (f(r[x]) for x in ("OpnPric", "HghPric", "LwPric", "ClsPric"))
            if None not in (o, h, l, c) and not (0 < l <= min(o, c) and max(o, c) <= h): bad += 1
            if r["TckrSymb"] in N50: cover[r["TckrSymb"]].add(r["TradDt"]); close[(r["TradDt"], r["TckrSymb"])] = c
total_rows += n
lo, hi = min(days), max(days)
print(f"CASH     rows={n:,} days={len(days)} range={lo}..{hi} duplicates={dup} bad_OHLC={bad}")
check(len(days) == len(DAYS), "cash: trading-day count mismatch")
check(dup == 0 and bad == 0, "cash: duplicates or bad prices")
check(date.fromisoformat(lo) >= START and date.fromisoformat(hi) <= END, "cash: data outside 12-month window")
short = {s: len(days) - len(v) for s, v in cover.items() if len(v) < len(days)}
missing_syms = N50 - set(cover)
print(f"         NIFTY50 coverage: {50 - len(missing_syms)}/50 stocks present; stocks with gaps: {short or 'none'}")
check(not missing_syms, f"cash: NIFTY50 stocks absent: {missing_syms}")

# ---- futures & options
n = dup = 0; keys = set(); fdays = set(); types = Counter(); chk = mism = 0
with gzip.open(D / "fo_nifty50_12m.csv.gz", "rt") as fh:
    for r in csv.DictReader(fh):
        n += 1; k = (r["TradDt"], r["FinInstrmId"]); dup += k in keys; keys.add(k); fdays.add(r["TradDt"]); types[r["FinInstrmTp"]] += 1
        if r["FinInstrmTp"] == "STF" and (r["TradDt"], r["TckrSymb"]) in close and r["UndrlygPric"]:
            chk += 1; spot = close[(r["TradDt"], r["TckrSymb"])]
            mism += abs(f(r["UndrlygPric"]) - spot) > 0.005 * spot
total_rows += n
print(f"F&O      rows={n:,} days={len(fdays)} duplicates={dup} types={dict(types)} futures-vs-cash mismatches={mism}/{chk:,}")
check(fdays == days, "F&O: trading days differ from cash")
check(dup == 0, "F&O: duplicates")
check(chk and mism / chk < 0.01, "F&O: >1% futures underlying prices disagree with cash close")

# ---- index closes
n = 0; idx_days = set(); nifty = {}
with gzip.open(D / "indices_close_12m.csv.gz", "rt") as fh:
    for r in csv.DictReader(fh):
        n += 1
        if r["Index Name"].strip().lower() == "nifty 50":
            dt = datetime.strptime(r["Index Date"], "%d-%m-%Y").date().isoformat(); idx_days.add(dt)
            nifty[dt] = f(r["Closing Index Value"])
total_rows += n
print(f"INDEX    rows={n:,} NIFTY50 days={len(nifty)} first/last close={nifty.get(lo)} / {nifty.get(hi)}")
check(idx_days == days, "index: NIFTY 50 days differ from trading days")

# ---- quarterly results
xb = list((D / "results_xbrl").glob("*.xml")); by_sym = Counter(p.name.split("_")[0] for p in xb)
qtrs = Counter(p.name.split("_")[1] for p in xb)
print(f"RESULTS  xbrl files={len(xb)} companies={len(by_sym)}/50 quarters={dict(sorted(qtrs.items()))}")
print(f"         companies with <4 files: {[s for s in N50 if by_sym.get(s, 0) < 4] or 'none'}")
check(len(by_sym) >= 48, "results: fewer than 48 companies have filings")

# ---- news
n = 0; per = Counter(); outside = 0; seen = set(); dupl = 0
with gzip.open(D / "news_headlines_12m.csv.gz", "rt") as fh:
    for r in csv.DictReader(fh):
        n += 1; per[r["symbol"]] += 1
        k = (r["symbol"], r["link"]); dupl += k in seen; seen.add(k)
        try:
            pd = datetime.strptime(r["pubDate"][5:16], "%d %b %Y").date()
            outside += not (date.fromisoformat(r["window_start"]) <= pd <= date.fromisoformat(r["window_end"]))
        except ValueError:
            outside += 1
total_rows += n
low = sorted((c, s) for s, c in per.items())[:5]
print(f"NEWS     headlines={n:,} stocks={len(per)}/50 duplicates={dupl} outside-window={outside} ({outside / max(n, 1):.1%})")
print(f"         fewest headlines: {low}")
check(len(per) == 50, "news: not all 50 stocks collected")
check(dupl == 0, "news: duplicate headlines")
check(outside / max(n, 1) < 0.05, "news: >5% of headlines dated outside their query window")

print(f"\nTOTAL ROWS (all datasets): {total_rows:,}")
print("RESULT:", "PASS" if not problems else "FAIL -> " + "; ".join(problems))
