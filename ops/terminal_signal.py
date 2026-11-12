"""One requested evaluation. Five facts stay separate.

Data validity, the technical match, the trade plan, research validation,
and inbox eligibility are not one score. A failed research rule can still
show a calculated long plan. That plan stays unapproved. A spot desk does
not open shorts. A persona changes the reward floor and the size, not the
candle and not the approval.
"""

import json
import os
import time
from pathlib import Path

from ops.bars import interval_ms
from ops.hypotheses import _atr
from ops.daily_rules import RULES as DAILY_RULES
from ops.gold_live import completed_bid_ask_bar, snapshot_reason
from ops.leaders import COMPRESS, CRYPTO_RULES, GOLD_RULES, LONDON, SWEEP
from ops.plan import propose_size
from ops.profiles import risk_cap
from ops.registry import BY_ID
from ops.interval_reading import read_interval, read_spot_sample

AUTO = {
    "BTCUSDT": COMPRESS,
    "ETHUSDT": SWEEP,
    "XAUUSD": LONDON,
}
RULES = {**CRYPTO_RULES, **GOLD_RULES, **DAILY_RULES}
CRYPTO_COST_BPS = 11
DECISIONS = Path(__file__).resolve().parents[1] / "docs" / "MARKET_DECISIONS.json"


def auto_strategy(symbol):
    if DECISIONS.exists():
        try:
            row = json.loads(DECISIONS.read_text(encoding="utf-8"))["markets"][symbol]
        except (KeyError, json.JSONDecodeError, OSError):
            row = None
        if row and row.get("strategy"):
            return row["strategy"]
    return AUTO.get(symbol)


def _path(user_id):
    text = str(user_id or "")
    if not text or "/" in text or ".." in text:
        return None
    root = Path(os.environ.get("AUREON_DATA", "data"))
    return root / "users" / text / "terminal.jsonl"


def read_history(user_id):
    path = _path(user_id)
    if path is None or not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def open_idea(user_id, symbol, strategy):
    latest = None
    for row in read_history(user_id):
        if row.get("symbol") == symbol and row.get("strategy") == strategy and row.get("decision") in {"BUY", "SELL"}:
            latest = row
    if latest and latest.get("decision") == "BUY":
        return latest
    return None


def save_result(user_id, result):
    path = _path(user_id)
    if path is None:
        return {"ok": False, "reason": "bad_user", "stored": False}
    event_id = result.get("id")
    rows = read_history(user_id)
    if any(row.get("id") == event_id for row in rows):
        return {"ok": True, "duplicate": True, "stored": False}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(result) + "\n")
    return {"ok": True, "duplicate": False, "stored": True}


def _checks(strategy, bars, index):
    close = bars[index]["close"]
    if strategy == COMPRESS and index >= 42:
        quiet = _atr(bars, index - 1, 10)
        slow = _atr(bars, index - 1, 40)
        ceiling = max(bar["high"] for bar in bars[index - 10 : index])
        failed = []
        if quiet is None or slow is None or slow <= 0 or quiet >= 0.6 * slow:
            failed.append("The short ATR is not below 60 percent of the 40-bar ATR.")
        if close <= ceiling:
            failed.append("The close has not broken the prior ten-bar high.")
        return {"close": close, "quiet_atr": quiet, "slow_atr": slow, "prior_ten_high": ceiling, "failed": failed}
    if strategy == SWEEP and index >= 7:
        prior = bars[index - 6 : index]
        prior_low = min(bar["low"] for bar in prior)
        prior_high = max(bar["high"] for bar in prior)
        failed = []
        if not (bars[index]["low"] < prior_low and close > prior_low):
            failed.append("Price did not pierce the prior six-bar low and close back above it.")
        return {"close": close, "prior_low": prior_low, "prior_high": prior_high, "failed": failed}
    if strategy == LONDON and index >= 5:
        failed = ["The London reclaim conditions were not all true on this completed hour."]
        return {"close": close, "failed": failed}
    return {"close": close, "failed": ["There are not enough completed bars for this rule."]}


def _levels(setup, price):
    if setup.get("target_mode") == "atr":
        stop = price - setup["stop_multiple"] * setup["atr"]
        target = price + setup["target_multiple"] * setup["atr"]
    else:
        stop = setup.get("stop_price")
        target = setup.get("target_price")
    reward = None if stop is None or target is None or price <= stop else (target - price) / (price - stop)
    return stop, target, reward


def _finish_gold(reading, base, live_quote, preface):
    """0.08 percent applies only when a real bid and ask are present.

    A missing quote is not treated as agreement, and it is not a reason to erase the candle plan.
    """
    note = preface
    quote_ok = bool(
        live_quote
        and live_quote.get("ok")
        and live_quote.get("bid") is not None
        and live_quote.get("ask") is not None
    )
    reading["quote_threshold"] = 0.0008
    reading["compared_bar_close_ms"] = base.get("bar_close_ms")
    if quote_ok:
        mid = (float(live_quote["bid"]) + float(live_quote["ask"])) / 2
        close = float(base.get("reference_price") or 0)
        gap = abs(close - mid) / mid if mid else 0
        reading["quote_alignment"] = "diverged" if gap > 0.0008 else "aligned"
        reading["quote_gap"] = gap
        note += f" A separate quote is bid {live_quote.get('bid')} ask {live_quote.get('ask')}."
        if reading["quote_alignment"] == "diverged":
            note += f" They differ by {gap * 100:.2f} percent, above the 0.08 percent limit, so they are not treated as one price."
        else:
            note += f" They differ by {gap * 100:.2f} percent, inside the 0.08 percent spot tolerance."
        reading["quote_time_ms"] = live_quote.get("timestamp_ms")
        if reading.get("quote_alignment") == "diverged":
            sample_at = base.get("bar_close_ms")
            quote_at = live_quote.get("timestamp_ms")
            note += f" Spot sample close time {sample_at}. Separate quote time {quote_at}. The comparison limit stays 0.08 percent."
    else:
        reading["quote_alignment"] = None
        reading["quote_gap"] = None
        note += " No bid/ask is configured, so this plan uses the completed candle only. It is not a broker fill."
    reading["reason"] = note + " " + (reading.get("reason") or "")
    reading["live_quote"] = live_quote
    if reading.get("quote_alignment") == "diverged" and reading.get("decision") in {"BUY", "SELL"}:
        reading["research_levels"] = {
            "entry": reading.get("entry"),
            "stop": reading.get("stop"),
            "target": reading.get("target"),
            "reward_risk": reading.get("reward_risk"),
            "watch_entry": reading.get("watch_entry"),
            "watch_stop": reading.get("watch_stop"),
            "watch_target": reading.get("watch_target"),
            "side": reading.get("decision"),
            "audit_only": True,
        }
        reading["technical_side"] = reading["decision"]
        reading["decision"] = "WAIT"
        if reading.get("runtime_status") != "reference_quote_unavailable":
            reading["runtime_status"] = "quote_divergence"
        reading["entry"] = None
        reading["stop"] = None
        reading["target"] = None
        reading["reward_risk"] = None
        reading["watch_entry"] = None
        reading["watch_stop"] = None
        reading["watch_target"] = None
        reading["eligible_for_alert"] = False
        reading["size"] = {"ok": False, "reason": "quote_divergence", "order": False, "quantity_orderable": False, "budget_ok": False}
        reading["reason"] += " The prices disagree, so this technical idea is not an actionable entry and is not sent as a trade. Entry, stop and target are withheld."
    elif reading.get("quote_alignment") == "diverged":
        reading["runtime_status"] = "quote_divergence"
    return reading


def explain_reading(result, user=None):
    """One explanation from the stored reading. A model is not required and cannot replace these numbers."""
    result = result or {}
    profile = ((user or {}).get("profile") or {}) if isinstance(user, dict) else {}
    name = result.get("persona_name") or profile.get("signal_style_name") or "This account"
    decision = result.get("decision") or "WAIT"
    symbol = result.get("symbol") or "the market"
    interval = result.get("interval") or "the requested candle"

    def price(value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return f"{float(value):.2f}"

    entry, stop, target = price(result.get("entry")), price(result.get("stop")), price(result.get("target"))
    lines = [f"{decision} {symbol} {interval}."]
    if entry and stop and target:
        lines.append(f"Entry {entry}. Stop {stop}. Target {target}.")
    else:
        lines.append("No entry, stop and target were calculated on this candle.")
    reward = result.get("reward_risk")
    if isinstance(reward, (int, float)) and not isinstance(reward, bool):
        lines.append(f"Reward to risk on the market plan is {float(reward):.2f}.")
    if symbol == "XAUUSD":
        lines.append("Gold is the completed public chart candle. It is not a bid, an ask, or a broker fill.")
    else:
        lines.append("This is the completed public candle. It is not a broker fill.")
    if result.get("feed_state") == "last_good":
        lines.append("The latest pull failed, so this is the last completed candle still on file. No price was invented.")
    note = result.get("persona_note")
    if isinstance(note, str) and note.strip():
        lines.append(note.strip())
    else:
        lines.append(f"{name} can read this. It is not an approved strategy, and the model did not create the levels.")
    return " ".join(lines)


def decide(symbol, interval, strategy, bars, now_ms, user, prior=None, live_quote=None):
    explicit = strategy not in {None, "", "auto"}
    result = apply_auto_policy(_evaluate(symbol, interval, strategy, bars, now_ms, user, prior, live_quote), explicit)
    result = apply_persona(result, user)
    from ops.plan import present_size
    result["size_presentation"] = present_size(result.get("size"))
    from ops.paperbook import paper_permission
    result["paper"] = paper_permission(user if isinstance(user, dict) and user.get("id") else {"id": None, "profile": (user or {}).get("profile") if isinstance(user, dict) else {}, "plan": (user or {}).get("plan") if isinstance(user, dict) else {}, "inbox_delivery": (user or {}).get("inbox_delivery") if isinstance(user, dict) else {}}, result)
    if result.get("runtime_status") == "experimental" and result.get("decision") == "BUY" and not result.get("blocked"):
        result["decision_label"] = "BUY · Experimental"
    elif result.get("runtime_status") == "experimental" and result.get("sell_meaning") == "short_idea" and not result.get("blocked"):
        result["decision_label"] = "SELL · Short idea"
    elif result.get("runtime_status") == "quote_divergence" and not result.get("blocked"):
        result["decision_label"] = "QUOTE DIVERGENCE"
    elif result.get("runtime_status") == "reference_quote_unavailable" and not result.get("blocked"):
        result["decision_label"] = "WAIT"
    elif result.get("runtime_status") == "watch" and not result.get("blocked"):
        result["decision_label"] = "WATCH"
    return result


def _evaluate(symbol, interval, strategy, bars, now_ms, user, prior=None, live_quote=None):
    chosen = auto_strategy(symbol) if strategy in {None, "", "auto"} else strategy
    spec = BY_ID.get(chosen) or {}
    base = {
        "symbol": symbol,
        "interval": interval,
        "strategy": chosen,
        "version": spec.get("version") or chosen,
        "validation_status": spec.get("research_status") or "unknown",
        "approved": False,
        "source": "user_requested",
        "delivered": False,
        "filled": False,
        "pnl": None,
        "order": False,
        "evaluated_ms": int(now_ms),
    }
    if symbol not in AUTO:
        return {**base, "decision": "WAIT", "reason": "This market is not supported.", "fresh": False, "reference_price": None}
    if chosen not in RULES or symbol not in (spec.get("instruments") or []):
        return {**base, "decision": "WAIT", "reason": "That strategy is not eligible for this market.", "fresh": False, "reference_price": None}
    if not bars:
        if symbol == "XAUUSD" and live_quote and live_quote.get("ok"):
            return {
                **base,
                "decision": "WAIT",
                "reason": snapshot_reason(live_quote),
                "fresh": False,
                "reference_price": None,
                "blocked": "snapshot_not_candle",
                "source_name": live_quote.get("provider"),
                "quote": "bid_ask_snapshot",
                "live_quote": live_quote,
            }
        return {**base, "decision": "WAIT", "reason": "No completed candle was returned.", "fresh": False, "reference_price": None, "blocked": "missing_feed"}
    last = bars[-1]
    if last.get("high") is None or last.get("low") is None or last.get("close") is None:
        return {**base, "decision": "WAIT", "reason": "The candle is missing a high, low or close, so no plan was calculated.", "blocked": "incomplete_candle", "fresh": False, "reference_price": None}
    price = last.get("close")
    fresh = bool(last.get("complete") and last.get("close_time_ms", 0) <= now_ms and now_ms - last["close_time_ms"] <= 2 * interval_ms(interval))
    base.update({
        "reference_price": price,
        "bar_close_ms": last.get("close_time_ms"),
        "bar_open_ms": last.get("open_time_ms"),
        "source_name": last.get("provider"),
        "quote": last.get("quote_semantics"),
        "fresh": fresh,
    })
    provider_source = {
        "binance-public": "binance_spot_rest_klines",
        "binance": "binance_spot_rest_klines",
        "xaus.com": "xaus_public_chart",
        "swissquote-public-bbo": "swissquote_public_bbo",
    }
    if last.get("quote_semantics") == "spot_sample_not_bid_ask":
        base["source_id"] = "xaus_spot_samples"
    elif last.get("provider") in provider_source:
        base["source_id"] = provider_source[last.get("provider")]
    if not fresh:
        age = now_ms - int(last.get("close_time_ms") or 0)
        gold_late = (
            symbol == "XAUUSD"
            and last.get("quote_semantics") == "ohlc_not_bid_ask"
            and last.get("complete")
            and 0 < age <= 15 * 60 * 1000
            and strategy in {None, "", "auto"}
        )
        if gold_late:
            base["reason_prefix"] = f"The last {interval} gold candle closed {max(1, round(age / 60000))} minutes ago. AutoPilot will not open a late candle. "
        else:
            if symbol == "XAUUSD":
                base["strategy"] = "gold-ohlc-reading"
                base["version"] = "gold-ohlc-reading"
            return {**base, "decision": "WAIT", "reason": "The latest candle is missing, still forming, or too old to treat as live.", "blocked": "stale_or_incomplete"}
    if symbol == "XAUUSD" and not completed_bid_ask_bar(last):
        quote = last.get("quote_semantics") or "missing_bid_ask"
        if strategy in {None, "", "auto"} and quote == "spot_sample_not_bid_ask" and len(bars) < 24:
            return {
                **base,
                "decision": "WAIT",
                "reason": f"Only {len(bars)} completed {interval} spot-sample bars were built. 24 are required. A finer candle was not invented.",
                "blocked": "insufficient_spot_samples",
                "live_quote": live_quote,
            }
        if strategy in {None, "", "auto"} and quote == "spot_sample_not_bid_ask" and len(bars) >= 24:
            reading = _requested_reading(base, symbol, interval, bars, user, read_spot_sample)
            reading["gold_basis"] = "spot_sample"
            reading["strategy"] = "gold-spot-sample"
            reading["version"] = "gold-spot-sample"
            reading = _finish_gold(reading, base, live_quote, f"First-party spot samples aggregated to this {interval}. Not the Yahoo chart and not a bid/ask hour. The London rule was not calculated.")
            return reading
        if strategy in {None, "", "auto"} and quote == "ohlc_not_bid_ask" and len(bars) >= 50:
            reading = _requested_reading(base, symbol, interval, bars, user)
            reading["gold_basis"] = "spot_ohlc"
            reading["strategy"] = "gold-ohlc-reading"
            reading["version"] = "gold-ohlc-reading"
            note = (base.get("reason_prefix") or "") + "Public chart candles, not a bid/ask. The London rule was not calculated."
            reading = _finish_gold(reading, base, live_quote, note)
            return reading
        extra = ""
        if live_quote and live_quote.get("ok"):
            extra = " " + snapshot_reason(live_quote)
        return {**base, "decision": "WAIT", "reason": f"Gold is blocked. The candle feed is {quote}, not verified bid/ask, so the London rule was not calculated." + extra, "blocked": "quote_not_bid_ask", "live_quote": live_quote}
    if interval != spec.get("timeframe"):
        if strategy in {None, "", "auto"} and symbol in {"BTCUSDT", "ETHUSDT"}:
            return _requested_reading(base, symbol, interval, bars, user)
        return {**base, "decision": "WAIT", "reason": f"This rule is defined on {spec.get('timeframe')} candles. {interval} was not substituted.", "blocked": "timeframe"}
    if prior and prior.get("decision") == "BUY":
        stop = prior.get("stop")
        target = prior.get("target")
        if stop is not None and price <= stop:
            return {**base, "decision": "SELL", "reason": "The last close is at or below the recorded stop. This means exit the recorded research long. It is not a spot short, and no holding was invented.", "sell_meaning": "exit_recorded_long", "stop": stop, "target": target}
        if target is not None and price >= target:
            return {**base, "decision": "SELL", "reason": "The last close reached the recorded target. This is an exit of the recorded idea, not a filled trade.", "sell_meaning": "exit_recorded_long", "stop": stop, "target": target}
        elapsed = sum(1 for bar in bars if bar["open_time_ms"] > prior.get("bar_open_ms", 0))
        if elapsed > prior.get("hold_bars", 10**9):
            return {**base, "decision": "SELL", "reason": "The rule's holding window has passed. Exit the recorded research long. No short was opened.", "sell_meaning": "exit_recorded_long", "stop": stop, "target": target}
        return {**base, "decision": "WAIT", "reason": "A recorded research long is still open. Its stop, target and holding window have not been reached. This is not a new buy and not a spot short.", "stop": stop, "target": target}
    setup = RULES[chosen](bars, len(bars) - 1, [], symbol)
    checks = _checks(chosen, bars, len(bars) - 1)
    if not setup:
        return {**base, "decision": "WAIT", "reason": " ".join(checks.get("failed") or ["The entry conditions are not true."]), "checks": checks}
    stop, target, reward = _levels(setup, price)
    profile = (user or {}).get("profile") or {}
    cap = risk_cap(profile.get("signal_style"))
    plan = (user or {}).get("plan") or {}
    risk = plan.get("risk_per_trade_percent")
    if risk is None:
        risk = cap
    size = {"ok": False, "reason": "missing_inputs", "order": False}
    if stop is None or stop >= price:
        size = {"ok": False, "reason": "invalid_stop", "order": False}
    elif profile.get("capital") and risk:
        size = propose_size(profile["capital"], risk, price, stop)
    costs = {"bps_per_fill": CRYPTO_COST_BPS, "fills": 2, "round_turn_bps": CRYPTO_COST_BPS * 2, "observed": False, "note": "Estimated from the research cost. Not a measured spread."} if symbol != "XAUUSD" else {"observed": False, "note": "A live gold spread was not available."}
    return {
        **base,
        "decision": "BUY",
        "reason": "The long-entry conditions are true on this completed candle. The frozen rule would enter the next candle's open. The levels below use the last close as a planning price, not a fill.",
        "direction": "LONG",
        "entry": price,
        "entry_note": "Planning price only. Not an order.",
        "stop": stop,
        "target": target,
        "reward_risk": reward,
        "hold_bars": setup.get("hold_bars"),
        "checks": checks,
        "invalidation": spec.get("invalidation"),
        "size": size,
        "costs": costs,
        "currency": profile.get("currency"),
    }


def _requested_reading(base, symbol, interval, bars, user, reader=None):
    reading = (reader or read_interval)(interval, bars)
    result = {
        **base,
        "strategy": "interval-reading",
        "version": "interval-reading",
        "validation_status": "FAIL",
        "reading": True,
        "decision": reading["decision"],
        "reason": reading["reason"],
        "entry": reading["entry"],
        "stop": reading["stop"],
        "target": reading["target"],
        "reward_risk": reading["reward_risk"],
        "rule": reading.get("rule"),
        "watch_entry": reading.get("watch_entry"),
        "watch_stop": reading.get("watch_stop"),
        "watch_target": reading.get("watch_target"),
        "runtime_status": reading.get("runtime_status"),
        "sell_meaning": reading.get("sell_meaning"),
        "hold_bars": 6,
        "invalidation": "The stop on this reading. A failed research rule was not relabeled as approved.",
    }
    if reading["decision"] not in {"BUY", "SELL"}:
        result["size"] = {"ok": False, "reason": "no_setup", "order": False}
        return result
    result["runtime_status"] = "experimental"
    result["direction"] = "LONG" if reading["decision"] == "BUY" else "SHORT_IDEA"
    result["sell_meaning"] = None if reading["decision"] == "BUY" else "short_idea"
    profile = (user or {}).get("profile") or {}
    cap = risk_cap(profile.get("signal_style"))
    plan = (user or {}).get("plan") or {}
    risk = plan.get("risk_per_trade_percent")
    if risk is None:
        risk = cap
    if profile.get("capital") and risk:
        result["size"] = propose_size(profile["capital"], risk, reading["entry"], reading["stop"])
    else:
        result["size"] = {"ok": False, "reason": "missing_inputs", "order": False}
    if result["size"].get("ok"):
        result["size"]["risk_budget"] = result["size"].get("risk_amount")
    result["currency"] = profile.get("currency")
    result["costs"] = {
        "bps_per_fill": CRYPTO_COST_BPS,
        "fills": 2,
        "round_turn_bps": CRYPTO_COST_BPS * 2,
        "observed": False,
        "note": "Estimated from the research cost. Not a measured spread.",
    }
    result["entry_note"] = "Planning price only. Not an order."
    return result


def apply_persona(result, user):
    """The reward floor applies to a buy and a sell. It does not delete the plan.

    Family counts are not used. The three setup families are different ideas,
    not independent votes, and no study has shown that requiring two or three
    of them is a valid confirmation.
    """
    from ops.plan import paper_cap_status, qualify_size
    from ops.profiles import canonical_style, get_profile

    result = dict(result)
    style = canonical_style(((user or {}).get("profile") or {}).get("signal_style"))
    spec = get_profile(style)
    if not spec:
        result["persona_release"] = False
        result["persona_note"] = "No persona is selected, so this account is not sized."
        result["account_status"] = "visible_unsized"
        return result
    result["persona"] = style
    result["persona_name"] = spec["name"]
    result["persona_min_rr"] = spec["min_rr"]
    result["persona_risk_cap"] = spec["risk_per_trade_percent"]
    result["persona_policy"] = {
        "entry_rule": "shared",
        "experimental": True,
        "min_rr": spec["min_rr"],
        "risk_cap": spec["risk_per_trade_percent"],
        "paper_timeframes": list(spec.get("paper_timeframes") or []),
        "note": "This persona does not use a different entry rule. It changes the reward floor, the risk cap and which timeframes may be opened as paper.",
    }
    result["paper_cap"] = paper_cap_status(spec.get("max_trades_per_day"), (user or {}).get("paper_orders_today"))
    decision = result.get("decision")
    if result.get("blocked"):
        result["persona_release"] = False
        result["account_status"] = "not_a_plan"
        result["persona_note"] = f"{spec['name']} does not size a blocked reading. No paper order is opened."
        return result
    if decision not in {"BUY", "SELL"} or result.get("reward_risk") is None:
        result["persona_release"] = False
        result["account_status"] = "not_a_plan"
        result["persona_note"] = f"{spec['name']} does not size this, because the result is {decision or 'empty'}, not a buy or a sell."
        return result
    reward = float(result["reward_risk"])
    floor = float(spec["min_rr"])
    if reward + 1e-9 < floor:
        result["persona_release"] = False
        result["account_status"] = "visible_unsized"
        result["size"] = {"ok": False, "reason": "below_persona_reward", "order": False, "quantity_orderable": False, "budget_ok": False}
        result["persona_note"] = (
            f"{spec['name']} does not size this {decision}. Reward/risk {reward:.2f} is below its floor of {floor}. "
            "The levels stay visible. No extra confirmation gate was applied."
        )
        entry = result.get("entry")
        stop = result.get("stop")
        if isinstance(entry, (int, float)) and isinstance(stop, (int, float)) and entry != stop:
            risk = abs(float(entry) - float(stop))
            result["account_target"] = float(entry) - floor * risk if decision == "SELL" else float(entry) + floor * risk
            result["persona_note"] += f" Meeting the {floor} floor would place the target near {result['account_target']:.2f}. The market plan was not rewritten."
        result["reason"] = f"{result.get('reason') or ''} {result['persona_note']}".strip()
        return result
    profile = (user or {}).get("profile") or {}
    plan = (user or {}).get("plan") or {}
    risk = plan.get("risk_per_trade_percent")
    if risk is None:
        risk = spec["risk_per_trade_percent"]
    risk = min(float(risk), float(spec["risk_per_trade_percent"]))
    sized = qualify_size(result.get("symbol"), profile.get("capital"), risk, profile.get("currency"), result.get("entry"), result.get("stop"))
    result["size"] = sized
    result["persona_release"] = bool(sized.get("budget_ok"))
    result["account_status"] = "budget_shown" if sized.get("budget_ok") else "visible_unsized"
    result["persona_note"] = (
        f"{spec['name']} allows up to {spec['risk_per_trade_percent']}% . {sized.get('note') or sized.get('reason')} "
        "The daily cap counts recorded paper orders, not this notification."
    )
    allowed = spec.get("paper_timeframes") or []
    if result.get("interval") and allowed and result.get("interval") not in allowed:
        result["persona_release"] = False
        result["account_status"] = "visible_unsized"
        result["persona_note"] += f" {spec['name']} does not open a paper order on {result.get('interval')}. The plan stays visible."
    return result


def apply_auto_policy(result, explicit):
    """Auto may name a frozen rule. It may not promote a failed or blocked one."""
    result = dict(result)
    result["eligible_for_alert"] = False
    result["approved"] = False
    result["selection_policy"] = "explicit_named_rule" if explicit else "approved_only"
    result["evidence_semantics"] = "A checklist is not a probability of profit. No strategy is approved."
    if result.get("reading"):
        result["auto_selected"] = False
        result["selection_policy"] = "requested_interval_reading"
    status = result.get("validation_status") or "unknown"
    if not result.get("reading") and not explicit and result.get("decision") == "BUY" and status != "PASS":
        result["runtime_status"] = "experimental"
        result["experimental_match"] = {
            "decision": "BUY",
            "label": "experimental_rule_match",
            "reason": result.get("reason"),
            "entry": result.get("entry"),
            "stop": result.get("stop"),
            "target": result.get("target"),
            "reward_risk": result.get("reward_risk"),
            "size": result.get("size"),
            "approved": False,
        }
        result["reason"] = (
            f"Experimental match on {result.get('strategy')}. Research status is {status}, so this is not an approved trade and not a claim of profit. "
            f"{result['experimental_match']['reason']}"
        )
        result["auto_selected"] = False
        result["selection_policy"] = "experimental_visible"
    else:
        result["auto_selected"] = bool(explicit is False and status == "PASS" and result.get("decision") == "BUY")
    result["decision_label"] = "BLOCKED" if result.get("blocked") else result.get("decision")
    if result.get("runtime_status") == "watch" and not result.get("blocked"):
        result["decision_label"] = "WATCH"
    if result.get("runtime_status") == "quote_divergence" and not result.get("blocked"):
        result["decision_label"] = "QUOTE DIVERGENCE"
    return result


def stamp(user_id, result):
    result = dict(result)
    result["user_id"] = user_id
    result["id"] = ":".join(str(result.get(key)) for key in ("symbol", "interval", "strategy", "bar_close_ms", "decision"))
    result["requested_ms"] = int(time.time() * 1000)
    from ops.entitlements import is_feed_derived, retention_granted, scrub_levels

    derived = is_feed_derived(result) and not retention_granted(result)
    stored = scrub_levels(result) if derived else dict(result)
    stored["id"] = result["id"]
    stored["user_id"] = result["user_id"]
    stored["requested_ms"] = result["requested_ms"]
    saved = save_result(user_id, stored)
    result["duplicate"] = saved.get("duplicate", False)
    result["levels_persisted"] = False if derived else True
    return result


def attach_request(body, result):
    """Echo the request. A different instrument is rejected instead of shown."""
    body = body or {}
    requested_symbol = body.get("symbol") or "BTCUSDT"
    requested_interval = body.get("interval") or "4h"
    requested_strategy = body.get("strategy") if body.get("strategy") not in {None, ""} else "auto"
    request_id = str(body.get("request_id") or "")
    result = dict(result or {})
    result["requested_symbol"] = requested_symbol
    result["requested_interval"] = requested_interval
    result["requested_strategy"] = requested_strategy
    result["request_id"] = request_id
    if result.get("symbol") != requested_symbol or str(result.get("interval") or "") != str(requested_interval):
        return {
            "decision": "WAIT",
            "reason": "The result did not match the requested market and was rejected.",
            "symbol": requested_symbol,
            "interval": requested_interval,
            "strategy": requested_strategy,
            "requested_symbol": requested_symbol,
            "requested_interval": requested_interval,
            "requested_strategy": requested_strategy,
            "request_id": request_id,
            "approved": False,
            "rejected": "market_mismatch",
            "fresh": False,
            "reference_price": None,
            "delivered": False,
            "filled": False,
            "order": False,
            "blocked": "market_mismatch",
            "validation_status": "unknown",
        }
    return result


def response_matches(requested, payload):
    """True only when this payload is the result for this exact request."""
    payload = payload or {}
    requested = requested or {}
    if payload.get("rejected") == "market_mismatch":
        return False
    if payload.get("symbol") != requested.get("symbol"):
        return False
    if str(payload.get("interval") or "") != str(requested.get("interval") or ""):
        return False
    wanted = str(requested.get("request_id") or "")
    if wanted and payload.get("request_id") != wanted:
        return False
    return True
