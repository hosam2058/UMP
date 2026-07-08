"""
====================================================================
 نظام معالجة البيانات للتداول الآلي
 Data Preprocessing Pipeline for Automated Trading Systems
====================================================================
يشمل:
  - تحميل بيانات السوق
  - تنظيف البيانات ومعالجة القيم المفقودة
  - هندسة الميزات (Feature Engineering)
  - تطبيع البيانات
  - تقسيم البيانات للتدريب والاختبار
  - إنشاء نوافذ زمنية (Sliding Windows)
====================================================================
"""

import numpy as np
import pandas as pd
from sklearn.preprocessing import (
    MinMaxScaler, StandardScaler, RobustScaler
)
from sklearn.model_selection import TimeSeriesSplit
from typing import Tuple, List, Optional, Dict
import warnings
warnings.filterwarnings("ignore")


# ─────────────────────────────────────────────────────────────────
# 1. تحميل البيانات
# ─────────────────────────────────────────────────────────────────

def load_market_data(
    symbol: str = "AAPL",
    start: str = "2018-01-01",
    end: str = "2024-01-01",
    source: str = "yfinance"
) -> pd.DataFrame:
    """
    تحميل بيانات السوق من مصادر متعددة.

    Parameters
    ----------
    symbol  : رمز السهم أو العملة
    start   : تاريخ البداية  (YYYY-MM-DD)
    end     : تاريخ النهاية  (YYYY-MM-DD)
    source  : 'yfinance' أو 'csv'

    Returns
    -------
    pd.DataFrame بأعمدة: Open, High, Low, Close, Volume
    """
    if source == "yfinance":
        try:
            import yfinance as yf
            df = yf.download(symbol, start=start, end=end, progress=False)
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
            df.index = pd.to_datetime(df.index)
            return df
        except ImportError:
            print("yfinance غير مثبّت. استخدم: pip install yfinance")
            return _generate_synthetic_data(start, end)

    elif source == "csv":
        raise ValueError("حدد مسار الملف عبر المعامل `filepath`.")

    else:
        return _generate_synthetic_data(start, end)


def _generate_synthetic_data(start: str, end: str) -> pd.DataFrame:
    """توليد بيانات اصطناعية للاختبار عند غياب مصدر حقيقي."""
    dates = pd.date_range(start=start, end=end, freq="B")
    n = len(dates)
    np.random.seed(42)
    close = 100 * np.cumprod(1 + np.random.normal(0.0002, 0.015, n))
    high  = close * (1 + np.abs(np.random.normal(0, 0.008, n)))
    low   = close * (1 - np.abs(np.random.normal(0, 0.008, n)))
    open_ = close * (1 + np.random.normal(0, 0.005, n))
    volume = np.random.randint(1_000_000, 10_000_000, n).astype(float)

    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=dates
    )


# ─────────────────────────────────────────────────────────────────
# 2. تنظيف البيانات
# ─────────────────────────────────────────────────────────────────

def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    تنظيف بيانات السوق:
      - إزالة القيم المكررة
      - تعبئة القيم المفقودة بالاستيفاء
      - إزالة الشموع المعطوبة (High < Low)
    """
    df = df.copy()
    df = df[~df.index.duplicated(keep="first")]
    df = df.sort_index()

    for col in ["Open", "High", "Low", "Close", "Volume"]:
        if col in df.columns:
            df[col] = df[col].replace(0, np.nan)
            df[col] = df[col].interpolate(method="time")
            df[col] = df[col].ffill().bfill()

    if "High" in df.columns and "Low" in df.columns:
        bad = df["High"] < df["Low"]
        df.loc[bad, ["High", "Low"]] = df.loc[bad, ["Low", "High"]].values

    df = df.dropna()
    return df


# ─────────────────────────────────────────────────────────────────
# 3. هندسة الميزات (Feature Engineering)
# ─────────────────────────────────────────────────────────────────

def add_technical_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    إضافة المؤشرات الفنية الكاملة كميزات:
      - المتوسطات المتحركة (SMA, EMA)
      - RSI, MACD, Bollinger Bands
      - ATR, OBV, Stochastic
      - نسب الأداء والعائد
    """
    df = df.copy()
    close = df["Close"]
    high  = df["High"]
    low   = df["Low"]
    vol   = df["Volume"]

    # ── المتوسطات المتحركة ──────────────────────────────────────
    for w in [5, 10, 20, 50, 200]:
        df[f"SMA_{w}"]  = close.rolling(w).mean()
        df[f"EMA_{w}"]  = close.ewm(span=w, adjust=False).mean()

    # ── RSI ─────────────────────────────────────────────────────
    for period in [7, 14, 21]:
        delta = close.diff()
        gain  = delta.clip(lower=0).rolling(period).mean()
        loss  = (-delta.clip(upper=0)).rolling(period).mean()
        rs    = gain / (loss + 1e-9)
        df[f"RSI_{period}"] = 100 - 100 / (1 + rs)

    # ── MACD ────────────────────────────────────────────────────
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df["MACD"]        = ema12 - ema26
    df["MACD_signal"] = df["MACD"].ewm(span=9, adjust=False).mean()
    df["MACD_hist"]   = df["MACD"] - df["MACD_signal"]

    # ── Bollinger Bands ──────────────────────────────────────────
    for w in [20, 50]:
        sma = close.rolling(w).mean()
        std = close.rolling(w).std()
        df[f"BB_upper_{w}"] = sma + 2 * std
        df[f"BB_lower_{w}"] = sma - 2 * std
        df[f"BB_width_{w}"] = (df[f"BB_upper_{w}"] - df[f"BB_lower_{w}"]) / (sma + 1e-9)
        df[f"BB_pct_{w}"]   = (close - df[f"BB_lower_{w}"]) / (df[f"BB_width_{w}"] * sma + 1e-9)

    # ── ATR (Average True Range) ────────────────────────────────
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs()
    ], axis=1).max(axis=1)
    df["ATR_14"] = tr.rolling(14).mean()
    df["ATR_7"]  = tr.rolling(7).mean()

    # ── Stochastic Oscillator ────────────────────────────────────
    for k in [14, 21]:
        lo_k = low.rolling(k).min()
        hi_k = high.rolling(k).max()
        df[f"Stoch_K_{k}"] = 100 * (close - lo_k) / (hi_k - lo_k + 1e-9)
        df[f"Stoch_D_{k}"] = df[f"Stoch_K_{k}"].rolling(3).mean()

    # ── OBV (On-Balance Volume) ──────────────────────────────────
    obv = (np.sign(close.diff()) * vol).cumsum()
    df["OBV"] = obv
    df["OBV_SMA_20"] = obv.rolling(20).mean()

    # ── CCI (Commodity Channel Index) ───────────────────────────
    typical = (high + low + close) / 3
    df["CCI_20"] = (typical - typical.rolling(20).mean()) / (0.015 * typical.rolling(20).std() + 1e-9)

    # ── Williams %R ─────────────────────────────────────────────
    df["Williams_R"] = -100 * (high.rolling(14).max() - close) / (
        high.rolling(14).max() - low.rolling(14).min() + 1e-9
    )

    # ── العوائد اليومية والتقلب ──────────────────────────────────
    df["Return_1d"]  = close.pct_change(1)
    df["Return_5d"]  = close.pct_change(5)
    df["Return_20d"] = close.pct_change(20)
    df["Volatility_20"] = df["Return_1d"].rolling(20).std() * np.sqrt(252)
    df["Volatility_60"] = df["Return_1d"].rolling(60).std() * np.sqrt(252)

    # ── Momentum ─────────────────────────────────────────────────
    df["Mom_10"] = close - close.shift(10)
    df["Mom_20"] = close - close.shift(20)

    # ── نسب السعر إلى المتوسطات ──────────────────────────────────
    df["Price_SMA20_ratio"] = close / (df["SMA_20"] + 1e-9)
    df["Price_SMA50_ratio"] = close / (df["SMA_50"] + 1e-9)

    # ── حجم التداول ─────────────────────────────────────────────
    df["Vol_SMA_20"] = vol.rolling(20).mean()
    df["Vol_ratio"]  = vol / (df["Vol_SMA_20"] + 1e-9)

    # ── الفجوات اليومية ──────────────────────────────────────────
    df["Gap"] = (df["Open"] - close.shift(1)) / (close.shift(1) + 1e-9)

    df = df.dropna()
    return df


def add_time_features(df: pd.DataFrame) -> pd.DataFrame:
    """إضافة ميزات الوقت الدورية."""
    df = df.copy()
    df["DayOfWeek"]    = df.index.dayofweek
    df["Month"]        = df.index.month
    df["Quarter"]      = df.index.quarter
    df["WeekOfYear"]   = df.index.isocalendar().week.astype(int)
    df["DayOfMonth"]   = df.index.day
    df["IsMonthStart"] = df.index.is_month_start.astype(int)
    df["IsMonthEnd"]   = df.index.is_month_end.astype(int)
    df["IsQuarterEnd"] = df.index.is_quarter_end.astype(int)

    df["DayOfWeek_sin"]  = np.sin(2 * np.pi * df["DayOfWeek"] / 5)
    df["DayOfWeek_cos"]  = np.cos(2 * np.pi * df["DayOfWeek"] / 5)
    df["Month_sin"]      = np.sin(2 * np.pi * df["Month"] / 12)
    df["Month_cos"]      = np.cos(2 * np.pi * df["Month"] / 12)
    return df


def create_labels(
    df: pd.DataFrame,
    horizon: int = 5,
    threshold: float = 0.01
) -> pd.DataFrame:
    """
    إنشاء تسميات التداول.

    Parameters
    ----------
    horizon   : عدد أيام المستقبل للتنبؤ
    threshold : حد العائد لتصنيف الإشارة

    Returns
    -------
    df بإضافة أعمدة:
      - future_return : العائد الفعلي
      - label_3class  : 0=بيع, 1=محايد, 2=شراء
      - label_binary  : 0=هبوط, 1=صعود
    """
    df = df.copy()
    df["future_return"] = df["Close"].shift(-horizon) / df["Close"] - 1

    conditions = [
        df["future_return"] < -threshold,
        df["future_return"] >  threshold
    ]
    choices = [0, 2]
    df["label_3class"] = np.select(conditions, choices, default=1)
    df["label_binary"] = (df["future_return"] > 0).astype(int)

    df = df.dropna(subset=["future_return"])
    return df


# ─────────────────────────────────────────────────────────────────
# 4. تطبيع البيانات وإنشاء النوافذ الزمنية
# ─────────────────────────────────────────────────────────────────

class DataProcessor:
    """
    معالج البيانات الشامل:
      - تطبيع الميزات
      - إنشاء نوافذ زمنية لـ LSTM / CNN
      - تقسيم زمني للتدريب والاختبار
    """

    def __init__(
        self,
        scaler_type: str = "minmax",
        window_size: int = 60,
        test_ratio: float = 0.2,
        val_ratio: float = 0.1
    ):
        self.window_size = window_size
        self.test_ratio  = test_ratio
        self.val_ratio   = val_ratio
        self.feature_cols: List[str] = []
        self.label_col: str = "label_binary"

        if scaler_type == "minmax":
            self.scaler = MinMaxScaler(feature_range=(-1, 1))
        elif scaler_type == "standard":
            self.scaler = StandardScaler()
        else:
            self.scaler = RobustScaler()

    def prepare(
        self,
        df: pd.DataFrame,
        feature_cols: Optional[List[str]] = None,
        label_col: str = "label_binary"
    ) -> Dict:
        """
        خط الأنابيب الكامل لمعالجة البيانات.

        Returns
        -------
        dict بمفاتيح: X_train, X_val, X_test, y_train, y_val, y_test,
                      X_seq_train, X_seq_val, X_seq_test,
                      feature_names, scaler
        """
        self.label_col = label_col

        if feature_cols is None:
            exclude = {"Open", "High", "Low", "Close", "Volume",
                       "future_return", "label_3class", "label_binary"}
            feature_cols = [c for c in df.columns if c not in exclude]
        self.feature_cols = feature_cols

        X = df[feature_cols].values
        y = df[label_col].values

        n = len(X)
        test_size = int(n * self.test_ratio)
        val_size  = int(n * self.val_ratio)
        train_end = n - test_size - val_size

        X_train_raw = X[:train_end]
        X_val_raw   = X[train_end:train_end + val_size]
        X_test_raw  = X[train_end + val_size:]

        y_train = y[:train_end]
        y_val   = y[train_end:train_end + val_size]
        y_test  = y[train_end + val_size:]

        X_train = self.scaler.fit_transform(X_train_raw)
        X_val   = self.scaler.transform(X_val_raw)
        X_test  = self.scaler.transform(X_test_raw)

        X_scaled_full = self.scaler.transform(X)

        X_seq_train, y_seq_train = self._make_sequences(
            X_scaled_full[:train_end], y[:train_end]
        )
        X_seq_val, y_seq_val = self._make_sequences(
            X_scaled_full[train_end:train_end + val_size],
            y[train_end:train_end + val_size]
        )
        X_seq_test, y_seq_test = self._make_sequences(
            X_scaled_full[train_end + val_size:],
            y[train_end + val_size:]
        )

        return {
            "X_train": X_train, "X_val": X_val, "X_test": X_test,
            "y_train": y_train, "y_val": y_val, "y_test": y_test,
            "X_seq_train": X_seq_train, "y_seq_train": y_seq_train,
            "X_seq_val":   X_seq_val,   "y_seq_val":   y_seq_val,
            "X_seq_test":  X_seq_test,  "y_seq_test":  y_seq_test,
            "feature_names": feature_cols,
            "scaler": self.scaler,
            "n_features": len(feature_cols),
            "window_size": self.window_size,
        }

    def _make_sequences(
        self, X: np.ndarray, y: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray]:
        """إنشاء نوافذ زمنية متداخلة لنماذج التسلسل."""
        if len(X) <= self.window_size:
            return np.empty((0, self.window_size, X.shape[1])), np.empty(0)
        Xs, ys = [], []
        for i in range(self.window_size, len(X)):
            Xs.append(X[i - self.window_size:i])
            ys.append(y[i])
        return np.array(Xs), np.array(ys)

    def get_timeseries_splits(self, X: np.ndarray, n_splits: int = 5):
        """مولّد للتحقق المتقاطع الزمني (Time-Series CV)."""
        tscv = TimeSeriesSplit(n_splits=n_splits)
        return tscv.split(X)


# ─────────────────────────────────────────────────────────────────
# مثال التشغيل
# ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  نظام معالجة البيانات للتداول الآلي")
    print("=" * 60)

    df_raw = load_market_data("AAPL", "2018-01-01", "2024-01-01")
    print(f"[1] تم تحميل البيانات: {len(df_raw)} صف")

    df_clean = clean_data(df_raw)
    print(f"[2] بعد التنظيف       : {len(df_clean)} صف")

    df_feat = add_technical_features(df_clean)
    df_feat = add_time_features(df_feat)
    print(f"[3] عدد الميزات       : {len(df_feat.columns)} عمود")

    df_labeled = create_labels(df_feat, horizon=5, threshold=0.01)
    print(f"[4] البيانات بعد التسميات: {len(df_labeled)} صف")
    print(f"    توزيع التسميات:\n{df_labeled['label_3class'].value_counts().to_string()}")

    processor = DataProcessor(scaler_type="minmax", window_size=60)
    data = processor.prepare(df_labeled)

    print(f"\n[5] أحجام مجموعات البيانات:")
    print(f"    تدريب     : X={data['X_train'].shape}, y={data['y_train'].shape}")
    print(f"    تحقق      : X={data['X_val'].shape},   y={data['y_val'].shape}")
    print(f"    اختبار    : X={data['X_test'].shape},  y={data['y_test'].shape}")
    print(f"    تسلسلات تدريب (LSTM): {data['X_seq_train'].shape}")
    print(f"    تسلسلات اختبار (LSTM): {data['X_seq_test'].shape}")
    print("\n✅ معالجة البيانات اكتملت بنجاح.")
