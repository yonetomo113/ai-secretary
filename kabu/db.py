import os
import sqlite3
import pandas as pd

DB_PATH = os.path.join(os.path.dirname(__file__), 'kabu.db')


def get_conn():
    return sqlite3.connect(DB_PATH)


def init_db():
    """テーブル初期化"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS daily_prices (
            symbol      TEXT NOT NULL,
            date        TEXT NOT NULL,
            open        REAL,
            high        REAL,
            low         REAL,
            close       REAL,
            volume      INTEGER,
            PRIMARY KEY (symbol, date)
        )
    """)
    conn.commit()
    conn.close()


def upsert_prices(symbol: str, df: pd.DataFrame):
    """DataFrameをDBにUPSERT"""
    conn = get_conn()
    cur = conn.cursor()
    for date, row in df.iterrows():
        cur.execute("""
            INSERT OR REPLACE INTO daily_prices
                (symbol, date, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            symbol,
            str(date.date()),
            float(row["Open"]),
            float(row["High"]),
            float(row["Low"]),
            float(row["Close"]),
            int(row["Volume"]),
        ))
    conn.commit()
    conn.close()


def load_prices(symbol: str, limit: int = 60) -> pd.DataFrame:
    """最新N日分を読み込みDataFrameで返す"""
    conn = get_conn()
    df = pd.read_sql_query(
        """
        SELECT date, open, high, low, close, volume
        FROM daily_prices
        WHERE symbol = ?
        ORDER BY date DESC
        LIMIT ?
        """,
        conn,
        params=(symbol, limit),
    )
    conn.close()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    df.columns = ["date", "Open", "High", "Low", "Close", "Volume"]
    return df
