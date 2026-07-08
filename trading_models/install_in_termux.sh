#!/bin/bash
# =====================================================
# سكريبت تثبيت نماذج التداول في Termux
# شغّل هذا السكريبت داخل مجلد مشروعك (UMP/)
# =====================================================
set -e

echo "======================================"
echo " تثبيت نماذج التداول الآلي"
echo "======================================"

# 1. إنشاء المجلد
mkdir -p trading_models
cd trading_models

echo "[1] تحميل الملفات من GitHub..."

BASE="https://raw.githubusercontent.com/hosam2058/UMP/main/trading_models"

FILES=(
  "data_preprocessing.py"
  "ml_models.py"
  "deep_learning_models.py"
  "computer_vision_models.py"
  "reinforcement_learning.py"
  "advanced_analysis.py"
  "sentiment_analysis.py"
  "risk_management.py"
  "trading_system.py"
  "requirements.txt"
)

# إذا لم تكن الملفات على GitHub بعد، سنستخدم نسخة محلية
# وإلا نُحملها مباشرة
for f in "${FILES[@]}"; do
  if [ -f "$f" ]; then
    echo "   ✓ موجود بالفعل: $f"
  else
    echo "   ⚠ لم يُعثر عليه: $f"
    echo "   → ستحتاج لنسخه يدوياً أو رفعه على GitHub أولاً"
  fi
done

echo ""
echo "[2] تثبيت المكتبات الأساسية لـ Termux..."

# مكتبات تعمل بشكل موثوق في Termux
pip install --upgrade pip 2>/dev/null || pip3 install --upgrade pip

BASIC_PACKAGES=(
  "numpy"
  "pandas"
  "scikit-learn"
  "scipy"
  "matplotlib"
  "statsmodels"
  "ta"
  "yfinance"
  "joblib"
  "pywavelets"
)

echo "   تثبيت المكتبات الأساسية..."
pip install "${BASIC_PACKAGES[@]}" --quiet

ADVANCED_PACKAGES=(
  "xgboost"
  "lightgbm"
  "optuna"
)

echo "   تثبيت XGBoost و LightGBM..."
pip install "${ADVANCED_PACKAGES[@]}" --quiet 2>/dev/null && echo "   ✓" || echo "   ⚠ بعض المكتبات قد تحتاج تثبيتاً يدوياً"

# PyTorch — مدعوم في Termux لكن قد يحتاج وقتاً
echo ""
echo "[3] محاولة تثبيت PyTorch..."
pip install torch --quiet 2>/dev/null && echo "   ✓ PyTorch" || {
  echo "   ⚠ PyTorch يحتاج تثبيت خاص في Termux:"
  echo "   → pip install torch --index-url https://download.pytorch.org/whl/cpu"
}

echo ""
echo "[4] فحص التثبيت..."
python3 -c "
import numpy as np
import pandas as pd
import sklearn
import scipy
print('✓ numpy:', np.__version__)
print('✓ pandas:', pd.__version__)
print('✓ scikit-learn:', sklearn.__version__)
try:
    import xgboost; print('✓ xgboost:', xgboost.__version__)
except: print('✗ xgboost - يحتاج تثبيت')
try:
    import lightgbm; print('✓ lightgbm:', lightgbm.__version__)
except: print('✗ lightgbm - يحتاج تثبيت')
try:
    import torch; print('✓ torch:', torch.__version__)
except: print('✗ torch - يحتاج تثبيت')
try:
    import statsmodels; print('✓ statsmodels:', statsmodels.__version__)
except: print('✗ statsmodels')
try:
    import yfinance; print('✓ yfinance')
except: print('✗ yfinance')
"

echo ""
echo "======================================"
echo " انتهى التثبيت!"
echo " لاختبار النظام:"
echo "   cd trading_models"
echo "   python3 data_preprocessing.py"
echo "   python3 ml_models.py"
echo "   python3 trading_system.py"
echo "======================================"
