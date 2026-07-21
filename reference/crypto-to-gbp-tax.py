#!/usr/bin/env python3
"""
crypto-to-gbp-tax.py
--------------------
Prices a Kraken spot "ledgers" CSV export in GBP, for UK personal tax prep.

PRICE SOURCE
  * Kraken's own public OHLC API (no key). Daily close on each row's date.
    This is the exchange you actually traded on, so it is the most defensible
    valuation for HMRC. Coins quoted only in USD on Kraken are converted to GBP
    via ECB daily FX (frankfurter.app, free, no key).

DISPOSAL PROCEEDS
  * When you sold crypto INTO GBP (or USD), the real fiat received is already in
    the paired ledger row (same refid). We use that ACTUAL figure as proceeds.
  * Crypto-to-crypto disposals have no fiat leg, so proceeds = GBP market value
    of the crypto disposed at that day's close (the HMRC rule).

CAPITAL GAINS
  * Computes UK CGT gains for 2025/26 using HMRC share matching:
    same-day -> 30-day (bed & breakfast) -> Section 104 pool. Feed it a FULL
    historical export (first ever trade -> today) so the pool is complete; the
    pool is built across all history and gains reported for 2025/26 disposals.
  * It is not tax advice.

USAGE
  pip install pandas requests
  python crypto-to-gbp-tax.py kraken-spot-ledgers-2025-04-05-2026-04-05.csv

OUTPUT
  <input>_full_gbp.csv          every row + price_gbp, value_gbp, fee_gbp, category
  <input>_disposals_cgt.csv     one row per disposal: proceeds + allowable fees
  <input>_acquisitions.csv      one row per buy: cost basis (feeds s104 pool)
  <input>_income.csv            rewards/airdrops valued in GBP (misc income)
  <input>_gains_cgt.csv         2025/26 gains per disposal (after matching)
  <input>_gains_working.csv     per-chunk audit: which rule matched what cost
  <input>_pool_carryforward.csv s104 pool per asset at year end (carry forward)
  <input>_summary.txt           totals + flags
  <input>_tax.xlsx              all of the above as tabs, one file for accountant
  .price_cache.json             cached price series so re-runs are instant
"""

import sys, os, json, time, datetime as dt
import pandas as pd
import requests

# ---------------------------------------------------------------------------
# Ticker normalisation for Kraken. Kraken uses XBT for Bitcoin in wsnames, and
# MATIC rebranded to POL (1:1 same token) so post-rebrand MATIC is priced as POL.
# Everything else maps by its plain ticker.
# ---------------------------------------------------------------------------
KRAKEN_ALIAS = {
    "BTC":   "XBT",
    "MATIC": "POL",   # MATIC->POL rebrand; same asset, price with POL pair
}

# Fiat (never priced as a coin; GBP=1.0, others via daily FX to GBP)
FIAT = {"GBP", "USD", "EUR"}

# Kraken sub-balances that are the SAME asset as their base (staking/parachain
# bonded variants). Stripped to the base ticker so the pool is one pool.
#   ADA.S -> ADA, DOT.P -> DOT, ETH2 / ETH2.S -> ETH
def norm_asset(a):
    if a in FIAT:
        return a
    base = a.split(".")[0]          # drop .S / .P / .B staking suffixes
    if base in ("ETH2",):
        base = "ETH"
    return POOL_ALIAS.get(base, base)

# Subtypes that are internal moves (spot<->staking, migrations) -> never a disposal.
INTERNAL_SUBTYPES = {
    "autoallocation", "allocation", "deallocation",
    "spottostaking", "stakingtospot", "spotfromstaking", "stakingfromspot",
    "migration", "delistingconversion", "dustsweeping", "spotfromfutures",
}
# Types that are income at receipt (in addition to subtype reward/airdrop).
INCOME_TYPES = {"staking", "dividend"}

KRAKEN_ASSETPAIRS = "https://api.kraken.com/0/public/AssetPairs"
KRAKEN_OHLC = "https://api.kraken.com/0/public/OHLC"
CACHE_FILE = ".price_cache.json"
QUOTE_PREFERENCE = ("GBP", "USD", "USDT")  # USDT treated as USD for FX

# UK CGT. Tax year runs 6 Apr -> 5 Apr. We REPORT 2025/26; the Section 104 pool
# is built from the ENTIRE ledger history supplied (give a full export).
TY_START = dt.date(2025, 4, 6)
TY_END = dt.date(2026, 4, 5)
AEA = 3000.0            # annual exempt amount 2025/26
REPORT_PROCEEDS = 50000.0  # SA reporting threshold on proceeds (fixed since 2023/24)

# Tickers pooled together despite a different symbol (rebrand = same asset).
POOL_ALIAS = {"MATIC": "POL"}


# --------------------------------------------------------------------------- #
# cache                                                                        #
# --------------------------------------------------------------------------- #
def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE) as f:
            return json.load(f)
    return {}


def save_cache(cache):
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f)


# --------------------------------------------------------------------------- #
# Kraken pair resolution                                                       #
# --------------------------------------------------------------------------- #
def build_kraken_pairmap():
    """base ticker -> {quote: altname}, e.g. {'ADA': {'GBP': 'ADAGBP', ...}}."""
    r = requests.get(KRAKEN_ASSETPAIRS, timeout=30)
    r.raise_for_status()
    res = r.json().get("result", {})
    m = {}
    for _, p in res.items():
        ws = p.get("wsname", "")
        if "/" not in ws:
            continue
        base, quote = ws.split("/")
        m.setdefault(base, {})[quote] = p["altname"]
    return m


def resolve_pair(ticker, pairmap):
    """(altname, quote) for the best available pair, or None."""
    base = KRAKEN_ALIAS.get(ticker, ticker)
    entry = pairmap.get(base)
    if not entry:
        return None
    for q in QUOTE_PREFERENCE:
        if q in entry:
            return entry[q], q
    return None


# --------------------------------------------------------------------------- #
# price fetching                                                               #
# --------------------------------------------------------------------------- #
def kraken_daily_close(pair, since_ts):
    """{'YYYY-MM-DD': close_in_quote_ccy} via one OHLC call (interval=1440)."""
    r = requests.get(
        KRAKEN_OHLC,
        params={"pair": pair, "interval": 1440, "since": int(since_ts)},
        timeout=30,
    )
    r.raise_for_status()
    j = r.json()
    if j.get("error"):
        raise RuntimeError(", ".join(j["error"]))
    res = j.get("result", {})
    key = next((k for k in res if k != "last"), None)
    if not key:
        raise RuntimeError("empty OHLC result")
    out = {}
    for c in res[key]:
        d = dt.datetime.fromtimestamp(int(c[0]), dt.timezone.utc).strftime("%Y-%m-%d")
        out[d] = float(c[4])  # close
    return out


def fetch_fx_gbp(ccy, lo, hi):
    """<ccy>->GBP daily FX from frankfurter.app (ECB data, free, no key)."""
    url = f"https://api.frankfurter.app/{lo}..{hi}"
    r = requests.get(url, params={"from": ccy, "to": "GBP"}, timeout=30)
    r.raise_for_status()
    return {d: v["GBP"] for d, v in r.json().get("rates", {}).items()}


def nearest_on_or_before(series, date_str):
    """That day's value; else most recent earlier day (FX gaps on weekends)."""
    if not series:
        return None
    if date_str in series:
        return series[date_str]
    earlier = [d for d in series if d <= date_str]
    return series[max(earlier)] if earlier else None


# --------------------------------------------------------------------------- #
# CGT engine: HMRC share matching (same-day -> 30-day -> Section 104 pool)     #
# --------------------------------------------------------------------------- #
def compute_cgt(disposals, acquisitions):
    """disposals:    [{dt(date), asset, qty, proceeds, fee}]
       acquisitions: [{dt(date), asset, qty, cost}]  cost = base cost incl. buy fee
    Returns (working_rows, gain_rows, pool_carryforward, flags)."""
    EPS = 1e-12
    assets = sorted(set(d["asset"] for d in disposals) |
                    set(a["asset"] for a in acquisitions))
    working, gains, pool_cf, flags = [], [], {}, []

    for asset in assets:
        acqs = sorted((dict(a) for a in acquisitions if a["asset"] == asset),
                      key=lambda x: x["dt"])
        disps = sorted((dict(d) for d in disposals if d["asset"] == asset),
                       key=lambda x: x["dt"])
        for a in acqs:
            a["rq"], a["rc"] = a["qty"], a["cost"]   # remaining qty / cost
        for d in disps:
            d["rq"], d["matched"] = d["qty"], []      # matched: [(rule, qty, cost)]

        # 1) same-day
        for d in disps:
            for a in acqs:
                if d["rq"] <= EPS:
                    break
                if a["rq"] > EPS and a["dt"] == d["dt"]:
                    m = min(d["rq"], a["rq"])
                    c = a["rc"] * (m / a["rq"])
                    a["rq"] -= m; a["rc"] -= c
                    d["rq"] -= m; d["matched"].append(("same-day", m, c))

        # 2) 30-day / bed-and-breakfast (acquisitions in the 30 days AFTER, earliest first)
        for d in disps:
            if d["rq"] <= EPS:
                continue
            window = sorted((a for a in acqs if a["rq"] > EPS
                             and 0 < (a["dt"] - d["dt"]).days <= 30),
                            key=lambda x: x["dt"])
            for a in window:
                if d["rq"] <= EPS:
                    break
                m = min(d["rq"], a["rq"])
                c = a["rc"] * (m / a["rq"])
                a["rq"] -= m; a["rc"] -= c
                d["rq"] -= m; d["matched"].append(("30-day", m, c))

        # 3) Section 104 pool (chronological over what is left; acqs before disps on a tie)
        pq = pc = 0.0
        events = ([("acq", a["dt"], a) for a in acqs if a["rq"] > EPS] +
                  [("disp", d["dt"], d) for d in disps if d["rq"] > EPS])
        events.sort(key=lambda x: (x[1], 0 if x[0] == "acq" else 1))
        for kind, _, o in events:
            if kind == "acq":
                pq += o["rq"]; pc += o["rc"]
            else:
                if o["rq"] > pq + 1e-9:
                    flags.append(f"{asset}: disposal {o['dt']} qty {o['rq']:.8f} exceeds "
                                 f"pool {pq:.8f} -- cost basis missing (incomplete history?)")
                    o["matched"].append(("s104-SHORT", o["rq"], pc))
                    pq = pc = 0.0
                else:
                    c = pc * (o["rq"] / pq) if pq > EPS else 0.0
                    o["matched"].append(("s104", o["rq"], c))
                    pq -= o["rq"]; pc -= c
                o["rq"] = 0.0
        pool_cf[asset] = {"qty_held": round(pq, 10), "pooled_cost_gbp": round(pc, 2)}

        # 4) gain rows + per-chunk working (proceeds & fee apportioned by qty)
        for d in disps:
            tot_cost = sum(c for _, _, c in d["matched"])
            gains.append({
                "date": d["dt"], "asset": asset, "quantity": d["qty"],
                "proceeds_gbp": round(d["proceeds"], 2),
                "allowable_cost_gbp": round(tot_cost, 2),
                "disposal_fee_gbp": round(d["fee"], 2),
                "gain_gbp": round(d["proceeds"] - tot_cost - d["fee"], 2),
                "matched": "; ".join(f"{r}:{q:.6f}" for r, q, _ in d["matched"]),
            })
            for rule, q, c in d["matched"]:
                share = q / d["qty"] if d["qty"] else 0.0
                pr, fe = d["proceeds"] * share, d["fee"] * share
                working.append({
                    "date": d["dt"], "asset": asset, "rule": rule,
                    "quantity": round(q, 10), "proceeds_gbp": round(pr, 2),
                    "cost_gbp": round(c, 2), "fee_gbp": round(fe, 2),
                    "gain_gbp": round(pr - c - fe, 2),
                })
    return working, gains, pool_cf, flags


# --------------------------------------------------------------------------- #
# main                                                                         #
# --------------------------------------------------------------------------- #
def main(paths):
    df = pd.concat([pd.read_csv(p) for p in paths], ignore_index=True)
    if len(paths) > 1:
        before = len(df)
        df = df.drop_duplicates(subset=["txid"]).reset_index(drop=True)
        print(f"merged {len(paths)} files: {before} -> {len(df)} rows "
              f"({before - len(df)} duplicate txids dropped)")
        out_base = os.path.join(os.path.dirname(os.path.abspath(paths[0])),
                                "kraken-full-history")
    else:
        out_base = os.path.splitext(paths[0])[0]
    df = df.sort_values("time").reset_index(drop=True)
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    df["fee"] = pd.to_numeric(df["fee"], errors="coerce").fillna(0.0)
    df["date"] = pd.to_datetime(df["time"]).dt.strftime("%Y-%m-%d")
    # normalise staking sub-balances (ADA.S->ADA, ETH2->ETH, MATIC->POL); keep raw
    df["asset_raw"] = df["asset"]
    df["asset"] = df["asset"].map(norm_asset)

    # Coins that existed BEFORE the data starts (opening balance != 0): their
    # pre-data acquisitions are missing, so the pool cost is incomplete. Detect
    # from Kraken's running 'balance' column (balance-before-first-row).
    df["balance"] = pd.to_numeric(df["balance"], errors="coerce")
    pre_data = {}
    for araw, g in df.sort_values("time").groupby("asset_raw"):
        if araw in FIAT:
            continue
        opening = g["balance"].iloc[0] - g["amount"].iloc[0]
        if opening > 1e-6:
            k = norm_asset(araw)
            pre_data[k] = round(pre_data.get(k, 0.0) + float(opening), 6)

    # ---- classify each row -------------------------------------------------
    def categorise(row):
        asset, st, ty, amt = row["asset"], row["subtype"], row["type"], row["amount"]
        if asset in FIAT:
            return "fiat_nontaxable"
        if st == "reward":
            return "income_reward"
        if st == "airdrop":
            return "income_airdrop"
        if st in INTERNAL_SUBTYPES:
            return "internal_nontaxable"          # spot<->staking, migration, dust
        if ty in INCOME_TYPES:
            return "income_reward"                # staking / dividend income
        if ty in ("transfer", "withdrawal"):
            return "internal_nontaxable"          # own-wallet move / send out
        if ty in ("deposit", "receive"):
            return "acquisition"                  # crypto in from outside: cost = mkt value (flagged)
        if ty in ("trade", "spend"):
            return "disposal" if amt < 0 else "acquisition"
        return "review"

    df["category"] = df.apply(categorise, axis=1)

    # ---- date window + FX --------------------------------------------------
    cache = load_cache()
    times = pd.to_datetime(df["time"])
    start_ts = times.min().timestamp() - 86400
    lo, hi = df["date"].min(), df["date"].max()

    fx = {}  # ccy -> {date: rate_to_gbp}
    for ccy in sorted(c for c in FIAT if c != "GBP"):
        fk = f"{ccy.lower()}gbp:{lo}:{hi}"
        if fk in cache:
            fx[ccy] = cache[fk]
        else:
            try:
                fx[ccy] = fetch_fx_gbp(ccy, lo, hi)
                cache[fk] = fx[ccy]
                save_cache(cache)
            except Exception as e:
                print(f"    !! {ccy}->GBP FX failed: {e}")
                fx[ccy] = {}
    usd_gbp = fx.get("USD", {})  # used to convert USD-quoted Kraken pairs

    # ---- resolve + fetch a GBP price series per asset ----------------------
    print("resolving Kraken pairs ...")
    pairmap = build_kraken_pairmap()

    series_by_asset, flagged = {}, []
    for asset in sorted(a for a in df["asset"].unique() if a not in FIAT):
        resolved = resolve_pair(asset, pairmap)
        if not resolved:
            print(f"  !! {asset}: no Kraken pair -> flagged (price by hand)")
            flagged.append(asset)
            continue
        pair, quote = resolved
        ck = f"kraken:{pair}:{quote}:{int(start_ts)}:{hi}"
        if ck in cache:
            series_by_asset[asset] = cache[ck]
            continue
        print(f"  fetching {asset} via {pair} ({quote}) ...")
        try:
            raw = kraken_daily_close(pair, start_ts)
            if quote == "GBP":
                gbp = raw
            else:  # USD / USDT -> GBP via daily FX
                gbp = {}
                for d, px in raw.items():
                    rate = nearest_on_or_before(usd_gbp, d)
                    if rate is not None:
                        gbp[d] = px * rate
            series_by_asset[asset] = gbp
            cache[ck] = gbp
            save_cache(cache)
            time.sleep(1.5)  # Kraken public ~1 req/s
        except Exception as e:
            print(f"    !! failed for {asset}: {e}")
            flagged.append(asset)

    # ---- price every row ---------------------------------------------------
    def price_for(row):
        a, d = row["asset"], row["date"]
        if a == "GBP":
            return 1.0
        if a in FIAT:                       # USD / EUR -> GBP via FX
            return nearest_on_or_before(fx.get(a, {}), d)
        return nearest_on_or_before(series_by_asset.get(a), d)

    df["price_gbp"] = df.apply(price_for, axis=1)
    df["value_gbp"] = (df["amount"] * df["price_gbp"]).round(2)
    df["fee_gbp"] = (df["fee"] * df["price_gbp"]).round(2)

    full_csv = out_base + "_full_gbp.csv"
    df.drop(columns=["date"]).to_csv(full_csv, index=False)

    # ---- disposals (CGT) ---------------------------------------------------
    # proceeds = actual fiat received in the paired refid row, else market value.
    by_refid = {rid: g for rid, g in df.groupby("refid")}
    disp_records = []
    for _, r in df[df["category"] == "disposal"].iterrows():
        sibs = by_refid.get(r["refid"])
        fiat_leg = sibs[(sibs["asset"].isin(FIAT)) & (sibs["amount"] > 0)]
        if len(fiat_leg):
            proceeds = round(float(fiat_leg["value_gbp"].sum()), 2)
            source = "actual_fiat_leg"
            dtype = "crypto->fiat"
        else:
            mv = abs(r["amount"]) * r["price_gbp"] if pd.notna(r["price_gbp"]) else None
            proceeds = round(float(mv), 2) if mv is not None else None
            source = "market_value"
            dtype = "crypto->crypto"
        # allowable disposal cost = all fees on this transaction (both legs)
        fee_total = round(float(sibs["fee_gbp"].fillna(0).sum()), 2)
        disp_records.append({
            "date": r["date"],
            "time": r["time"],
            "asset": r["asset"],
            "quantity": abs(r["amount"]),
            "disposal_type": dtype,
            "proceeds_gbp": proceeds,
            "proceeds_source": source,
            "allowable_fee_gbp": fee_total,
            "refid": r["refid"],
        })
    disp_df = pd.DataFrame(disp_records).sort_values(["date", "asset"]) \
        if disp_records else pd.DataFrame()
    disposals_csv = out_base + "_disposals_cgt.csv"
    disp_df.to_csv(disposals_csv, index=False)

    # ---- acquisitions (build / feed the Section 104 pool) -----------------
    # cost = actual fiat paid in the paired refid row, else market value of the
    # crypto acquired. Needed for same-day / 30-day matching and pool updates.
    # Fee note: for crypto->crypto the single trade fee is attributed to the
    # DISPOSAL leg, so the acquisition fee here is 0 to avoid double counting.
    acq_records = []
    for _, r in df[df["category"] == "acquisition"].iterrows():
        sibs = by_refid.get(r["refid"])
        fiat_leg = sibs[(sibs["asset"].isin(FIAT)) & (sibs["amount"] < 0)]
        if len(fiat_leg):
            cost = round(float(fiat_leg["value_gbp"].abs().sum()), 2)
            source = "actual_fiat_leg"
            atype = "fiat->crypto"
            fee_total = round(float(sibs["fee_gbp"].fillna(0).sum()), 2)
        else:
            mv = abs(r["amount"]) * r["price_gbp"] if pd.notna(r["price_gbp"]) else None
            cost = round(float(mv), 2) if mv is not None else None
            source = "market_value"
            atype = "external_in" if r["type"] in ("deposit", "receive") else "crypto->crypto"
            fee_total = 0.0  # fee counted on the paired disposal record
        acq_records.append({
            "date": r["date"],
            "time": r["time"],
            "asset": r["asset"],
            "quantity": r["amount"],
            "acquisition_type": atype,
            "cost_gbp": cost,
            "cost_source": source,
            "allowable_fee_gbp": fee_total,
            "refid": r["refid"],
        })
    acq_df = pd.DataFrame(acq_records).sort_values(["date", "asset"]) \
        if acq_records else pd.DataFrame()
    acq_csv = out_base + "_acquisitions.csv"
    acq_df.to_csv(acq_csv, index=False)

    # ---- income (rewards / airdrops) --------------------------------------
    # `inc` (all history) feeds the pool below; `inc_ty` (2025/26) is what we report.
    inc = df[df["category"].str.startswith("income")].copy()
    inc["_d"] = pd.to_datetime(inc["time"]).dt.date
    inc_ty = inc[(inc["_d"] >= TY_START) & (inc["_d"] <= TY_END)]
    inc_out = pd.DataFrame({
        "date": inc_ty["date"],
        "time": inc_ty["time"],
        "asset": inc_ty["asset"],
        "quantity": inc_ty["amount"],
        "category": inc_ty["category"],
        "net_gbp": inc_ty["value_gbp"],
        "fee_gbp": inc_ty["fee_gbp"],
        # HMRC income = gross value at receipt (net received + fee taken)
        "gross_gbp": (inc_ty["value_gbp"].fillna(0) + inc_ty["fee_gbp"].fillna(0)).round(2),
        "price_gbp": inc_ty["price_gbp"],
    }).sort_values(["date", "asset"]) if len(inc_ty) else pd.DataFrame()
    income_csv = out_base + "_income.csv"
    inc_out.to_csv(income_csv, index=False)

    # ---- CGT gains (full HMRC matching) ------------------------------------
    pk = lambda a: POOL_ALIAS.get(a, a)
    eng_disposals = [{
        "dt": pd.to_datetime(r["time"]).date(),
        "asset": pk(r["asset"]),
        "qty": float(r["quantity"]),
        "proceeds": float(r["proceeds_gbp"] or 0.0),
        "fee": float(r["allowable_fee_gbp"] or 0.0),
    } for r in disp_records]
    eng_acquisitions = [{
        "dt": pd.to_datetime(r["time"]).date(),
        "asset": pk(r["asset"]),
        "qty": float(r["quantity"]),
        "cost": float((r["cost_gbp"] or 0.0) + (r["allowable_fee_gbp"] or 0.0)),
    } for r in acq_records]
    # rewards/airdrops enter the pool at their gross GBP value on receipt
    for _, r in inc.iterrows():
        eng_acquisitions.append({
            "dt": pd.to_datetime(r["time"]).date(),
            "asset": pk(r["asset"]),
            "qty": float(r["amount"]),
            "cost": float((r["value_gbp"] or 0.0) + (r["fee_gbp"] or 0.0)),
        })

    work_rows, gain_rows, pool_cf, cgt_flags = compute_cgt(eng_disposals, eng_acquisitions)
    gains_df = pd.DataFrame(gain_rows)
    working_df = pd.DataFrame(work_rows)
    pool_df = pd.DataFrame([{"asset": k, **v} for k, v in sorted(pool_cf.items())])

    in_ty = lambda x: TY_START <= x <= TY_END
    ty_gains = gains_df[gains_df["date"].apply(in_ty)] if len(gains_df) else gains_df
    ty_work = working_df[working_df["date"].apply(in_ty)] if len(working_df) else working_df

    proceeds_ty = ty_gains["proceeds_gbp"].sum() if len(ty_gains) else 0.0
    gain_ty = ty_gains.loc[ty_gains["gain_gbp"] > 0, "gain_gbp"].sum() if len(ty_gains) else 0.0
    loss_ty = ty_gains.loc[ty_gains["gain_gbp"] < 0, "gain_gbp"].sum() if len(ty_gains) else 0.0
    net_ty = ty_gains["gain_gbp"].sum() if len(ty_gains) else 0.0
    taxable_ty = max(0.0, net_ty - AEA)
    must_report = (proceeds_ty > REPORT_PROCEEDS) or (net_ty > AEA)

    gains_csv = out_base + "_gains_cgt.csv"
    working_csv = out_base + "_gains_working.csv"
    pool_csv = out_base + "_pool_carryforward.csv"
    ty_gains.to_csv(gains_csv, index=False)
    ty_work.to_csv(working_csv, index=False)
    pool_df.to_csv(pool_csv, index=False)

    # ---- summary -----------------------------------------------------------
    # only count rows that actually NEED a price (taxable events), not internal moves
    need_price = df["category"].isin(
        ["disposal", "acquisition", "income_reward", "income_airdrop"])
    unpriced = df[df["price_gbp"].isna() & need_price & ~df["asset"].isin(FIAT)]
    income_net = inc_ty["value_gbp"].sum() if len(inc_ty) else 0.0
    income_fees = inc_ty["fee_gbp"].sum() if len(inc_ty) else 0.0
    proceeds_total = disp_df["proceeds_gbp"].sum() if len(disp_df) else 0.0
    n_market = int((disp_df["proceeds_source"] == "market_value").sum()) if len(disp_df) else 0

    lines = []
    lines.append("KRAKEN LEDGER -> GBP  (UK personal tax prep)")
    lines.append("=" * 52)
    lines.append(f"Rows: {len(df)}   Priced: {len(df)-len(unpriced)}   "
                 f"Unpriced (non-fiat): {len(unpriced)}")
    lines.append("Price source: Kraken daily close (USD pairs -> GBP via ECB FX)")
    lines.append("")
    lines.append("INCOME  (2025/26 staking/airdrops -- misc income, taxed at receipt)")
    lines.append(f"  Net reward+airdrop value (after Kraken fee): GBP {income_net:,.2f}")
    lines.append(f"  Kraken fees taken on rewards:                GBP {income_fees:,.2f}")
    lines.append(f"  GROSS reward value (the HMRC figure):        GBP {income_net+income_fees:,.2f}")
    lines.append("  -> Report the GROSS figure. £1,000 trading/misc allowance may")
    lines.append("     cover it if this is your only misc income. Confirm with accountant.")
    lines.append("")
    lines.append("CAPITAL GAINS  (2025/26)  -- HMRC same-day -> 30-day -> s104 pool")
    lines.append(f"  Disposals in year: {len(ty_gains)}   Proceeds: GBP {proceeds_ty:,.2f}")
    lines.append(f"  Total gains:   GBP {gain_ty:,.2f}")
    lines.append(f"  Total losses:  GBP {loss_ty:,.2f}")
    lines.append(f"  NET gain:      GBP {net_ty:,.2f}")
    lines.append(f"  Less AEA:      GBP {AEA:,.2f}")
    lines.append(f"  TAXABLE gain:  GBP {taxable_ty:,.2f}")
    lines.append(f"  -> CGT reporting {'REQUIRED' if must_report else 'likely NOT required'} "
                 f"(proceeds > £{REPORT_PROCEEDS:,.0f} or net gain > £{AEA:,.0f}).")
    lines.append(f"  Pool carry-forward to 2026/27: {len(pool_df)} assets (see pool file).")
    lines.append("")
    if flagged or len(unpriced) or cgt_flags or pre_data:
        lines.append("FLAGS -- fix before relying on numbers")
        for a in sorted(set(flagged)):
            lines.append(f"  * {a}: no Kraken pair -- price by hand or add to KRAKEN_ALIAS")
        if len(unpriced):
            bad = unpriced["asset"].value_counts().to_dict()
            lines.append(f"  * {len(unpriced)} taxable rows unpriced (>720d? delisted?): {bad}")
        if pre_data:
            lines.append("  * PRE-DATA HOLDINGS -- coins held before the ledger starts; their")
            lines.append("    pre-history cost is missing. Only PAXG of these was sold in 2025/26.")
            lines.append(f"    opening balances: {pre_data}")
        n_ext = int((acq_df.get('acquisition_type') == 'external_in').sum()) if len(acq_df) else 0
        if n_ext:
            lines.append(f"  * {n_ext} external deposits valued at market price on receipt "
                         f"(USDC etc.) -- source cost assumed = market value.")
        for f in cgt_flags:
            lines.append(f"  * POOL SHORT -- {f}")
    summary = "\n".join(lines)
    out_txt = out_base + "_summary.txt"
    with open(out_txt, "w") as f:
        f.write(summary + "\n")

    # ---- one-file workbook for the accountant ------------------------------
    xlsx = out_base + "_tax.xlsx"
    try:
        with pd.ExcelWriter(xlsx, engine="openpyxl") as xl:
            pd.DataFrame({"summary": summary.split("\n")}).to_excel(
                xl, sheet_name="Summary", index=False, header=False)
            (ty_gains if len(ty_gains) else pd.DataFrame(columns=["(no gains)"])) \
                .to_excel(xl, sheet_name="Gains_CGT", index=False)
            (ty_work if len(ty_work) else pd.DataFrame(columns=["(no working)"])) \
                .to_excel(xl, sheet_name="Gains_Working", index=False)
            (pool_df if len(pool_df) else pd.DataFrame(columns=["(no pool)"])) \
                .to_excel(xl, sheet_name="Pool_Carryforward", index=False)
            (disp_df if len(disp_df) else pd.DataFrame(columns=["(no disposals)"])) \
                .to_excel(xl, sheet_name="Disposals", index=False)
            (acq_df if len(acq_df) else pd.DataFrame(columns=["(no acquisitions)"])) \
                .to_excel(xl, sheet_name="Acquisitions", index=False)
            (inc_out if len(inc_out) else pd.DataFrame(columns=["(no income)"])) \
                .to_excel(xl, sheet_name="Income", index=False)
            df.drop(columns=["date"]).to_excel(xl, sheet_name="Full_Ledger", index=False)
        wrote_xlsx = xlsx
    except Exception as e:
        print(f"    !! xlsx workbook skipped: {e}")
        wrote_xlsx = None

    print("\n" + summary)
    for p in (full_csv, disposals_csv, acq_csv, income_csv,
              gains_csv, working_csv, pool_csv, out_txt, wrote_xlsx):
        if p:
            print(f"Wrote: {p}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python crypto-to-gbp-tax.py <ledgers.csv> [<more.csv> ...]")
        sys.exit(1)
    main(sys.argv[1:])
