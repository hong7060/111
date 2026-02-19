"""트레이딩 엔진.

전략 분석 → 리스크 관리 → 주문 실행의 전체 흐름을 관리한다.
"""

import time
from datetime import datetime

from config.settings import AppConfig
from core.kis_api import KISApi
from core.risk_manager import RiskManager, OrderPlan
from strategies.base import BaseStrategy, Signal
from strategies.ensemble import EnsembleStrategy
from strategies.momentum import MomentumStrategy
from strategies.mean_reversion import MeanReversionStrategy
from strategies.ml_strategy import MLStrategy
from utils.logger import setup_logger

logger = setup_logger("trading_engine")

# API 호출 간 딜레이 (초당 요청 제한 준수)
API_CALL_DELAY = 0.5


def _get_strategy(name: str) -> BaseStrategy:
    """전략 이름으로 전략 객체를 반환한다."""
    strategies = {
        "ensemble": EnsembleStrategy,
        "momentum": MomentumStrategy,
        "mean_reversion": MeanReversionStrategy,
        "ml": MLStrategy,
    }
    cls = strategies.get(name, EnsembleStrategy)
    return cls()


class TradingEngine:
    """자동매매 엔진."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.api = KISApi(config.kis)
        self.risk_manager = RiskManager(config.trade)
        self.strategy = _get_strategy(config.strategy.strategy)
        logger.info("트레이딩 엔진 초기화 (전략: %s)", self.strategy.name)

    def run_cycle(self) -> dict:
        """매매 사이클 1회를 실행한다.

        1. 잔고 조회
        2. 보유 종목 손절/익절 확인
        3. 대상 종목 분석 → 매매 신호 생성
        4. 주문 실행

        Returns:
            실행 결과 요약 dict
        """
        logger.info("=" * 60)
        logger.info("매매 사이클 시작: %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        results = {
            "timestamp": datetime.now().isoformat(),
            "orders_executed": [],
            "signals": [],
            "errors": [],
        }

        # 1. 잔고 조회
        try:
            balance = self.api.get_balance()
            if not balance:
                results["errors"].append("잔고 조회 실패")
                return results
        except Exception as e:
            logger.error("잔고 조회 오류: %s", e)
            results["errors"].append(f"잔고 조회 오류: {e}")
            return results

        cash = balance["cash"]
        total_eval = balance["total_eval"] or cash
        holdings = balance["holdings"]
        holding_codes = {h["stock_code"] for h in holdings}

        logger.info("현금: %s원, 총평가: %s원, 보유종목: %d개",
                     f"{cash:,}", f"{total_eval:,}", len(holdings))

        # 2. 보유 종목 손절/익절 확인
        for holding in holdings:
            time.sleep(API_CALL_DELAY)
            code = holding["stock_code"]

            if self.risk_manager.check_stop_loss(holding):
                plan = OrderPlan(
                    stock_code=code,
                    action="sell",
                    quantity=holding["quantity"],
                    price=0,  # 시장가
                    reason=f"손절 (수익률: {holding['profit_rate']:.2f}%)",
                )
                self._execute_order(plan, cash, holdings, results)
                continue

            if self.risk_manager.check_take_profit(holding):
                plan = OrderPlan(
                    stock_code=code,
                    action="sell",
                    quantity=holding["quantity"],
                    price=0,  # 시장가
                    reason=f"익절 (수익률: {holding['profit_rate']:.2f}%)",
                )
                self._execute_order(plan, cash, holdings, results)
                continue

        # 3. 대상 종목 분석
        for stock_code in self.config.strategy.target_stocks:
            time.sleep(API_CALL_DELAY)

            try:
                # 일별 시세 조회
                daily_prices = self.api.get_daily_prices(
                    stock_code,
                    count=self.config.strategy.lookback_days,
                )
                time.sleep(API_CALL_DELAY)

                # 현재가 조회
                current_price = self.api.get_current_price(stock_code)
                if not current_price or not daily_prices:
                    logger.warning("[%s] 시세 데이터 조회 실패", stock_code)
                    continue

                # 전략 분석
                signal, confidence, reason = self.strategy.analyze(daily_prices, current_price)
                results["signals"].append({
                    "stock_code": stock_code,
                    "signal": signal.name,
                    "confidence": confidence,
                    "reason": reason,
                    "price": current_price["price"],
                })

                logger.info("[%s] %s (conf=%.2f, price=%s): %s",
                            stock_code, signal.name, confidence,
                            f"{current_price['price']:,}", reason)

                # 4. 매매 결정
                price = current_price["price"]
                if price <= 0:
                    continue

                # 매수 신호
                if signal in (Signal.STRONG_BUY, Signal.BUY) and confidence >= 0.3:
                    quantity = self.risk_manager.calculate_position_size(
                        stock_code, price, cash, total_eval, holdings,
                    )
                    if quantity > 0:
                        plan = OrderPlan(
                            stock_code=stock_code,
                            action="buy",
                            quantity=quantity,
                            price=0,  # 시장가
                            reason=reason,
                            stop_loss=self.risk_manager.calculate_stop_loss_price(price),
                            take_profit=self.risk_manager.calculate_take_profit_price(price),
                        )
                        result = self._execute_order(plan, cash, holdings, results)
                        if result and result.get("success"):
                            cash -= price * quantity  # 가용 현금 갱신

                # 매도 신호 (보유 중인 경우)
                elif signal in (Signal.STRONG_SELL, Signal.SELL) and stock_code in holding_codes:
                    holding = next(h for h in holdings if h["stock_code"] == stock_code)
                    sell_qty = holding["quantity"]
                    if signal == Signal.SELL:
                        sell_qty = max(1, sell_qty // 2)  # 일반 매도는 절반만

                    plan = OrderPlan(
                        stock_code=stock_code,
                        action="sell",
                        quantity=sell_qty,
                        price=0,
                        reason=reason,
                    )
                    self._execute_order(plan, cash, holdings, results)

            except Exception as e:
                logger.error("[%s] 분석/주문 오류: %s", stock_code, e)
                results["errors"].append(f"[{stock_code}] {e}")

        logger.info("매매 사이클 완료: 주문 %d건", len(results["orders_executed"]))
        logger.info("=" * 60)
        return results

    def _execute_order(self, plan: OrderPlan, cash: float, holdings: list[dict], results: dict) -> dict | None:
        """주문을 실행한다."""
        is_valid, msg = self.risk_manager.validate_order(plan, cash, holdings)
        if not is_valid:
            logger.warning("[%s] 주문 검증 실패: %s", plan.stock_code, msg)
            return None

        logger.info("[%s] 주문 실행: %s %d주 @%s (%s)",
                     plan.stock_code, plan.action,
                     plan.quantity, "시장가" if plan.price == 0 else f"{plan.price:,}",
                     plan.reason)

        if plan.action == "buy":
            result = self.api.buy(plan.stock_code, plan.quantity, plan.price)
        else:
            result = self.api.sell(plan.stock_code, plan.quantity, plan.price)

        results["orders_executed"].append({
            "stock_code": plan.stock_code,
            "action": plan.action,
            "quantity": plan.quantity,
            "price": plan.price,
            "reason": plan.reason,
            "result": result,
        })
        return result

    def get_portfolio_status(self) -> dict:
        """현재 포트폴리오 상태를 조회한다."""
        balance = self.api.get_balance()
        if not balance:
            return {}

        status = {
            "timestamp": datetime.now().isoformat(),
            "cash": balance["cash"],
            "total_eval": balance["total_eval"],
            "total_profit": balance["total_profit"],
            "total_profit_rate": balance["total_profit_rate"],
            "holdings": [],
        }

        for h in balance["holdings"]:
            status["holdings"].append({
                "stock_code": h["stock_code"],
                "name": h["name"],
                "quantity": h["quantity"],
                "avg_price": h["avg_price"],
                "current_price": h["current_price"],
                "profit": h["profit"],
                "profit_rate": h["profit_rate"],
                "stop_loss_triggered": self.risk_manager.check_stop_loss(h),
                "take_profit_triggered": self.risk_manager.check_take_profit(h),
            })

        return status
