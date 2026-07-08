"""
====================================================================
 نظام إدارة المخاطر لأنظمة التداول الآلي
 Risk Management System for Automated Trading
====================================================================
الوحدات المشمولة:
  1. تحديد حجم المركز (Position Sizing)
     - Kelly Criterion (الكامل والجزئي)
     - Fixed Risk per Trade
     - Volatility-Based Sizing
  2. حساب المخاطر (Risk Metrics)
     - Value at Risk (VaR) – Historical, Parametric, Monte Carlo
     - Conditional VaR (CVaR / Expected Shortfall)
     - Maximum Drawdown
     - Sharpe, Sortino, Calmar Ratios
  3. إدارة المحفظة (Portfolio Management)
     - Mean-Variance Optimization (Markowitz)
     - Risk Parity
     - Maximum Sharpe
  4. نظام وقف الخسارة (Stop-Loss System)
     - ATR-based Dynamic Stop
     - Trailing Stop
     - Time-Based Exit
  5. نظام الرقابة والإنذار (Monitoring & Alerts)
====================================================================
"""

import numpy as np
import pandas as pd
from scipy import optimize, stats
from typing import Dict, List, Optional, Tuple
import warnings
warnings.filterwarnings("ignore")


# ─────────────────────────────────────────────────────────────────
# 1. تحديد حجم المركز
# ─────────────────────────────────────────────────────────────────

class PositionSizer:
    """
    حاسبة حجم المركز المثلى باستخدام عدة طرق:
      1. Kelly Criterion
      2. Fixed Fractional (% ثابتة من رأس المال)
      3. Volatility-Adjusted
      4. ATR-Based
    """

    def __init__(self, account_balance: float = 100_000.0):
        self.balance = account_balance

    def kelly_criterion(
        self,
        win_rate: float,
        avg_win: float,
        avg_loss: float,
        fraction: float = 0.25    # 25% من Kelly الكامل (Half Kelly)
    ) -> Dict:
        """
        معيار Kelly لتحديد الحجم الأمثل.

        f* = W/L - (1-W)/W    حيث:
            W = معدل الفوز
            W/L = نسبة الربح/الخسارة
        """
        if avg_loss <= 0 or win_rate <= 0 or win_rate >= 1:
            return {"kelly_fraction": 0, "position_size": 0}

        b      = avg_win / avg_loss      # نسبة المكسب إلى الخسارة
        f_star = (b * win_rate - (1 - win_rate)) / b  # Kelly الكامل
        f_safe = max(0, f_star * fraction)             # Kelly الجزئي

        position_size = self.balance * f_safe

        return {
            "kelly_fraction":    round(f_star, 4),
            "safe_fraction":     round(f_safe, 4),
            "position_size":     round(position_size, 2),
            "max_risk":          round(position_size * (avg_loss / 100), 2),
            "expected_growth":   round(win_rate * np.log(1 + f_safe * b) +
                                       (1 - win_rate) * np.log(1 - f_safe), 6)
        }

    def fixed_fractional(
        self,
        risk_pct: float = 0.02,    # 2% من رأس المال لكل صفقة
        stop_loss_pct: float = 0.05
    ) -> Dict:
        """
        طريقة الكسر الثابت: المخاطرة بـ risk_pct من رأس المال لكل صفقة.
        """
        max_loss_amount = self.balance * risk_pct
        position_size   = max_loss_amount / stop_loss_pct if stop_loss_pct > 0 else 0

        return {
            "position_size":    round(position_size, 2),
            "max_loss_amount":  round(max_loss_amount, 2),
            "risk_pct":         risk_pct,
            "pct_of_balance":   round(position_size / self.balance, 4)
        }

    def volatility_adjusted(
        self,
        price: float,
        volatility_daily: float,
        target_risk_pct: float = 0.01    # 1% يومياً
    ) -> Dict:
        """
        حجم مُعدَّل بالتقلب: الأصول الأكثر تقلباً تأخذ مراكز أصغر.
        """
        target_dollar_risk = self.balance * target_risk_pct
        dollar_volatility  = price * volatility_daily
        n_shares = int(target_dollar_risk / (dollar_volatility + 1e-9))
        position_value = n_shares * price

        return {
            "n_shares":          n_shares,
            "position_value":    round(position_value, 2),
            "pct_of_balance":    round(position_value / self.balance, 4),
            "daily_risk_target": round(target_dollar_risk, 2)
        }

    def atr_based(
        self,
        price: float,
        atr: float,
        risk_pct: float = 0.02,
        atr_multiplier: float = 2.0
    ) -> Dict:
        """
        حجم قائم على ATR: وقف الخسارة = N × ATR.
        """
        stop_distance  = atr * atr_multiplier
        max_loss       = self.balance * risk_pct
        n_shares       = int(max_loss / (stop_distance + 1e-9))
        stop_loss_price = price - stop_distance

        return {
            "n_shares":         n_shares,
            "position_value":   round(n_shares * price, 2),
            "stop_loss_price":  round(stop_loss_price, 4),
            "stop_distance":    round(stop_distance, 4),
            "max_loss":         round(max_loss, 2)
        }


# ─────────────────────────────────────────────────────────────────
# 2. مقاييس المخاطر
# ─────────────────────────────────────────────────────────────────

class RiskMetrics:
    """
    حساب شامل لمقاييس المخاطر والأداء:
      - VaR (تاريخي، بارامتري، مونتي كارلو)
      - CVaR / Expected Shortfall
      - Maximum Drawdown
      - Sharpe / Sortino / Calmar / Omega Ratios
      - Beta / Alpha / Information Ratio
    """

    def __init__(self, risk_free_rate: float = 0.04):
        self.rf = risk_free_rate / 252   # معدل خالٍ من المخاطر يومياً

    def var_historical(
        self,
        returns: np.ndarray,
        alpha: float = 0.05
    ) -> float:
        """VaR التاريخي عند مستوى ثقة (1 - alpha)."""
        return float(np.percentile(returns, alpha * 100))

    def var_parametric(
        self,
        returns: np.ndarray,
        alpha: float = 0.05
    ) -> float:
        """VaR البارامتري (افتراض التوزيع الطبيعي)."""
        mu  = returns.mean()
        sig = returns.std()
        z   = stats.norm.ppf(alpha)
        return float(mu + z * sig)

    def var_monte_carlo(
        self,
        returns: np.ndarray,
        alpha: float = 0.05,
        n_sims: int = 10_000
    ) -> float:
        """VaR مونتي كارلو."""
        mu    = returns.mean()
        sigma = returns.std()
        sim   = np.random.normal(mu, sigma, n_sims)
        return float(np.percentile(sim, alpha * 100))

    def cvar(
        self,
        returns: np.ndarray,
        alpha: float = 0.05
    ) -> float:
        """CVaR (Expected Shortfall) – متوسط الخسائر ما وراء VaR."""
        var = self.var_historical(returns, alpha)
        return float(returns[returns <= var].mean())

    def max_drawdown(self, returns: np.ndarray) -> Dict:
        """أقصى تراجع وفترة الاسترداد."""
        cumulative = (1 + returns).cumprod()
        peak       = cumulative.cummax()
        drawdown   = (cumulative - peak) / peak

        max_dd     = float(drawdown.min())
        dd_idx     = drawdown.idxmin() if hasattr(drawdown, "idxmin") else np.argmin(drawdown)
        duration   = int(np.argmin(drawdown)) - int(
            np.argmax(cumulative[:np.argmin(drawdown)])
        ) if len(drawdown) > 1 else 0

        return {
            "max_drawdown":        max_dd,
            "max_drawdown_pct":    round(max_dd * 100, 2),
            "drawdown_duration":   duration,
            "current_drawdown":    float(drawdown.iloc[-1]) if hasattr(drawdown, "iloc") else float(drawdown[-1])
        }

    def sharpe_ratio(
        self,
        returns: np.ndarray,
        annualize: bool = True
    ) -> float:
        """نسبة شارب المُعدَّلة بالمخاطر."""
        excess = returns - self.rf
        sr = excess.mean() / (excess.std() + 1e-9)
        return float(sr * np.sqrt(252) if annualize else sr)

    def sortino_ratio(
        self,
        returns: np.ndarray,
        annualize: bool = True
    ) -> float:
        """نسبة سورتينو – تعاقب الانحراف السلبي فقط."""
        excess    = returns - self.rf
        neg       = excess[excess < 0]
        downside  = neg.std() if len(neg) > 0 else 1e-9
        sr        = excess.mean() / downside
        return float(sr * np.sqrt(252) if annualize else sr)

    def calmar_ratio(self, returns: np.ndarray) -> float:
        """نسبة كالمار = العائد السنوي / أقصى تراجع."""
        annual_return = (1 + returns.mean()) ** 252 - 1
        dd = self.max_drawdown(returns)["max_drawdown"]
        return float(annual_return / (abs(dd) + 1e-9))

    def omega_ratio(self, returns: np.ndarray, threshold: float = 0) -> float:
        """نسبة أوميجا = المكاسب / الخسائر."""
        gains  = returns[returns > threshold] - threshold
        losses = threshold - returns[returns <= threshold]
        return float(gains.sum() / (losses.sum() + 1e-9))

    def beta_alpha(
        self,
        portfolio_returns: np.ndarray,
        benchmark_returns: np.ndarray
    ) -> Dict:
        """Beta و Alpha مقارنة بالمرجع."""
        if len(portfolio_returns) != len(benchmark_returns):
            n = min(len(portfolio_returns), len(benchmark_returns))
            portfolio_returns  = portfolio_returns[-n:]
            benchmark_returns  = benchmark_returns[-n:]

        cov_matrix = np.cov(portfolio_returns, benchmark_returns)
        beta       = cov_matrix[0, 1] / (cov_matrix[1, 1] + 1e-9)
        alpha      = (portfolio_returns.mean() - benchmark_returns.mean()) * 252

        correlation = np.corrcoef(portfolio_returns, benchmark_returns)[0, 1]
        ir_num      = (portfolio_returns - benchmark_returns).mean()
        ir_den      = (portfolio_returns - benchmark_returns).std() + 1e-9
        info_ratio  = ir_num / ir_den * np.sqrt(252)

        return {
            "beta":             round(float(beta), 4),
            "alpha_annual":     round(float(alpha), 4),
            "correlation":      round(float(correlation), 4),
            "information_ratio":round(float(info_ratio), 4),
        }

    def full_report(
        self,
        returns: np.ndarray,
        benchmark: Optional[np.ndarray] = None
    ) -> Dict:
        """تقرير مخاطر شامل."""
        returns = np.array(returns)
        annual_return = (1 + returns.mean()) ** 252 - 1
        annual_vol    = returns.std() * np.sqrt(252)

        report = {
            "annual_return":        round(annual_return * 100, 2),
            "annual_volatility":    round(annual_vol    * 100, 2),
            "sharpe_ratio":         round(self.sharpe_ratio(returns),  4),
            "sortino_ratio":        round(self.sortino_ratio(returns), 4),
            "calmar_ratio":         round(self.calmar_ratio(returns),  4),
            "omega_ratio":          round(self.omega_ratio(returns),   4),
            "VaR_5pct_daily":       round(self.var_historical(returns, 0.05) * 100, 4),
            "CVaR_5pct_daily":      round(self.cvar(returns, 0.05) * 100,          4),
            **{k: v for k, v in self.max_drawdown(returns).items()},
            "skewness":             round(float(stats.skew(returns)),     4),
            "kurtosis":             round(float(stats.kurtosis(returns)), 4),
            "win_rate":             round(float((returns > 0).mean()),    4),
            "profit_factor":        round(float(returns[returns > 0].sum() /
                                               (abs(returns[returns < 0].sum()) + 1e-9)), 4),
        }

        if benchmark is not None:
            report.update(self.beta_alpha(returns, benchmark))

        return report


# ─────────────────────────────────────────────────────────────────
# 3. تحسين المحفظة (Portfolio Optimization)
# ─────────────────────────────────────────────────────────────────

class PortfolioOptimizer:
    """
    تحسين المحفظة بعدة أساليب:
      1. Mean-Variance (Markowitz) – أقصى شارب
      2. Minimum Variance
      3. Risk Parity (Equal Risk Contribution)
      4. Maximum Diversification
    """

    def __init__(
        self,
        returns_matrix: np.ndarray,
        asset_names: Optional[List[str]] = None,
        risk_free_rate: float = 0.04
    ):
        self.R         = returns_matrix           # (T, n_assets)
        self.mu        = returns_matrix.mean(axis=0) * 252
        self.cov       = np.cov(returns_matrix.T) * 252
        self.n         = returns_matrix.shape[1]
        self.names     = asset_names or [f"Asset_{i}" for i in range(self.n)]
        self.rf        = risk_free_rate

    def _portfolio_stats(self, w: np.ndarray) -> Tuple[float, float, float]:
        ret  = float(np.dot(w, self.mu))
        vol  = float(np.sqrt(w @ self.cov @ w))
        sr   = (ret - self.rf) / (vol + 1e-9)
        return ret, vol, sr

    def maximize_sharpe(self) -> Dict:
        """أوزان المحفظة ذات أقصى نسبة شارب."""
        def neg_sharpe(w):
            _, _, sr = self._portfolio_stats(w)
            return -sr

        constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}]
        bounds      = [(0, 1)] * self.n
        w0          = np.ones(self.n) / self.n

        result = optimize.minimize(
            neg_sharpe, w0, method="SLSQP",
            bounds=bounds, constraints=constraints,
            options={"ftol": 1e-9, "maxiter": 1000}
        )

        if result.success:
            w = result.x
        else:
            w = w0

        ret, vol, sr = self._portfolio_stats(w)
        return {
            "method":      "Maximum Sharpe",
            "weights":     dict(zip(self.names, w.round(4))),
            "return":      round(ret * 100, 4),
            "volatility":  round(vol * 100, 4),
            "sharpe":      round(sr, 4),
        }

    def minimum_variance(self) -> Dict:
        """أوزان أدنى تذبذب ممكن."""
        def portfolio_vol(w):
            return float(np.sqrt(w @ self.cov @ w))

        constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}]
        bounds      = [(0, 1)] * self.n
        w0          = np.ones(self.n) / self.n

        result = optimize.minimize(
            portfolio_vol, w0, method="SLSQP",
            bounds=bounds, constraints=constraints
        )
        w = result.x if result.success else w0
        ret, vol, sr = self._portfolio_stats(w)

        return {
            "method":     "Minimum Variance",
            "weights":    dict(zip(self.names, w.round(4))),
            "return":     round(ret * 100, 4),
            "volatility": round(vol * 100, 4),
            "sharpe":     round(sr, 4),
        }

    def risk_parity(self) -> Dict:
        """
        توزيع متساوٍ للمخاطر بين الأصول.
        مساهمة كل أصل في مخاطر المحفظة = 1/n.
        """
        def risk_contrib_error(w):
            w     = np.abs(w) / np.sum(np.abs(w))
            vol   = np.sqrt(w @ self.cov @ w)
            mrc   = (self.cov @ w) / (vol + 1e-9)
            rc    = w * mrc
            target = np.full(self.n, vol / self.n)
            return np.sum((rc - target) ** 2)

        w0     = np.ones(self.n) / self.n
        result = optimize.minimize(
            risk_contrib_error, w0, method="SLSQP",
            bounds=[(0.01, 0.99)] * self.n,
            constraints=[{"type": "eq", "fun": lambda w: np.sum(w) - 1}],
            options={"maxiter": 1000}
        )
        w = np.abs(result.x) / np.sum(np.abs(result.x))
        ret, vol, sr = self._portfolio_stats(w)

        return {
            "method":     "Risk Parity",
            "weights":    dict(zip(self.names, w.round(4))),
            "return":     round(ret * 100, 4),
            "volatility": round(vol * 100, 4),
            "sharpe":     round(sr, 4),
        }

    def efficient_frontier(self, n_points: int = 50) -> pd.DataFrame:
        """توليد حدود الكفاءة."""
        target_returns = np.linspace(self.mu.min(), self.mu.max(), n_points)
        results = []

        for target in target_returns:
            def port_vol(w):
                return float(np.sqrt(w @ self.cov @ w))

            constraints = [
                {"type": "eq", "fun": lambda w: np.sum(w) - 1},
                {"type": "eq", "fun": lambda w: np.dot(w, self.mu) - target}
            ]
            res = optimize.minimize(
                port_vol, np.ones(self.n) / self.n,
                method="SLSQP",
                bounds=[(0, 1)] * self.n,
                constraints=constraints
            )
            if res.success:
                vol = res.fun
                sr  = (target - self.rf) / (vol + 1e-9)
                results.append({
                    "return":     target * 100,
                    "volatility": vol    * 100,
                    "sharpe":     sr
                })

        return pd.DataFrame(results)

    def compare_strategies(self) -> pd.DataFrame:
        """مقارنة جميع استراتيجيات التحسين."""
        strategies = [
            self.maximize_sharpe(),
            self.minimum_variance(),
            self.risk_parity(),
        ]
        return pd.DataFrame([{
            "Method":     s["method"],
            "Return %":   s["return"],
            "Volatility%":s["volatility"],
            "Sharpe":     s["sharpe"],
        } for s in strategies])


# ─────────────────────────────────────────────────────────────────
# 4. نظام وقف الخسارة الديناميكي
# ─────────────────────────────────────────────────────────────────

class StopLossManager:
    """
    نظام شامل لإدارة وقف الخسارة:
      - ATR-based Stop (وقف قائم على التقلب)
      - Trailing Stop (وقف متحرك)
      - Time-based Exit (خروج بالزمن)
      - Chandelier Exit
    """

    def __init__(self, atr_multiplier: float = 2.0, trailing_pct: float = 0.05):
        self.atr_multiplier = atr_multiplier
        self.trailing_pct   = trailing_pct

    def atr_stop(
        self,
        entry_price: float,
        current_atr: float,
        direction: str = "long"
    ) -> Dict:
        """وقف قائم على ATR."""
        stop = entry_price - self.atr_multiplier * current_atr \
               if direction == "long" else \
               entry_price + self.atr_multiplier * current_atr

        risk_pct = abs(stop - entry_price) / entry_price
        return {
            "stop_price":    round(stop, 4),
            "risk_pct":      round(risk_pct * 100, 2),
            "method":        "ATR-Based",
        }

    def trailing_stop(
        self,
        prices: np.ndarray,
        direction: str = "long"
    ) -> float:
        """وقف متحرك (Trailing Stop)."""
        if direction == "long":
            peak  = prices.max()
            return float(peak * (1 - self.trailing_pct))
        else:
            trough = prices.min()
            return float(trough * (1 + self.trailing_pct))

    def chandelier_exit(
        self,
        prices: np.ndarray,
        atr: float,
        n: int = 22,
        direction: str = "long"
    ) -> float:
        """Chandelier Exit – وقف قائم على أعلى/أدنى N فترة."""
        if direction == "long":
            highest = prices[-n:].max()
            return float(highest - self.atr_multiplier * atr)
        else:
            lowest = prices[-n:].min()
            return float(lowest + self.atr_multiplier * atr)

    def check_exits(
        self,
        current_price: float,
        entry_price: float,
        stop_loss: float,
        take_profit: Optional[float] = None,
        holding_days: int = 0,
        max_holding_days: int = 20,
        direction: str = "long"
    ) -> Dict:
        """
        فحص شروط الخروج المتعددة.
        """
        exit_signal = False
        exit_reason = None

        if direction == "long":
            if current_price <= stop_loss:
                exit_signal = True
                exit_reason = "STOP_LOSS"
            elif take_profit and current_price >= take_profit:
                exit_signal = True
                exit_reason = "TAKE_PROFIT"
        else:
            if current_price >= stop_loss:
                exit_signal = True
                exit_reason = "STOP_LOSS"
            elif take_profit and current_price <= take_profit:
                exit_signal = True
                exit_reason = "TAKE_PROFIT"

        if holding_days >= max_holding_days and not exit_signal:
            exit_signal = True
            exit_reason = "TIME_EXIT"

        pnl_pct = (current_price - entry_price) / entry_price * 100 \
                  if direction == "long" else \
                  (entry_price - current_price) / entry_price * 100

        return {
            "exit_signal":  exit_signal,
            "exit_reason":  exit_reason,
            "current_pnl_pct": round(pnl_pct, 2),
            "distance_to_stop": round(abs(current_price - stop_loss), 4),
        }


# ─────────────────────────────────────────────────────────────────
# 5. نظام الرقابة والإنذار
# ─────────────────────────────────────────────────────────────────

class RiskMonitor:
    """
    رقابة مستمرة على المخاطر مع نظام تنبيهات متدرج:
      🟡 تحذير (Warning)  – تجاوز 75% من الحد
      🟠 تنبيه  (Alert)   – تجاوز 90% من الحد
      🔴 خطر   (Critical)– تجاوز الحد الأقصى
    """

    def __init__(
        self,
        max_daily_loss_pct: float = 0.03,
        max_drawdown_pct:   float = 0.15,
        max_position_pct:   float = 0.20,
        max_leverage:       float = 2.0,
        var_limit_pct:      float = 0.05
    ):
        self.limits = {
            "max_daily_loss":    max_daily_loss_pct,
            "max_drawdown":      max_drawdown_pct,
            "max_position_size": max_position_pct,
            "max_leverage":      max_leverage,
            "var_limit":         var_limit_pct,
        }
        self.alerts_log: List[Dict] = []

    def _level(self, pct_of_limit: float) -> str:
        if pct_of_limit >= 1.0:   return "🔴 CRITICAL"
        elif pct_of_limit >= 0.9: return "🟠 ALERT"
        elif pct_of_limit >= 0.75:return "🟡 WARNING"
        return "✅ OK"

    def check(
        self,
        daily_pnl_pct:    float,
        current_drawdown: float,
        position_sizes:   Dict[str, float],
        portfolio_value:  float,
        returns:          np.ndarray,
        leverage:         float = 1.0
    ) -> Dict:
        """
        فحص شامل للمخاطر.

        Returns
        -------
        dict: تقرير بالمستويات والتنبيهات
        """
        checks = {}

        # خسارة يومية
        dl_ratio = abs(daily_pnl_pct) / self.limits["max_daily_loss"]
        checks["daily_loss"] = {
            "value":  round(daily_pnl_pct * 100, 4),
            "limit":  self.limits["max_daily_loss"] * 100,
            "status": self._level(dl_ratio)
        }

        # أقصى تراجع
        dd_ratio = abs(current_drawdown) / self.limits["max_drawdown"]
        checks["drawdown"] = {
            "value":  round(current_drawdown * 100, 4),
            "limit":  self.limits["max_drawdown"] * 100,
            "status": self._level(dd_ratio)
        }

        # حجم المراكز
        if portfolio_value > 0:
            for asset, size in position_sizes.items():
                pct  = size / portfolio_value
                ratio = pct / self.limits["max_position_size"]
                checks[f"position_{asset}"] = {
                    "value":  round(pct * 100, 2),
                    "limit":  self.limits["max_position_size"] * 100,
                    "status": self._level(ratio)
                }

        # الرافعة المالية
        lev_ratio = leverage / self.limits["max_leverage"]
        checks["leverage"] = {
            "value":  round(leverage, 2),
            "limit":  self.limits["max_leverage"],
            "status": self._level(lev_ratio)
        }

        # VaR
        if len(returns) >= 20:
            var_5 = abs(np.percentile(returns, 5))
            var_ratio = var_5 / self.limits["var_limit"]
            checks["var_5pct"] = {
                "value":  round(var_5 * 100, 4),
                "limit":  self.limits["var_limit"] * 100,
                "status": self._level(var_ratio)
            }

        # التحقق من الإجراءات المطلوبة
        critical_flags = [k for k, v in checks.items()
                          if "CRITICAL" in v.get("status", "")]
        alert_flags    = [k for k, v in checks.items()
                          if "ALERT" in v.get("status", "")]

        action = "NORMAL"
        if critical_flags:
            action = "STOP_TRADING"
        elif alert_flags:
            action = "REDUCE_POSITIONS"

        report = {
            "checks":         checks,
            "critical_count": len(critical_flags),
            "alert_count":    len(alert_flags),
            "action":         action,
            "critical_items": critical_flags,
            "alert_items":    alert_flags,
        }

        self.alerts_log.append({
            "timestamp": pd.Timestamp.now(),
            "action":    action,
            "n_critical":len(critical_flags)
        })

        return report

    def print_report(self, report: Dict):
        """طباعة تقرير المخاطر بصرياً."""
        print("\n" + "─" * 50)
        print("  تقرير المخاطر الحالي")
        print("─" * 50)
        for name, item in report["checks"].items():
            print(f"  {item['status']}  {name:25s} "
                  f"= {item['value']:>8.2f} / {item['limit']:>6.2f}")
        print("─" * 50)
        print(f"  الإجراء المطلوب: {report['action']}")
        if report["critical_items"]:
            print(f"  ⚠️  بنود حرجة: {', '.join(report['critical_items'])}")
        print("─" * 50)


# ─────────────────────────────────────────────────────────────────
# مثال التشغيل
# ─────────────────────────────────────────────────────────────────

def demo_risk_management():
    print("=" * 60)
    print("  نظام إدارة المخاطر للتداول الآلي")
    print("=" * 60)

    import sys, os
    sys.path.insert(0, os.path.dirname(__file__))
    from data_preprocessing import load_market_data, clean_data

    df   = clean_data(load_market_data("AAPL", "2018-01-01", "2024-01-01"))
    rets = df["Close"].pct_change().dropna().values

    # ── حجم المركز ────────────────────────────────────────────
    print("\n[1] تحديد حجم المركز:")
    sizer = PositionSizer(account_balance=100_000)

    kelly = sizer.kelly_criterion(win_rate=0.55, avg_win=0.03, avg_loss=0.02)
    print(f"    Kelly Criterion  : حجم={kelly['position_size']:,.0f}$ "
          f"| f*={kelly['kelly_fraction']:.4f}")

    ff = sizer.fixed_fractional(risk_pct=0.02, stop_loss_pct=0.05)
    print(f"    Fixed Fractional : حجم={ff['position_size']:,.0f}$ "
          f"| خسارة قصوى={ff['max_loss_amount']:,.0f}$")

    price = df["Close"].iloc[-1]
    atr   = df["High"].rolling(14).max().iloc[-1] - df["Low"].rolling(14).min().iloc[-1]
    va = sizer.volatility_adjusted(price=price, volatility_daily=rets[-60:].std())
    print(f"    Volatility-Adj   : {va['n_shares']} سهم "
          f"| {va['pct_of_balance']:.1%} من رأس المال")

    atr_sz = sizer.atr_based(price=price, atr=atr / 14)
    print(f"    ATR-Based        : {atr_sz['n_shares']} سهم "
          f"| وقف الخسارة={atr_sz['stop_loss_price']:.2f}$")

    # ── مقاييس المخاطر ────────────────────────────────────────
    print("\n[2] مقاييس المخاطر:")
    rm = RiskMetrics(risk_free_rate=0.04)
    report = rm.full_report(rets)
    for metric, value in report.items():
        print(f"    {metric:30s}: {value}")

    # ── تحسين المحفظة ─────────────────────────────────────────
    print("\n[3] تحسين المحفظة:")
    df2  = clean_data(load_market_data("MSFT", "2018-01-01", "2024-01-01"))
    df3  = clean_data(load_market_data("GOOGL","2018-01-01", "2024-01-01"))
    min_len = min(len(df), len(df2), len(df3))
    ret_matrix = np.column_stack([
        df["Close"].pct_change().dropna().values[-min_len:],
        df2["Close"].pct_change().dropna().values[-min_len:],
        df3["Close"].pct_change().dropna().values[-min_len:],
    ])
    optimizer = PortfolioOptimizer(
        ret_matrix,
        asset_names=["AAPL", "MSFT", "GOOGL"]
    )
    comparison = optimizer.compare_strategies()
    print(comparison.to_string(index=False))

    # ── وقف الخسارة ───────────────────────────────────────────
    print("\n[4] نظام وقف الخسارة:")
    sl_mgr = StopLossManager(atr_multiplier=2.0, trailing_pct=0.05)
    atr_daily = rets[-14:].std() * price

    stop  = sl_mgr.atr_stop(price, atr_daily, "long")
    print(f"    ATR Stop    : سعر الوقف={stop['stop_price']:.2f}$ | خطر={stop['risk_pct']:.2f}%")

    trail = sl_mgr.trailing_stop(df["Close"].values[-30:], "long")
    print(f"    Trailing Stop: {trail:.2f}$")

    exit_check = sl_mgr.check_exits(
        current_price=price * 0.97,
        entry_price=price,
        stop_loss=price * 0.95,
        take_profit=price * 1.10,
        holding_days=5,
        max_holding_days=20,
        direction="long"
    )
    print(f"    فحص الخروج: {exit_check}")

    # ── نظام الرقابة ───────────────────────────────────────────
    print("\n[5] نظام الرقابة والإنذار:")
    monitor = RiskMonitor(
        max_daily_loss_pct=0.03,
        max_drawdown_pct=0.15,
        max_position_pct=0.20
    )
    risk_report = monitor.check(
        daily_pnl_pct=-0.025,
        current_drawdown=-0.08,
        position_sizes={"AAPL": 25_000, "MSFT": 15_000},
        portfolio_value=100_000,
        returns=rets[-252:],
        leverage=1.2
    )
    monitor.print_report(risk_report)

    print("\n✅ اكتمل تحليل إدارة المخاطر بنجاح.")


if __name__ == "__main__":
    demo_risk_management()
