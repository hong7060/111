"""모멘텀 기반 트레이딩 전략.

이동평균선 교차, RSI, MACD 등 기술적 지표를 활용한 추세 추종 전략.
"""

import numpy as np
import pandas as pd

from strategies.base import BaseStrategy, Signal


def _to_dataframe(daily_prices: list[dict]) -> pd.DataFrame:
    """일별 가격 리스트를 DataFrame으로 변환한다 (오래된 순 정렬)."""
    df = pd.DataFrame(daily_prices)
    df = df.sort_values("date").reset_index(drop=True)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


class MomentumStrategy(BaseStrategy):
    """모멘텀 / 추세 추종 전략.

    판단 기준:
    - 5일/20일 이동평균선 골든크로스/데드크로스
    - RSI 과매수/과매도
    - MACD 시그널 교차
    - 거래량 급증 여부
    """

    @property
    def name(self) -> str:
        return "Momentum"

    def analyze(self, daily_prices: list[dict], current_price: dict) -> tuple[Signal, float, str]:
        if len(daily_prices) < 26:
            return Signal.HOLD, 0.0, "데이터 부족"

        df = _to_dataframe(daily_prices)
        score = 0.0
        reasons = []

        # --- 이동평균선 ---
        df["ma5"] = df["close"].rolling(5).mean()
        df["ma20"] = df["close"].rolling(20).mean()
        df["ma60"] = df["close"].rolling(60).mean()

        last = df.iloc[-1]
        prev = df.iloc[-2]

        # 골든크로스 / 데드크로스 (5일선 & 20일선)
        if pd.notna(last["ma5"]) and pd.notna(last["ma20"]):
            if last["ma5"] > last["ma20"] and prev["ma5"] <= prev["ma20"]:
                score += 2.0
                reasons.append("5/20일선 골든크로스")
            elif last["ma5"] < last["ma20"] and prev["ma5"] >= prev["ma20"]:
                score -= 2.0
                reasons.append("5/20일선 데드크로스")
            elif last["ma5"] > last["ma20"]:
                score += 0.5
                reasons.append("5일선 > 20일선 (상승추세)")
            else:
                score -= 0.5
                reasons.append("5일선 < 20일선 (하락추세)")

        # 현재가 vs 이동평균선 배열
        price = last["close"]
        if pd.notna(last.get("ma60")):
            if price > last["ma5"] > last["ma20"] > last["ma60"]:
                score += 1.5
                reasons.append("정배열 (강한 상승)")
            elif price < last["ma5"] < last["ma20"] < last["ma60"]:
                score -= 1.5
                reasons.append("역배열 (강한 하락)")

        # --- RSI (14일) ---
        delta = df["close"].diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        current_rsi = rsi.iloc[-1]

        if pd.notna(current_rsi):
            if current_rsi < 30:
                score += 2.0
                reasons.append(f"RSI 과매도 ({current_rsi:.1f})")
            elif current_rsi < 40:
                score += 1.0
                reasons.append(f"RSI 매수 구간 ({current_rsi:.1f})")
            elif current_rsi > 70:
                score -= 2.0
                reasons.append(f"RSI 과매수 ({current_rsi:.1f})")
            elif current_rsi > 60:
                score -= 1.0
                reasons.append(f"RSI 매도 구간 ({current_rsi:.1f})")

        # --- MACD ---
        ema12 = df["close"].ewm(span=12, adjust=False).mean()
        ema26 = df["close"].ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        signal_line = macd.ewm(span=9, adjust=False).mean()
        histogram = macd - signal_line

        if len(histogram) >= 2:
            if histogram.iloc[-1] > 0 and histogram.iloc[-2] <= 0:
                score += 1.5
                reasons.append("MACD 골든크로스")
            elif histogram.iloc[-1] < 0 and histogram.iloc[-2] >= 0:
                score -= 1.5
                reasons.append("MACD 데드크로스")

        # --- 거래량 분석 ---
        avg_volume = df["volume"].rolling(20).mean().iloc[-1]
        if pd.notna(avg_volume) and avg_volume > 0:
            volume_ratio = last["volume"] / avg_volume
            if volume_ratio > 2.0 and last["close"] > prev["close"]:
                score += 1.0
                reasons.append(f"거래량 급증 상승 (x{volume_ratio:.1f})")
            elif volume_ratio > 2.0 and last["close"] < prev["close"]:
                score -= 1.0
                reasons.append(f"거래량 급증 하락 (x{volume_ratio:.1f})")

        # --- 종합 판단 ---
        max_score = 8.0
        confidence = min(abs(score) / max_score, 1.0)

        if score >= 3.0:
            signal = Signal.STRONG_BUY
        elif score >= 1.0:
            signal = Signal.BUY
        elif score <= -3.0:
            signal = Signal.STRONG_SELL
        elif score <= -1.0:
            signal = Signal.SELL
        else:
            signal = Signal.HOLD

        reason = " | ".join(reasons) if reasons else "중립"
        return signal, confidence, reason
