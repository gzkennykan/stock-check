"""
数据本地缓存读写
"""
import pandas as pd
from pathlib import Path
from config import DATA_DIR


def get_cache_path(symbol: str) -> Path:
    return DATA_DIR / f"{symbol}.csv"


def load_from_csv(symbol: str) -> pd.DataFrame | None:
    path = get_cache_path(symbol)
    if path.exists():
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        if not df.empty:
            return df
    return None


def save_to_csv(symbol: str, df: pd.DataFrame) -> None:
    path = get_cache_path(symbol)
    df.to_csv(path)
