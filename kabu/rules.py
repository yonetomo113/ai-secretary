"""
逆張り8ルール判定モジュール

戻り値の判定フラグ:
  BUY      : 買い候補
  SELL     : 売り候補（空売り含む）
  WATCH    : 静観
  WAIT     : ブレイク待ち / 見送り
  NONE     : 該当なし
"""

import pandas as pd
import ta
from config import ATR_PERIOD, RSI_PERIOD, BB_PERIOD, BB_STD, HIGH_LOOKBACK, RANGE_LOOKBACK, THRESHOLD

FLAG_BUY = "BUY"
FLAG_SELL = "SELL"
FLAG_WATCH = "WATCH"
FLAG_WAIT = "WAIT"
FLAG_NONE = "NONE"


def _add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """テクニカル指標を一括付与して返す"""
    df = df.copy()

    # ATR
    df["atr"] = ta.volatility.AverageTrueRange(
        df["High"], df["Low"], df["Close"], window=ATR_PERIOD
    ).average_true_range()

    # RSI
    df["rsi"] = ta.momentum.RSIIndicator(
        df["Close"], window=RSI_PERIOD
    ).rsi()

    # Bollinger Bands
    bb = ta.volatility.BollingerBands(
        df["Close"], window=BB_PERIOD, window_dev=BB_STD
    )
    df["bb_upper"] = bb.bollinger_hband()
    df["bb_lower"] = bb.bollinger_lband()

    # 終値ベースの前日比変化率（ルール4/5用）
    df["pct_change"] = df["Close"].pct_change() * 100

    # 始値 vs 前日終値の変化率（ルール1/2用）
    df["open_change"] = (df["Open"] - df["Close"].shift(1)) / df["Close"].shift(1) * 100

    return df


def evaluate_rules(df: pd.DataFrame, symbol: str = "") -> list[dict]:
    """
    直近データを基に8ルールを評価し、トリガーしたルールのリストを返す。
    各要素: {"rule": int, "flag": str, "reason": str}
    symbol: THRESHOLD辞書のキー（銘柄コード）
    """
    if len(df) < max(ATR_PERIOD, BB_PERIOD) + 2:
        return [{"rule": 0, "flag": FLAG_WATCH, "reason": "データ不足"}]

    df = _add_indicators(df)
    latest = df.iloc[-1]
    results = []

    # 銘柄別しきい値（未登録の場合は2.0をデフォルト）
    threshold = THRESHOLD.get(symbol, 2.0)

    # ---- ルール1: 始値が前日終値比 -THRESHOLD%以下 → 買い候補 -------------
    if pd.notna(latest["open_change"]) and latest["open_change"] <= -threshold:
        results.append({
            "rule": 1,
            "flag": FLAG_BUY,
            "reason": f"始値が前日終値比{latest['open_change']:.1f}%（しきい値-{threshold}%以下）",
        })

    # ---- ルール2: 始値が前日終値比 +THRESHOLD%以上 → 売り候補 -------------
    if pd.notna(latest["open_change"]) and latest["open_change"] >= threshold:
        results.append({
            "rule": 2,
            "flag": FLAG_SELL,
            "reason": f"始値が前日終値比+{latest['open_change']:.1f}%（しきい値+{threshold}%以上）",
        })

    # ---- ルール3: ATRが直近平均の50%未満 → 静観 ---------------------------
    recent_atr_mean = df["atr"].iloc[-ATR_PERIOD:].mean()
    if pd.notna(latest["atr"]) and pd.notna(recent_atr_mean) and recent_atr_mean > 0:
        atr_ratio = latest["atr"] / recent_atr_mean
        if atr_ratio < 0.5:
            results.append({
                "rule": 3,
                "flag": FLAG_WATCH,
                "reason": f"ATR={latest['atr']:.1f}（直近平均の{atr_ratio*100:.0f}%、ボラ低下）",
            })

    # ---- ルール4: 高値更新中かつ押し目なし → 買い見送り -------------------
    lookback_high = df["High"].iloc[-HIGH_LOOKBACK:].max()
    is_at_high = latest["Close"] >= lookback_high * 0.98
    # 押し目なし = 直近5日で1度も前日比マイナスがない
    no_pullback = all(df["pct_change"].iloc[-5:] >= 0)
    if is_at_high and no_pullback:
        results.append({
            "rule": 4,
            "flag": FLAG_WAIT,
            "reason": f"{HIGH_LOOKBACK}日高値更新中かつ直近5日に押し目なし",
        })

    # ---- ルール5: 日足陰線/陽線 → 買い優先 / 売り優先 ---------------------
    body = latest["Close"] - latest["Open"]
    if body < 0:
        results.append({
            "rule": 5,
            "flag": FLAG_BUY,
            "reason": f"陰線（始値{latest['Open']:.0f}→終値{latest['Close']:.0f}）",
        })
    elif body > 0:
        results.append({
            "rule": 5,
            "flag": FLAG_SELL,
            "reason": f"陽線（始値{latest['Open']:.0f}→終値{latest['Close']:.0f}）",
        })

    # ---- ルール6: レンジ幅3%未満の持ち合い → ブレイク待ち -----------------
    recent = df.iloc[-RANGE_LOOKBACK:]
    price_range_pct = (recent["High"].max() - recent["Low"].min()) / recent["Low"].min() * 100
    if price_range_pct < 3.0:
        results.append({
            "rule": 6,
            "flag": FLAG_WAIT,
            "reason": f"直近{RANGE_LOOKBACK}日のレンジ幅{price_range_pct:.1f}%（3%未満の持ち合い）",
        })

    # ---- ルール7: ボリンジャーバンド逸脱 -----------------------------------
    if pd.notna(latest["bb_lower"]) and pd.notna(latest["bb_upper"]):
        if latest["Close"] <= latest["bb_lower"]:
            results.append({
                "rule": 7,
                "flag": FLAG_BUY,
                "reason": f"BB下限割れ（終値{latest['Close']:.0f} ≤ -2σ={latest['bb_lower']:.0f}）",
            })
        elif latest["Close"] >= latest["bb_upper"]:
            results.append({
                "rule": 7,
                "flag": FLAG_SELL,
                "reason": f"BB上限超え（終値{latest['Close']:.0f} ≥ +2σ={latest['bb_upper']:.0f}）",
            })

    # ---- ルール8: RSI過売買 ------------------------------------------------
    if pd.notna(latest["rsi"]):
        if latest["rsi"] <= 30:
            results.append({
                "rule": 8,
                "flag": FLAG_BUY,
                "reason": f"RSI={latest['rsi']:.1f}（30以下、売られ過ぎ）",
            })
        elif latest["rsi"] >= 70:
            results.append({
                "rule": 8,
                "flag": FLAG_SELL,
                "reason": f"RSI={latest['rsi']:.1f}（70以上、買われ過ぎ）",
            })

    return results if results else [{"rule": 0, "flag": FLAG_NONE, "reason": "条件該当なし"}]


def summarize_flags(rule_results: list[dict]) -> str:
    """ルール結果から最終判定を集約する"""
    flags = [r["flag"] for r in rule_results]
    if FLAG_WATCH in flags:
        return FLAG_WATCH
    buy_count = flags.count(FLAG_BUY)
    sell_count = flags.count(FLAG_SELL)
    wait_count = flags.count(FLAG_WAIT)
    if wait_count >= 1 and buy_count == 0:
        return FLAG_WAIT
    if buy_count > sell_count:
        return FLAG_BUY
    if sell_count > buy_count:
        return FLAG_SELL
    if wait_count > 0:
        return FLAG_WAIT
    return FLAG_NONE
