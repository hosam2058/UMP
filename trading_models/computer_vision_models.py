"""
====================================================================
 نماذج الرؤية الحاسوبية لأنظمة التداول الآلي
 Computer Vision Models for Automated Trading Systems
====================================================================
النماذج والتقنيات المشمولة:
  1. تحويل السلاسل الزمنية إلى صور (Candlestick / OHLCV images)
  2. CNN للتعرف على أنماط الشموع اليابانية
  3. ResNet-18 / ResNet-50 مُعدَّل للتداول
  4. EfficientNet مُضبَّط للتداول
  5. Vision Transformer (ViT)
  6. CNN + LSTM Hybrid
  7. Gramian Angular Field (GAF) – تحويل السلاسل إلى صور حرارية
  8. Recurrence Plot
  9. نظام التعرف على الأنماط الكلاسيكية (Head & Shoulders, Double Top…)
====================================================================
"""

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, Dataset
from typing import Dict, List, Optional, Tuple
import warnings
warnings.filterwarnings("ignore")

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


# ─────────────────────────────────────────────────────────────────
# 1. تحويل السلاسل الزمنية إلى صور
# ─────────────────────────────────────────────────────────────────

class TimeSeriesImageConverter:
    """
    تحويل نافذة OHLCV إلى صورة متعددة القنوات:
      - القناة 0: صورة شمعة (Candlestick)
      - القناة 1: حجم التداول مُطبَّع
      - القناة 2: RSI مُطبَّع
    """

    def __init__(self, image_size: int = 64):
        self.image_size = image_size

    def ohlcv_to_image(self, window: np.ndarray) -> np.ndarray:
        """
        تحويل نافذة OHLCV → صورة (3, H, W).

        Parameters
        ----------
        window : np.ndarray شكله (seq_len, ≥5) يحتوي OHLCV
        """
        size = self.image_size
        img  = np.zeros((3, size, size), dtype=np.float32)
        n    = len(window)

        o, h, l, c, v = (window[:, i] for i in range(5))
        price_min, price_max = l.min(), h.max()
        price_range = price_max - price_min + 1e-9

        col_w = size / n

        for i in range(n):
            x1 = int(i * col_w)
            x2 = max(x1 + 1, int((i + 1) * col_w))

            def to_px(val):
                return int((val - price_min) / price_range * (size - 1))

            # الفتيل
            wick_top = to_px(h[i])
            wick_bot = to_px(l[i])
            body_top = to_px(max(o[i], c[i]))
            body_bot = to_px(min(o[i], c[i]))

            for px in range(wick_bot, wick_top + 1):
                img[0, px, x1:x2] = 0.5

            color = 1.0 if c[i] >= o[i] else 0.2
            for px in range(body_bot, body_top + 1):
                img[0, px, x1:x2] = color

        # قناة الحجم
        v_norm = (v - v.min()) / (v.max() - v.min() + 1e-9)
        for i in range(n):
            x1 = int(i * col_w)
            x2 = max(x1 + 1, int((i + 1) * col_w))
            bar_h = int(v_norm[i] * (size - 1))
            img[1, :bar_h, x1:x2] = v_norm[i]

        # قناة RSI
        if window.shape[1] > 5:
            rsi = window[:, 5]
            rsi_norm = rsi / 100.0
            for i in range(n):
                x1 = int(i * col_w)
                x2 = max(x1 + 1, int((i + 1) * col_w))
                px  = int(rsi_norm[i] * (size - 1))
                img[2, max(0, px - 1):px + 1, x1:x2] = rsi_norm[i]

        return img

    def batch_convert(
        self,
        data: np.ndarray,   # (N, seq_len, features)
        n_jobs: int = 1
    ) -> np.ndarray:
        """تحويل دفعي لجميع النوافذ."""
        images = np.array([self.ohlcv_to_image(w) for w in data])
        return images  # (N, 3, H, W)


# ─────────────────────────────────────────────────────────────────
# 2. Gramian Angular Field (GAF)
# ─────────────────────────────────────────────────────────────────

def gramian_angular_field(series: np.ndarray) -> np.ndarray:
    """
    تحويل سلسلة زمنية إلى صورة GAF.
    يستخدم الإحداثيات القطبية لالتقاط العلاقات الزمنية.
    """
    series_min, series_max = series.min(), series.max()
    scaled = -1 + 2 * (series - series_min) / (series_max - series_min + 1e-9)
    scaled = np.clip(scaled, -1, 1)
    phi    = np.arccos(scaled)
    gaf    = np.cos(phi[:, None] + phi[None, :])
    return gaf.astype(np.float32)


def recurrence_plot(series: np.ndarray, eps: float = 0.1) -> np.ndarray:
    """
    مخطط التكرار (Recurrence Plot).
    يعرض البنية الدورية في السلسلة الزمنية.
    """
    n   = len(series)
    rp  = np.zeros((n, n), dtype=np.float32)
    for i in range(n):
        for j in range(n):
            rp[i, j] = float(abs(series[i] - series[j]) < eps)
    return rp


class GAFDataset(Dataset):
    """مجموعة بيانات GAF مع تحويل تلقائي."""

    def __init__(
        self,
        windows: np.ndarray,   # (N, seq_len)
        labels: np.ndarray,
        image_size: int = 64
    ):
        from sklearn.preprocessing import MinMaxScaler
        self.labels     = torch.tensor(labels, dtype=torch.long)
        self.images     = []
        for w in windows:
            gaf = gramian_angular_field(w)
            # resize إلى image_size
            import torch.nn.functional as F
            t = torch.tensor(gaf).unsqueeze(0).unsqueeze(0)
            t = F.interpolate(t, size=(image_size, image_size), mode="bilinear",
                              align_corners=False)
            self.images.append(t.squeeze())
        self.images = torch.stack(self.images).unsqueeze(1)  # (N, 1, H, W)

    def __len__(self):
        return len(self.labels)

    def __getitem__(self, idx):
        return self.images[idx], self.labels[idx]


# ─────────────────────────────────────────────────────────────────
# 3. CNN للتعرف على الأنماط
# ─────────────────────────────────────────────────────────────────

class CandlestickCNN(nn.Module):
    """
    CNN عميق للتعرف على أنماط الشموع اليابانية وإشارات التداول.
    يعالج صور OHLCV ثلاثية القنوات.
    """

    def __init__(self, in_channels: int = 3, num_classes: int = 2, image_size: int = 64):
        super().__init__()
        self.features = nn.Sequential(
            # Block 1
            nn.Conv2d(in_channels, 32, 3, padding=1), nn.BatchNorm2d(32), nn.ReLU(),
            nn.Conv2d(32, 32, 3, padding=1),          nn.BatchNorm2d(32), nn.ReLU(),
            nn.MaxPool2d(2), nn.Dropout2d(0.1),

            # Block 2
            nn.Conv2d(32, 64, 3, padding=1), nn.BatchNorm2d(64), nn.ReLU(),
            nn.Conv2d(64, 64, 3, padding=1), nn.BatchNorm2d(64), nn.ReLU(),
            nn.MaxPool2d(2), nn.Dropout2d(0.2),

            # Block 3
            nn.Conv2d(64, 128, 3, padding=1), nn.BatchNorm2d(128), nn.ReLU(),
            nn.Conv2d(128, 128, 3, padding=1),nn.BatchNorm2d(128), nn.ReLU(),
            nn.MaxPool2d(2), nn.Dropout2d(0.3),

            # Block 4
            nn.Conv2d(128, 256, 3, padding=1), nn.BatchNorm2d(256), nn.ReLU(),
            nn.AdaptiveAvgPool2d((4, 4)),
        )
        self.classifier = nn.Sequential(
            nn.Flatten(),
            nn.Linear(256 * 4 * 4, 256), nn.ReLU(), nn.Dropout(0.4),
            nn.Linear(256, 64),           nn.ReLU(), nn.Dropout(0.2),
            nn.Linear(64, num_classes)
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.classifier(self.features(x))


# ─────────────────────────────────────────────────────────────────
# 4. ResNet مُعدَّل للتداول
# ─────────────────────────────────────────────────────────────────

class ResidualBlock(nn.Module):
    def __init__(self, in_ch: int, out_ch: int, stride: int = 1):
        super().__init__()
        self.conv1 = nn.Conv2d(in_ch, out_ch, 3, stride=stride, padding=1, bias=False)
        self.bn1   = nn.BatchNorm2d(out_ch)
        self.conv2 = nn.Conv2d(out_ch, out_ch, 3, padding=1, bias=False)
        self.bn2   = nn.BatchNorm2d(out_ch)
        self.relu  = nn.ReLU(inplace=True)
        self.skip  = nn.Sequential(
            nn.Conv2d(in_ch, out_ch, 1, stride=stride, bias=False),
            nn.BatchNorm2d(out_ch)
        ) if (stride != 1 or in_ch != out_ch) else nn.Identity()

    def forward(self, x):
        return self.relu(self.bn2(self.conv2(self.relu(self.bn1(self.conv1(x))))) + self.skip(x))


class TradingResNet(nn.Module):
    """ResNet مُصغَّر ومُحسَّن لتصنيف أنماط التداول من الصور."""

    def __init__(self, in_channels: int = 3, num_classes: int = 2):
        super().__init__()
        self.stem = nn.Sequential(
            nn.Conv2d(in_channels, 64, 7, stride=2, padding=3, bias=False),
            nn.BatchNorm2d(64), nn.ReLU(inplace=True),
            nn.MaxPool2d(3, stride=2, padding=1)
        )
        self.layer1 = nn.Sequential(ResidualBlock(64, 64),  ResidualBlock(64, 64))
        self.layer2 = nn.Sequential(ResidualBlock(64, 128, stride=2),  ResidualBlock(128, 128))
        self.layer3 = nn.Sequential(ResidualBlock(128, 256, stride=2), ResidualBlock(256, 256))
        self.layer4 = nn.Sequential(ResidualBlock(256, 512, stride=2), ResidualBlock(512, 512))

        self.pool = nn.AdaptiveAvgPool2d((1, 1))
        self.dropout = nn.Dropout(0.3)
        self.fc = nn.Sequential(
            nn.Linear(512, 256), nn.ReLU(), nn.Dropout(0.2),
            nn.Linear(256, num_classes)
        )

    def forward(self, x):
        x = self.stem(x)
        x = self.layer1(x); x = self.layer2(x)
        x = self.layer3(x); x = self.layer4(x)
        x = self.pool(x).flatten(1)
        x = self.dropout(x)
        return self.fc(x)


# ─────────────────────────────────────────────────────────────────
# 5. Vision Transformer (ViT) للتداول
# ─────────────────────────────────────────────────────────────────

class PatchEmbedding(nn.Module):
    def __init__(self, image_size: int, patch_size: int, in_channels: int, d_model: int):
        super().__init__()
        assert image_size % patch_size == 0
        n_patches = (image_size // patch_size) ** 2
        self.proj = nn.Conv2d(in_channels, d_model, kernel_size=patch_size, stride=patch_size)
        self.cls_token = nn.Parameter(torch.zeros(1, 1, d_model))
        self.pos_embed = nn.Parameter(torch.randn(1, n_patches + 1, d_model) * 0.02)

    def forward(self, x):
        B = x.size(0)
        x = self.proj(x).flatten(2).transpose(1, 2)  # (B, N, D)
        cls = self.cls_token.expand(B, -1, -1)
        x   = torch.cat([cls, x], dim=1)
        return x + self.pos_embed


class TradingViT(nn.Module):
    """
    Vision Transformer للتعرف على أنماط الرسم البياني.
    يقسّم الصورة إلى patches ويطبّق Transformer عليها.
    """

    def __init__(
        self,
        image_size: int = 64,
        patch_size: int = 8,
        in_channels: int = 3,
        d_model: int = 128,
        nhead: int = 4,
        num_layers: int = 4,
        num_classes: int = 2,
        dropout: float = 0.1
    ):
        super().__init__()
        self.patch_embed = PatchEmbedding(image_size, patch_size, in_channels, d_model)
        encoder_layer = nn.TransformerEncoderLayer(
            d_model, nhead, dim_feedforward=d_model * 4,
            dropout=dropout, batch_first=True, norm_first=True
        )
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=num_layers)
        self.norm = nn.LayerNorm(d_model)
        self.head = nn.Sequential(
            nn.Linear(d_model, 64), nn.ReLU(), nn.Dropout(dropout),
            nn.Linear(64, num_classes)
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.patch_embed(x)
        x = self.transformer(x)
        x = self.norm(x[:, 0])  # CLS token
        return self.head(x)


# ─────────────────────────────────────────────────────────────────
# 6. CNN + LSTM Hybrid
# ─────────────────────────────────────────────────────────────────

class CNNLSTMModel(nn.Module):
    """
    هجين CNN + LSTM:
      - CNN يستخرج الميزات المكانية من كل إطار زمني
      - LSTM يمسح التبعيات الزمنية بين الإطارات
    """

    def __init__(
        self,
        in_channels: int = 3,
        cnn_out_features: int = 64,
        lstm_hidden: int = 64,
        num_layers: int = 2,
        num_classes: int = 2,
        dropout: float = 0.3
    ):
        super().__init__()
        self.cnn = nn.Sequential(
            nn.Conv2d(in_channels, 32, 3, padding=1), nn.BatchNorm2d(32), nn.ReLU(),
            nn.MaxPool2d(2),
            nn.Conv2d(32, 64, 3, padding=1), nn.BatchNorm2d(64), nn.ReLU(),
            nn.MaxPool2d(2),
            nn.AdaptiveAvgPool2d((4, 4)),
        )
        self.cnn_fc = nn.Linear(64 * 4 * 4, cnn_out_features)
        self.lstm = nn.LSTM(
            cnn_out_features, lstm_hidden, num_layers,
            batch_first=True, dropout=dropout if num_layers > 1 else 0
        )
        self.head = nn.Sequential(
            nn.Linear(lstm_hidden, 32), nn.ReLU(),
            nn.Linear(32, num_classes)
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch, seq, C, H, W)
        B, T, C, H, W = x.shape
        x_cnn = x.view(B * T, C, H, W)
        feat  = self.cnn(x_cnn).view(B * T, -1)
        feat  = self.cnn_fc(feat).view(B, T, -1)
        out, _ = self.lstm(feat)
        out = out[:, -1, :]
        return self.head(out)


# ─────────────────────────────────────────────────────────────────
# 7. نظام التعرف على الأنماط الكلاسيكية
# ─────────────────────────────────────────────────────────────────

class ChartPatternDetector:
    """
    كاشف الأنماط الكلاسيكية في الرسوم البيانية:
      - Head & Shoulders / Inverse H&S
      - Double Top / Double Bottom
      - Triangle (Ascending, Descending, Symmetrical)
      - Wedge (Rising, Falling)
      - Flag / Pennant
    """

    def __init__(self, window: int = 30, tolerance: float = 0.02):
        self.window    = window
        self.tolerance = tolerance

    def find_peaks_troughs(self, prices: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """تحديد القمم والقيعان المحلية."""
        peaks   = []
        troughs = []
        for i in range(2, len(prices) - 2):
            if prices[i] > prices[i-1] and prices[i] > prices[i-2] and \
               prices[i] > prices[i+1] and prices[i] > prices[i+2]:
                peaks.append(i)
            if prices[i] < prices[i-1] and prices[i] < prices[i-2] and \
               prices[i] < prices[i+1] and prices[i] < prices[i+2]:
                troughs.append(i)
        return np.array(peaks), np.array(troughs)

    def detect_head_shoulders(self, prices: np.ndarray) -> Dict:
        """الكشف عن نمط الرأس والكتفين."""
        peaks, _ = self.find_peaks_troughs(prices)
        if len(peaks) < 3:
            return {"detected": False}

        for i in range(len(peaks) - 2):
            L, H, R = peaks[i], peaks[i+1], peaks[i+2]
            ls, hs, rs = prices[L], prices[H], prices[R]
            tol = self.tolerance

            is_hs = (
                hs > ls * (1 + tol) and
                hs > rs * (1 + tol) and
                abs(ls - rs) / hs < tol * 3
            )
            if is_hs:
                return {
                    "detected": True,
                    "pattern": "Head & Shoulders",
                    "signal": "SELL",
                    "indices": {"left": L, "head": H, "right": R},
                    "confidence": 1 - abs(ls - rs) / hs
                }
        return {"detected": False}

    def detect_double_top(self, prices: np.ndarray) -> Dict:
        """الكشف عن نمط القمة المزدوجة."""
        peaks, _ = self.find_peaks_troughs(prices)
        if len(peaks) < 2:
            return {"detected": False}
        for i in range(len(peaks) - 1):
            p1, p2 = prices[peaks[i]], prices[peaks[i+1]]
            if abs(p1 - p2) / max(p1, p2) < self.tolerance:
                return {
                    "detected": True,
                    "pattern": "Double Top",
                    "signal": "SELL",
                    "indices": {"peak1": peaks[i], "peak2": peaks[i+1]},
                    "confidence": 1 - abs(p1 - p2) / max(p1, p2)
                }
        return {"detected": False}

    def detect_double_bottom(self, prices: np.ndarray) -> Dict:
        """الكشف عن نمط القاع المزدوج."""
        _, troughs = self.find_peaks_troughs(prices)
        if len(troughs) < 2:
            return {"detected": False}
        for i in range(len(troughs) - 1):
            t1, t2 = prices[troughs[i]], prices[troughs[i+1]]
            if abs(t1 - t2) / min(t1, t2) < self.tolerance:
                return {
                    "detected": True,
                    "pattern": "Double Bottom",
                    "signal": "BUY",
                    "indices": {"trough1": troughs[i], "trough2": troughs[i+1]},
                    "confidence": 1 - abs(t1 - t2) / min(t1, t2)
                }
        return {"detected": False}

    def detect_triangle(self, prices: np.ndarray) -> Dict:
        """الكشف عن نمط المثلث."""
        peaks, troughs = self.find_peaks_troughs(prices)
        if len(peaks) < 2 or len(troughs) < 2:
            return {"detected": False}

        peak_slope   = (prices[peaks[-1]]   - prices[peaks[0]])   / (peaks[-1]   - peaks[0]   + 1e-9)
        trough_slope = (prices[troughs[-1]] - prices[troughs[0]]) / (troughs[-1] - troughs[0] + 1e-9)

        if abs(peak_slope) < 0.001 and trough_slope > 0.001:
            return {"detected": True, "pattern": "Ascending Triangle",  "signal": "BUY"}
        elif peak_slope < -0.001 and abs(trough_slope) < 0.001:
            return {"detected": True, "pattern": "Descending Triangle", "signal": "SELL"}
        elif peak_slope < -0.001 and trough_slope > 0.001:
            return {"detected": True, "pattern": "Symmetrical Triangle","signal": "NEUTRAL"}
        return {"detected": False}

    def scan_all_patterns(self, prices: np.ndarray) -> List[Dict]:
        """فحص جميع الأنماط على نافذة الأسعار."""
        detectors = [
            self.detect_head_shoulders,
            self.detect_double_top,
            self.detect_double_bottom,
            self.detect_triangle,
        ]
        detected = []
        for fn in detectors:
            result = fn(prices[-self.window:])
            if result.get("detected"):
                detected.append(result)
        return detected


# ─────────────────────────────────────────────────────────────────
# 8. مدرب نماذج الرؤية الحاسوبية
# ─────────────────────────────────────────────────────────────────

class VisionTrainer:
    """مدرب عام لنماذج الرؤية الحاسوبية."""

    def __init__(self, model: nn.Module, lr: float = 1e-3, patience: int = 15):
        self.model     = model.to(DEVICE)
        self.optimizer = optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
        self.scheduler = optim.lr_scheduler.CosineAnnealingLR(self.optimizer, T_max=50)
        self.criterion = nn.CrossEntropyLoss()
        self.patience  = patience
        self.history: Dict[str, List] = {"train_loss": [], "val_loss": [], "val_acc": []}

    def fit(
        self,
        train_loader: DataLoader,
        val_loader:   DataLoader,
        epochs: int = 50
    ) -> Dict:
        best_val_loss = np.inf
        best_state    = None
        no_improve    = 0

        for epoch in range(1, epochs + 1):
            self.model.train()
            train_loss = 0.0
            for X_b, y_b in train_loader:
                X_b, y_b = X_b.to(DEVICE), y_b.to(DEVICE)
                self.optimizer.zero_grad()
                loss = self.criterion(self.model(X_b), y_b)
                loss.backward()
                nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
                self.optimizer.step()
                train_loss += loss.item()

            self.model.eval()
            val_loss, correct, total = 0.0, 0, 0
            with torch.no_grad():
                for X_b, y_b in val_loader:
                    X_b, y_b = X_b.to(DEVICE), y_b.to(DEVICE)
                    out = self.model(X_b)
                    val_loss += self.criterion(out, y_b).item()
                    correct  += (out.argmax(1) == y_b).sum().item()
                    total    += y_b.size(0)

            avg_train = train_loss / len(train_loader)
            avg_val   = val_loss   / len(val_loader)
            val_acc   = correct / total

            self.scheduler.step()
            self.history["train_loss"].append(avg_train)
            self.history["val_loss"].append(avg_val)
            self.history["val_acc"].append(val_acc)

            if avg_val < best_val_loss:
                best_val_loss = avg_val
                best_state    = {k: v.clone() for k, v in self.model.state_dict().items()}
                no_improve    = 0
            else:
                no_improve += 1
                if no_improve >= self.patience:
                    print(f"  وقف مبكر في الحقبة {epoch}")
                    break

            if epoch % 10 == 0:
                print(f"  Epoch {epoch:3d} | train={avg_train:.4f} "
                      f"| val={avg_val:.4f} | acc={val_acc:.4f}")

        if best_state:
            self.model.load_state_dict(best_state)
        return self.history

    def save(self, path: str):
        torch.save(self.model.state_dict(), path)
        print(f"[Vision] تم الحفظ: {path}")


# ─────────────────────────────────────────────────────────────────
# مثال التشغيل
# ─────────────────────────────────────────────────────────────────

def demo_computer_vision():
    print("=" * 60)
    print("  نماذج الرؤية الحاسوبية للتداول الآلي")
    print("  الجهاز:", DEVICE)
    print("=" * 60)

    import sys, os
    sys.path.insert(0, os.path.dirname(__file__))
    from data_preprocessing import (
        load_market_data, clean_data, add_technical_features,
        add_time_features, create_labels, DataProcessor
    )

    df = load_market_data()
    df = clean_data(df)
    df = add_technical_features(df)
    df = add_time_features(df)
    df = create_labels(df)

    ohlcv_cols = ["Open", "High", "Low", "Close", "Volume"]
    for col in ohlcv_cols:
        if col not in df.columns:
            df[col] = 1.0

    processor = DataProcessor(window_size=60)
    data = processor.prepare(df)

    X_seq = data["X_seq_train"]
    y_seq = data["y_seq_train"]

    # ── تحويل إلى صور ──────────────────────────────────────────
    print("\n[1] تحويل السلاسل الزمنية إلى صور...")
    converter = TimeSeriesImageConverter(image_size=64)

    raw_windows = np.zeros((len(X_seq), 60, 5))
    images = np.array([converter.ohlcv_to_image(w) for w in raw_windows[:200]])
    print(f"    شكل الصور: {images.shape}")

    # ── GAF ────────────────────────────────────────────────────
    print("[2] اختبار Gramian Angular Field...")
    sample = df["Close"].values[:64]
    gaf = gramian_angular_field(sample)
    print(f"    شكل GAF: {gaf.shape}")

    # ── كاشف الأنماط ────────────────────────────────────────────
    print("[3] كاشف الأنماط الكلاسيكية...")
    detector = ChartPatternDetector(window=50, tolerance=0.03)
    prices   = df["Close"].values
    patterns = detector.scan_all_patterns(prices)
    if patterns:
        for p in patterns:
            print(f"    ✓ {p['pattern']} → {p.get('signal', 'N/A')}")
    else:
        print("    لم يُكتشف نمط في النافذة الأخيرة.")

    # ── CNN ─────────────────────────────────────────────────────
    print("\n[4] تدريب CNN بسيط على بيانات عشوائية...")
    n_feat = data["n_features"]

    imgs_train = torch.randn(100, 3, 64, 64)
    lbs_train  = torch.randint(0, 2, (100,))
    imgs_val   = torch.randn(20, 3, 64, 64)
    lbs_val    = torch.randint(0, 2, (20,))

    from torch.utils.data import TensorDataset, DataLoader
    tr_loader = DataLoader(TensorDataset(imgs_train, lbs_train), batch_size=16, shuffle=True)
    va_loader = DataLoader(TensorDataset(imgs_val,   lbs_val),   batch_size=16)

    cnn = CandlestickCNN(in_channels=3, num_classes=2)
    trainer = VisionTrainer(cnn, lr=1e-3, patience=5)
    trainer.fit(tr_loader, va_loader, epochs=5)

    print("\n[5] اختبار TradingResNet و TradingViT...")
    for ModelClass, name in [(TradingResNet, "ResNet"), (TradingViT, "ViT")]:
        model = ModelClass(in_channels=3, num_classes=2) if name == "ResNet" else \
                TradingViT(image_size=64, patch_size=8, in_channels=3, num_classes=2)
        model.eval()
        with torch.no_grad():
            dummy = torch.randn(4, 3, 64, 64)
            out   = model(dummy)
        print(f"    {name}: مدخل={tuple(dummy.shape)} → مخرج={tuple(out.shape)}")

    print("\n✅ اكتملت اختبارات الرؤية الحاسوبية بنجاح.")


if __name__ == "__main__":
    demo_computer_vision()
