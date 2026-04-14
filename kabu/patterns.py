"""
ローソク足パターン検出モジュール
直近3日分のデータでパターンを判定する。
"""

import pandas as pd

# 小実体の定義: ボディがレンジ全体の30%以下
SMALL_BODY_RATIO = 0.30


def _body(row) -> float:
    """ローソク足のボディ絶対値"""
    return abs(row["Close"] - row["Open"])


def _range(row) -> float:
    """ローソク足のレンジ（高値-安値）"""
    r = row["High"] - row["Low"]
    return r if r > 0 else 1e-9


def _is_bearish(row) -> bool:
    return row["Close"] < row["Open"]


def _is_bullish(row) -> bool:
    return row["Close"] > row["Open"]


def _is_small_body(row) -> bool:
    return _body(row) / _range(row) <= SMALL_BODY_RATIO


def detect_patterns(df: pd.DataFrame) -> list[dict]:
    """
    直近3日分でローソク足パターンを検出。
    戻り値: [{"name": str, "signal": "BUY"|"SELL", "description": str}, ...]
    """
    if len(df) < 3:
        return []

    d1, d2, d3 = df.iloc[-3], df.iloc[-2], df.iloc[-1]
    found = []

    # ---- 黒三兵（Three Black Crows）: 売りシグナル -----------------------
    # 3日連続陰線 かつ 各日終値が前日終値を下回る
    if (
        _is_bearish(d1)
        and _is_bearish(d2)
        and _is_bearish(d3)
        and d2["Close"] < d1["Close"]
        and d3["Close"] < d2["Close"]
    ):
        found.append({
            "name": "黒三兵（Three Black Crows）",
            "signal": "SELL",
            "description": "3日連続陰線・終値切り下げ → 下落継続の強い売りシグナル",
        })

    # ---- 赤三兵（Three White Soldiers）: 買いシグナル --------------------
    # 3日連続陽線 かつ 各日終値が前日終値を上回る
    if (
        _is_bullish(d1)
        and _is_bullish(d2)
        and _is_bullish(d3)
        and d2["Close"] > d1["Close"]
        and d3["Close"] > d2["Close"]
    ):
        found.append({
            "name": "赤三兵（Three White Soldiers）",
            "signal": "BUY",
            "description": "3日連続陽線・終値切り上げ → 上昇継続の強い買いシグナル",
        })

    # ---- 宵の明星（Evening Star）: 売りシグナル --------------------------
    # 陽線 → 小実体（窓開け不要） → 陰線
    # 陽線の終値より3日目終値が低いことを条件に追加
    if (
        _is_bullish(d1)
        and _is_small_body(d2)
        and _is_bearish(d3)
        and d3["Close"] < d1["Close"]
    ):
        found.append({
            "name": "宵の明星（Evening Star）",
            "signal": "SELL",
            "description": "陽線→十字線→陰線の反転パターン → 天井圏の売りシグナル",
        })

    # ---- 明けの明星（Morning Star）: 買いシグナル -----------------------
    # 陰線 → 小実体 → 陽線
    # 陰線の終値より3日目終値が高いことを条件に追加
    if (
        _is_bearish(d1)
        and _is_small_body(d2)
        and _is_bullish(d3)
        and d3["Close"] > d1["Close"]
    ):
        found.append({
            "name": "明けの明星（Morning Star）",
            "signal": "BUY",
            "description": "陰線→十字線→陽線の反転パターン → 底値圏の買いシグナル",
        })

    return found
