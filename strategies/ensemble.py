"""앙상블 전략.

여러 개별 전략의 결과를 가중 평균하여 최종 매매 신호를 결정한다.
"""

from strategies.base import BaseStrategy, Signal
from strategies.momentum import MomentumStrategy
from strategies.mean_reversion import MeanReversionStrategy
from strategies.ml_strategy import MLStrategy
from utils.logger import setup_logger

logger = setup_logger("ensemble")


class EnsembleStrategy(BaseStrategy):
    """앙상블 전략.

    개별 전략별 가중치:
    - 모멘텀: 0.30
    - 평균회귀: 0.30
    - ML: 0.40
    """

    def __init__(self):
        self._strategies: list[tuple[BaseStrategy, float]] = [
            (MomentumStrategy(), 0.30),
            (MeanReversionStrategy(), 0.30),
            (MLStrategy(), 0.40),
        ]

    @property
    def name(self) -> str:
        return "Ensemble"

    def analyze(self, daily_prices: list[dict], current_price: dict) -> tuple[Signal, float, str]:
        signal_values = {
            Signal.STRONG_BUY: 2.0,
            Signal.BUY: 1.0,
            Signal.HOLD: 0.0,
            Signal.SELL: -1.0,
            Signal.STRONG_SELL: -2.0,
        }

        weighted_score = 0.0
        total_weight = 0.0
        all_reasons = []

        for strategy, weight in self._strategies:
            try:
                signal, confidence, reason = strategy.analyze(daily_prices, current_price)
                score = signal_values[signal] * confidence * weight
                weighted_score += score
                total_weight += weight
                all_reasons.append(f"[{strategy.name}] {signal.name}(conf={confidence:.2f}): {reason}")
                logger.debug("[%s] signal=%s, conf=%.2f, reason=%s", strategy.name, signal.name, confidence, reason)
            except Exception as e:
                logger.warning("[%s] 분석 실패: %s", strategy.name, e)
                all_reasons.append(f"[{strategy.name}] 오류: {e}")

        if total_weight == 0:
            return Signal.HOLD, 0.0, "모든 전략 실패"

        normalized_score = weighted_score / total_weight
        confidence = min(abs(normalized_score) / 2.0, 1.0)

        if normalized_score >= 1.0:
            signal = Signal.STRONG_BUY
        elif normalized_score >= 0.3:
            signal = Signal.BUY
        elif normalized_score <= -1.0:
            signal = Signal.STRONG_SELL
        elif normalized_score <= -0.3:
            signal = Signal.SELL
        else:
            signal = Signal.HOLD

        reason = f"종합점수: {normalized_score:.2f} | " + " | ".join(all_reasons)
        return signal, confidence, reason
