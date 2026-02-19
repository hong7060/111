#!/usr/bin/env python3
"""웹 대시보드 서버 실행.

사용법:
    python run_web.py              # http://localhost:5000 에서 대시보드 열기
    python run_web.py --port 8080  # 포트 변경
"""

import argparse
import webbrowser
import threading

from config.settings import AppConfig
from web.app import create_app
from utils.logger import setup_logger

logger = setup_logger("web_main")


def main():
    parser = argparse.ArgumentParser(description="AI 자동매매 봇 웹 대시보드")
    parser.add_argument("--port", type=int, default=5000, help="포트 번호 (기본: 5000)")
    parser.add_argument("--host", default="127.0.0.1", help="호스트 (기본: 127.0.0.1)")
    parser.add_argument("--no-browser", action="store_true", help="브라우저 자동 열기 비활성화")
    args = parser.parse_args()

    config = AppConfig()
    if not config.kis.app_key or not config.kis.app_secret:
        logger.error("API 키가 설정되지 않았습니다. .env 파일을 확인하세요.")
        return

    app = create_app(config)

    logger.info("=" * 50)
    logger.info("AI 자동매매 봇 웹 대시보드")
    logger.info("  URL: http://%s:%d", args.host, args.port)
    logger.info("  모드: %s", "모의투자" if config.kis.is_virtual else "실전투자")
    logger.info("=" * 50)

    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(f"http://{args.host}:{args.port}")).start()

    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
