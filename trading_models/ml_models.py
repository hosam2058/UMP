"""
====================================================================
 نماذج التعلم الآلي لأنظمة التداول الآلي
 Machine Learning Models for Automated Trading Systems
====================================================================
النماذج المشمولة:
  1. Random Forest Classifier
  2. XGBoost Classifier / Regressor
  3. LightGBM
  4. CatBoost
  5. Support Vector Machine (SVM)
  6. Gradient Boosting Ensemble
  7. Meta-Learner (Stacking)
  8. Bayesian Hyperparameter Optimization
  9. SHAP Feature Importance
====================================================================
"""

import numpy as np
import pandas as pd
from typing import Dict, Tuple, Optional, List
import warnings
warnings.filterwarnings("ignore")

from sklearn.ensemble import (
    RandomForestClassifier, GradientBoostingClassifier,
    VotingClassifier, StackingClassifier
)
from sklearn.svm import SVC
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score, f1_score, classification_report,
    roc_auc_score, confusion_matrix
)
from sklearn.calibration import CalibratedClassifierCV
import joblib


# ─────────────────────────────────────────────────────────────────
# 1. نموذج الغابة العشوائية
# ─────────────────────────────────────────────────────────────────

class RandomForestTrader:
    """
    مصنّف الغابة العشوائية المُحسَّن للتداول.
    يدعم التنبؤ الثنائي (شراء/بيع) والثلاثي (شراء/محايد/بيع).
    """

    def __init__(
        self,
        n_estimators: int = 500,
        max_depth: int = 10,
        min_samples_leaf: int = 10,
        n_jobs: int = -1,
        class_weight: str = "balanced",
        random_state: int = 42
    ):
        self.model = RandomForestClassifier(
            n_estimators=n_estimators,
            max_depth=max_depth,
            min_samples_leaf=min_samples_leaf,
            n_jobs=n_jobs,
            class_weight=class_weight,
            random_state=random_state,
            oob_score=True,
        )
        self.feature_names: List[str] = []
        self.is_fitted = False

    def fit(self, X_train: np.ndarray, y_train: np.ndarray,
            feature_names: Optional[List[str]] = None) -> "RandomForestTrader":
        self.feature_names = feature_names or [f"f{i}" for i in range(X_train.shape[1])]
        self.model.fit(X_train, y_train)
        self.is_fitted = True
        print(f"[RF] OOB Score: {self.model.oob_score_:.4f}")
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        return self.model.predict(X)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        return self.model.predict_proba(X)

    def evaluate(self, X_test: np.ndarray, y_test: np.ndarray) -> Dict:
        preds = self.predict(X_test)
        proba = self.predict_proba(X_test)
        metrics = {
            "accuracy": accuracy_score(y_test, preds),
            "f1_weighted": f1_score(y_test, preds, average="weighted"),
            "report": classification_report(y_test, preds),
            "confusion_matrix": confusion_matrix(y_test, preds),
        }
        if proba.shape[1] == 2:
            metrics["roc_auc"] = roc_auc_score(y_test, proba[:, 1])
        return metrics

    def feature_importance(self, top_n: int = 20) -> pd.DataFrame:
        importances = self.model.feature_importances_
        df = pd.DataFrame({
            "feature": self.feature_names,
            "importance": importances
        }).sort_values("importance", ascending=False).head(top_n)
        return df

    def save(self, path: str):
        joblib.dump(self.model, path)
        print(f"[RF] تم الحفظ: {path}")

    def load(self, path: str):
        self.model = joblib.load(path)
        self.is_fitted = True


# ─────────────────────────────────────────────────────────────────
# 2. نموذج XGBoost
# ─────────────────────────────────────────────────────────────────

class XGBoostTrader:
    """
    نموذج XGBoost متكامل للتداول مع دعم Early Stopping.
    """

    def __init__(
        self,
        n_estimators: int = 500,
        learning_rate: float = 0.05,
        max_depth: int = 6,
        subsample: float = 0.8,
        colsample_bytree: float = 0.8,
        use_gpu: bool = False,
        task: str = "classify"   # 'classify' أو 'regress'
    ):
        try:
            import xgboost as xgb
        except ImportError:
            raise ImportError("pip install xgboost")

        tree_method = "gpu_hist" if use_gpu else "hist"
        self.task = task

        if task == "classify":
            self.model = xgb.XGBClassifier(
                n_estimators=n_estimators,
                learning_rate=learning_rate,
                max_depth=max_depth,
                subsample=subsample,
                colsample_bytree=colsample_bytree,
                tree_method=tree_method,
                eval_metric="logloss",
                use_label_encoder=False,
                random_state=42,
                n_jobs=-1,
            )
        else:
            self.model = xgb.XGBRegressor(
                n_estimators=n_estimators,
                learning_rate=learning_rate,
                max_depth=max_depth,
                subsample=subsample,
                colsample_bytree=colsample_bytree,
                tree_method=tree_method,
                eval_metric="rmse",
                random_state=42,
                n_jobs=-1,
            )
        self.feature_names: List[str] = []

    def fit(
        self,
        X_train, y_train,
        X_val=None, y_val=None,
        early_stopping_rounds: int = 50,
        feature_names: Optional[List[str]] = None
    ) -> "XGBoostTrader":
        self.feature_names = feature_names or [f"f{i}" for i in range(X_train.shape[1])]
        eval_set = [(X_val, y_val)] if X_val is not None else None
        self.model.fit(
            X_train, y_train,
            eval_set=eval_set,
            verbose=False,
            early_stopping_rounds=early_stopping_rounds if eval_set else None,
        )
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        return self.model.predict(X)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if self.task == "classify":
            return self.model.predict_proba(X)
        return self.model.predict(X)

    def evaluate(self, X_test: np.ndarray, y_test: np.ndarray) -> Dict:
        preds = self.predict(X_test)
        if self.task == "classify":
            return {
                "accuracy": accuracy_score(y_test, preds),
                "f1_weighted": f1_score(y_test, preds, average="weighted"),
                "report": classification_report(y_test, preds),
            }
        else:
            from sklearn.metrics import mean_squared_error, r2_score
            return {
                "rmse": np.sqrt(mean_squared_error(y_test, preds)),
                "r2": r2_score(y_test, preds),
            }

    def feature_importance(self, top_n: int = 20) -> pd.DataFrame:
        importances = self.model.feature_importances_
        return pd.DataFrame({
            "feature": self.feature_names,
            "importance": importances
        }).sort_values("importance", ascending=False).head(top_n)

    def save(self, path: str):
        self.model.save_model(path)

    def load(self, path: str):
        self.model.load_model(path)


# ─────────────────────────────────────────────────────────────────
# 3. نموذج LightGBM
# ─────────────────────────────────────────────────────────────────

class LightGBMTrader:
    """نموذج LightGBM – سريع وخفيف ودقيق للبيانات المالية الكبيرة."""

    def __init__(
        self,
        n_estimators: int = 500,
        learning_rate: float = 0.05,
        max_depth: int = -1,
        num_leaves: int = 31,
        subsample: float = 0.8,
        task: str = "classify"
    ):
        try:
            import lightgbm as lgb
        except ImportError:
            raise ImportError("pip install lightgbm")

        params = dict(
            n_estimators=n_estimators,
            learning_rate=learning_rate,
            max_depth=max_depth,
            num_leaves=num_leaves,
            subsample=subsample,
            n_jobs=-1,
            random_state=42,
            verbose=-1,
        )
        self.task = task
        if task == "classify":
            self.model = lgb.LGBMClassifier(class_weight="balanced", **params)
        else:
            self.model = lgb.LGBMRegressor(**params)
        self.feature_names: List[str] = []

    def fit(self, X_train, y_train, X_val=None, y_val=None,
            feature_names: Optional[List[str]] = None) -> "LightGBMTrader":
        self.feature_names = feature_names or [f"f{i}" for i in range(X_train.shape[1])]
        callbacks = []
        try:
            import lightgbm as lgb
            callbacks.append(lgb.early_stopping(50, verbose=False))
            callbacks.append(lgb.log_evaluation(period=-1))
        except Exception:
            pass
        eval_set = [(X_val, y_val)] if X_val is not None else None
        self.model.fit(
            X_train, y_train,
            eval_set=eval_set,
            callbacks=callbacks if eval_set else None,
        )
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        return self.model.predict(X)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if self.task == "classify":
            return self.model.predict_proba(X)
        return self.model.predict(X)

    def evaluate(self, X_test, y_test) -> Dict:
        preds = self.predict(X_test)
        return {
            "accuracy": accuracy_score(y_test, preds),
            "f1_weighted": f1_score(y_test, preds, average="weighted"),
            "report": classification_report(y_test, preds),
        }

    def feature_importance(self, top_n: int = 20) -> pd.DataFrame:
        return pd.DataFrame({
            "feature": self.feature_names,
            "importance": self.model.feature_importances_
        }).sort_values("importance", ascending=False).head(top_n)


# ─────────────────────────────────────────────────────────────────
# 4. نموذج CatBoost
# ─────────────────────────────────────────────────────────────────

class CatBoostTrader:
    """CatBoost – ممتاز للميزات الفئوية وبيانات السوق المالي."""

    def __init__(
        self,
        iterations: int = 500,
        learning_rate: float = 0.05,
        depth: int = 6,
        use_gpu: bool = False,
        task: str = "classify"
    ):
        try:
            from catboost import CatBoostClassifier, CatBoostRegressor
        except ImportError:
            raise ImportError("pip install catboost")

        task_type = "GPU" if use_gpu else "CPU"
        if task == "classify":
            from catboost import CatBoostClassifier
            self.model = CatBoostClassifier(
                iterations=iterations,
                learning_rate=learning_rate,
                depth=depth,
                task_type=task_type,
                auto_class_weights="Balanced",
                verbose=False,
                random_seed=42,
            )
        else:
            from catboost import CatBoostRegressor
            self.model = CatBoostRegressor(
                iterations=iterations,
                learning_rate=learning_rate,
                depth=depth,
                task_type=task_type,
                verbose=False,
                random_seed=42,
            )
        self.task = task
        self.feature_names: List[str] = []

    def fit(self, X_train, y_train, X_val=None, y_val=None,
            feature_names: Optional[List[str]] = None) -> "CatBoostTrader":
        from catboost import Pool
        self.feature_names = feature_names or [f"f{i}" for i in range(X_train.shape[1])]
        train_pool = Pool(X_train, y_train)
        eval_pool  = Pool(X_val, y_val) if X_val is not None else None
        self.model.fit(
            train_pool,
            eval_set=eval_pool,
            early_stopping_rounds=50 if eval_pool else None,
        )
        return self

    def predict(self, X):
        return self.model.predict(X)

    def predict_proba(self, X):
        if self.task == "classify":
            return self.model.predict_proba(X)
        return self.model.predict(X)

    def evaluate(self, X_test, y_test) -> Dict:
        preds = self.predict(X_test).flatten().astype(int)
        return {
            "accuracy": accuracy_score(y_test, preds),
            "f1_weighted": f1_score(y_test, preds, average="weighted"),
            "report": classification_report(y_test, preds),
        }


# ─────────────────────────────────────────────────────────────────
# 5. نموذج SVM
# ─────────────────────────────────────────────────────────────────

class SVMTrader:
    """دعم المتجهات – فعّال للبيانات عالية الأبعاد."""

    def __init__(self, kernel: str = "rbf", C: float = 1.0,
                 gamma: str = "scale", probability: bool = True):
        base = SVC(kernel=kernel, C=C, gamma=gamma,
                   probability=probability, class_weight="balanced")
        self.model = CalibratedClassifierCV(base, cv=3)

    def fit(self, X_train, y_train) -> "SVMTrader":
        self.model.fit(X_train, y_train)
        return self

    def predict(self, X):
        return self.model.predict(X)

    def predict_proba(self, X):
        return self.model.predict_proba(X)

    def evaluate(self, X_test, y_test) -> Dict:
        preds = self.predict(X_test)
        return {
            "accuracy": accuracy_score(y_test, preds),
            "f1_weighted": f1_score(y_test, preds, average="weighted"),
            "report": classification_report(y_test, preds),
        }


# ─────────────────────────────────────────────────────────────────
# 6. Ensemble Voting
# ─────────────────────────────────────────────────────────────────

class EnsembleTrader:
    """
    تجميع نماذج متعددة باستخدام Soft Voting أو Stacking.
    يدمج: RF + XGBoost + LightGBM + GBM
    """

    def __init__(self, voting: str = "soft"):
        from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier

        estimators = [
            ("rf",  RandomForestClassifier(n_estimators=200, class_weight="balanced",
                                           n_jobs=-1, random_state=42)),
            ("gbm", GradientBoostingClassifier(n_estimators=200, learning_rate=0.05,
                                               max_depth=5, random_state=42)),
        ]
        try:
            import xgboost as xgb
            estimators.append(("xgb", xgb.XGBClassifier(
                n_estimators=200, learning_rate=0.05, max_depth=5,
                use_label_encoder=False, eval_metric="logloss", n_jobs=-1,
                random_state=42
            )))
        except ImportError:
            pass
        try:
            import lightgbm as lgb
            estimators.append(("lgb", lgb.LGBMClassifier(
                n_estimators=200, learning_rate=0.05, verbose=-1,
                n_jobs=-1, random_state=42
            )))
        except ImportError:
            pass

        self.model = VotingClassifier(estimators=estimators, voting=voting, n_jobs=-1)

    def fit(self, X_train, y_train) -> "EnsembleTrader":
        self.model.fit(X_train, y_train)
        return self

    def predict(self, X):
        return self.model.predict(X)

    def predict_proba(self, X):
        return self.model.predict_proba(X)

    def evaluate(self, X_test, y_test) -> Dict:
        preds = self.predict(X_test)
        return {
            "accuracy": accuracy_score(y_test, preds),
            "f1_weighted": f1_score(y_test, preds, average="weighted"),
            "report": classification_report(y_test, preds),
        }


# ─────────────────────────────────────────────────────────────────
# 7. Stacking Meta-Learner
# ─────────────────────────────────────────────────────────────────

class StackingTrader:
    """
    نموذج التكديس (Stacking):
    - مستوى أول: RF, GBM, (XGBoost, LightGBM اختيارياً)
    - مستوى ثانٍ (Meta-Learner): Logistic Regression
    """

    def __init__(self):
        from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier

        estimators = [
            ("rf",  RandomForestClassifier(n_estimators=100, n_jobs=-1, random_state=42)),
            ("gbm", GradientBoostingClassifier(n_estimators=100, random_state=42)),
        ]
        self.model = StackingClassifier(
            estimators=estimators,
            final_estimator=LogisticRegression(max_iter=1000),
            cv=5,
            n_jobs=-1,
            passthrough=True,
        )

    def fit(self, X_train, y_train) -> "StackingTrader":
        self.model.fit(X_train, y_train)
        return self

    def predict(self, X):
        return self.model.predict(X)

    def predict_proba(self, X):
        return self.model.predict_proba(X)

    def evaluate(self, X_test, y_test) -> Dict:
        preds = self.predict(X_test)
        return {
            "accuracy": accuracy_score(y_test, preds),
            "f1_weighted": f1_score(y_test, preds, average="weighted"),
            "report": classification_report(y_test, preds),
        }


# ─────────────────────────────────────────────────────────────────
# 8. تحسين المعاملات الفائقة (Bayesian – Optuna)
# ─────────────────────────────────────────────────────────────────

class BayesianOptimizer:
    """
    تحسين المعاملات الفائقة لنماذج XGBoost / LightGBM
    باستخدام Optuna (بحث بيزي).
    """

    def __init__(self, model_type: str = "xgboost", n_trials: int = 50):
        self.model_type = model_type
        self.n_trials   = n_trials
        self.best_params: Dict = {}

    def optimize(self, X_train, y_train, X_val, y_val) -> Dict:
        try:
            import optuna
            optuna.logging.set_verbosity(optuna.logging.WARNING)
        except ImportError:
            raise ImportError("pip install optuna")

        def objective(trial):
            if self.model_type == "xgboost":
                import xgboost as xgb
                params = {
                    "n_estimators":    trial.suggest_int("n_estimators", 100, 1000),
                    "learning_rate":   trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
                    "max_depth":       trial.suggest_int("max_depth", 3, 10),
                    "subsample":       trial.suggest_float("subsample", 0.5, 1.0),
                    "colsample_bytree":trial.suggest_float("colsample_bytree", 0.5, 1.0),
                    "reg_alpha":       trial.suggest_float("reg_alpha", 1e-4, 10, log=True),
                    "reg_lambda":      trial.suggest_float("reg_lambda", 1e-4, 10, log=True),
                    "use_label_encoder": False,
                    "eval_metric": "logloss",
                    "n_jobs": -1,
                }
                model = xgb.XGBClassifier(**params)
            else:
                import lightgbm as lgb
                params = {
                    "n_estimators":  trial.suggest_int("n_estimators", 100, 1000),
                    "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
                    "num_leaves":    trial.suggest_int("num_leaves", 16, 256),
                    "max_depth":     trial.suggest_int("max_depth", 3, 12),
                    "subsample":     trial.suggest_float("subsample", 0.5, 1.0),
                    "reg_alpha":     trial.suggest_float("reg_alpha", 1e-4, 10, log=True),
                    "n_jobs": -1,
                    "verbose": -1,
                }
                model = lgb.LGBMClassifier(**params)

            model.fit(X_train, y_train)
            preds = model.predict(X_val)
            return f1_score(y_val, preds, average="weighted")

        study = optuna.create_study(direction="maximize")
        study.optimize(objective, n_trials=self.n_trials, show_progress_bar=False)
        self.best_params = study.best_params
        print(f"[Optuna] أفضل F1: {study.best_value:.4f}")
        print(f"[Optuna] أفضل معاملات: {self.best_params}")
        return self.best_params


# ─────────────────────────────────────────────────────────────────
# 9. SHAP – تفسير النماذج
# ─────────────────────────────────────────────────────────────────

class ModelExplainer:
    """
    تفسير أهمية الميزات باستخدام SHAP.
    يدعم XGBoost و LightGBM والغابة العشوائية.
    """

    def __init__(self, model, X_background: np.ndarray):
        try:
            import shap
        except ImportError:
            raise ImportError("pip install shap")
        import shap
        self.shap_values = None
        try:
            self.explainer = shap.TreeExplainer(model)
        except Exception:
            self.explainer = shap.KernelExplainer(
                model.predict_proba, shap.sample(X_background, 100)
            )

    def compute_shap(self, X: np.ndarray) -> np.ndarray:
        import shap
        self.shap_values = self.explainer.shap_values(X)
        return self.shap_values

    def summary(self, X: np.ndarray, feature_names: List[str]):
        import shap, matplotlib.pyplot as plt
        sv = self.compute_shap(X)
        if isinstance(sv, list):
            sv = sv[1]
        shap.summary_plot(sv, X, feature_names=feature_names, show=False)
        plt.tight_layout()
        plt.savefig("shap_summary.png", dpi=150)
        plt.close()
        print("[SHAP] تم حفظ المخطط: shap_summary.png")


# ─────────────────────────────────────────────────────────────────
# مثال التشغيل
# ─────────────────────────────────────────────────────────────────

def demo_ml_models():
    print("=" * 60)
    print("  نماذج التعلم الآلي للتداول الآلي")
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

    X_tr, y_tr = data["X_train"], data["y_train"]
    X_v,  y_v  = data["X_val"],   data["y_val"]
    X_te, y_te = data["X_test"],  data["y_test"]
    fnames = data["feature_names"]

    models = {
        "RandomForest": RandomForestTrader(n_estimators=200),
        "XGBoost":      XGBoostTrader(n_estimators=200),
        "LightGBM":     LightGBMTrader(n_estimators=200),
        "Ensemble":     EnsembleTrader(),
    }

    results = {}
    for name, mdl in models.items():
        print(f"\n── تدريب {name} ──")
        if isinstance(mdl, (XGBoostTrader, LightGBMTrader)):
            mdl.fit(X_tr, y_tr, X_v, y_v, feature_names=fnames)
        elif isinstance(mdl, RandomForestTrader):
            mdl.fit(X_tr, y_tr, feature_names=fnames)
        else:
            mdl.fit(X_tr, y_tr)
        metrics = mdl.evaluate(X_te, y_te)
        results[name] = metrics
        print(f"   دقة: {metrics['accuracy']:.4f} | F1: {metrics['f1_weighted']:.4f}")

    print("\n" + "=" * 60)
    print("  ملخص المقارنة")
    print("=" * 60)
    for name, m in results.items():
        print(f"  {name:15s} → Acc={m['accuracy']:.4f}  F1={m['f1_weighted']:.4f}")
    print("\n✅ اكتمل التدريب والتقييم بنجاح.")


if __name__ == "__main__":
    demo_ml_models()
