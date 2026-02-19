"""평균 회귀 전략.

볼린저 밴드와 가격 이탈도를 활용하여 과매수/과매도 구간에서
평균으로의 회귀를 기대하는 역추세 전략.
"""

import numpy as np
import pandas as pd

from strategies.base import BaseStrategy, Signal


class MeanReversionStrategy(BaseStrategy):
    """평균 회귀 전략.

    판단 기준:
    - 볼린저 밴드 (20일, 2σ) 이탈
    - 가격 이격도 (20일 이동평균 대비)
    - 윌리엄스 %R
    - 스토캐스틱 오실레이터
    """

    @property
    def name(self) -> str:
        return "MeanReversion"

    def analyze(self, daily_prices: list[dict], current_price: dict) -> tuple[Signal, float, str]:
        if len(daily_prices) < 20:
            return Signal.HOLD, 0.0, "데이터 부족"

        df = pd.DataFrame(daily_prices).sort_values("date").reset_index(drop=True)
        for col in ("open", "high", "low", "close", "volume"):
            df[col] = pd.to_numeric(df[col], errors="coerce")

        score = 0.0
        reasons = []
        last = df.iloc[-1]

        # --- 볼린저 밴드 ---
        ma20 = df["close"].rolling(20).mean()
        std20 = df["close"].rolling(20).std()
        upper = ma20 + 2 * std20
        lower = ma20 - 2 * std20

        if pd.notna(upper.iloc[-1]):
            price = last["close"]
            bb_upper = upper.iloc[-1]
            bb_lower = lower.iloc[-1]
            bb_mid = ma20.iloc[-1]

            # %B 계산 (0~1 사이가 밴드 내부)
            bb_width = bb_upper - bb_lower
            if bb_width > 0:
                pct_b = (price - bb_lower) / bb_width

                if pct_b < 0:
                    score += 2.5
                    reasons.append(f"볼린저 하단 이탈 (%B={pct_b:.2f})")
                elif pct_b < 0.2:
                    score += 1.5
                    reasons.append(f"볼린저 하단 근접 (%B={pct_b:.2f})")
                elif pct_b > 1.0:
                    score -= 2.5
                    reasons.append(f"볼린저 상단 이탈 (%B={pct_b:.2f})")
                elif pct_b > 0.8:
                    score -= 1.5
                    reasons.append(f"볼린저 상단 근접 (%B={pct_b:.2f})")

        # --- 이격도 (Disparity) ---
        if pd.notna(ma20.iloc[-1]) and ma20.iloc[-1] > 0:
            disparity = (last["close"] / ma20.iloc[-1]) * 100
            if disparity < 95:
                score += 2.0
                reasons.append(f"이격도 과매도 ({disparity:.1f}%)")
            elif disparity < 98:
                score += 1.0
                reasons.append(f"이격도 매수 구간 ({disparity:.1f}%)")
            elif disparity > 105:
                score -= 2.0
                reasons.append(f"이격도 과매수 ({disparity:.1f}%)")
            elif disparity > 102:
                score -= 1.0
                reasons.append(f"이격도 매도 구간 ({disparity:.1f}%)")

        # --- 스토캐스틱 %K, %D ---
        if len(df) >= 14:
            low14 = df["low"].rolling(14).min()
            high14 = df["high"].rolling(14).max()
            denom = high14 - low14
            stoch_k = ((df["close"] - low14) / denom.replace(0, np.nan)) * 100
            stoch_d = stoch_k.rolling(3).mean()

            k_val = stoch_k.iloc[-1]
            d_val = stoch_d.iloc[-1]

            if pd.notna(k_val) and pd.notna(d_val):
                if k_val < 20 and d_val < 20:
                    score += 1.5
                    reasons.append(f"스토캐스틱 과매도 (K={k_val:.0f}, D={d_val:.0f})")
                elif k_val > 80 and d_val > 80:
                    score -= 1.5
                    reasons.append(f"스토캐스틱 과매수 (K={k_val:.0f}, D={d_val:.0f})")

                # %K가 %D를 상향 돌파
                prev_k = stoch_k.iloc[-2]
                prev_d = stoch_d.iloc[-2]
                if pd.notna(prev_k) and pd.notna(prev_d):
                    if k_val > d_val and prev_k <= prev_d and k_val < 30:
                        score += 1.0
                        reasons.append("스토캐스틱 골든크로스 (저점)")

        # --- 윌리엄스 %R ---
        if len(df) >= 14:
            high14 = df["high"].rolling(14).max()
            low14 = df["low"].rolling(14).min()
            wr = ((high14 - df["close"]) / (high14 - low14).replace(0, np.nan)) * -100
            wr_val = wr.iloc[-1]

            if pd.notna(wr_val):
                if wr_val < -80:
                    score += 1.0
                    reasons.append(f"윌리엄스 %R 과매도 ({wr_val:.0f})")
                elif wr_val > -20:
                    score -= 1.0
                    reasons.append(f"윌리엄스 %R 과매수 ({wr_val:.0f})")

        # --- 종합 ---
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
