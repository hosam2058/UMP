"""
====================================================================
 نماذج التحليل المتطور لأنظمة التداول الآلي
 Advanced Analysis Models for Automated Trading Systems
====================================================================
النماذج والتقنيات المشمولة:
  1. تحليل فورييه وموجلت للسلاسل الزمنية
  2. نموذج ARIMA / SARIMA / SARIMAX
  3. GARCH لنمذجة التقلب
  4. Hidden Markov Model (HMM) لتحديد أنظمة السوق
  5. Kalman Filter للتتبع الديناميكي
  6. Copula لتحليل الارتباط بين الأصول
  7. Monte Carlo للمحاكاة وإدارة المخاطر
  8. PCA + ICA لاستخراج عوامل السوق الخفية
  9. Regime Detection – تحديد حالات السوق (صعود/هبوط/تذبذب)
  10. Pairs Trading – استراتيجية الأزواج
====================================================================
"""

import numpy as np
import pandas as pd
from scipy import signal, stats
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA, FastICA
from sklearn.cluster import KMeans
from typing import Dict, List, Optional, Tuple
import warnings
warnings.filterwarnings("ignore")


# ─────────────────────────────────────────────────────────────────
# 1. تحليل فورييه للكشف عن الدورات
# ─────────────────────────────────────────────────────────────────

class FourierAnalyzer:
    """
    تحليل فورييه للكشف عن الدورات الزمنية في أسعار الأصول:
      - استخراج الترددات السائدة
      - إزالة الضجيج (Denoising)
      - إعادة بناء السلسلة بالمكونات الرئيسية
    """

    def __init__(self, top_n_frequencies: int = 10):
        self.top_n = top_n_frequencies
        self.dominant_frequencies: np.ndarray = None
        self.dominant_amplitudes:  np.ndarray = None
        self.dominant_periods:     np.ndarray = None

    def analyze(self, prices: np.ndarray, dt: float = 1.0) -> Dict:
        """
        تحليل السلسلة الزمنية في الفضاء الترددي.

        Parameters
        ----------
        prices : سلسلة الأسعار (أو العوائد)
        dt     : الفاصل الزمني (1 يوم افتراضياً)
        """
        n      = len(prices)
        fft    = np.fft.rfft(prices - prices.mean())
        freqs  = np.fft.rfftfreq(n, d=dt)
        amps   = np.abs(fft)

        # أعلى N ترددات
        top_idx = np.argsort(amps)[::-1][:self.top_n]
        self.dominant_frequencies = freqs[top_idx]
        self.dominant_amplitudes  = amps[top_idx]
        with np.errstate(divide="ignore"):
            self.dominant_periods = np.where(
                self.dominant_frequencies > 0,
                1.0 / self.dominant_frequencies,
                np.inf
            )

        return {
            "frequencies": self.dominant_frequencies,
            "amplitudes":  self.dominant_amplitudes,
            "periods_days":self.dominant_periods,
            "power_spectrum": amps ** 2,
        }

    def denoise(self, prices: np.ndarray, retain_pct: float = 0.1) -> np.ndarray:
        """إزالة الضجيج بالاحتفاظ بأقوى الترددات فقط."""
        fft  = np.fft.rfft(prices)
        amps = np.abs(fft)
        threshold = np.percentile(amps, (1 - retain_pct) * 100)
        fft_filtered = fft * (amps >= threshold)
        return np.fft.irfft(fft_filtered, n=len(prices))

    def reconstruct(self, n: int, sample_rate: float = 1.0) -> np.ndarray:
        """إعادة بناء السلسلة من المكونات الترددية الرئيسية."""
        t = np.arange(n) / sample_rate
        signal_r = np.zeros(n)
        for freq, amp in zip(self.dominant_frequencies, self.dominant_amplitudes):
            signal_r += amp * np.cos(2 * np.pi * freq * t)
        return signal_r


# ─────────────────────────────────────────────────────────────────
# 2. تحليل الموجلت (Wavelet)
# ─────────────────────────────────────────────────────────────────

class WaveletAnalyzer:
    """
    تحليل الموجلت متعدد المقاييس:
      - كشف نقاط التحول
      - تحليل التقلب عبر مقاييس زمنية مختلفة
      - إزالة الضجيج
    """

    def __init__(self, wavelet: str = "db4", levels: int = 5):
        self.wavelet = wavelet
        self.levels  = levels
        try:
            import pywt
            self.pywt = pywt
        except ImportError:
            raise ImportError("pip install pywavelets")

    def decompose(self, prices: np.ndarray) -> Dict:
        """تحليل الموجلت متعدد المستويات."""
        coeffs = self.pywt.wavedec(prices, self.wavelet, level=self.levels)
        return {
            "approximation":  coeffs[0],
            "details":        coeffs[1:],
            "n_levels":       self.levels,
        }

    def denoise(self, prices: np.ndarray, threshold_mode: str = "soft") -> np.ndarray:
        """إزالة الضجيج بتعيين عتبة على المعاملات."""
        coeffs = self.pywt.wavedec(prices, self.wavelet, level=self.levels)
        sigma  = np.median(np.abs(coeffs[-1])) / 0.6745
        thresh = sigma * np.sqrt(2 * np.log(len(prices)))

        def threshold_coeff(c):
            return self.pywt.threshold(c, thresh, mode=threshold_mode)

        denoised_coeffs = [coeffs[0]] + [threshold_coeff(c) for c in coeffs[1:]]
        return self.pywt.waverec(denoised_coeffs, self.wavelet)[:len(prices)]

    def energy_by_level(self, prices: np.ndarray) -> Dict:
        """توزيع الطاقة عبر مستويات الموجلت."""
        result = self.decompose(prices)
        energies = {f"D{i+1}": np.sum(d**2) for i, d in enumerate(result["details"])}
        energies["A"]  = np.sum(result["approximation"] ** 2)
        total = sum(energies.values())
        return {k: v / total for k, v in energies.items()}


# ─────────────────────────────────────────────────────────────────
# 3. نماذج ARIMA / SARIMA
# ─────────────────────────────────────────────────────────────────

class ARIMAForecaster:
    """
    نموذج ARIMA/SARIMA للتنبؤ بالأسعار.
    يدعم الاختيار التلقائي للمعاملات باستخدام AIC.
    """

    def __init__(self, order=(1, 1, 1), seasonal_order=(0, 0, 0, 0)):
        self.order          = order
        self.seasonal_order = seasonal_order
        self.model_fit      = None
        self.aic: float     = np.inf

    def fit(self, series: pd.Series, auto: bool = False) -> "ARIMAForecaster":
        try:
            from statsmodels.tsa.statespace.sarimax import SARIMAX
        except ImportError:
            raise ImportError("pip install statsmodels")

        if auto:
            self.order, self.aic = self._auto_select(series)

        model = SARIMAX(
            series,
            order=self.order,
            seasonal_order=self.seasonal_order,
            enforce_stationarity=False,
            enforce_invertibility=False
        )
        self.model_fit = model.fit(disp=False)
        self.aic = self.model_fit.aic
        return self

    def _auto_select(self, series: pd.Series) -> Tuple[Tuple, float]:
        """اختيار أفضل (p, d, q) بتقليل AIC."""
        from statsmodels.tsa.statespace.sarimax import SARIMAX
        best_aic   = np.inf
        best_order = (1, 1, 1)
        for p in range(0, 4):
            for d in range(0, 3):
                for q in range(0, 4):
                    try:
                        m = SARIMAX(series, order=(p, d, q),
                                    enforce_stationarity=False,
                                    enforce_invertibility=False)
                        r = m.fit(disp=False)
                        if r.aic < best_aic:
                            best_aic   = r.aic
                            best_order = (p, d, q)
                    except Exception:
                        pass
        return best_order, best_aic

    def forecast(self, steps: int = 5) -> pd.DataFrame:
        """التنبؤ بالخطوات المستقبلية مع فترات الثقة."""
        if self.model_fit is None:
            raise ValueError("يجب تدريب النموذج أولاً.")
        pred   = self.model_fit.forecast(steps=steps)
        conf   = self.model_fit.get_forecast(steps=steps).conf_int()
        result = pd.DataFrame({
            "forecast": pred.values,
            "lower_95": conf.iloc[:, 0].values,
            "upper_95": conf.iloc[:, 1].values,
        })
        return result

    def residual_diagnostics(self) -> Dict:
        """تشخيص البواقي."""
        resid = self.model_fit.resid
        _, p_ljung   = stats.normaltest(resid)
        _, p_adf     = (None, None)
        try:
            from statsmodels.stats.stattools import durbin_watson
            dw = durbin_watson(resid)
        except Exception:
            dw = None
        return {
            "mean":      resid.mean(),
            "std":       resid.std(),
            "skew":      stats.skew(resid),
            "kurtosis":  stats.kurtosis(resid),
            "normality_p": p_ljung,
            "durbin_watson": dw,
        }


# ─────────────────────────────────────────────────────────────────
# 4. GARCH لنمذجة التقلب
# ─────────────────────────────────────────────────────────────────

class GARCHModel:
    """
    نماذج GARCH لتقدير التقلب:
      - GARCH(1,1) الكلاسيكي
      - EGARCH (التقلب غير المتماثل)
      - GJR-GARCH
    """

    def __init__(self, p: int = 1, q: int = 1, model_type: str = "garch"):
        self.p          = p
        self.q          = q
        self.model_type = model_type
        self.model_fit  = None

    def fit(self, returns: pd.Series) -> "GARCHModel":
        try:
            from arch import arch_model
        except ImportError:
            raise ImportError("pip install arch")

        scaled = returns * 100  # arch يتوقع بالنسبة المئوية

        if self.model_type == "egarch":
            am = arch_model(scaled, vol="EGARCH", p=self.p, q=self.q, dist="normal")
        elif self.model_type == "gjr":
            am = arch_model(scaled, vol="GARCH",  p=self.p, o=1, q=self.q, dist="normal")
        else:
            am = arch_model(scaled, vol="GARCH",  p=self.p, q=self.q, dist="normal")

        self.model_fit = am.fit(disp="off")
        return self

    def forecast_volatility(self, horizon: int = 5) -> np.ndarray:
        """التنبؤ بالتقلب لـ horizon أيام."""
        fc = self.model_fit.forecast(horizon=horizon, reindex=False)
        return np.sqrt(fc.variance.values[-1]) / 100  # إعادة التحويل

    def conditional_volatility(self) -> pd.Series:
        """التقلب الشرطي التاريخي."""
        return self.model_fit.conditional_volatility / 100

    def value_at_risk(self, alpha: float = 0.05) -> float:
        """VaR عند مستوى ثقة (1 - alpha)."""
        vol  = self.conditional_volatility().iloc[-1]
        z    = stats.norm.ppf(alpha)
        return z * vol


# ─────────────────────────────────────────────────────────────────
# 5. Hidden Markov Model – تحديد أنظمة السوق
# ─────────────────────────────────────────────────────────────────

class MarketRegimeHMM:
    """
    HMM لتحديد حالات/أنظمة السوق:
      - حالة الصعود  (Bull Market)
      - حالة الهبوط  (Bear Market)
      - حالة التذبذب (Sideways)
    """

    def __init__(self, n_regimes: int = 3, n_iter: int = 100):
        self.n_regimes = n_regimes
        self.n_iter    = n_iter
        self.model     = None
        self.regime_labels: Dict[int, str] = {}

    def fit(self, returns: np.ndarray) -> "MarketRegimeHMM":
        try:
            from hmmlearn import hmm
        except ImportError:
            print("hmmlearn غير متاح. استخدام KMeans كبديل.")
            return self._fit_kmeans(returns)

        features = np.column_stack([
            returns,
            np.abs(returns),
            returns ** 2,
        ])

        self.model = hmm.GaussianHMM(
            n_components=self.n_regimes,
            covariance_type="full",
            n_iter=self.n_iter
        )
        self.model.fit(features)
        self._label_regimes(returns)
        return self

    def _fit_kmeans(self, returns: np.ndarray) -> "MarketRegimeHMM":
        features = np.column_stack([returns, np.abs(returns)])
        km = KMeans(n_clusters=self.n_regimes, random_state=42, n_init=10)
        self._kmeans = km.fit(features)
        self._label_regimes_kmeans(returns)
        return self

    def _label_regimes(self, returns: np.ndarray):
        states = self.model.predict(np.column_stack([
            returns, np.abs(returns), returns ** 2
        ]))
        regime_means = {}
        for s in range(self.n_regimes):
            mask = states == s
            if mask.sum() > 0:
                regime_means[s] = returns[mask].mean()

        sorted_states = sorted(regime_means, key=regime_means.get)
        if len(sorted_states) >= 3:
            self.regime_labels = {
                sorted_states[0]: "Bear",
                sorted_states[1]: "Sideways",
                sorted_states[2]: "Bull",
            }
        elif len(sorted_states) == 2:
            self.regime_labels = {sorted_states[0]: "Bear", sorted_states[1]: "Bull"}

    def _label_regimes_kmeans(self, returns: np.ndarray):
        states = self._kmeans.labels_
        regime_means = {s: returns[states == s].mean() for s in range(self.n_regimes)}
        sorted_s = sorted(regime_means, key=regime_means.get)
        labels = ["Bear", "Sideways", "Bull"][:len(sorted_s)]
        self.regime_labels = {s: l for s, l in zip(sorted_s, labels)}

    def predict(self, returns: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """التنبؤ بالنظام الحالي مع احتمالاته."""
        if self.model is not None:
            features = np.column_stack([returns, np.abs(returns), returns ** 2])
            states   = self.model.predict(features)
            probs    = self.model.predict_proba(features)
        else:
            features = np.column_stack([returns, np.abs(returns)])
            states   = self._kmeans.predict(features)
            probs    = np.eye(self.n_regimes)[states]

        labels = np.array([self.regime_labels.get(s, "Unknown") for s in states])
        return labels, probs

    def get_current_regime(self, recent_returns: np.ndarray) -> Dict:
        labels, probs = self.predict(recent_returns)
        current_label = labels[-1]
        current_probs = probs[-1]
        return {
            "regime": current_label,
            "probabilities": {
                self.regime_labels.get(i, f"S{i}"): float(current_probs[i])
                for i in range(self.n_regimes)
            },
            "trading_signal": {
                "Bull":    "BUY",
                "Bear":    "SELL",
                "Sideways":"HOLD"
            }.get(current_label, "HOLD")
        }


# ─────────────────────────────────────────────────────────────────
# 6. Kalman Filter – التتبع الديناميكي للسعر
# ─────────────────────────────────────────────────────────────────

class KalmanPriceFilter:
    """
    مرشح كالمان لتتبع الاتجاه الحقيقي للسعر وتصفية الضجيج.
    يُستخدم أيضاً في استراتيجية الأزواج (Pairs Trading).
    """

    def __init__(self, process_noise: float = 1e-4, measurement_noise: float = 1e-2):
        self.Q  = process_noise       # تشتت العملية
        self.R  = measurement_noise   # تشتت القياس
        self.P  = 1.0                 # مصفوفة التغاير
        self.x  = None                # التقدير الحالي
        self.K  = 0.0                 # كسب كالمان
        self.filtered_values: List[float] = []

    def reset(self, initial_value: float):
        self.x = initial_value
        self.P = 1.0
        self.filtered_values = [initial_value]

    def update(self, measurement: float) -> float:
        """تحديث تقدير كالمان بقياس جديد."""
        if self.x is None:
            self.reset(measurement)
            return self.x

        # خطوة التنبؤ
        x_pred = self.x
        P_pred = self.P + self.Q

        # خطوة التحديث
        self.K = P_pred / (P_pred + self.R)
        self.x = x_pred + self.K * (measurement - x_pred)
        self.P = (1 - self.K) * P_pred

        self.filtered_values.append(self.x)
        return self.x

    def filter_series(self, prices: np.ndarray) -> np.ndarray:
        """تصفية سلسلة أسعار كاملة."""
        self.reset(prices[0])
        for p in prices[1:]:
            self.update(p)
        return np.array(self.filtered_values)

    def get_trend_signal(self) -> str:
        """إشارة الاتجاه بناءً على كسب كالمان."""
        if len(self.filtered_values) < 2:
            return "NEUTRAL"
        momentum = self.filtered_values[-1] - self.filtered_values[-5] \
            if len(self.filtered_values) >= 5 else 0
        if momentum > 0:
            return "BUY"
        elif momentum < 0:
            return "SELL"
        return "HOLD"


# ─────────────────────────────────────────────────────────────────
# 7. Monte Carlo – محاكاة المخاطر
# ─────────────────────────────────────────────────────────────────

class MonteCarloSimulator:
    """
    محاكاة مونتي كارلو لمسارات الأسعار وقياس المخاطر:
      - محاكاة Geometric Brownian Motion (GBM)
      - حساب VaR و CVaR (Expected Shortfall)
      - تحليل سيناريوهات الانهيار
    """

    def __init__(self, n_simulations: int = 10_000, time_horizon: int = 252):
        self.n_sims   = n_simulations
        self.horizon  = time_horizon
        self.paths:   np.ndarray = None
        self.returns: np.ndarray = None

    def simulate_gbm(
        self,
        S0: float,
        mu: float,
        sigma: float,
        dt: float = 1/252
    ) -> np.ndarray:
        """
        محاكاة Geometric Brownian Motion.

        dS = μ·S·dt + σ·S·dW
        """
        Z     = np.random.standard_normal((self.n_sims, self.horizon))
        drift = (mu - 0.5 * sigma**2) * dt
        diff  = sigma * np.sqrt(dt) * Z
        log_ret = drift + diff
        self.paths = S0 * np.exp(np.cumsum(log_ret, axis=1))
        self.returns = self.paths[:, -1] / S0 - 1
        return self.paths

    def simulate_from_history(
        self,
        historical_returns: np.ndarray,
        S0: float,
        method: str = "bootstrap"
    ) -> np.ndarray:
        """محاكاة من البيانات التاريخية بالـ Bootstrap أو الحاكاة النظامية."""
        if method == "bootstrap":
            sampled = np.random.choice(historical_returns,
                                       (self.n_sims, self.horizon), replace=True)
        else:
            mu    = historical_returns.mean()
            sigma = historical_returns.std()
            sampled = np.random.normal(mu, sigma, (self.n_sims, self.horizon))

        self.paths   = S0 * np.exp(np.cumsum(sampled, axis=1))
        self.returns = self.paths[:, -1] / S0 - 1
        return self.paths

    def value_at_risk(self, alpha: float = 0.05) -> float:
        """Value at Risk عند مستوى (1 - alpha)."""
        if self.returns is None:
            raise ValueError("يجب تشغيل المحاكاة أولاً.")
        return float(np.percentile(self.returns, alpha * 100))

    def conditional_var(self, alpha: float = 0.05) -> float:
        """CVaR (Expected Shortfall) – متوسط الخسائر ما وراء VaR."""
        if self.returns is None:
            raise ValueError("يجب تشغيل المحاكاة أولاً.")
        var   = self.value_at_risk(alpha)
        cvar  = float(self.returns[self.returns <= var].mean())
        return cvar

    def probability_of_profit(self) -> float:
        """احتمال تحقيق ربح."""
        return float((self.returns > 0).mean())

    def summary_statistics(self) -> Dict:
        """ملخص إحصاءات المحاكاة."""
        return {
            "mean_return":     float(self.returns.mean()),
            "std_return":      float(self.returns.std()),
            "min_return":      float(self.returns.min()),
            "max_return":      float(self.returns.max()),
            "VaR_5pct":        self.value_at_risk(0.05),
            "CVaR_5pct":       self.conditional_var(0.05),
            "prob_profit":     self.probability_of_profit(),
            "sharpe_ratio":    float(self.returns.mean() / (self.returns.std() + 1e-9)),
            "skewness":        float(stats.skew(self.returns)),
            "kurtosis":        float(stats.kurtosis(self.returns)),
        }


# ─────────────────────────────────────────────────────────────────
# 8. PCA + ICA لاستخراج العوامل الخفية
# ─────────────────────────────────────────────────────────────────

class FactorAnalyzer:
    """
    تحليل العوامل الخفية في بيانات السوق:
      - PCA: العوامل المتعامدة ذات الأكبر تباين
      - ICA: المكونات المستقلة إحصائياً (العوامل الاقتصادية)
    """

    def __init__(self, n_factors: int = 5):
        self.n_factors = n_factors
        self.pca = PCA(n_components=n_factors)
        self.ica = FastICA(n_components=n_factors, random_state=42, max_iter=500)
        self.scaler = StandardScaler()
        self.pca_factors: np.ndarray = None
        self.ica_factors: np.ndarray = None

    def fit_transform(self, returns_matrix: np.ndarray) -> Dict:
        """
        تحليل مصفوفة العوائد.

        Parameters
        ----------
        returns_matrix : (T, n_assets) عوائد الأصول
        """
        X_scaled = self.scaler.fit_transform(returns_matrix)

        self.pca_factors = self.pca.fit_transform(X_scaled)
        try:
            self.ica_factors = self.ica.fit_transform(X_scaled)
        except Exception:
            self.ica_factors = self.pca_factors.copy()

        return {
            "pca_factors":             self.pca_factors,
            "ica_factors":             self.ica_factors,
            "pca_explained_variance":  self.pca.explained_variance_ratio_,
            "pca_loadings":            self.pca.components_,
        }

    def get_factor_signals(self) -> np.ndarray:
        """إشارات التداول بناءً على العوامل الرئيسية."""
        if self.pca_factors is None:
            raise ValueError("يجب تدريب النموذج أولاً.")
        # استخدام momentum العوامل
        factor_returns = np.diff(self.pca_factors, axis=0)
        signals = np.sign(factor_returns[-1])  # آخر خطوة
        return signals


# ─────────────────────────────────────────────────────────────────
# 9. Pairs Trading – استراتيجية الأزواج
# ─────────────────────────────────────────────────────────────────

class PairsTradingStrategy:
    """
    استراتيجية الأزواج المتكاملة:
      1. اختبار Cointegration (Engle-Granger)
      2. حساب انتشار الأسعار (Spread)
      3. توليد إشارات التداول
      4. تحسين نافذة الدخول/الخروج
    """

    def __init__(self, z_entry: float = 2.0, z_exit: float = 0.5,
                 lookback: int = 60):
        self.z_entry  = z_entry
        self.z_exit   = z_exit
        self.lookback = lookback
        self.hedge_ratio: float = 1.0
        self.is_cointegrated: bool = False

    def test_cointegration(
        self,
        price1: np.ndarray,
        price2: np.ndarray
    ) -> Dict:
        """اختبار التكامل المشترك بين زوج من الأسعار."""
        try:
            from statsmodels.tsa.stattools import coint
            t_stat, p_value, crit_values = coint(price1, price2)
            self.is_cointegrated = p_value < 0.05
            return {
                "t_statistic":   t_stat,
                "p_value":       p_value,
                "critical_values": {"1%": crit_values[0], "5%": crit_values[1], "10%": crit_values[2]},
                "is_cointegrated": self.is_cointegrated,
            }
        except ImportError:
            # تبسيط بدون statsmodels
            corr = np.corrcoef(price1, price2)[0, 1]
            self.is_cointegrated = abs(corr) > 0.8
            return {"correlation": corr, "is_cointegrated": self.is_cointegrated}

    def fit(self, price1: np.ndarray, price2: np.ndarray) -> "PairsTradingStrategy":
        """حساب نسبة التحوط (Hedge Ratio)."""
        from numpy.polynomial import polynomial as P
        log_p1 = np.log(price1)
        log_p2 = np.log(price2)

        # OLS لحساب Beta
        X = np.column_stack([log_p2, np.ones(len(log_p2))])
        beta = np.linalg.lstsq(X, log_p1, rcond=None)[0]
        self.hedge_ratio = beta[0]
        return self

    def compute_spread(self, price1: np.ndarray, price2: np.ndarray) -> np.ndarray:
        """حساب انتشار السعر المُعدَّل بنسبة التحوط."""
        return np.log(price1) - self.hedge_ratio * np.log(price2)

    def generate_signals(
        self,
        price1: np.ndarray,
        price2: np.ndarray
    ) -> pd.DataFrame:
        """
        توليد إشارات التداول بناءً على Z-Score للانتشار.

        إشارات:
          +1: شراء asset1، بيع asset2  (spread منخفض جداً)
          -1: بيع asset1، شراء asset2  (spread مرتفع جداً)
           0: إغلاق المركز
        """
        spread = self.compute_spread(price1, price2)
        z_score = pd.Series(spread).rolling(self.lookback).apply(
            lambda x: (x.iloc[-1] - x.mean()) / (x.std() + 1e-9)
        )

        signals = pd.DataFrame({
            "spread":  spread,
            "z_score": z_score.values,
            "signal":  0,
        })

        long_entry  = z_score < -self.z_entry
        short_entry = z_score >  self.z_entry
        long_exit   = z_score.between(-self.z_exit, self.z_exit)
        short_exit  = z_score.between(-self.z_exit, self.z_exit)

        signals.loc[long_entry,  "signal"] =  1
        signals.loc[short_entry, "signal"] = -1
        signals.loc[long_exit | short_exit, "signal"] = 0

        return signals

    def backtest(
        self,
        price1: np.ndarray,
        price2: np.ndarray,
        initial_capital: float = 100_000
    ) -> Dict:
        """اختبار الاستراتيجية على البيانات التاريخية."""
        signals = self.generate_signals(price1, price2)
        r1 = pd.Series(price1).pct_change().fillna(0).values
        r2 = pd.Series(price2).pct_change().fillna(0).values

        portfolio_returns = []
        position = 0
        for i in range(1, len(signals)):
            sig = signals["signal"].iloc[i - 1]
            if sig == 1:
                port_ret = r1[i] - self.hedge_ratio * r2[i]
            elif sig == -1:
                port_ret = -r1[i] + self.hedge_ratio * r2[i]
            else:
                port_ret = 0.0
            portfolio_returns.append(port_ret)

        portfolio_returns = np.array(portfolio_returns)
        cumulative = (1 + portfolio_returns).cumprod()
        total_ret  = cumulative[-1] - 1 if len(cumulative) > 0 else 0
        sharpe     = (portfolio_returns.mean() / (portfolio_returns.std() + 1e-9)) * np.sqrt(252)
        max_dd     = (cumulative / cumulative.cummax() - 1).min() if len(cumulative) > 0 else 0

        return {
            "total_return_pct": total_ret * 100,
            "sharpe_ratio":     sharpe,
            "max_drawdown_pct": max_dd * 100,
            "n_trades":         (signals["signal"].diff() != 0).sum(),
        }


# ─────────────────────────────────────────────────────────────────
# مثال التشغيل
# ─────────────────────────────────────────────────────────────────

def demo_advanced_analysis():
    print("=" * 60)
    print("  التحليل المتطور لأنظمة التداول الآلي")
    print("=" * 60)

    import sys, os
    sys.path.insert(0, os.path.dirname(__file__))
    from data_preprocessing import (
        load_market_data, clean_data, add_technical_features
    )

    df = clean_data(load_market_data("AAPL", "2018-01-01", "2024-01-01"))
    prices  = df["Close"].values
    returns = pd.Series(prices).pct_change().dropna().values

    # ── فورييه ────────────────────────────────────────────────
    print("\n[1] تحليل فورييه...")
    fa = FourierAnalyzer(top_n_frequencies=5)
    result = fa.analyze(prices)
    for f, a, p in zip(result["frequencies"][:5], result["amplitudes"][:5], result["periods_days"][:5]):
        if np.isfinite(p):
            print(f"    تردد={f:.4f} | سعة={a:.2f} | دورة={p:.1f} يوم")
    denoised = fa.denoise(prices, retain_pct=0.1)
    print(f"    إزالة الضجيج – ارتباط الأصلي/المُصفَّى: "
          f"{np.corrcoef(prices, denoised[:len(prices)])[0,1]:.4f}")

    # ── الموجلت ───────────────────────────────────────────────
    print("\n[2] تحليل الموجلت...")
    try:
        wa = WaveletAnalyzer(wavelet="db4", levels=4)
        energy = wa.energy_by_level(prices)
        for lvl, e in energy.items():
            print(f"    {lvl}: {e:.4f}")
        denoised_wt = wa.denoise(prices)
        print(f"    شكل بعد إزالة الضجيج: {denoised_wt.shape}")
    except ImportError:
        print("    pywavelets غير مثبّت. تخطي.")

    # ── ARIMA ─────────────────────────────────────────────────
    print("\n[3] تحليل ARIMA...")
    arima = ARIMAForecaster(order=(2, 1, 2))
    try:
        arima.fit(pd.Series(prices[-500:]))
        fc = arima.forecast(steps=5)
        print("    توقعات 5 أيام:")
        print(fc.to_string())
    except Exception as e:
        print(f"    خطأ: {e}")

    # ── GARCH ─────────────────────────────────────────────────
    print("\n[4] نمذجة التقلب GARCH...")
    try:
        garch = GARCHModel(p=1, q=1)
        garch.fit(pd.Series(returns[-500:]))
        fc_vol = garch.forecast_volatility(horizon=5)
        print(f"    توقع التقلب اليومي (5 أيام): {fc_vol}")
        var_5 = garch.value_at_risk(alpha=0.05)
        print(f"    VaR (95%): {var_5:.4f}")
    except ImportError:
        print("    arch غير مثبّت. تخطي.")

    # ── HMM ───────────────────────────────────────────────────
    print("\n[5] تحديد أنظمة السوق (HMM)...")
    hmm_model = MarketRegimeHMM(n_regimes=3)
    hmm_model.fit(returns)
    regime_info = hmm_model.get_current_regime(returns[-60:])
    print(f"    النظام الحالي: {regime_info['regime']}")
    print(f"    إشارة التداول: {regime_info['trading_signal']}")
    for regime, prob in regime_info["probabilities"].items():
        print(f"      {regime}: {prob:.2%}")

    # ── Kalman Filter ──────────────────────────────────────────
    print("\n[6] مرشح كالمان...")
    kf = KalmanPriceFilter(process_noise=1e-4, measurement_noise=0.01)
    filtered = kf.filter_series(prices)
    print(f"    السعر الأصلي (آخر 5):  {prices[-5:]}")
    print(f"    السعر المُصفَّى (آخر 5): {filtered[-5:].round(2)}")
    print(f"    إشارة الاتجاه: {kf.get_trend_signal()}")

    # ── Monte Carlo ────────────────────────────────────────────
    print("\n[7] محاكاة مونتي كارلو...")
    mu    = returns.mean() * 252
    sigma = returns.std()  * np.sqrt(252)
    mc    = MonteCarloSimulator(n_simulations=5000, time_horizon=252)
    mc.simulate_gbm(prices[-1], mu, sigma)
    stats_mc = mc.summary_statistics()
    print(f"    VaR 5%       : {stats_mc['VaR_5pct']:.4f}")
    print(f"    CVaR 5%      : {stats_mc['CVaR_5pct']:.4f}")
    print(f"    احتمال الربح : {stats_mc['prob_profit']:.2%}")
    print(f"    نسبة شارب    : {stats_mc['sharpe_ratio']:.4f}")

    # ── PCA ───────────────────────────────────────────────────
    print("\n[8] تحليل العوامل (PCA)...")
    df2  = clean_data(load_market_data("MSFT", "2018-01-01", "2024-01-01"))
    df3  = clean_data(load_market_data("GOOGL", "2018-01-01", "2024-01-01"))
    min_len = min(len(df), len(df2), len(df3))
    ret_matrix = np.column_stack([
        pd.Series(df["Close"].values[:min_len]).pct_change().fillna(0).values,
        pd.Series(df2["Close"].values[:min_len]).pct_change().fillna(0).values,
        pd.Series(df3["Close"].values[:min_len]).pct_change().fillna(0).values,
    ])
    fa2 = FactorAnalyzer(n_factors=3)
    factors = fa2.fit_transform(ret_matrix)
    print(f"    نسب التباين المفسَّر: "
          f"{factors['pca_explained_variance'].round(4)}")

    # ── Pairs Trading ──────────────────────────────────────────
    print("\n[9] استراتيجية الأزواج (AAPL / MSFT)...")
    p1 = df["Close"].values[:min_len]
    p2 = df2["Close"].values[:min_len]
    pt = PairsTradingStrategy(z_entry=2.0, z_exit=0.5, lookback=60)
    coint_test = pt.test_cointegration(p1, p2)
    print(f"    p-value التكامل: {coint_test.get('p_value', 'N/A')}")
    print(f"    متكاملان: {coint_test['is_cointegrated']}")
    pt.fit(p1, p2)
    bt = pt.backtest(p1, p2)
    print(f"    عائد الاختبار : {bt['total_return_pct']:.2f}%")
    print(f"    نسبة شارب     : {bt['sharpe_ratio']:.4f}")
    print(f"    أقصى تراجع    : {bt['max_drawdown_pct']:.2f}%")

    print("\n✅ اكتمل التحليل المتطور بنجاح.")


if __name__ == "__main__":
    demo_advanced_analysis()
