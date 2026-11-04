"""Release-audit regressions. Market rows in this file are fixtures, not captured vendor history."""

from ops.bars import make_bar
from ops.desk_snapshot import assemble
from ops.feeds import aggregate_spot_samples, xaus_spot_bars
from ops.paperbook import load, open_order, plan_preview, save
from ops.profiles import PROFILES
from ops.test_paperbook import _account
from ops.users import update_profile


BTC_BUY = {"entry": 77644.43, "stop": 77485.77, "target": 77930.01}
ETH_BUY = {"entry": 2296.39, "stop": 2289.26, "target": 2309.23}
NOW = 1_700_003_600_000


def _prints(start_ms, count, price=2000.0):
    return [{"t": (start_ms + index * 300_000) // 1000, "p": price + index} for index in range(count)]


def _bucket(now_ms, interval_ms):
    return now_ms - (now_ms % interval_ms) - interval_ms


def test_fixture_fifteen_minute_samples_need_every_print():
    bucket = _bucket(NOW, 900_000)
    complete = _prints(bucket, 3)
    bars = aggregate_spot_samples(complete, "15m", NOW)
    assert len(bars) == 1
    assert bars[0]["open"] == 2000.0
    assert bars[0]["close"] == 2002.0
    assert bars[0]["high"] == 2002.0
    assert bars[0]["volume"] is None
    assert bars[0]["source_type"] == "spot_sample"
    assert bars[0]["quote_semantics"] == "spot_sample_not_bid_ask"
    reversed_points = list(reversed(complete))
    ordered = aggregate_spot_samples(reversed_points, "15m", NOW)
    assert ordered[0]["open"] == 2000.0
    assert ordered[0]["close"] == 2002.0
    assert aggregate_spot_samples(complete[:2], "15m", NOW) == []
    conflict = complete + [{"t": complete[1]["t"], "p": 9}]
    assert aggregate_spot_samples(conflict, "15m", NOW) == []
    duplicate = complete + [{"t": complete[1]["t"], "p": complete[1]["p"]}]
    assert len(aggregate_spot_samples(duplicate, "15m", NOW)) == 1
    assert xaus_spot_bars("1m", now_ms=NOW)["reason"] == "sample_is_5m"
    assert xaus_spot_bars("3m", now_ms=NOW)["bars"] == []


def test_fixture_hour_needs_twelve_samples_and_not_a_short_gap():
    bucket = _bucket(NOW, 3_600_000)
    assert aggregate_spot_samples(_prints(bucket, 11), "1h", NOW) == []
    bars = aggregate_spot_samples(_prints(bucket, 12), "1h", NOW)
    assert len(bars) == 1
    assert bars[0]["interval"] == "1h"
    assert bars[0]["volume"] is None
    assert bars[0]["open_time_ms"] == bucket
    gapped = _prints(bucket, 12)
    gapped[4]["t"] = gapped[4]["t"] + 120
    assert aggregate_spot_samples(gapped, "1h", NOW) == []


def test_a_quote_does_not_replace_the_completed_close_or_the_snapshot():
    bucket = _bucket(NOW, 900_000)
    bar = make_bar(
        symbol="XAUUSD", instrument="XAUUSD_SPOT", interval="15m",
        open_time_ms=bucket, close_time_ms=bucket + 899_999,
        open=2000, high=2004, low=1998, close=2001, volume=None,
        provider="xaus.com", source_type="spot_sample", quote_semantics="spot_sample_not_bid_ask",
        complete=True, fresh=True,
    )
    quote = {"ok": True, "bid": 2100, "ask": 2102, "timestamp_ms": NOW - 1000}
    snap = assemble("XAUUSD", "15m", NOW, bars=[bar], quote=quote, semantics="spot_sample_not_bid_ask")
    assert snap["display"]["close"] == 2001
    assert snap["display"]["price"] == 2001
    assert snap["display"]["quote"]["price"] == 2101
    assert snap["display"]["quote"]["timestamp_ms"] == NOW - 1000
    assert snap["display"]["quote"]["not_a_candle"] is True
    assert snap["display"]["candle_semantics"] == "spot_sample_not_bid_ask"
    assert "2101" not in snap["snapshot_id"]
    assert snap["candle"]["close"] == 2001


def test_health_names_its_own_completed_kline_and_not_the_desk_snapshot(monkeypatch):
    from ops.app import app
    called = {"market": 0}

    def snapshot():
        called["market"] += 1
        return {
            "BTCUSDT": {"close_time_ms": NOW - 1000, "checked_at_ms": NOW, "source": "binance-public"},
            "ETHUSDT": {"close_time_ms": NOW - 1000, "checked_at_ms": NOW, "source": "binance-public"},
        }

    monkeypatch.setattr("ops.app.market_snapshot", snapshot)
    body = app.test_client().get("/health").get_json()
    row = body["market_data"]["BTCUSDT"]
    assert body["status"] == "reading_unavailable"
    assert body["process"] == "ok"
    assert called["market"] == 0
    assert row["kind"] == "not_a_customer_reading"
    assert row["status"] == "not_shown"
    assert row["last_close_time_ms"] is None
    assert "fresh" not in row["note"]


def test_klines_and_the_snapshot_are_the_same_reading(monkeypatch):
    from ops.app import app
    def boom(*_args, **_kwargs):
        raise AssertionError("customer klines must not read an unverified candle")
    monkeypatch.setattr("ops.desk_snapshot.observe", boom)
    monkeypatch.setattr("ops.market.fetch_klines", boom)
    body = app.test_client().get("/api/klines?symbol=BTCUSDT&interval=15m").get_json()
    assert body["candles"] == []
    assert body["customer_status"] == "reading_unavailable"
    assert body["kind"] == "unavailable"
    assert "105" not in str(body)


def _reward(entry, stop, target):
    return abs(target - entry) / abs(entry - stop)


def _order(symbol, side, levels, stamp):
    entry = levels["entry"]
    risk = abs(entry - levels["stop"])
    reward = abs(levels["target"] - entry)
    if side == "SELL":
        stop = entry + risk
        target = entry - reward
    else:
        stop = levels["stop"]
        target = levels["target"]
    return {
        "opportunity_id": f"fixture:{symbol}:{side}:{stamp}",
        "symbol": symbol,
        "interval": "15m",
        "direction": side,
        "entry": entry,
        "stop": stop,
        "target": target,
        "lifecycle": "active",
        "family": "fixture-reading",
    }


def test_fixture_example_plans_clear_only_the_apex_floor():
    btc = _reward(**BTC_BUY)
    eth = _reward(**ETH_BUY)
    assert round(btc, 2) == 1.80
    assert round(eth, 2) == 1.80
    assert btc >= PROFILES["apex_momentum"]["min_rr"]
    assert eth >= PROFILES["apex_momentum"]["min_rr"]
    assert btc < PROFILES["orion_precision"]["min_rr"]
    assert eth < PROFILES["aegis_shield"]["min_rr"]


def test_confirm_uses_the_current_persona_floor_on_both_sides(tmp_path, monkeypatch):
    users, owner, other = _account(tmp_path, monkeypatch, style="apex_momentum", capital=10_000)
    user = users.get(owner["id"])
    user["id"] = owner["id"]
    checked = []
    for symbol, levels in (("BTCUSDT", BTC_BUY), ("ETHUSDT", ETH_BUY)):
        for side in ("BUY", "SELL"):
            row = _order(symbol, side, levels, 1_700_000_000_000)
            preview = plan_preview(user, row)
            assert preview["allowed"] is True, preview
            assert preview["order_opened"] is False
            assert preview["persona"] == "Apex Momentum"
            probed = open_order(user, row, 1_700_000_100_000, commit=False)
            assert probed["ok"] is True, (symbol, side, probed)
            checked.append(round(_reward(row["entry"], row["stop"], row["target"]), 2))
    assert checked == [1.80, 1.80, 1.80, 1.80]
    opened = open_order(user, _order("BTCUSDT", "BUY", BTC_BUY, 1_700_000_110_000), 1_700_000_110_000)
    assert opened["ok"] is True
    assert opened["order"]["executable"] is False
    assert opened["order"]["opened_by"] == "account"
    assert round(opened["order"]["reward_risk"], 2) == 1.80
    update_profile(owner["id"], {"signal_style": "orion_precision", "capital": 10_000, "currency": "USD"})
    orion = users.get(owner["id"])
    orion["id"] = owner["id"]
    blocked = open_order(orion, _order("BTCUSDT", "SELL", BTC_BUY, 1_700_000_500_000), 1_700_000_500_000)
    assert blocked["reason"] == "below_persona_reward"
    assert blocked["floor"] == 2.0
    update_profile(owner["id"], {"signal_style": "aegis_shield", "capital": 10_000, "currency": "USD"})
    aegis = users.get(owner["id"])
    aegis["id"] = owner["id"]
    shielded = open_order(aegis, _order("ETHUSDT", "BUY", ETH_BUY, 1_700_000_600_000), 1_700_000_600_000)
    assert shielded["reason"] == "below_persona_reward"
    assert shielded["floor"] == 2.5
    foreign = users.get(other["id"])
    foreign["id"] = other["id"]
    assert load(other["id"])["orders"] == []
    assert open_order(foreign, _order("BTCUSDT", "BUY", BTC_BUY, 1_700_000_700_000), 1_700_000_700_000)["ok"] is True
    assert len(load(owner["id"])["orders"]) == 1


def test_confirm_repeats_account_limits_and_refuses_gold_sizing(tmp_path, monkeypatch):
    users, owner, _other = _account(tmp_path, monkeypatch, style="orion_precision", capital=10_000)
    user = users.get(owner["id"])
    user["id"] = owner["id"]
    strong = {"entry": 100.0, "stop": 99.0, "target": 102.5}
    assert _reward(**strong) == 2.5
    minute = _order("BTCUSDT", "BUY", strong, 1_700_000_800_000)
    minute["interval"] = "1m"
    from ops.users import save_inbox_delivery
    save_inbox_delivery(owner["id"], {"experimental": True, "markets": ["BTCUSDT", "ETHUSDT", "XAUUSD"], "timeframes": ["1m", "15m", "1h"], "buy": True, "sell": True})
    user = users.get(owner["id"])
    user["id"] = owner["id"]
    assert open_order(user, minute, 1_700_000_800_000)["reason"] == "persona_timeframe"
    gold = _order("XAUUSD", "BUY", strong, 1_700_000_900_000)
    gold["symbol"] = "XAUUSD"
    assert open_order(user, gold, 1_700_000_900_000)["reason"] == "contract_unverified"
    first = _order("BTCUSDT", "BUY", strong, 1_700_001_000_000)
    assert open_order(user, first, 1_700_001_000_000)["ok"] is True
    book = load(owner["id"])
    book["orders"].append({
        "id": "fixture-loss",
        "status": "closed",
        "pnl_usd": -300,
        "closed_ms": 1_700_001_100_000,
        "opened_ms": 1_700_001_000_000,
        "week": "2023-W46",
        "opportunity_id": "fixture-loss",
    })
    save(owner["id"], book)
    daily = open_order(user, _order("ETHUSDT", "SELL", strong, 1_700_001_200_000), 1_700_001_100_000)
    assert daily["reason"] == "daily_loss"
    save_inbox_delivery(owner["id"], {"experimental": True, "markets": ["ETHUSDT"], "timeframes": ["15m"], "buy": False, "sell": True})
    user = users.get(owner["id"])
    user["id"] = owner["id"]
    assert open_order(user, _order("BTCUSDT", "BUY", strong, 1_700_001_300_000), 1_700_001_300_000)["reason"] == "market"
    assert open_order(user, _order("ETHUSDT", "BUY", strong, 1_700_001_400_000), 1_700_001_400_000)["reason"] == "buy_off"
