"""머신러닝 기반 트레이딩 전략.

기술적 지표를 피처로 사용하여 RandomForest 모델로 향후 수익률을 예측한다.
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler

from strategies.base import BaseStrategy, Signal
from utils.logger import setup_logger

logger = setup_logger("ml_strategy")


def _compute_features(df: pd.DataFrame) -> pd.DataFrame:
    """가격 DataFrame에서 ML 피처를 계산한다."""
    feat = pd.DataFrame(index=df.index)

    # 수익률 기반 피처
    feat["return_1d"] = df["close"].pct_change(1)
    feat["return_3d"] = df["close"].pct_change(3)
    feat["return_5d"] = df["close"].pct_change(5)
    feat["return_10d"] = df["close"].pct_change(10)

    # 이동평균 비율
    for w in (5, 10, 20):
        ma = df["close"].rolling(w).mean()
        feat[f"ma_ratio_{w}"] = df["close"] / ma - 1

    # 변동성
    feat["volatility_5d"] = df["close"].pct_change().rolling(5).std()
    feat["volatility_20d"] = df["close"].pct_change().rolling(20).std()

    # RSI
    delta = df["close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    feat["rsi"] = 100 - (100 / (1 + rs))

    # MACD
    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()
    feat["macd"] = ema12 - ema26
    feat["macd_signal"] = feat["macd"].ewm(span=9, adjust=False).mean()
    feat["macd_hist"] = feat["macd"] - feat["macd_signal"]

    # 볼린저 밴드 %B
    ma20 = df["close"].rolling(20).mean()
    std20 = df["close"].rolling(20).std()
    feat["bb_pctb"] = (df["close"] - (ma20 - 2 * std20)) / (4 * std20).replace(0, np.nan)

    # 거래량 비율
    vol_ma = df["volume"].rolling(20).mean()
    feat["volume_ratio"] = df["volume"] / vol_ma.replace(0, np.nan)

    # 캔들 패턴 (단순)
    feat["body_ratio"] = (df["close"] - df["open"]) / (df["high"] - df["low"]).replace(0, np.nan)
    feat["upper_shadow"] = (df["high"] - df[["open", "close"]].max(axis=1)) / (df["high"] - df["low"]).replace(0, np.nan)

    return feat


class MLStrategy(BaseStrategy):
    """머신러닝 기반 전략.

    학습: 최근 N일간 데이터로 5일 후 수익률을 예측하는 분류 모델 학습.
    타깃: 5일 후 수익률이 +2% 이상이면 매수(1), -2% 이하면 매도(-1), 그 외 홀드(0).
    """

    def __init__(self):
        self._model = RandomForestClassifier(
            n_estimators=100,
            max_depth=5,
            min_samples_leaf=5,
            random_state=42,
            n_jobs=-1,
        )
        self._scaler = StandardScaler()

    @property
    def name(self) -> str:
        return "MLForest"

    def analyze(self, daily_prices: list[dict], current_price: dict) -> tuple[Signal, float, str]:
        if len(daily_prices) < 40:
            return Signal.HOLD, 0.0, "데이터 부족 (최소 40일 필요)"

        df = pd.DataFrame(daily_prices).sort_values("date").reset_index(drop=True)
        for col in ("open", "high", "low", "close", "volume"):
            df[col] = pd.to_numeric(df[col], errors="coerce")

        features = _compute_features(df)

        # 타깃: 5일 후 수익률 기반 라벨
        future_return = df["close"].pct_change(5).shift(-5)
        labels = pd.Series(0, index=df.index)
        labels[future_return > 0.02] = 1    # 매수
        labels[future_return < -0.02] = -1   # 매도

        # 학습 데이터 준비 (마지막 5일은 타깃 없음)
        valid_mask = features.notna().all(axis=1) & labels.notna() & future_return.notna()
        train_idx = valid_mask[valid_mask].index

        if len(train_idx) < 20:
            return Signal.HOLD, 0.0, "학습 데이터 부족"

        X_train = features.loc[train_idx].values
        y_train = labels.loc[train_idx].values

        # 스케일링 및 학습
        X_train_scaled = self._scaler.fit_transform(X_train)
        self._model.fit(X_train_scaled, y_train)

        # 최신 데이터로 예측
        latest_features = features.iloc[[-1]]
        if latest_features.isna().any(axis=1).iloc[0]:
            return Signal.HOLD, 0.0, "피처 계산 불가"

        X_pred = self._scaler.transform(latest_features.values)
        prediction = self._model.predict(X_pred)[0]
        probabilities = self._model.predict_proba(X_pred)[0]
        confidence = float(max(probabilities))

        # 피처 중요도 상위 3개
        importances = self._model.feature_importances_
        feature_names = features.columns.tolist()
        top_indices = np.argsort(importances)[-3:][::-1]
        top_features = [f"{feature_names[i]}({importances[i]:.2f})" for i in top_indices]

        reason_parts = [f"예측: {'매수' if prediction == 1 else '매도' if prediction == -1 else '홀드'}"]
        reason_parts.append(f"확률: {confidence:.1%}")
        reason_parts.append(f"주요 피처: {', '.join(top_features)}")
        reason = " | ".join(reason_parts)

        if prediction == 1:
            signal = Signal.STRONG_BUY if confidence > 0.6 else Signal.BUY
        elif prediction == -1:
            signal = Signal.STRONG_SELL if confidence > 0.6 else Signal.SELL
        else:
            signal = Signal.HOLD

        return signal, confidence, reason
