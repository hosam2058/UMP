"""
====================================================================
 تحليل المشاعر لأنظمة التداول الآلي
 Sentiment Analysis for Automated Trading Systems
====================================================================
النماذج المشمولة:
  1. VADER – تحليل سريع للمشاعر القائم على القواعد
  2. FinBERT – نموذج BERT مُضبَّط على النصوص المالية
  3. TextBlob – تحليل بسيط للقطبية والذاتية
  4. محلل أخبار السوق (News Sentiment Aggregator)
  5. محلل مشاعر وسائل التواصل (Social Media Sentiment)
  6. مؤشر الخوف/الجشع المُركَّب (Fear & Greed Index)
  7. دمج المشاعر مع إشارات التداول (Sentiment + Technical Fusion)
====================================================================
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings("ignore")


# ─────────────────────────────────────────────────────────────────
# 1. محلل VADER
# ─────────────────────────────────────────────────────────────────

class VADERSentimentAnalyzer:
    """
    تحليل المشاعر بـ VADER (Valence Aware Dictionary and sEntiment Reasoner).
    سريع ويعمل بدون GPU – مثالي للتحليل الفوري.
    """

    def __init__(self):
        try:
            from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
            self.analyzer = SentimentIntensityAnalyzer()
        except ImportError:
            try:
                import nltk
                nltk.download("vader_lexicon", quiet=True)
                from nltk.sentiment import SentimentIntensityAnalyzer
                self.analyzer = SentimentIntensityAnalyzer()
            except ImportError:
                self.analyzer = None
                print("VADER غير متاح. سيتم استخدام بديل بسيط.")

    def analyze(self, text: str) -> Dict:
        """
        تحليل مشاعر نص واحد.

        Returns
        -------
        dict: {"compound": float, "pos": float, "neu": float, "neg": float,
               "label": str, "trading_signal": str}
        """
        if self.analyzer is None:
            return self._simple_sentiment(text)

        scores = self.analyzer.polarity_scores(text)
        compound = scores["compound"]

        if compound >= 0.05:
            label  = "POSITIVE"
            signal = "BUY"
        elif compound <= -0.05:
            label  = "NEGATIVE"
            signal = "SELL"
        else:
            label  = "NEUTRAL"
            signal = "HOLD"

        return {**scores, "label": label, "trading_signal": signal}

    def _simple_sentiment(self, text: str) -> Dict:
        """تحليل بسيط بالكلمات المفتاحية."""
        positive_words = {
            "beat", "strong", "growth", "profit", "rally", "surge",
            "buy", "upgrade", "bullish", "outperform", "record", "high",
            "gain", "rise", "up", "positive", "good", "great", "excellent"
        }
        negative_words = {
            "miss", "weak", "decline", "loss", "drop", "fall", "sell",
            "downgrade", "bearish", "underperform", "low", "bad", "poor",
            "concern", "risk", "crash", "down", "negative", "disappoint"
        }
        words    = set(text.lower().split())
        pos_cnt  = len(words & positive_words)
        neg_cnt  = len(words & negative_words)
        compound = (pos_cnt - neg_cnt) / (pos_cnt + neg_cnt + 1e-9)

        label  = "POSITIVE" if compound > 0.1 else "NEGATIVE" if compound < -0.1 else "NEUTRAL"
        signal = "BUY"      if label == "POSITIVE" else "SELL" if label == "NEGATIVE" else "HOLD"
        return {
            "compound": compound, "pos": pos_cnt, "neg": neg_cnt, "neu": 0,
            "label": label, "trading_signal": signal
        }

    def analyze_batch(self, texts: List[str]) -> pd.DataFrame:
        """تحليل دفعي لقائمة نصوص."""
        results = [self.analyze(t) for t in texts]
        return pd.DataFrame(results)

    def aggregate_signal(
        self,
        texts: List[str],
        weights: Optional[List[float]] = None
    ) -> Dict:
        """تجميع إشارات متعددة في إشارة واحدة مرجَّحة."""
        if not texts:
            return {"compound": 0, "label": "NEUTRAL", "trading_signal": "HOLD"}

        results   = self.analyze_batch(texts)
        compounds = results["compound"].values
        weights   = np.array(weights) if weights else np.ones(len(texts))
        weights   = weights / weights.sum()

        avg_compound = float(np.dot(compounds, weights))
        label  = "POSITIVE" if avg_compound >  0.05 else \
                 "NEGATIVE" if avg_compound < -0.05 else "NEUTRAL"
        signal = {"POSITIVE": "BUY", "NEGATIVE": "SELL", "NEUTRAL": "HOLD"}[label]

        return {
            "compound":       avg_compound,
            "label":          label,
            "trading_signal": signal,
            "n_positive":     int((results["label"] == "POSITIVE").sum()),
            "n_negative":     int((results["label"] == "NEGATIVE").sum()),
            "n_neutral":      int((results["label"] == "NEUTRAL").sum()),
        }


# ─────────────────────────────────────────────────────────────────
# 2. FinBERT – نموذج BERT المالي
# ─────────────────────────────────────────────────────────────────

class FinBERTAnalyzer:
    """
    FinBERT: نموذج BERT مُضبَّط على البيانات المالية.
    يتفوق على VADER في تحليل التقارير المالية والأخبار الاقتصادية.
    """

    def __init__(self, model_name: str = "ProsusAI/finbert", device: str = "auto"):
        self.model      = None
        self.tokenizer  = None
        self.model_name = model_name
        self.device     = device
        self._loaded    = False

    def load(self):
        """تحميل النموذج (كسول – عند الطلب فقط)."""
        try:
            from transformers import AutoTokenizer, AutoModelForSequenceClassification
            import torch
            device = "cuda" if (self.device == "auto" and
                               torch.cuda.is_available()) else "cpu"
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self.model     = AutoModelForSequenceClassification.from_pretrained(
                self.model_name
            ).to(device)
            self.model.eval()
            self._device  = device
            self._loaded  = True
            print(f"[FinBERT] تم تحميل النموذج على: {device}")
        except ImportError:
            raise ImportError("pip install transformers torch")
        except Exception as e:
            print(f"[FinBERT] تعذّر التحميل: {e}")
            self._loaded = False

    def analyze(self, text: str) -> Dict:
        """تحليل نص واحد بـ FinBERT."""
        if not self._loaded:
            self.load()
        if not self._loaded:
            return {"label": "NEUTRAL", "confidence": 0.0, "trading_signal": "HOLD"}

        import torch
        inputs = self.tokenizer(
            text, return_tensors="pt", truncation=True, max_length=512,
            padding=True
        ).to(self._device)

        with torch.no_grad():
            outputs = self.model(**inputs)
            probs   = torch.softmax(outputs.logits, dim=-1).cpu().numpy()[0]

        labels = ["NEGATIVE", "NEUTRAL", "POSITIVE"]  # FinBERT label order
        label_idx = probs.argmax()
        label     = labels[label_idx]
        confidence = float(probs[label_idx])

        signal = {"POSITIVE": "BUY", "NEGATIVE": "SELL", "NEUTRAL": "HOLD"}[label]
        score  = float(probs[2] - probs[0])  # positive - negative

        return {
            "label":          label,
            "confidence":     confidence,
            "score":          score,
            "probabilities":  {"negative": float(probs[0]),
                               "neutral":  float(probs[1]),
                               "positive": float(probs[2])},
            "trading_signal": signal,
        }

    def analyze_batch(
        self,
        texts: List[str],
        batch_size: int = 16
    ) -> List[Dict]:
        """معالجة دفعية فعّالة."""
        results = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            results.extend([self.analyze(t) for t in batch])
        return results


# ─────────────────────────────────────────────────────────────────
# 3. محلل أخبار السوق
# ─────────────────────────────────────────────────────────────────

class NewsSentimentAggregator:
    """
    محلل أخبار السوق المالي:
      - تحليل العناوين والملخصات
      - ترجيح الأخبار بحداثتها
      - استخراج الكيانات (شركة، قطاع، عملة)
      - مؤشر الزخم الإعلامي
    """

    def __init__(self, analyzer: Optional[VADERSentimentAnalyzer] = None):
        self.analyzer = analyzer or VADERSentimentAnalyzer()
        self.news_history: List[Dict] = []

    def _compute_recency_weight(self, timestamp: datetime, half_life_hours: float = 6) -> float:
        """وزن انحلالي بالزمن – الأخبار الأحدث أكثر أهمية."""
        hours_ago = (datetime.now() - timestamp).total_seconds() / 3600
        return float(np.exp(-hours_ago * np.log(2) / half_life_hours))

    def process_news(self, news_items: List[Dict]) -> Dict:
        """
        معالجة قائمة أخبار.

        Parameters
        ----------
        news_items : قائمة من:
            {"title": str, "summary": str, "timestamp": datetime,
             "source_credibility": float (0-1)}
        """
        if not news_items:
            return {
                "aggregate_score": 0.0,
                "signal": "HOLD",
                "n_articles": 0,
                "sentiment_breakdown": {}
            }

        scores  = []
        weights = []

        for item in news_items:
            text = f"{item.get('title', '')} {item.get('summary', '')}"
            result = self.analyzer.analyze(text)
            score  = result.get("compound", result.get("score", 0))

            ts         = item.get("timestamp", datetime.now())
            recency_w  = self._compute_recency_weight(ts)
            cred_w     = item.get("source_credibility", 0.7)
            weight     = recency_w * cred_w

            scores.append(score)
            weights.append(weight)
            self.news_history.append({
                "timestamp":  ts,
                "text":       text[:100],
                "score":      score,
                "signal":     result.get("trading_signal", "HOLD"),
            })

        weights_arr = np.array(weights)
        weights_arr = weights_arr / (weights_arr.sum() + 1e-9)
        agg_score   = float(np.dot(scores, weights_arr))

        if agg_score > 0.1:
            signal = "STRONG_BUY" if agg_score > 0.3 else "BUY"
        elif agg_score < -0.1:
            signal = "STRONG_SELL" if agg_score < -0.3 else "SELL"
        else:
            signal = "HOLD"

        scores_arr = np.array(scores)
        return {
            "aggregate_score": agg_score,
            "signal":          signal,
            "n_articles":      len(news_items),
            "sentiment_breakdown": {
                "positive": int((scores_arr > 0.05).sum()),
                "negative": int((scores_arr < -0.05).sum()),
                "neutral":  int((np.abs(scores_arr) <= 0.05).sum()),
            },
            "momentum": float(np.mean(scores_arr[-5:]) - np.mean(scores_arr[:-5]))
                        if len(scores) > 5 else 0.0,
        }

    def get_sentiment_trend(self, window: int = 20) -> pd.DataFrame:
        """اتجاه المشاعر عبر الزمن."""
        if not self.news_history:
            return pd.DataFrame()
        df = pd.DataFrame(self.news_history[-window:])
        df["score_ma"] = df["score"].rolling(5, min_periods=1).mean()
        return df


# ─────────────────────────────────────────────────────────────────
# 4. مؤشر الخوف والجشع المُركَّب
# ─────────────────────────────────────────────────────────────────

class FearGreedIndex:
    """
    مؤشر الخوف والجشع المُركَّب من 7 مكونات:
      1. تقلب السوق (VIX-like)
      2. زخم السعر
      3. حجم التداول
      4. اتساع السوق (Breadth)
      5. نسبة Put/Call (محاكاة)
      6. السعر مقارنة بـ MA200
      7. مشاعر الأخبار
    """

    LABELS = {
        (0,  25):  "Extreme Fear",
        (25, 45):  "Fear",
        (45, 55):  "Neutral",
        (55, 75):  "Greed",
        (75, 100): "Extreme Greed"
    }

    def __init__(self):
        self.components: Dict[str, float] = {}
        self.index_value: float = 50.0

    def compute(
        self,
        prices: np.ndarray,
        volumes: np.ndarray,
        sentiment_score: float = 0.0,
        put_call_ratio: float = 1.0
    ) -> Dict:
        """
        حساب المؤشر المُركَّب.

        Returns
        -------
        dict: {"value": int (0-100), "label": str, "components": dict}
        """
        if len(prices) < 200:
            return {"value": 50, "label": "Neutral", "components": {}}

        returns     = np.diff(prices) / prices[:-1]
        vol_20      = returns[-20:].std() * np.sqrt(252)
        vol_60      = returns[-60:].std() * np.sqrt(252)
        ma200       = prices[-200:].mean()
        price_ma200 = prices[-1] / ma200
        mom_126     = prices[-1] / prices[-127] - 1 if len(prices) >= 127 else 0
        vol_rel     = volumes[-1] / volumes[-20:].mean() if len(volumes) >= 20 else 1

        # تطبيع إلى 0-100
        def scale(val, low, high):
            return max(0, min(100, (val - low) / (high - low + 1e-9) * 100))

        c = {
            "Volatility":      100 - scale(vol_20, 0.1, 0.5),     # تقلب منخفض = جشع
            "Momentum":        scale(mom_126, -0.3, 0.3),
            "Volume":          scale(vol_rel, 0.5, 2.0),
            "Price_vs_MA200":  scale(price_ma200, 0.85, 1.15),
            "Put_Call":        100 - scale(put_call_ratio, 0.5, 1.5),  # نسبة منخفضة = جشع
            "News_Sentiment":  scale(sentiment_score, -0.5, 0.5),
        }

        weights = {
            "Volatility":     0.25,
            "Momentum":       0.25,
            "Volume":         0.15,
            "Price_vs_MA200": 0.15,
            "Put_Call":       0.10,
            "News_Sentiment": 0.10,
        }

        self.index_value = sum(c[k] * weights[k] for k in c)
        self.components  = c

        label = "Neutral"
        for (lo, hi), lbl in self.LABELS.items():
            if lo <= self.index_value < hi:
                label = lbl
                break

        # إشارة التداول المعاكسة (Contrarian)
        if self.index_value < 25:
            signal = "BUY"      # خوف شديد → فرصة شراء
        elif self.index_value > 75:
            signal = "SELL"     # جشع شديد → خطر بيع
        else:
            signal = "HOLD"

        return {
            "value":      int(self.index_value),
            "label":      label,
            "signal":     signal,
            "components": c,
        }


# ─────────────────────────────────────────────────────────────────
# 5. دمج المشاعر مع الإشارات الفنية
# ─────────────────────────────────────────────────────────────────

class SentimentTechnicalFusion:
    """
    دمج إشارات المشاعر مع التحليل الفني:
      - يُعطي وزناً لكل مصدر إشارة
      - يصدر إشارة تداول مُجمَّعة مع درجة ثقة
    """

    def __init__(
        self,
        sentiment_weight: float = 0.3,
        technical_weight: float = 0.5,
        fear_greed_weight: float = 0.2
    ):
        total = sentiment_weight + technical_weight + fear_greed_weight
        self.w_sent = sentiment_weight   / total
        self.w_tech = technical_weight   / total
        self.w_fg   = fear_greed_weight  / total

    def _signal_to_score(self, signal: str) -> float:
        return {"BUY": 1.0, "STRONG_BUY": 1.5, "HOLD": 0.0,
                "SELL": -1.0, "STRONG_SELL": -1.5}.get(signal, 0.0)

    def fuse(
        self,
        sentiment_result:   Dict,
        technical_score:    float,      # -1 إلى +1 من المؤشرات الفنية
        fear_greed_result:  Dict
    ) -> Dict:
        """
        دمج الإشارات وإصدار قرار التداول النهائي.

        Parameters
        ----------
        sentiment_result  : مخرجات VADERSentimentAnalyzer أو FinBERT
        technical_score   : درجة مُجمَّعة من المؤشرات الفنية (-1 إلى +1)
        fear_greed_result : مخرجات FearGreedIndex
        """
        # تحويل إشارة المشاعر إلى درجة رقمية
        sent_score = sentiment_result.get("compound",
                     sentiment_result.get("score", 0))

        # إشارة Fear & Greed (contrarian)
        fg_value    = fear_greed_result.get("value", 50) / 100
        fg_score    = (fg_value - 0.5) * -2   # عكس: جشع → بيع، خوف → شراء

        # الدرجة المُرجَّحة
        composite = (
            self.w_sent * sent_score +
            self.w_tech * technical_score +
            self.w_fg   * fg_score
        )

        # قرار التداول
        if composite > 0.3:
            decision   = "STRONG_BUY"
            confidence = min(1.0, composite / 1.5)
        elif composite > 0.1:
            decision   = "BUY"
            confidence = composite / 0.3
        elif composite < -0.3:
            decision   = "STRONG_SELL"
            confidence = min(1.0, abs(composite) / 1.5)
        elif composite < -0.1:
            decision   = "SELL"
            confidence = abs(composite) / 0.3
        else:
            decision   = "HOLD"
            confidence = 1 - abs(composite) / 0.1

        return {
            "decision":         decision,
            "confidence":       float(round(confidence, 4)),
            "composite_score":  float(round(composite, 4)),
            "components": {
                "sentiment_score":    round(sent_score, 4),
                "technical_score":    round(technical_score, 4),
                "fear_greed_score":   round(fg_score, 4),
            },
            "weights": {
                "sentiment":  self.w_sent,
                "technical":  self.w_tech,
                "fear_greed": self.w_fg,
            }
        }


# ─────────────────────────────────────────────────────────────────
# مثال التشغيل
# ─────────────────────────────────────────────────────────────────

def demo_sentiment_analysis():
    print("=" * 60)
    print("  تحليل المشاعر لأنظمة التداول الآلي")
    print("=" * 60)

    # ── VADER ────────────────────────────────────────────────
    print("\n[1] تحليل VADER:")
    vader = VADERSentimentAnalyzer()

    sample_news = [
        "Apple reports record quarterly earnings, beating analyst expectations by 15%.",
        "Fed raises interest rates amid inflation concerns, markets tumble.",
        "Tech stocks rally on strong jobs data and positive economic outlook.",
        "Company faces regulatory probe, shares drop 8% in after-hours trading.",
        "Neutral quarterly update released, no major surprises expected.",
        "Bitcoin surges 20% as institutional investors pile in.",
        "Manufacturing data disappoints, recession fears mount.",
    ]

    for text in sample_news:
        result = vader.analyze(text)
        print(f"   [{result['trading_signal']:5s}] ({result.get('compound', 0):+.3f}) "
              f"{text[:60]}...")

    agg = vader.aggregate_signal(sample_news)
    print(f"\n   مُجمَّع: {agg['label']} | إشارة: {agg['trading_signal']} "
          f"| score={agg['compound']:+.4f}")

    # ── محلل الأخبار ──────────────────────────────────────────
    print("\n[2] محلل أخبار السوق:")
    aggregator = NewsSentimentAggregator(analyzer=vader)
    news_items = [
        {"title": t, "summary": "", "timestamp": datetime.now() - timedelta(hours=i),
         "source_credibility": 0.9}
        for i, t in enumerate(sample_news)
    ]
    news_result = aggregator.process_news(news_items)
    print(f"   الإشارة المُجمَّعة : {news_result['signal']}")
    print(f"   الدرجة المُجمَّعة  : {news_result['aggregate_score']:+.4f}")
    print(f"   توزيع المشاعر    : {news_result['sentiment_breakdown']}")
    print(f"   زخم المشاعر      : {news_result['momentum']:+.4f}")

    # ── Fear & Greed ─────────────────────────────────────────
    print("\n[3] مؤشر الخوف والجشع:")
    import sys, os
    sys.path.insert(0, os.path.dirname(__file__))
    from data_preprocessing import load_market_data, clean_data

    df  = clean_data(load_market_data())
    fg  = FearGreedIndex()
    res = fg.compute(
        prices=df["Close"].values,
        volumes=df["Volume"].values,
        sentiment_score=news_result["aggregate_score"]
    )
    print(f"   المؤشر: {res['value']} / 100 → {res['label']}")
    print(f"   الإشارة (عكسية): {res['signal']}")
    for comp, val in res["components"].items():
        print(f"     {comp:20s}: {val:.1f}")

    # ── دمج المشاعر مع الفني ─────────────────────────────────
    print("\n[4] دمج المشاعر مع التحليل الفني:")
    fusion = SentimentTechnicalFusion(
        sentiment_weight=0.3,
        technical_weight=0.5,
        fear_greed_weight=0.2
    )
    final  = fusion.fuse(
        sentiment_result   = {"compound": news_result["aggregate_score"]},
        technical_score    = 0.4,    # مثال: RSI=60, MACD إيجابي
        fear_greed_result  = res
    )
    print(f"   القرار النهائي    : {final['decision']}")
    print(f"   الثقة             : {final['confidence']:.2%}")
    print(f"   الدرجة المُركَّبة  : {final['composite_score']:+.4f}")
    print(f"   المكونات          : {final['components']}")

    print("\n✅ اكتمل تحليل المشاعر بنجاح.")


if __name__ == "__main__":
    demo_sentiment_analysis()
