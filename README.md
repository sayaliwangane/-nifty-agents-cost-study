# -nifty-agents-cost-study

---

## Contents

| File | What it contains | Rows / files | Size |
|---|---|---|---|
| `data/cm_bhavcopy_12m.csv.gz` | Daily prices for every NSE-listed security | 828,248 rows | 46 MB |
| `data/fo_nifty50_12m.csv.gz` | Daily futures and options data for NIFTY 50 stocks and the NIFTY index | 2,737,405 rows | 89 MB |
| `data/indices_close_12m.csv.gz` | Daily values of NIFTY 50 and all other NSE indices | 36,996 rows | 1.3 MB |
| `data/news_headlines_12m.csv.gz` | Dated news headlines for the 50 NIFTY stocks | 61,089 rows | 24 MB |
| `data/results_xbrl/` | Official quarterly financial results (XBRL) for the 50 companies | 493 files | 234 MB |
| `data/results_meta/` | Filing details per company (dates, links, filing type) | 50 files | small |
| `data/N50_symbols.txt` | The 50 NIFTY stock symbols used, plus `NIFTY` | 51 lines | — |
| `data/trading_days.txt` | The 246 trading days in the window (`YYYYMMDD`) | 246 lines | — |
| `collect_all.py` | Downloads every dataset | — | — |
| `validate_all.py` | Checks every dataset and prints PASS / FAIL | — | — |

`.csv.gz` files are compressed CSV. Open them with pandas (`pd.read_csv("file.csv.gz")`) or double-click in Finder to unpack.

---

## How the data was collected

All data comes from **public sources** and was downloaded with `collect_all.py`, which has four stages:

```bash
python3 collect_all.py prices    # cash + F&O bhavcopy  (~25 min)
python3 collect_all.py index     # index closes         (~3 min)
python3 collect_all.py results   # quarterly results    (~15 min)
python3 collect_all.py news      # news headlines       (~2.5 hours)
python3 validate_all.py          # check everything
```

Only the Python standard library and `curl` are needed. The script:

- downloads one file per trading day and **skips market holidays** (NSE returns HTTP 404 for days with no trading);
- **checks every zip file opens** and retries up to 4 times if a download is cut off;
- writes to temporary files first, so a failed run never overwrites good data;
- waits between requests (0.4–1.2 s) to avoid overloading the servers.

### 1. Daily prices — `cm_bhavcopy_12m.csv.gz`

- **Source:** NSE cash-market bhavcopy (the official end-of-day price file), one file per trading day:
  `https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_<YYYYMMDD>_F_0000.csv.zip`
- **Browse by date:** https://www.nseindia.com/all-reports → *CM – Bhavcopy*
- **What it specifies:** open, high, low and close price, volume and turnover for **every security traded on NSE** each day (about 3,300–3,700 rows per day). Covers all series; ordinary shares are series `EQ`.
- **Used for:** trade prices, portfolio values, buy-and-hold returns, technical indicators.

### 2. Futures & options — `fo_nifty50_12m.csv.gz`

- **Source:** NSE F&O bhavcopy, one file per trading day:
  `https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_<YYYYMMDD>_F_0000.csv.zip`
- **Browse by date:** https://www.nseindia.com/all-reports-derivatives → *F&O – Bhavcopy*
- **Filtered to:** the 50 NIFTY stocks and the NIFTY index (the full daily file has about 35,000–38,000 contracts).
- **What it specifies:** price, settlement price, **open interest** (contracts still outstanding) and volume for every futures and options contract. Contract types in `FinInstrmTp`:

  | Code | Meaning | Rows |
  |---|---|---|
  | `STO` | Stock options | 2,278,852 |
  | `IDO` | Index options (NIFTY) | 420,960 |
  | `STF` | Stock futures | 36,855 |
  | `IDF` | Index futures (NIFTY) | 738 |

- **Used for:** a derivatives-analyst agent (e.g., put–call ratio, changes in open interest), and to cross-check cash prices.

**Columns** (same layout for files 1 and 2):

| Column | Meaning |
|---|---|
| `TradDt` | Trading date |
| `TckrSymb` | Stock symbol (e.g., `INFY`) |
| `SctySrs` | Series (`EQ` = ordinary shares) — cash only |
| `FinInstrmTp` | Instrument type (see table above) — F&O only |
| `XpryDt`, `StrkPric`, `OptnTp` | Expiry date, strike price, option type (`CE` call / `PE` put) — F&O only |
| `OpnPric`, `HghPric`, `LwPric`, `ClsPric` | Open, high, low, close price (₹) |
| `PrvsClsgPric` | Previous day's close (₹) |
| `UndrlygPric` | Price of the underlying stock or index — F&O only |
| `SttlmPric` | Official settlement price (₹) |
| `OpnIntrst`, `ChngInOpnIntrst` | Open interest and its daily change — F&O only |
| `TtlTradgVol`, `TtlTrfVal`, `TtlNbOfTxsExctd` | Total volume, turnover (₹), number of trades |
| `ISIN`, `FinInstrmId`, `FinInstrmNm` | Security identifiers and name |

### 3. Index closes — `indices_close_12m.csv.gz`

- **Source:** NSE daily index file, one per trading day:
  `https://nsearchives.nseindia.com/content/indices/ind_close_all_<DDMMYYYY>.csv`
- **Browse:** https://www.nseindia.com/reports-indices-historical-index-data
- **What it specifies:** daily open, high, low and close of **every NSE index** (NIFTY 50, NIFTY Bank, NIFTY IT, sector indices and more), plus volume, turnover, and the index P/E, P/B and dividend yield.
- **Columns:** `Index Name`, `Index Date`, `Open Index Value`, `High Index Value`, `Low Index Value`, `Closing Index Value`, `Points Change`, `Change(%)`, `Volume`, `Turnover (Rs. Cr.)`, `P/E`, `P/B`, `Div Yield`
- **Used for:** the NIFTY 50 benchmark. Over the window, NIFTY 50 moved from **24,836.30** (1 Oct 2025) to **22,620.45** (30 Sep 2026), about −9%.

### 4. Quarterly results — `results_xbrl/` and `results_meta/`

- **Source:** NSE *Integrated Filing – Financials*, the format SEBI introduced for quarterly results in 2025:
  `https://www.nseindia.com/api/integrated-filing-results?index=equities&period=Quarterly&symbol=<SYMBOL>`
  Each filing links to an official **XBRL** file (a structured, machine-readable version of the financial statements).
- **Window:** results released from 1 July 2025 to 30 September 2026, i.e. quarters ending **Jun 2025, Sep 2025, Dec 2025, Mar 2026 and Jun 2026**. (Jun 2025 results are included because they were the latest available when the test period began.)
- **What it specifies:** revenue, expenses, profit, earnings per share and other line items, both **consolidated (`C`)** and **standalone (`S`)**.
- **File names:** `<SYMBOL>_<QUARTER-END>_<C|S>_<Original|Revised>.xml`, e.g. `INFY_30-JUN-2026_C_Original.xml`
- `results_meta/<SYMBOL>.json` holds each filing's broadcast date, quarter, type and links (also includes governance filings).
- **Used for:** the fundamental-analyst agent. The broadcast date ensures an agent only sees results **after** they were made public.

### 5. News headlines — `news_headlines_12m.csv.gz`

- **Source:** Google News RSS search, run **week by week** for each company with a date filter:
  `"<Company name>" stock after:<week start> before:<week end>` (India edition, English)
  Google returns at most 100 results per search, so busy weeks were automatically **re-queried one day at a time** to avoid missing headlines.
- **What it specifies:** headline, publisher and publication time for news about each NIFTY 50 company.
- **Columns:**

  | Column | Meaning |
  |---|---|
  | `symbol`, `company` | NSE symbol and the company name used in the search |
  | `window_start`, `window_end` | The date range searched |
  | `pubDate` | Publication date and time (GMT) |
  | `title` | Headline text |
  | `source` | Publisher (e.g., The Economic Times, Moneycontrol) |
  | `link` | Google News link to the article |

- **Volume:** 61,089 headlines; between 330 (ONGC) and 4,476 (HDFC Bank) per stock, excluding BSE (see notes).
- **Used for:** the news and sentiment analyst agents.

---

## Validation

`validate_all.py` checks every dataset. Latest run: **PASS**

| Check | Result |
|---|---|
| Date range | All data within 1 Oct 2025 – 30 Sep 2026 |
| Trading days | 246 in cash, F&O and index data (holidays correctly absent) |
| Duplicates | 0 in every dataset |
| Price sanity (low ≤ open/close ≤ high) | 0 bad rows |
| NIFTY 50 coverage | 50 / 50 stocks in prices, results and news |
| Futures vs. cash price | 6 of 36,855 differ by more than 0.5% (likely corporate-action days) |
| News dates | 100% of headlines fall inside the week they were searched for |

### Known notes

- **TMPV** (Tata Motors Passenger Vehicles) has no data for the first 15 trading days, because Tata Motors split into two companies in October 2025 and the new symbol started trading later.
- **BSE** (BSE Ltd, the exchange operator) has 5,797 headlines, which is inflated: a search for "BSE" also matches general market news such as "shares rose on the BSE". Filter BSE headlines to those about the company itself (e.g., containing "BSE Ltd" or "BSE share") before use.
- **SBI Life** has 5 result files instead of 10, because it files only one version (not both consolidated and standalone).
- The **NIFTY 50 list** is the list as of collection (30 Sep 2026). To avoid survivorship bias (testing only companies that stayed in the index), match each date to the index membership at that time, using NSE's index-change announcements.

---

## Data use

Collected from public sources for academic research only. NSE data and news headlines remain the property of their owners; do not redistribute.
