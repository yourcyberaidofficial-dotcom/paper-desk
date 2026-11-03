"""Format recorded research into one diagnosis. This module does not resimulate and does not approve."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


def _load(name):
    path = DOCS / name
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _num(value):
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


def _line(title, row):
    if not row:
        return f"- {title}: no stored row."
    return (
        f"- {title}: {row.get('judgment')} n={row.get('trades')} "
        f"gross={_num(row.get('gross_sum'))} net={_num(row.get('net_sum'))} "
        f"cost_drag={_num(row.get('cost_drag'))} mean={_num(row.get('base_mean'))} "
        f"stress={_num(row.get('stress_mean'))} lower={_num(row.get('normal_95_lower'))} "
        f"equity={_num(row.get('equity'))} drawdown={_num(row.get('max_drawdown'))} "
        f"streak={row.get('worst_loss_streak')} win_rate={_num(row.get('win_rate'))} "
        f"profit_factor={_num(row.get('profit_factor'))} failed={row.get('failed')} blocked={row.get('blocked')}"
    )


def render():
    gate3 = _load("GATE3_RESULTS.json") or {}
    spot = _load("SPOT_RESEARCH_RESULTS.json") or {}
    leader = _load("LEADER_RESULTS.json") or {}
    daily = _load("DAILY_RESULTS.json") or {}
    gate4 = _load("GATE4_RESULTS.json") or {}
    discovery = _load("DISCOVERY_RESULTS.json") or {}
    lines = [
        "# Strategy diagnosis",
        "",
        "This note reads the stored result files. It does not rescore them and it does not open a holdout.",
        "Costs in the research simulator are 11 bps per fill at the base case and 15 bps under stress, two fills, deducted once.",
        "That is an assumption, not a measured exchange fee. The paper book separately assumes 2 bps of adverse slippage on a candle-estimated exit. Those 2 bps are not added again inside the research simulator.",
        "A same-candle stop and target stays unresolved in the paper book. The research simulator checks the stop before the target. Historical results were not rewritten to change that.",
        "No registered strategy is approved for paper. AutoPilot still requires an exact approved version.",
        "",
        "## Data that can and cannot support a new study",
        "",
        "Retained in this checkout: BTCUSDT and ETHUSDT Binance spot 4h from 2023-01-01, 8,378 bars, no gaps in the stored validation. The last 20 percent, from 2026-01-22, was not simulated by the leader study or by the new follow-up.",
        "Retained gold: Dukascopy bid/ask hours, 717 bars, 2024-06-03 to 2024-07-12. The series has closed-market gaps. It was already used. It is not a fresh sample and it is not a licence for 1-minute or 3-minute gold.",
        "Not retained: crypto 1m, 3m, 15m and 1h history, and the longer Gate 4 Dukascopy gold pull. Those earlier results stay as recorded. They are not replayed from memory and the missing files are not invented.",
        "XAUUSD 1m and 3m stay `xau_minute_unlicensed`. Synthetic fixtures are not an approval source.",
        "The twelve desk pairs therefore have no retained candle file long enough for a new holdout study. The only new study this checkout can support is on the already-used 4h crypto prefix.",
        "",
        "## Registry strategies",
        "",
        "### E1-donchian-20 (`e1-20261016`)",
        "",
        "Hypothesis: a close beyond the prior 20 completed bars continues. Invalidation is the other side of that channel. Timeframe 15m, BTC and ETH.",
        "Recorded status: FAIL. `docs/GATE2_RESULTS.md` is not in this checkout, so trade counts are not restated from memory and the rule was not retuned.",
        "Mechanism from the later record: the benchmark stayed failed after costs. This is a recorded failure, not a new measurement.",
        "",
        "### Trend pullback, volatility breakout, range reversion, gold session (`20261027`)",
        "",
        "Gate 3, chronological development and validation, holdout not opened because nothing passed validation.",
        "Crypto rows have hundreds of trades and means near -0.2 percent per trade after the 22 bps round turn. Gross edge was not large enough for that turnover. Both directions and both regime buckets in the later Gate 4 reproduction were negative. That is a no-edge or cost-dominated failure, not an implementation defect that was later corrected.",
        "Gold rows used chart OHLC without measured bid/ask, so they are blocked on that point even where a point estimate was positive. The gold session validation sample was 23 trades. Positive gold point estimates are not approval.",
    ]
    for row in gate3.get("rows") or []:
        if row.get("split") == "validation":
            lines.append(_line(f"{row.get('symbol')} {row.get('strategy')} validation", row))
    lines.extend([
        "",
        "### spot-tsmom-1h-20261028",
        "",
        "Hypothesis: long only after a higher 24-hour close that is also above the 20-bar average. Stop 1.5 ATR, hold 24 bars. BTC and ETH 1h, about 400 days starting 2025-09-23. Holdout of 1,920 bars was not opened.",
        "BTC: 417 trades, gross sum +0.088, cost drag 0.917, net sum -0.829, mean -0.00199. The gross sum is positive and smaller than the cost. Failure mechanism: excessive turnover relative to the gross move, then the existing expectancy, uncertainty, flat and drawdown gates.",
        "ETH: 420 trades, gross sum already -0.201, net -1.125, mean -0.00268. Failure mechanism: no positive gross edge, plus costs.",
        "XAUUSD was not run. Reason recorded: no measured bid/ask. That is insufficient data, not a proven gold failure of this rule.",
        "",
        "### tight-range-long-1h-20261028",
        "",
        "Hypothesis: long near the bottom of a 20-bar range narrower than 1.5 percent. Spot shorts are not taken.",
        "BTC: 45 trades, gross sum about 0, cost drag 0.099, mean -0.00221. FAIL. The range rule did not produce a gross edge that could pay 22 bps.",
        "ETH: 9 trades. BLOCKED for sample size. The point estimate is not a result.",
        "",
        "### sweep-reclaim-4h-20261028 and compress-break-4h-20261028",
        "",
        "Scored once on the retained 4h prefix (6,702 bars, 2023-01-01 through 2026-01-21). Holdout 1,676 bars not opened. Long only. Buy-and-hold on that prefix was largely positive (BTC gross about +4.41, ETH about +1.49) after one 22 bps round turn.",
    ])
    for market in leader.get("markets") or []:
        lines.append(f"- {market.get('symbol')} leader rank: {json.dumps(market.get('leader'), sort_keys=True)}. Rank is not approval.")
        for row in market.get("rows") or []:
            lines.append(_line(f"{market.get('symbol')} {row.get('strategy')} pre-holdout", row))
    lines.extend([
        "BTC sweep gross sum was positive (+0.173) and cost drag was 0.711 across 323 trades. Same cost-versus-turnover mechanism as the 1h momentum rule. Compression breakout was the least-bad BTC rank and still failed uncertainty and the second half; its gross sum (+0.138) did not clear costs (net -0.011) on 68 trades.",
        "ETH sweep gross sum was already negative. ETH compression was negative and blocked for unstable folds. These are failures against a rising market, not a claim that every long rule must lose.",
        "",
        "### london-reclaim-1h-20261028",
        "",
        "Gold only, Dukascopy bid/ask, buy the ask and sell the bid, plus 0.10 USD per side. 6 trades. BLOCKED for sample. Mean was negative. Insufficient evidence, not a precise performance claim. The live chart feed does not run this rule.",
        "",
        "### dip-in-trend-1d-20261028 and quiet-week-reversal-1d-20261028",
        "",
        "Daily bars were built only from complete UTC 4h groups. Holdout not opened. The 4h failures were not retuned.",
    ])
    for market in daily.get("markets") or []:
        for row in market.get("rows") or []:
            lines.append(_line(f"{market.get('symbol')} {row.get('strategy')}", row))
    lines.extend([
        "The daily dip failed after costs on both markets, with a negative median fold, while buy-and-hold on the same prefix was positive. Quiet-week had 9 BTC trades and 4 ETH trades. BLOCKED. The positive BTC point estimate is not evidence.",
        "",
        "## Recorded experiments that are not live registry rows",
        "",
        "Gate 4 added fail-break, quiet-expand and hour-close-drive on crypto, and three gold rules on a Dukascopy pull that is not retained here. Holdout was not opened (`no_validation_pass`).",
    ])
    for row in (gate4.get("crypto") or {}).get("rows") or []:
        if row.get("split") == "validation":
            lines.append(_line(f"{row.get('symbol')} {row.get('strategy')} validation", row))
    gold = gate4.get("gold_measured") or {}
    for row in gold.get("rows") or []:
        if row.get("split") == "validation":
            lines.append(_line(f"XAUUSD {row.get('strategy')} validation", row))
    lines.extend([
        "xau-london-range validation n=24 had a positive point estimate and was BLOCKED for sample. xau-session-day validation failed expectancy. xau-climax-fade had one validation trade. None is approved. The gold file used for that study is not in this checkout, so it was not rerun.",
        "",
        "## New candidate, trend-hold-4h-20261103",
        "",
        "Declared before this scoring as one configuration: long only when a completed 4h close is above the prior 60 highs and above the 120-bar average; stop 3 ATR; target 6 ATR; maximum hold 42 bars; next-bar entry. It is not a parameter edit of compression-breakout (10-bar high, quiet ATR, 1 ATR stop, hold 12) or of E1 (20-bar, 15m).",
        "Reason to test it once: several earlier BTC rules had a small positive gross sum that 11 bps per fill erased. A slower hold was the mechanism suggested by that diagnosis. Because the idea came from those comparisons, it is a follow-up. A pass would not have been an independent discovery.",
        "Development was simulated without validation prices. Validation signals in the first 42 bars were embargoed. The final 20 percent stayed sealed because validation did not PASS.",
        "The existing judge was not edited. A positive mean with a 95 percent lower bound below zero is a FAIL on uncertainty. A window under 30 trades is BLOCKED, not a success.",
    ])
    if not discovery:
        lines.append("The discovery result file is not present.")
    else:
        lines.append(f"Protocol sha256 {discovery.get('protocol_sha256')}. Parent software sha {discovery.get('software_sha')}. Approved list: {discovery.get('approved_for_paper')}. Holdout opened for: {discovery.get('holdout_opened_for') or 'nobody'}.")
        for market in discovery.get("markets") or []:
            lines.append(_line(f"{market.get('symbol')} development", market.get("development")))
            lines.append(_line(f"{market.get('symbol')} validation", market.get("validation")))
            lines.append(f"- {market.get('symbol')} holdout: {market.get('holdout')}. Prefix buy-and-hold gross {_num((market.get('benchmark_prefix') or {}).get('buy_and_hold_gross'))}. Folds {market.get('folds_on_prefix_signals')}.")
        lines.extend([
            "Development on both markets had a positive cost-adjusted point estimate and still failed the pre-registered uncertainty gate. The lower bound of the normal interval was below zero. That interval assumes independent trades; overlapping trends make it a screen, not a proof of skill either way.",
            "BTC validation, 18 trades, mean -0.00140 after costs. Blocked for sample. The point estimate is on the wrong side of the no-trade baseline and the window is too small to call that a measured failure of expectancy.",
            "ETH validation, 24 trades, mean +0.00687. Blocked for sample and for the second half count. The recorded drawdown on that window is about 0.312, above the 0.25 cap, but the frozen judge does not apply the drawdown cap until the sample gate is clear. The judgment is left as BLOCKED. The positive mean is not promoted.",
            "ETH prefix folds are not stable (the first fold mean is negative). BTC prefix folds are positive and still do not override the failed development uncertainty gate or the blocked validation window.",
            "Neither symbol beat the decision rule. The holdout that starts 2026-01-22 was not opened. The version is not approved for paper and it is not a live desk signal.",
            "",
            "## What this does not show",
            "",
            "It does not show that no slower rule could ever pass. It shows that this pre-registered follow-up did not. Another configuration would be a new version and would carry the same multiple-testing warning. It would still have to pass development, untouched validation, and only then the sealed holdout.",
            "Desk 1m, 3m, 15m and 1h research cannot be advanced from files in this checkout without a new retained download, and a download is not a reason to tune a rule that has already seen this 4h sample.",
            "",
        ])
    return "\n".join(lines) + "\n"


def write():
    text = render()
    path = DOCS / "STRATEGY_DIAGNOSIS.md"
    path.write_text(text, encoding="utf-8")
    return path
