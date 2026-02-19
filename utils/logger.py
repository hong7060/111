"""로깅 유틸리티."""

import logging
import os
import sys
from datetime import datetime


def setup_logger(name: str = "trading_bot", level: int = logging.INFO) -> logging.Logger:
    """로거를 설정하고 반환한다."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(level)
    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 콘솔 핸들러
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 파일 핸들러
    os.makedirs("logs", exist_ok=True)
    file_handler = logging.FileHandler(
        f"logs/trading_{datetime.now().strftime('%Y%m%d')}.log",
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger
