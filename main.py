#!/usr/bin/env python3
"""한국투자증권 AI 자동매매 봇 메인 엔트리포인트.

사용법:
    python main.py              # 자동매매 시작 (스케줄 모드)
    python main.py --once       # 1회 실행 후 종료
    python main.py --status     # 포트폴리오 상태 확인
    python main.py --dry-run    # 분석만 수행 (주문 미실행)
    python main.py --force      # 장 마감 시간에도 강제 실행
"""

import argparse
import json
import signal
import sys
import time
from datetime import datetime

import schedule

from config.settings import AppConfig
from core.trading_engine import TradingEngine
from utils.logger import setup_logger

logger = setup_logger("main")

# 장 운영 시간 (한국 시간)
MARKET_OPEN_HOUR = 9
MARKET_OPEN_MINUTE = 5   # 동시호가 후 안정화 대기
MARKET_CLOSE_HOUR = 15
MARKET_CLOSE_MINUTE = 20

_running = True


def _signal_handler(signum, frame):
    global _running
    logger.info("종료 신호 수신 (signal=%d). 안전하게 종료합니다.", signum)
    _running = False


def is_market_open() -> bool:
    """현재 장이 열려 있는지 확인한다."""
    now = datetime.now()
    # 주말 체크
    if now.weekday() >= 5:
        return False
    # 시간 체크
    market_open = now.replace(hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MINUTE, second=0)
    market_close = now.replace(hour=MARKET_CLOSE_HOUR, minute=MARKET_CLOSE_MINUTE, second=0)
    return market_open <= now <= market_close


def run_trading_cycle(engine: TradingEngine, dry_run: bool = False, force: bool = False):
    """매매 사이클을 실행한다."""
    if not force and not is_market_open():
        logger.info("장 마감 상태 - 다음 장 개시까지 대기 (--force 옵션으로 강제 실행 가능)")
        return

    if dry_run:
        logger.info("[DRY-RUN] 분석 모드로 실행합니다 (실제 주문 없음)")
        # dry-run 모드에서는 시세 분석만 수행
        _run_analysis_only(engine)
        return

    results = engine.run_cycle()

    # 결과 요약 출력
    if results.get("orders_executed"):
        logger.info("--- 주문 실행 결과 ---")
        for order in results["orders_executed"]:
            logger.info("  [%s] %s %d주: %s",
                         order["stock_code"], order["action"],
                         order["quantity"], order["result"].get("message", ""))

    if results.get("errors"):
        logger.warning("--- 오류 ---")
        for err in results["errors"]:
            logger.warning("  %s", err)


def _run_analysis_only(engine: TradingEngine):
    """분석만 수행한다 (주문 없음)."""
    from core.kis_api import KISApi
    from strategies.base import Signal
    import time as _time

    api = engine.api
    strategy = engine.strategy

    logger.info("=== 분석 시작 ===")
    for stock_code in engine.config.strategy.target_stocks:
        try:
            daily = api.get_daily_prices(stock_code, count=engine.config.strategy.lookback_days)
            _time.sleep(0.5)
            current = api.get_current_price(stock_code)
            _time.sleep(0.5)

            if not daily or not current:
                logger.warning("[%s] 데이터 조회 실패", stock_code)
                continue

            signal, confidence, reason = strategy.analyze(daily, current)
            logger.info("[%s] 가격=%s | %s (conf=%.2f) | %s",
                         stock_code, f"{current['price']:,}",
                         signal.name, confidence, reason)
        except Exception as e:
            logger.error("[%s] 분석 오류: %s", stock_code, e)
    logger.info("=== 분석 완료 ===")


def print_status(engine: TradingEngine):
    """포트폴리오 상태를 출력한다."""
    status = engine.get_portfolio_status()
    if not status:
        print("포트폴리오 조회 실패")
        return

    print("\n" + "=" * 60)
    print(f"포트폴리오 현황 ({status['timestamp']})")
    print("=" * 60)
    print(f"  예수금:      {status['cash']:>15,}원")
    print(f"  총평가:      {status['total_eval']:>15,}원")
    print(f"  총손익:      {status['total_profit']:>15,}원")
    print(f"  총수익률:    {status['total_profit_rate']:>14.2f}%")
    print("-" * 60)

    if status["holdings"]:
        print(f"  {'종목':<10} {'수량':>6} {'평균가':>10} {'현재가':>10} {'수익률':>8}")
        print("  " + "-" * 50)
        for h in status["holdings"]:
            marker = ""
            if h["stop_loss_triggered"]:
                marker = " [손절]"
            elif h["take_profit_triggered"]:
                marker = " [익절]"
            print(f"  {h['name']:<10} {h['quantity']:>6} {h['avg_price']:>10,} "
                  f"{h['current_price']:>10,} {h['profit_rate']:>7.2f}%{marker}")
    else:
        print("  보유 종목 없음")
    print("=" * 60 + "\n")


def main():
    parser = argparse.ArgumentParser(description="한국투자증권 AI 자동매매 봇")
    parser.add_argument("--once", action="store_true", help="1회 실행 후 종료")
    parser.add_argument("--status", action="store_true", help="포트폴리오 상태 확인")
    parser.add_argument("--dry-run", action="store_true", help="분석만 수행 (주문 없음)")
    parser.add_argument("--force", action="store_true", help="장 마감 시간에도 강제 실행")
    args = parser.parse_args()

    config = AppConfig()
    if not config.kis.app_key or not config.kis.app_secret:
        logger.error("API 키가 설정되지 않았습니다. .env 파일을 확인하세요.")
        sys.exit(1)

    logger.info("=" * 60)
    logger.info("한국투자증권 AI 자동매매 봇 시작")
    logger.info("  모드: %s", "모의투자" if config.kis.is_virtual else "실전투자")
    logger.info("  전략: %s", config.strategy.strategy)
    logger.info("  계좌: %s", config.kis.account_no)
    logger.info("  리밸런싱 주기: %d분", config.strategy.rebalance_interval_minutes)
    logger.info("=" * 60)

    engine = TradingEngine(config)

    if args.status:
        print_status(engine)
        return

    if args.once:
        run_trading_cycle(engine, dry_run=args.dry_run, force=args.force)
        return

    # 스케줄 모드: 설정된 간격마다 실행
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    interval = config.strategy.rebalance_interval_minutes
    schedule.every(interval).minutes.do(run_trading_cycle, engine=engine, dry_run=args.dry_run, force=args.force)

    # 시작 시 1회 실행
    run_trading_cycle(engine, dry_run=args.dry_run, force=args.force)

    logger.info("스케줄 모드 실행 중 (%d분 간격). Ctrl+C로 종료.", interval)
    while _running:
        schedule.run_pending()
        time.sleep(1)

    logger.info("봇이 정상 종료되었습니다.")


if __name__ == "__main__":
    main()
