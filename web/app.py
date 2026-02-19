"""웹 대시보드 서버.

Flask 기반 웹 UI로 봇 상태 모니터링, 시작/중지, 매매 이력 확인 기능 제공.
"""

import json
import threading
import time
from datetime import datetime

import requests as _requests
from flask import Flask, render_template, jsonify, request, redirect

from config.settings import AppConfig
from core.trading_engine import TradingEngine
from utils.logger import setup_logger

logger = setup_logger("web")

app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static",
)

# 전역 상태
_engine: TradingEngine | None = None
_config: AppConfig | None = None
_bot_thread: threading.Thread | None = None
_bot_running = False
_trade_history: list[dict] = []
_signal_history: list[dict] = []
_last_cycle_result: dict = {}


def _bot_loop(engine: TradingEngine, interval_minutes: int, force: bool):
    """봇 자동매매 루프 (별도 스레드)."""
    global _bot_running, _last_cycle_result
    while _bot_running:
        try:
            from main import is_market_open
            if force or is_market_open():
                result = engine.run_cycle()
                _last_cycle_result = result
                _trade_history.extend(result.get("orders_executed", []))
                _signal_history.extend(result.get("signals", []))
                # 최근 200건만 유지
                if len(_trade_history) > 200:
                    _trade_history[:] = _trade_history[-200:]
                if len(_signal_history) > 500:
                    _signal_history[:] = _signal_history[-500:]
            else:
                logger.info("[웹] 장 마감 상태 - 대기 중")
        except Exception as e:
            logger.error("[웹] 매매 사이클 오류: %s", e)

        # 대기 (1초 단위로 체크하여 빠른 중지 지원)
        for _ in range(interval_minutes * 60):
            if not _bot_running:
                break
            time.sleep(1)

    logger.info("[웹] 봇 루프 종료")


# ------------------------------------------------------------------
# 라우트
# ------------------------------------------------------------------

@app.route("/")
def index():
    """메인 대시보드 페이지."""
    return render_template("dashboard.html")


@app.route("/status")
def status_simple():
    """간단 상태 응답 (브라우저 확장 등의 폴링 대응)."""
    return jsonify({"status": "ok", "bot_running": _bot_running})


_auth_error_logged = False


@app.route("/api/status")
def api_status():
    """봇 상태 및 포트폴리오 정보."""
    global _auth_error_logged
    if not _engine:
        return jsonify({"error": "엔진 미초기화"}), 500

    balance = {}
    auth_ok = True
    try:
        balance = _engine.api.get_balance()
        _auth_error_logged = False
    except _requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 403:
            auth_ok = False
            if not _auth_error_logged:
                logger.error("API 인증 실패 (403) - .env 파일의 APP_KEY/APP_SECRET을 확인하세요")
                _auth_error_logged = True
        else:
            logger.error("잔고 조회 실패: %s", e)
    except Exception as e:
        logger.error("잔고 조회 실패: %s", e)

    return jsonify({
        "bot_running": _bot_running,
        "auth_ok": auth_ok,
        "timestamp": datetime.now().isoformat(),
        "strategy": _config.strategy.strategy if _config else "",
        "mode": "모의투자" if _config and _config.kis.is_virtual else "실전투자",
        "account": _config.kis.account_no if _config else "",
        "balance": balance,
        "last_cycle": _last_cycle_result,
    })


@app.route("/api/start", methods=["POST"])
def api_start():
    """봇 시작."""
    global _bot_thread, _bot_running
    if _bot_running:
        return jsonify({"message": "이미 실행 중입니다"}), 400

    force = request.json.get("force", False) if request.json else False
    interval = _config.strategy.rebalance_interval_minutes if _config else 30

    _bot_running = True
    _bot_thread = threading.Thread(
        target=_bot_loop,
        args=(_engine, interval, force),
        daemon=True,
    )
    _bot_thread.start()
    logger.info("[웹] 봇 시작 (간격: %d분, force=%s)", interval, force)
    return jsonify({"message": f"봇 시작됨 ({interval}분 간격)"})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    """봇 중지."""
    global _bot_running
    if not _bot_running:
        return jsonify({"message": "봇이 실행 중이 아닙니다"}), 400

    _bot_running = False
    logger.info("[웹] 봇 중지 요청")
    return jsonify({"message": "봇 중지 요청됨"})


@app.route("/api/run-once", methods=["POST"])
def api_run_once():
    """1회 매매 사이클 실행."""
    if not _engine:
        return jsonify({"error": "엔진 미초기화"}), 500

    try:
        result = _engine.run_cycle()
        _last_cycle_result = result
        _trade_history.extend(result.get("orders_executed", []))
        _signal_history.extend(result.get("signals", []))
        return jsonify({"message": "매매 사이클 완료", "result": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    """분석만 수행 (주문 없음)."""
    if not _engine:
        return jsonify({"error": "엔진 미초기화"}), 500

    results = []
    for stock_code in _engine.config.strategy.target_stocks:
        try:
            daily = _engine.api.get_daily_prices(stock_code, count=_engine.config.strategy.lookback_days)
            time.sleep(0.3)
            current = _engine.api.get_current_price(stock_code)
            time.sleep(0.3)

            if not daily or not current:
                results.append({"stock_code": stock_code, "error": "데이터 조회 실패"})
                continue

            signal, confidence, reason = _engine.strategy.analyze(daily, current)
            results.append({
                "stock_code": stock_code,
                "price": current["price"],
                "change_rate": current["change_rate"],
                "signal": signal.name,
                "confidence": round(confidence, 3),
                "reason": reason,
            })
        except Exception as e:
            results.append({"stock_code": stock_code, "error": str(e)})

    return jsonify({"signals": results})


@app.route("/api/history")
def api_history():
    """매매 이력."""
    return jsonify({
        "trades": _trade_history[-50:],
        "signals": _signal_history[-100:],
    })


def create_app(config: AppConfig | None = None) -> Flask:
    """앱 팩토리."""
    global _engine, _config
    _config = config or AppConfig()
    _engine = TradingEngine(_config)
    return app
