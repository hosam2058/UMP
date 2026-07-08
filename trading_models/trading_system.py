"""
====================================================================
 نظام التداول الآلي المتكامل
 Integrated Automated Trading System
====================================================================
يجمع جميع النماذج في منظومة متكاملة:
  ┌─────────────────────────────────────────┐
  │          بيانات السوق (Market Data)      │
  └──────────────────┬──────────────────────┘
                     │
  ┌──────────────────▼──────────────────────┐
  │     معالجة البيانات (Preprocessing)      │
  │   تحليل فني | موجلت | فورييه | PCA      │
  └──────────────────┬──────────────────────┘
                     │
  ┌──────────────────▼──────────────────────┐
  │         طبقة النماذج (Models Layer)      │
  │  ML | DL | CV | RL | Sentiment | HMM   │
  └──────────────────┬──────────────────────┘
                     │
  ┌──────────────────▼──────────────────────┐
  │      دمج الإشارات (Signal Fusion)        │
  │    ترجيح + فلترة + إدارة مخاطر          │
  └──────────────────┬──────────────────────┘
                     │
  ┌──────────────────▼──────────────────────┐
  │       تنفيذ الصفقات (Execution)          │
  │    حجم المركز | وقف الخسارة | مراقبة   │
  └─────────────────────────────────────────┘
====================================================================
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import warnings
warnings.filterwarnings("ignore")

from data_preprocessing import (
    load_market_data, clean_data, add_technical_features,
    add_time_features, create_labels, DataProcessor
)
from ml_models import RandomForestTrader, XGBoostTrader, LightGBMTrader, EnsembleTrader
from advanced_analysis import (
    FourierAnalyzer, MarketRegimeHMM, KalmanPriceFilter,
    MonteCarloSimulator, GARCHModel
)
from sentiment_analysis import (
    VADERSentimentAnalyzer, FearGreedIndex, SentimentTechnicalFusion
)
from risk_management import (
    PositionSizer, RiskMetrics, PortfolioOptimizer,
    StopLossManager, RiskMonitor
)


# ─────────────────────────────────────────────────────────────────
# محرك دمج الإشارات
# ─────────────────────────────────────────────────────────────────

class SignalFusion:
    """
    يجمع إشارات من مصادر متعددة ويُصدر قرار تداول نهائي مرجَّح.
    """

    WEIGHTS = {
        "ml_ensemble":   0.25,
        "deep_learning": 0.20,
        "regime":        0.15,
        "sentiment":     0.15,
        "technical":     0.15,
        "fear_greed":    0.10,
    }

    @staticmethod
    def signal_to_score(signal: str) -> float:
        mapping = {
            "STRONG_BUY": 1.5, "BUY": 1.0,
            "HOLD": 0.0,
            "SELL": -1.0, "STRONG_SELL": -1.5,
        }
        return mapping.get(signal.upper(), 0.0)

    @staticmethod
    def score_to_signal(score: float) -> str:
        if score >= 0.7:   return "STRONG_BUY"
        elif score >= 0.3: return "BUY"
        elif score <= -0.7:return "STRONG_SELL"
        elif score <= -0.3:return "SELL"
        return "HOLD"

    def fuse(self, signals: Dict[str, str]) -> Dict:
        """
        Parameters
        ----------
        signals : {"source_name": "BUY"|"SELL"|"HOLD", ...}

        Returns
        -------
        dict: قرار التداول النهائي مع تفاصيل المكونات
        """
        composite = 0.0
        total_w   = 0.0

        for source, signal in signals.items():
            w = self.WEIGHTS.get(source, 0.1)
            composite += w * self.signal_to_score(signal)
            total_w   += w

        composite /= (total_w + 1e-9)
        final_signal = self.score_to_signal(composite)
        confidence   = min(1.0, abs(composite) / 1.5)

        return {
            "signal":     final_signal,
            "confidence": round(confidence, 4),
            "score":      round(composite, 4),
            "components": {s: self.signal_to_score(v) for s, v in signals.items()},
            "timestamp":  datetime.now().isoformat(),
        }


# ─────────────────────────────────────────────────────────────────
# محرك التداول الكامل
# ─────────────────────────────────────────────────────────────────

class AutomatedTradingEngine:
    """
    محرك التداول الآلي الكامل:
      - تدريب جميع النماذج
      - توليد الإشارات اليومية
      - اختبار تاريخي (Backtesting)
      - تقرير أداء شامل
    """

    def __init__(
        self,
        symbol: str = "AAPL",
        start: str = "2018-01-01",
        end: str = "2024-01-01",
        initial_balance: float = 100_000.0,
        risk_pct_per_trade: float = 0.02,
        window_size: int = 60
    ):
        self.symbol          = symbol
        self.initial_balance = initial_balance
        self.risk_pct        = risk_pct_per_trade
        self.window_size     = window_size
        self.start           = start
        self.end             = end

        # مكونات النظام
        self.processor    = DataProcessor(window_size=window_size)
        self.ml_ensemble  = EnsembleTrader()
        self.rf_model     = RandomForestTrader(n_estimators=200)
        self.xgb_model    = XGBoostTrader(n_estimators=200)
        self.lgb_model    = LightGBMTrader(n_estimators=200)
        self.hmm_model    = MarketRegimeHMM(n_regimes=3)
        self.kalman       = KalmanPriceFilter()
        self.fourier      = FourierAnalyzer(top_n_frequencies=10)
        self.vader        = VADERSentimentAnalyzer()
        self.fear_greed   = FearGreedIndex()
        self.position_sizer = PositionSizer(initial_balance)
        self.stop_manager = StopLossManager(atr_multiplier=2.0, trailing_pct=0.05)
        self.risk_monitor = RiskMonitor()
        self.risk_metrics = RiskMetrics()
        self.signal_fusion = SignalFusion()

        self._trained = False
        self.data:  Dict = {}
        self.df_raw: pd.DataFrame = None

    def load_and_prepare(self) -> "AutomatedTradingEngine":
        """تحميل البيانات وإعدادها."""
        print(f"\n{'='*55}")
        print(f"  نظام التداول الآلي المتكامل")
        print(f"  الأصل: {self.symbol} | {self.start} → {self.end}")
        print(f"{'='*55}")
        print("\n[1] تحميل ومعالجة البيانات...")

        df = load_market_data(self.symbol, self.start, self.end)
        df = clean_data(df)
        df = add_technical_features(df)
        df = add_time_features(df)
        df = create_labels(df, horizon=5, threshold=0.01)

        self.df_raw = df
        self.data   = self.processor.prepare(df)
        print(f"    الصفوف: {len(df)} | الميزات: {self.data['n_features']}")
        return self

    def train_models(self) -> "AutomatedTradingEngine":
        """تدريب جميع نماذج التعلم الآلي."""
        print("\n[2] تدريب نماذج التعلم الآلي...")
        X_tr, y_tr = self.data["X_train"], self.data["y_train"]
        X_v,  y_v  = self.data["X_val"],   self.data["y_val"]
        fnames = self.data["feature_names"]

        self.rf_model.fit(X_tr, y_tr, feature_names=fnames)
        print(f"    RandomForest  ✓ OOB={self.rf_model.model.oob_score_:.4f}")

        self.xgb_model.fit(X_tr, y_tr, X_v, y_v, feature_names=fnames)
        print("    XGBoost       ✓")

        self.lgb_model.fit(X_tr, y_tr, X_v, y_v, feature_names=fnames)
        print("    LightGBM      ✓")

        self.ml_ensemble.fit(X_tr, y_tr)
        print("    Ensemble      ✓")

        print("\n[3] تدريب نماذج التحليل المتطور...")
        returns = self.df_raw["Close"].pct_change().dropna().values
        self.hmm_model.fit(returns)
        print(f"    HMM (أنظمة السوق) ✓ | الأنظمة: {self.hmm_model.regime_labels}")

        try:
            from advanced_analysis import GARCHModel
            self.garch = GARCHModel(p=1, q=1)
            self.garch.fit(pd.Series(returns[-500:]))
            print("    GARCH (التقلب) ✓")
        except Exception:
            self.garch = None

        self._trained = True
        return self

    def generate_signal(
        self,
        recent_df: Optional[pd.DataFrame] = None,
        news_texts: Optional[List[str]] = None
    ) -> Dict:
        """
        توليد إشارة تداول للحظة الراهنة بجمع جميع المصادر.

        Parameters
        ----------
        recent_df  : بيانات حديثة للتحليل (تستخدم آخر البيانات إذا None)
        news_texts : عناوين أخبار حديثة (اختياري)
        """
        if not self._trained:
            raise ValueError("يجب تدريب النموذج أولاً باستدعاء train_models()")

        df = recent_df if recent_df is not None else self.df_raw
        prices  = df["Close"].values
        volumes = df["Volume"].values
        returns = pd.Series(prices).pct_change().dropna().values

        # ── إشارات ML ──────────────────────────────────────────
        X_latest = self.data["X_test"][-1:] if len(self.data["X_test"]) > 0 \
                   else self.data["X_val"][-1:]
        if len(X_latest) > 0:
            rf_pred  = int(self.rf_model.predict(X_latest)[0])
            xgb_pred = int(self.xgb_model.predict(X_latest)[0])
            lgb_pred = int(self.lgb_model.predict(X_latest)[0])
            ens_pred = int(self.ml_ensemble.predict(X_latest)[0])

            def pred_to_signal(p):
                return "BUY" if p == 1 else "SELL"

            ml_signals = {
                "rf":  pred_to_signal(rf_pred),
                "xgb": pred_to_signal(xgb_pred),
                "lgb": pred_to_signal(lgb_pred),
                "ens": pred_to_signal(ens_pred),
            }
            votes = list(ml_signals.values())
            ml_signal = "BUY" if votes.count("BUY") > len(votes) / 2 else "SELL"
        else:
            ml_signal = "HOLD"

        # ── نظام السوق (HMM) ────────────────────────────────────
        regime_info = self.hmm_model.get_current_regime(returns[-60:])
        regime_signal = regime_info["trading_signal"]

        # ── مشاعر الأخبار ────────────────────────────────────────
        if news_texts:
            agg = self.vader.aggregate_signal(news_texts)
            sentiment_signal = agg["trading_signal"]
            sentiment_score  = agg["compound"]
        else:
            sentiment_signal = "HOLD"
            sentiment_score  = 0.0

        # ── مؤشر الخوف والجشع ────────────────────────────────────
        fg_result = self.fear_greed.compute(prices, volumes, sentiment_score)
        fg_signal = fg_result["signal"]

        # ── تحليل فورييه ─────────────────────────────────────────
        fourier_result = self.fourier.analyze(prices[-252:])

        # ── كالمان ───────────────────────────────────────────────
        kalman_filtered = self.kalman.filter_series(prices[-60:])
        kalman_signal   = self.kalman.get_trend_signal()

        # ── مؤشرات فنية ─────────────────────────────────────────
        close = pd.Series(prices)
        rsi   = 100 - 100 / (1 + close.diff().clip(lower=0).rolling(14).mean() /
                               (-close.diff().clip(upper=0)).rolling(14).mean() + 1e-9)
        rsi_val = rsi.iloc[-1] if not rsi.empty else 50

        macd   = close.ewm(span=12).mean() - close.ewm(span=26).mean()
        macd_s = macd.ewm(span=9).mean()
        macd_val = macd.iloc[-1] - macd_s.iloc[-1] if len(macd) > 0 else 0

        # تحويل المؤشرات إلى درجة (-1 إلى +1)
        rsi_score   = (rsi_val - 50) / 50  if not np.isnan(rsi_val)  else 0
        macd_score  = np.clip(macd_val / (close.std() + 1e-9), -1, 1)
        tech_score  = (rsi_score + macd_score) / 2
        tech_signal = "BUY" if tech_score > 0.1 else "SELL" if tech_score < -0.1 else "HOLD"

        # ── دمج الإشارات ─────────────────────────────────────────
        all_signals = {
            "ml_ensemble":   ml_signal,
            "regime":        regime_signal,
            "sentiment":     sentiment_signal,
            "technical":     tech_signal,
            "fear_greed":    fg_signal,
        }
        fused = self.signal_fusion.fuse(all_signals)

        # ── حجم المركز ───────────────────────────────────────────
        atr_daily = pd.Series(prices).diff().abs().rolling(14).mean().iloc[-1]
        if np.isnan(atr_daily):
            atr_daily = prices[-1] * 0.01

        sizing = self.position_sizer.atr_based(
            price=prices[-1],
            atr=atr_daily,
            risk_pct=self.risk_pct
        )

        # ── وقف الخسارة ─────────────────────────────────────────
        stop = self.stop_manager.atr_stop(
            entry_price=prices[-1],
            current_atr=atr_daily,
            direction="long" if fused["signal"] in ["BUY", "STRONG_BUY"] else "short"
        )

        return {
            "symbol":        self.symbol,
            "timestamp":     datetime.now().isoformat(),
            "current_price": round(float(prices[-1]), 4),
            "final_signal":  fused["signal"],
            "confidence":    fused["confidence"],
            "composite_score": fused["score"],
            "individual_signals": all_signals,
            "regime":        regime_info["regime"],
            "fear_greed_index": fg_result["value"],
            "fear_greed_label": fg_result["label"],
            "position_sizing": sizing,
            "stop_loss":     stop,
            "rsi":           round(float(rsi_val), 2) if not np.isnan(rsi_val) else None,
            "tech_score":    round(float(tech_score), 4),
        }

    def backtest(
        self,
        transaction_cost: float = 0.001,
        slippage: float = 0.0005
    ) -> Dict:
        """
        اختبار تاريخي شامل للاستراتيجية على بيانات الاختبار.
        يعمل بدون نموذج التعلم المعزز – مباشرة من إشارات ML.
        """
        print("\n[4] اختبار تاريخي...")
        if not self._trained:
            raise ValueError("يجب تدريب النموذج أولاً.")

        X_test = self.data["X_test"]
        y_test = self.data["y_test"]

        if len(X_test) == 0:
            return {"error": "لا توجد بيانات اختبار كافية."}

        # استخراج الأسعار المقابلة
        n_test = len(X_test)
        prices = self.df_raw["Close"].values
        test_prices = prices[len(prices) - n_test:]

        # إشارات من نموذج XGBoost
        signals = self.xgb_model.predict(X_test)    # 0=بيع، 1=شراء

        # محاكاة التداول
        balance  = self.initial_balance
        shares   = 0.0
        trades   = []
        portfolio_values = [balance]

        for i in range(1, len(signals)):
            price  = test_prices[i]
            signal = signals[i]
            prev   = signals[i - 1]

            if signal == 1 and prev != 1 and balance > 0:
                # شراء
                buy_amount = balance * 0.95
                cost = buy_amount * (1 + transaction_cost + slippage)
                shares   = buy_amount / (price + 1e-9)
                balance -= cost
                trades.append({"type": "BUY", "price": price, "step": i})

            elif signal == 0 and prev != 0 and shares > 0:
                # بيع
                revenue  = shares * price * (1 - transaction_cost - slippage)
                balance += revenue
                shares   = 0.0
                trades.append({"type": "SELL", "price": price, "step": i})

            portfolio_values.append(balance + shares * price)

        # إغلاق المركز النهائي
        if shares > 0:
            balance += shares * test_prices[-1] * (1 - transaction_cost)
            portfolio_values[-1] = balance

        # حساب مقاييس الأداء
        portfolio_returns = np.diff(portfolio_values) / np.array(portfolio_values[:-1])
        bh_return = (test_prices[-1] / test_prices[0] - 1) * 100
        strat_return = (balance / self.initial_balance - 1) * 100

        metrics = {}
        if len(portfolio_returns) > 5:
            metrics = self.risk_metrics.full_report(portfolio_returns)

        result = {
            "strategy_return_pct":  round(strat_return, 2),
            "buy_hold_return_pct":  round(bh_return, 2),
            "alpha_pct":            round(strat_return - bh_return, 2),
            "final_balance":        round(balance, 2),
            "n_trades":             len(trades),
            "test_days":            len(signals),
            **metrics,
        }

        print(f"    عائد الاستراتيجية : {result['strategy_return_pct']:+.2f}%")
        print(f"    عائد الاحتجاز     : {result['buy_hold_return_pct']:+.2f}%")
        print(f"    Alpha             : {result['alpha_pct']:+.2f}%")
        print(f"    عدد الصفقات       : {result['n_trades']}")

        return result

    def full_run(self, news_texts: Optional[List[str]] = None) -> Dict:
        """
        تشغيل النظام الكامل:
         1. تحميل البيانات
         2. تدريب النماذج
         3. توليد إشارة الآن
         4. اختبار تاريخي
         5. تقرير مخاطر المحفظة
        """
        self.load_and_prepare()
        self.train_models()

        print("\n[5] توليد الإشارة الحالية...")
        signal = self.generate_signal(news_texts=news_texts)
        print(f"\n  ┌─────────────────────────────────────────────┐")
        print(f"  │  الإشارة النهائية   : {signal['final_signal']:^15s}               │")
        print(f"  │  الثقة              : {signal['confidence']:.2%}                         │")
        print(f"  │  السعر الحالي       : {signal['current_price']:>12.4f}$               │")
        print(f"  │  نظام السوق         : {signal['regime']:^15s}               │")
        print(f"  │  F&G Index          : {signal['fear_greed_index']:^3d} ({signal['fear_greed_label']})           │")
        print(f"  │  RSI                : {str(signal['rsi']):^10s}                       │")
        print(f"  │  الأسهم المقترحة    : {signal['position_sizing']['n_shares']:^10d}                   │")
        print(f"  │  سعر وقف الخسارة    : {signal['stop_loss']['stop_price']:>12.4f}$               │")
        print(f"  └─────────────────────────────────────────────┘")

        print("\n  إشارات المكونات:")
        for src, sig in signal["individual_signals"].items():
            print(f"    {src:20s}: {sig}")

        backtest_result = self.backtest()

        returns = self.df_raw["Close"].pct_change().dropna().values
        print("\n[6] تقرير المخاطر...")
        risk_report = self.risk_monitor.check(
            daily_pnl_pct=returns[-1],
            current_drawdown=self.risk_metrics.max_drawdown(returns)["max_drawdown"],
            position_sizes={"portfolio": signal["position_sizing"]["position_value"]},
            portfolio_value=self.initial_balance,
            returns=returns[-252:],
        )
        print(f"    الإجراء المطلوب: {risk_report['action']}")

        print("\n✅ اكتمل تشغيل نظام التداول الآلي.")
        return {
            "signal":    signal,
            "backtest":  backtest_result,
            "risk":      risk_report,
        }


# ─────────────────────────────────────────────────────────────────
# نقطة الدخول
# ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    sample_news = [
        "Apple beats quarterly earnings estimates with record iPhone sales.",
        "Fed signals slower rate hikes, technology stocks rally.",
        "Supply chain improvements boost Apple production numbers.",
        "Analyst upgrades AAPL to Buy with $220 price target.",
        "Concerns over China demand weigh on tech sector outlook.",
    ]

    engine = AutomatedTradingEngine(
        symbol="AAPL",
        start="2018-01-01",
        end="2024-01-01",
        initial_balance=100_000,
        risk_pct_per_trade=0.02,
        window_size=60
    )

    result = engine.full_run(news_texts=sample_news)
