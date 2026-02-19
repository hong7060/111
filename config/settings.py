"""한국투자증권 AI 자동매매 봇 설정."""

import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class KISConfig:
    """한국투자증권 API 설정."""
    base_url: str = os.getenv("KIS_BASE_URL", "https://openapivts.koreainvestment.com:29443")
    app_key: str = os.getenv("KIS_APP_KEY", "")
    app_secret: str = os.getenv("KIS_APP_SECRET", "")
    account_no: str = os.getenv("KIS_ACCOUNT_NO", "")
    account_type: str = os.getenv("KIS_ACCOUNT_TYPE", "01")

    @property
    def account_prefix(self) -> str:
        return self.account_no.split("-")[0] if "-" in self.account_no else self.account_no[:8]

    @property
    def account_suffix(self) -> str:
        return self.account_no.split("-")[1] if "-" in self.account_no else self.account_no[8:]

    @property
    def is_virtual(self) -> bool:
        return "vts" in self.base_url


@dataclass
class TradeConfig:
    """거래 설정."""
    trade_mode: str = os.getenv("TRADE_MODE", "virtual")
    max_investment_ratio: float = float(os.getenv("MAX_INVESTMENT_RATIO", "0.8"))
    max_single_stock_ratio: float = float(os.getenv("MAX_SINGLE_STOCK_RATIO", "0.15"))
    stop_loss_ratio: float = float(os.getenv("STOP_LOSS_RATIO", "0.05"))
    take_profit_ratio: float = float(os.getenv("TAKE_PROFIT_RATIO", "0.10"))


@dataclass
class StrategyConfig:
    """AI 전략 설정."""
    strategy: str = os.getenv("STRATEGY", "ensemble")
    lookback_days: int = int(os.getenv("LOOKBACK_DAYS", "60"))
    rebalance_interval_minutes: int = int(os.getenv("REBALANCE_INTERVAL_MINUTES", "30"))
    # 매매 대상 종목 (KOSPI/KOSDAQ 대표 종목)
    target_stocks: list = field(default_factory=lambda: [
        "005930",  # 삼성전자
        "000660",  # SK하이닉스
        "035420",  # NAVER
        "035720",  # 카카오
        "051910",  # LG화학
        "006400",  # 삼성SDI
        "068270",  # 셀트리온
        "105560",  # KB금융
        "055550",  # 신한지주
        "003670",  # 포스코퓨처엠
    ])


@dataclass
class AppConfig:
    """전체 앱 설정."""
    kis: KISConfig = field(default_factory=KISConfig)
    trade: TradeConfig = field(default_factory=TradeConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
