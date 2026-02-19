"""트레이딩 전략 기본 클래스."""

from abc import ABC, abstractmethod
from enum import Enum


class Signal(Enum):
    """매매 신호."""
    STRONG_BUY = 2
    BUY = 1
    HOLD = 0
    SELL = -1
    STRONG_SELL = -2


class BaseStrategy(ABC):
    """모든 전략의 기본 클래스."""

    @property
    @abstractmethod
    def name(self) -> str:
        """전략 이름."""

    @abstractmethod
    def analyze(self, daily_prices: list[dict], current_price: dict) -> tuple[Signal, float, str]:
        """종목을 분석하여 매매 신호를 반환한다.

        Args:
            daily_prices: 일별 가격 데이터 (최신순)
            current_price: 현재가 정보

        Returns:
            (signal, confidence, reason)
            - signal: 매매 신호
            - confidence: 신뢰도 (0.0 ~ 1.0)
            - reason: 판단 근거
        """
