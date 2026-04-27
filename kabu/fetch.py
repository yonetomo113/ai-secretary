import yfinance as yf
from config import SYMBOLS, FETCH_PERIOD
from db import init_db, upsert_prices


def fetch_and_store():
    """全銘柄の過去3ヶ月日足をyfinanceで取得してDBに保存"""
    init_db()
    for symbol in SYMBOLS:
        print(f"  取得中: {symbol} ...", end=" ")
        ticker = yf.Ticker(symbol)
        try:
            df = ticker.history(period=FETCH_PERIOD, interval="1d", auto_adjust=True)
        except Exception as e:
            # 祝日・市場休場時など yfinance が None を返して内部クラッシュする場合
            print(f"取得失敗（スキップ）: {e}")
            continue
        if df is None or df.empty:
            print("データなし（スキップ）")
            continue
        df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
        upsert_prices(symbol, df)
        print(f"{len(df)}件保存")


if __name__ == "__main__":
    print("=== データ取得開始 ===")
    fetch_and_store()
    print("=== 取得完了 ===")
