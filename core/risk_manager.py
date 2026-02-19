"""리스크 관리 모듈.

포지션 크기 결정, 손절/익절 관리, 포트폴리오 비중 제한 등
리스크 관리 로직을 담당한다.
"""

from dataclasses import dataclass

from config.settings import TradeConfig
from utils.logger import setup_logger

logger = setup_logger("risk_manager")


@dataclass
class OrderPlan:
    """주문 계획."""
    stock_code: str
    action: str          # "buy" or "sell"
    quantity: int
    price: int
    reason: str
    stop_loss: int = 0
    take_profit: int = 0


class RiskManager:
    """리스크 관리자."""

    def __init__(self, config: TradeConfig):
        self.config = config

    def calculate_position_size(
        self,
        stock_code: str,
        price: int,
        cash: float,
        total_eval: float,
        current_holdings: list[dict],
    ) -> int:
        """매수 수량을 계산한다.

        제약 조건:
        1. 총 투자금의 max_investment_ratio 이내
        2. 개별 종목 비중 max_single_stock_ratio 이내
        3. 최소 1주 이상

        Args:
            stock_code: 종목코드
            price: 현재 주가
            cash: 가용 현금
            total_eval: 총 평가금액
            current_holdings: 현재 보유 종목 리스트

        Returns:
            매수 가능 수량 (0이면 매수 불가)
        """
        if price <= 0 or cash <= 0 or total_eval <= 0:
            return 0

        # 1) 총 투자 한도
        max_total_investment = total_eval * self.config.max_investment_ratio
        current_invested = sum(h.get("eval_amount", 0) for h in current_holdings)
        available_for_investment = max_total_investment - current_invested

        # 2) 개별 종목 한도
        max_single = total_eval * self.config.max_single_stock_ratio
        already_holding = 0
        for h in current_holdings:
            if h.get("stock_code") == stock_code:
                already_holding = h.get("eval_amount", 0)
                break
        available_for_stock = max_single - already_holding

        # 3) 실제 투자 가능 금액
        investable = min(cash, available_for_investment, available_for_stock)
        if investable < price:
            return 0

        quantity = int(investable // price)
        logger.info(
            "[%s] 포지션 계산: 가격=%d, 현금=%d, 투자한도=%d, 종목한도=%d → %d주",
            stock_code, price, int(cash), int(available_for_investment),
            int(available_for_stock), quantity,
        )
        return quantity

    def check_stop_loss(self, holding: dict) -> bool:
        """손절 조건을 확인한다.

        Returns:
            True이면 손절 필요
        """
        profit_rate = holding.get("profit_rate", 0)
        if profit_rate <= -(self.config.stop_loss_ratio * 100):
            logger.warning(
                "[%s] 손절 조건 충족: 수익률=%.2f%% (한도=-%.1f%%)",
                holding.get("stock_code"), profit_rate, self.config.stop_loss_ratio * 100,
            )
            return True
        return False

    def check_take_profit(self, holding: dict) -> bool:
        """익절 조건을 확인한다.

        Returns:
            True이면 익절 필요
        """
        profit_rate = holding.get("profit_rate", 0)
        if profit_rate >= self.config.take_profit_ratio * 100:
            logger.info(
                "[%s] 익절 조건 충족: 수익률=%.2f%% (목표=%.1f%%)",
                holding.get("stock_code"), profit_rate, self.config.take_profit_ratio * 100,
            )
            return True
        return False

    def validate_order(self, plan: OrderPlan, cash: float, holdings: list[dict]) -> tuple[bool, str]:
        """주문 전 유효성을 검증한다.

        Returns:
            (is_valid, reason)
        """
        if plan.quantity <= 0:
            return False, "수량이 0 이하"

        if plan.action == "buy":
            total_cost = plan.price * plan.quantity
            if total_cost > cash:
                return False, f"현금 부족 (필요: {total_cost:,}, 보유: {int(cash):,})"

        elif plan.action == "sell":
            held_qty = 0
            for h in holdings:
                if h.get("stock_code") == plan.stock_code:
                    held_qty = h.get("quantity", 0)
                    break
            if plan.quantity > held_qty:
                return False, f"보유 수량 부족 (요청: {plan.quantity}, 보유: {held_qty})"

        return True, "OK"

    def calculate_stop_loss_price(self, buy_price: int) -> int:
        """손절가를 계산한다."""
        return int(buy_price * (1 - self.config.stop_loss_ratio))

    def calculate_take_profit_price(self, buy_price: int) -> int:
        """익절가를 계산한다."""
        return int(buy_price * (1 + self.config.take_profit_ratio))
