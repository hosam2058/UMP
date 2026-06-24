"""
====================================================================
 نماذج التعلم العميق لأنظمة التداول الآلي
 Deep Learning Models for Automated Trading Systems
====================================================================
النماذج المشمولة:
  1. LSTM (Long Short-Term Memory)
  2. Bidirectional LSTM
  3. GRU (Gated Recurrent Unit)
  4. Temporal Convolutional Network (TCN)
  5. Transformer (Attention Is All You Need)
  6. Temporal Fusion Transformer (TFT)
  7. WaveNet للتنبؤ بالأسعار
  8. LSTM-Attention Hybrid
====================================================================
"""

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset
from typing import Dict, List, Optional, Tuple
import warnings
warnings.filterwarnings("ignore")


# ─────────────────────────────────────────────────────────────────
# أدوات مساعدة
# ─────────────────────────────────────────────────────────────────

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


def to_tensor(arr: np.ndarray, dtype=torch.float32) -> torch.Tensor:
    return torch.tensor(arr, dtype=dtype).to(DEVICE)


def make_dataloader(X: np.ndarray, y: np.ndarray,
                    batch_size: int = 64, shuffle: bool = True) -> DataLoader:
    dataset = TensorDataset(
        to_tensor(X),
        to_tensor(y, dtype=torch.long)
    )
    return DataLoader(dataset, batch_size=batch_size, shuffle=shuffle)


class EarlyStopping:
    """وقف مبكر لتجنب الإفراط في التدريب."""

    def __init__(self, patience: int = 15, min_delta: float = 1e-4):
        self.patience  = patience
        self.min_delta = min_delta
        self.best_loss = np.inf
        self.counter   = 0
        self.stop      = False

    def __call__(self, val_loss: float):
        if val_loss < self.best_loss - self.min_delta:
            self.best_loss = val_loss
            self.counter   = 0
        else:
            self.counter += 1
            if self.counter >= self.patience:
                self.stop = True


# ─────────────────────────────────────────────────────────────────
# 1. LSTM الكلاسيكي
# ─────────────────────────────────────────────────────────────────

class LSTMModel(nn.Module):
    """
    LSTM متعدد الطبقات مع:
      - Dropout للتنظيم
      - Layer Normalization
      - Residual Connection (اختياري)
    """

    def __init__(
        self,
        input_size: int,
        hidden_size: int = 128,
        num_layers: int = 3,
        num_classes: int = 2,
        dropout: float = 0.3,
        bidirectional: bool = False
    ):
        super().__init__()
        self.hidden_size   = hidden_size
        self.num_layers    = num_layers
        self.bidirectional = bidirectional
        D = 2 if bidirectional else 1

        self.lstm = nn.LSTM(
            input_size, hidden_size, num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0,
            bidirectional=bidirectional
        )
        self.layer_norm = nn.LayerNorm(hidden_size * D)
        self.dropout    = nn.Dropout(dropout)
        self.fc1 = nn.Linear(hidden_size * D, 64)
        self.fc2 = nn.Linear(64, num_classes)
        self.relu = nn.ReLU()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch, seq_len, features)
        out, _ = self.lstm(x)
        out = out[:, -1, :]           # آخر خطوة زمنية
        out = self.layer_norm(out)
        out = self.dropout(out)
        out = self.relu(self.fc1(out))
        out = self.fc2(out)
        return out


# ─────────────────────────────────────────────────────────────────
# 2. GRU
# ─────────────────────────────────────────────────────────────────

class GRUModel(nn.Module):
    """GRU – أسرع من LSTM مع أداء مقارب للبيانات المالية."""

    def __init__(
        self,
        input_size: int,
        hidden_size: int = 128,
        num_layers: int = 2,
        num_classes: int = 2,
        dropout: float = 0.3
    ):
        super().__init__()
        self.gru = nn.GRU(
            input_size, hidden_size, num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0
        )
        self.bn      = nn.BatchNorm1d(hidden_size)
        self.dropout = nn.Dropout(dropout)
        self.fc1     = nn.Linear(hidden_size, 64)
        self.fc2     = nn.Linear(64, num_classes)
        self.relu    = nn.ReLU()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out, _ = self.gru(x)
        out = out[:, -1, :]
        out = self.bn(out)
        out = self.dropout(out)
        out = self.relu(self.fc1(out))
        return self.fc2(out)


# ─────────────────────────────────────────────────────────────────
# 3. Temporal Convolutional Network (TCN)
# ─────────────────────────────────────────────────────────────────

class CausalConv1d(nn.Module):
    """طبقة الالتفاف السببي (Causal Convolution)."""

    def __init__(self, in_channels, out_channels, kernel_size, dilation):
        super().__init__()
        self.padding = (kernel_size - 1) * dilation
        self.conv = nn.Conv1d(
            in_channels, out_channels, kernel_size,
            padding=self.padding, dilation=dilation
        )

    def forward(self, x):
        out = self.conv(x)
        return out[:, :, :-self.padding] if self.padding else out


class TCNBlock(nn.Module):
    def __init__(self, in_ch, out_ch, kernel_size, dilation, dropout=0.2):
        super().__init__()
        self.conv1 = CausalConv1d(in_ch, out_ch, kernel_size, dilation)
        self.conv2 = CausalConv1d(out_ch, out_ch, kernel_size, dilation)
        self.bn1   = nn.BatchNorm1d(out_ch)
        self.bn2   = nn.BatchNorm1d(out_ch)
        self.drop  = nn.Dropout(dropout)
        self.relu  = nn.ReLU()
        self.skip  = nn.Conv1d(in_ch, out_ch, 1) if in_ch != out_ch else nn.Identity()

    def forward(self, x):
        residual = self.skip(x)
        out = self.relu(self.bn1(self.conv1(x)))
        out = self.drop(out)
        out = self.relu(self.bn2(self.conv2(out)))
        out = self.drop(out)
        return self.relu(out + residual)


class TCNModel(nn.Module):
    """Temporal Convolutional Network – استقبال سياق واسع بتكلفة حسابية منخفضة."""

    def __init__(
        self,
        input_size: int,
        num_channels: List[int] = None,
        kernel_size: int = 3,
        dropout: float = 0.2,
        num_classes: int = 2
    ):
        super().__init__()
        if num_channels is None:
            num_channels = [64, 128, 128, 64]

        layers = []
        in_ch = input_size
        for i, out_ch in enumerate(num_channels):
            dilation = 2 ** i
            layers.append(TCNBlock(in_ch, out_ch, kernel_size, dilation, dropout))
            in_ch = out_ch

        self.network = nn.Sequential(*layers)
        self.fc      = nn.Linear(num_channels[-1], num_classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch, seq, features)  →  (batch, features, seq)
        x = x.permute(0, 2, 1)
        out = self.network(x)
        out = out[:, :, -1]    # آخر خطوة زمنية
        return self.fc(out)


# ─────────────────────────────────────────────────────────────────
# 4. Transformer للتداول
# ─────────────────────────────────────────────────────────────────

class PositionalEncoding(nn.Module):
    """ترميز الموقع الجيبي للـ Transformer."""

    def __init__(self, d_model: int, max_len: int = 512, dropout: float = 0.1):
        super().__init__()
        self.dropout = nn.Dropout(dropout)
        pe = torch.zeros(max_len, d_model)
        pos = torch.arange(0, max_len).unsqueeze(1).float()
        div = torch.exp(torch.arange(0, d_model, 2).float() * (-np.log(10000.0) / d_model))
        pe[:, 0::2] = torch.sin(pos * div)
        pe[:, 1::2] = torch.cos(pos * div)
        self.register_buffer("pe", pe.unsqueeze(0))  # (1, max_len, d_model)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x + self.pe[:, :x.size(1)]
        return self.dropout(x)


class TransformerTrader(nn.Module):
    """
    Transformer encoder للتنبؤ بالتداول.
    يستخدم آلية الانتباه الذاتي (Self-Attention) لالتقاط
    التبعيات بعيدة المدى في السلاسل الزمنية.
    """

    def __init__(
        self,
        input_size: int,
        d_model: int = 128,
        nhead: int = 8,
        num_layers: int = 4,
        dim_feedforward: int = 256,
        dropout: float = 0.1,
        num_classes: int = 2,
        max_seq_len: int = 512
    ):
        super().__init__()
        self.input_proj = nn.Linear(input_size, d_model)
        self.pos_enc    = PositionalEncoding(d_model, max_seq_len, dropout)

        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=nhead,
            dim_feedforward=dim_feedforward,
            dropout=dropout,
            batch_first=True,
            norm_first=True    # Pre-LN (أكثر استقراراً)
        )
        self.transformer_encoder = nn.TransformerEncoder(
            encoder_layer, num_layers=num_layers,
            norm=nn.LayerNorm(d_model)
        )
        self.pool = nn.AdaptiveAvgPool1d(1)
        self.head = nn.Sequential(
            nn.Linear(d_model, 64),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(64, num_classes)
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch, seq, features)
        x = self.input_proj(x)
        x = self.pos_enc(x)
        x = self.transformer_encoder(x)
        x = self.pool(x.permute(0, 2, 1)).squeeze(-1)  # Global Average Pooling
        return self.head(x)


# ─────────────────────────────────────────────────────────────────
# 5. LSTM + Attention Hybrid
# ─────────────────────────────────────────────────────────────────

class AttentionLayer(nn.Module):
    """آلية الانتباه الذاتي فوق مخرجات LSTM."""

    def __init__(self, hidden_size: int):
        super().__init__()
        self.attn   = nn.Linear(hidden_size, 1)
        self.softmax = nn.Softmax(dim=1)

    def forward(self, lstm_out: torch.Tensor) -> torch.Tensor:
        # lstm_out: (batch, seq, hidden)
        scores  = self.attn(lstm_out).squeeze(-1)   # (batch, seq)
        weights = self.softmax(scores).unsqueeze(-1) # (batch, seq, 1)
        context = (weights * lstm_out).sum(dim=1)    # (batch, hidden)
        return context


class LSTMAttentionModel(nn.Module):
    """LSTM مع Attention – التقاط السياق الأكثر أهمية في النافذة الزمنية."""

    def __init__(
        self,
        input_size: int,
        hidden_size: int = 128,
        num_layers: int = 2,
        num_classes: int = 2,
        dropout: float = 0.3
    ):
        super().__init__()
        self.lstm = nn.LSTM(
            input_size, hidden_size, num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0
        )
        self.attention = AttentionLayer(hidden_size)
        self.dropout   = nn.Dropout(dropout)
        self.fc1 = nn.Linear(hidden_size, 64)
        self.fc2 = nn.Linear(64, num_classes)
        self.relu = nn.ReLU()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out, _ = self.lstm(x)
        context = self.attention(out)
        context = self.dropout(context)
        out = self.relu(self.fc1(context))
        return self.fc2(out)


# ─────────────────────────────────────────────────────────────────
# 6. WaveNet للتنبؤ بالأسعار
# ─────────────────────────────────────────────────────────────────

class WaveNetBlock(nn.Module):
    def __init__(self, residual_channels: int, dilation: int):
        super().__init__()
        self.dilated_conv = nn.Conv1d(
            residual_channels, 2 * residual_channels,
            kernel_size=2, dilation=dilation, padding=dilation
        )
        self.res_conv  = nn.Conv1d(residual_channels, residual_channels, 1)
        self.skip_conv = nn.Conv1d(residual_channels, residual_channels, 1)

    def forward(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        out = self.dilated_conv(x)
        out = out[:, :, :x.size(2)]
        tanh_out = torch.tanh(out[:, :out.size(1)//2])
        sig_out  = torch.sigmoid(out[:, out.size(1)//2:])
        gate = tanh_out * sig_out
        res  = self.res_conv(gate) + x
        skip = self.skip_conv(gate)
        return res, skip


class WaveNetModel(nn.Module):
    """
    WaveNet مُعدَّل للتنبؤ بعوائد الأسعار (regression).
    يستخدم الالتفافات المتمددة لالتقاط الأنماط متعددة المقاييس.
    """

    def __init__(
        self,
        input_size: int,
        residual_channels: int = 32,
        num_blocks: int = 3,
        num_layers_per_block: int = 4,
        output_size: int = 1
    ):
        super().__init__()
        self.input_conv = nn.Conv1d(input_size, residual_channels, 1)

        self.blocks = nn.ModuleList()
        for _ in range(num_blocks):
            for layer in range(num_layers_per_block):
                self.blocks.append(
                    WaveNetBlock(residual_channels, 2 ** layer)
                )

        self.output = nn.Sequential(
            nn.ReLU(),
            nn.Conv1d(residual_channels, 64, 1),
            nn.ReLU(),
            nn.Conv1d(64, output_size, 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch, seq, features)
        x = x.permute(0, 2, 1)            # (batch, features, seq)
        x = self.input_conv(x)
        skip_sum = torch.zeros_like(x)
        for block in self.blocks:
            x, skip = block(x)
            skip_sum = skip_sum + skip
        out = self.output(skip_sum)
        return out[:, :, -1]              # آخر خطوة زمنية


# ─────────────────────────────────────────────────────────────────
# 7. مدرب موحّد لجميع النماذج
# ─────────────────────────────────────────────────────────────────

class DeepLearningTrainer:
    """
    مدرب عام لجميع نماذج PyTorch:
      - حلقة تدريب مع Early Stopping
      - جدولة معدل التعلم
      - تقييم تلقائي
      - حفظ وتحميل النموذج
    """

    def __init__(
        self,
        model: nn.Module,
        lr: float = 1e-3,
        weight_decay: float = 1e-4,
        patience: int = 15,
        task: str = "classify"    # 'classify' أو 'regress'
    ):
        self.model      = model.to(DEVICE)
        self.optimizer  = optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
        self.scheduler  = optim.lr_scheduler.ReduceLROnPlateau(
            self.optimizer, patience=5, factor=0.5, verbose=False
        )
        self.early_stop = EarlyStopping(patience=patience)
        self.task       = task
        self.criterion  = nn.CrossEntropyLoss() if task == "classify" else nn.MSELoss()
        self.history: Dict[str, List[float]] = {
            "train_loss": [], "val_loss": [], "val_acc": []
        }

    def train_epoch(self, loader: DataLoader) -> float:
        self.model.train()
        total_loss = 0.0
        for X_batch, y_batch in loader:
            self.optimizer.zero_grad()
            out  = self.model(X_batch)
            if self.task == "regress":
                loss = self.criterion(out.squeeze(), y_batch.float())
            else:
                loss = self.criterion(out, y_batch)
            loss.backward()
            nn.utils.clip_grad_norm_(self.model.parameters(), max_norm=1.0)
            self.optimizer.step()
            total_loss += loss.item()
        return total_loss / len(loader)

    @torch.no_grad()
    def evaluate(self, loader: DataLoader) -> Tuple[float, float]:
        self.model.eval()
        total_loss, correct, total = 0.0, 0, 0
        for X_batch, y_batch in loader:
            out  = self.model(X_batch)
            if self.task == "regress":
                loss = self.criterion(out.squeeze(), y_batch.float())
            else:
                loss = self.criterion(out, y_batch)
                preds = out.argmax(dim=1)
                correct += (preds == y_batch).sum().item()
                total   += y_batch.size(0)
            total_loss += loss.item()
        avg_loss = total_loss / len(loader)
        accuracy = correct / total if self.task == "classify" else 0.0
        return avg_loss, accuracy

    def fit(
        self,
        X_train: np.ndarray, y_train: np.ndarray,
        X_val:   np.ndarray, y_val:   np.ndarray,
        epochs: int = 100,
        batch_size: int = 64
    ) -> Dict:
        train_loader = make_dataloader(X_train, y_train, batch_size, shuffle=True)
        val_loader   = make_dataloader(X_val,   y_val,   batch_size, shuffle=False)

        best_val_loss = np.inf
        best_state    = None

        for epoch in range(1, epochs + 1):
            train_loss = self.train_epoch(train_loader)
            val_loss, val_acc = self.evaluate(val_loader)

            self.scheduler.step(val_loss)
            self.early_stop(val_loss)

            self.history["train_loss"].append(train_loss)
            self.history["val_loss"].append(val_loss)
            self.history["val_acc"].append(val_acc)

            if val_loss < best_val_loss:
                best_val_loss = val_loss
                best_state    = {k: v.clone() for k, v in self.model.state_dict().items()}

            if epoch % 10 == 0:
                print(f"  Epoch {epoch:4d} | train_loss={train_loss:.4f} "
                      f"| val_loss={val_loss:.4f} | val_acc={val_acc:.4f}")

            if self.early_stop.stop:
                print(f"  وقف مبكر في الحقبة {epoch}")
                break

        if best_state:
            self.model.load_state_dict(best_state)

        return self.history

    @torch.no_grad()
    def predict(self, X: np.ndarray) -> np.ndarray:
        self.model.eval()
        tensor = to_tensor(X)
        out = self.model(tensor)
        if self.task == "classify":
            return out.argmax(dim=1).cpu().numpy()
        return out.squeeze().cpu().numpy()

    @torch.no_grad()
    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        self.model.eval()
        tensor = to_tensor(X)
        out = self.model(tensor)
        return torch.softmax(out, dim=1).cpu().numpy()

    def save(self, path: str):
        torch.save({"model_state": self.model.state_dict(),
                    "history": self.history}, path)
        print(f"[DL] تم الحفظ: {path}")

    def load(self, path: str):
        ckpt = torch.load(path, map_location=DEVICE)
        self.model.load_state_dict(ckpt["model_state"])
        self.history = ckpt.get("history", {})


# ─────────────────────────────────────────────────────────────────
# مثال التشغيل
# ─────────────────────────────────────────────────────────────────

def demo_deep_learning():
    print("=" * 60)
    print("  نماذج التعلم العميق للتداول الآلي")
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

    processor = DataProcessor(window_size=60)
    data = processor.prepare(df)

    X_tr = data["X_seq_train"]; y_tr = data["y_seq_train"]
    X_v  = data["X_seq_val"];   y_v  = data["y_seq_val"]
    X_te = data["X_seq_test"];  y_te = data["y_seq_test"]
    n_feat = data["n_features"]
    print(f"شكل بيانات التدريب: {X_tr.shape}")

    models_cfg = {
        "LSTM":         LSTMModel(n_feat, hidden_size=64, num_layers=2, num_classes=2),
        "BiLSTM":       LSTMModel(n_feat, hidden_size=64, num_layers=2, num_classes=2, bidirectional=True),
        "GRU":          GRUModel(n_feat, hidden_size=64, num_layers=2, num_classes=2),
        "TCN":          TCNModel(n_feat, num_channels=[32, 64, 64, 32], num_classes=2),
        "Transformer":  TransformerTrader(n_feat, d_model=64, nhead=4, num_layers=2, num_classes=2),
        "LSTMAttn":     LSTMAttentionModel(n_feat, hidden_size=64, num_layers=2, num_classes=2),
    }

    results = {}
    for name, model in models_cfg.items():
        print(f"\n── تدريب {name} ──")
        trainer = DeepLearningTrainer(model, lr=1e-3, patience=10)
        trainer.fit(X_tr, y_tr, X_v, y_v, epochs=30, batch_size=64)
        preds = trainer.predict(X_te)
        from sklearn.metrics import accuracy_score, f1_score
        acc = accuracy_score(y_te, preds)
        f1  = f1_score(y_te, preds, average="weighted", zero_division=0)
        results[name] = {"accuracy": acc, "f1": f1}
        print(f"   دقة: {acc:.4f} | F1: {f1:.4f}")

    print("\n" + "=" * 60)
    print("  ملخص النتائج")
    print("=" * 60)
    for name, m in results.items():
        print(f"  {name:15s} → Acc={m['accuracy']:.4f}  F1={m['f1']:.4f}")
    print("\n✅ اكتمل التدريب بنجاح.")


if __name__ == "__main__":
    demo_deep_learning()
