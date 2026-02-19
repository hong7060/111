"""한국투자증권 Open API 클라이언트.

REST API를 통해 인증, 시세 조회, 주문 실행 기능을 제공한다.
API 문서: https://apiportal.koreainvestment.com/
"""

import json
import time
from datetime import datetime, timedelta
from typing import Optional

import requests

from config.settings import KISConfig
from utils.logger import setup_logger

logger = setup_logger("kis_api")


class KISApi:
    """한국투자증권 Open API 클라이언트."""

    def __init__(self, config: KISConfig):
        self.config = config
        self.base_url = config.base_url
        self._access_token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None
        self._session = requests.Session()

    # ------------------------------------------------------------------
    # 인증
    # ------------------------------------------------------------------

    def _get_access_token(self) -> str:
        """OAuth 액세스 토큰을 발급받는다. 캐시된 토큰이 유효하면 재사용."""
        if self._access_token and self._token_expires_at and datetime.now() < self._token_expires_at:
            return self._access_token

        url = f"{self.base_url}/oauth2/tokenP"
        payload = {
            "grant_type": "client_credentials",
            "appkey": self.config.app_key,
            "appsecret": self.config.app_secret,
        }
        resp = self._session.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        self._access_token = data["access_token"]
        expires_in = int(data.get("expires_in", 86400))
        self._token_expires_at = datetime.now() + timedelta(seconds=expires_in - 60)
        logger.info("액세스 토큰 발급 완료 (만료: %s)", self._token_expires_at)
        return self._access_token

    def _get_hashkey(self, body: dict) -> str:
        """요청 본문의 hashkey를 생성한다."""
        url = f"{self.base_url}/uapi/hashkey"
        headers = {
            "Content-Type": "application/json",
            "appkey": self.config.app_key,
            "appsecret": self.config.app_secret,
        }
        resp = self._session.post(url, headers=headers, json=body, timeout=10)
        resp.raise_for_status()
        return resp.json()["HASH"]

    def _build_headers(self, tr_id: str, *, needs_hash: bool = False, body: Optional[dict] = None) -> dict:
        """공통 요청 헤더를 생성한다."""
        token = self._get_access_token()
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "authorization": f"Bearer {token}",
            "appkey": self.config.app_key,
            "appsecret": self.config.app_secret,
            "tr_id": tr_id,
        }
        if needs_hash and body:
            headers["hashkey"] = self._get_hashkey(body)
        return headers

    # ------------------------------------------------------------------
    # 시세 조회
    # ------------------------------------------------------------------

    def get_current_price(self, stock_code: str) -> dict:
        """주식 현재가를 조회한다.

        Returns:
            dict with keys: price, change, change_rate, volume, high, low, open
        """
        tr_id = "FHKST01010100"
        if self.config.is_virtual:
            tr_id = "FHKST01010100"

        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-price"
        headers = self._build_headers(tr_id)
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": stock_code,
        }

        resp = self._session.get(url, headers=headers, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        if data.get("rt_cd") != "0":
            logger.error("현재가 조회 실패 [%s]: %s", stock_code, data.get("msg1"))
            return {}

        output = data.get("output", {})
        return {
            "stock_code": stock_code,
            "price": int(output.get("stck_prpr", 0)),
            "change": int(output.get("prdy_vrss", 0)),
            "change_rate": float(output.get("prdy_ctrt", 0)),
            "volume": int(output.get("acml_vol", 0)),
            "high": int(output.get("stck_hgpr", 0)),
            "low": int(output.get("stck_lwpr", 0)),
            "open": int(output.get("stck_oprc", 0)),
        }

    def get_daily_prices(self, stock_code: str, period: str = "D", count: int = 60) -> list[dict]:
        """일별 주가 데이터를 조회한다.

        Args:
            stock_code: 종목코드 (6자리)
            period: D(일), W(주), M(월)
            count: 조회 건수

        Returns:
            [{date, open, high, low, close, volume}, ...] 최신순
        """
        tr_id = "FHKST01010400"
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-daily-price"
        headers = self._build_headers(tr_id)

        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=count * 2)).strftime("%Y%m%d")

        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": stock_code,
            "FID_INPUT_DATE_1": start_date,
            "FID_INPUT_DATE_2": end_date,
            "FID_PERIOD_DIV_CODE": period,
            "FID_ORG_ADJ_PRC": "0",
        }

        resp = self._session.get(url, headers=headers, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        if data.get("rt_cd") != "0":
            logger.error("일별 시세 조회 실패 [%s]: %s", stock_code, data.get("msg1"))
            return []

        results = []
        for item in data.get("output2", [])[:count]:
            if not item.get("stck_bsop_date"):
                continue
            results.append({
                "date": item["stck_bsop_date"],
                "open": int(item.get("stck_oprc", 0)),
                "high": int(item.get("stck_hgpr", 0)),
                "low": int(item.get("stck_lwpr", 0)),
                "close": int(item.get("stck_clpr", 0)),
                "volume": int(item.get("acml_vol", 0)),
            })
        return results

    def get_minute_prices(self, stock_code: str, time_unit: str = "1") -> list[dict]:
        """분봉 데이터를 조회한다.

        Args:
            stock_code: 종목코드
            time_unit: 분 단위 (1, 3, 5, 10, 15, 30, 60)
        """
        tr_id = "FHKST01010200"
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
        headers = self._build_headers(tr_id)

        now = datetime.now().strftime("%H%M%S")
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": stock_code,
            "FID_INPUT_HOUR_1": now,
            "FID_PW_DATA_INCU_YN": "Y",
        }

        resp = self._session.get(url, headers=headers, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        if data.get("rt_cd") != "0":
            return []

        results = []
        for item in data.get("output2", []):
            results.append({
                "time": item.get("stck_cntg_hour", ""),
                "open": int(item.get("stck_oprc", 0)),
                "high": int(item.get("stck_hgpr", 0)),
                "low": int(item.get("stck_lwpr", 0)),
                "close": int(item.get("stck_prpr", 0)),
                "volume": int(item.get("cntg_vol", 0)),
            })
        return results

    # ------------------------------------------------------------------
    # 주문
    # ------------------------------------------------------------------

    def buy(self, stock_code: str, quantity: int, price: int = 0, order_type: str = "00") -> dict:
        """매수 주문을 실행한다.

        Args:
            stock_code: 종목코드
            quantity: 수량
            price: 지정가 (0이면 시장가)
            order_type: 00(지정가), 01(시장가), ...

        Returns:
            주문 결과 dict (order_no, message)
        """
        if price == 0:
            order_type = "01"

        tr_id = "VTTC0802U" if self.config.is_virtual else "TTTC0802U"
        return self._place_order(tr_id, stock_code, quantity, price, order_type)

    def sell(self, stock_code: str, quantity: int, price: int = 0, order_type: str = "00") -> dict:
        """매도 주문을 실행한다."""
        if price == 0:
            order_type = "01"

        tr_id = "VTTC0801U" if self.config.is_virtual else "TTTC0801U"
        return self._place_order(tr_id, stock_code, quantity, price, order_type)

    def _place_order(self, tr_id: str, stock_code: str, quantity: int, price: int, order_type: str) -> dict:
        """주문 공통 처리."""
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/order-cash"
        body = {
            "CANO": self.config.account_prefix,
            "ACNT_PRDT_CD": self.config.account_suffix,
            "PDNO": stock_code,
            "ORD_DVSN": order_type,
            "ORD_QTY": str(quantity),
            "ORD_UNPR": str(price),
        }
        headers = self._build_headers(tr_id, needs_hash=True, body=body)

        resp = self._session.post(url, headers=headers, json=body, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        if data.get("rt_cd") != "0":
            logger.error("주문 실패 [%s]: %s", stock_code, data.get("msg1"))
            return {"success": False, "message": data.get("msg1", "주문 실패")}

        output = data.get("output", {})
        order_no = output.get("ODNO", "")
        logger.info("주문 성공 [%s] 주문번호: %s (수량: %d, 가격: %d)", stock_code, order_no, quantity, price)
        return {"success": True, "order_no": order_no, "message": "주문 성공"}

    # ------------------------------------------------------------------
    # 잔고 / 계좌
    # ------------------------------------------------------------------

    def get_balance(self) -> dict:
        """계좌 잔고를 조회한다.

        Returns:
            {
                "cash": 예수금,
                "total_eval": 총평가금액,
                "total_profit": 총수익,
                "total_profit_rate": 총수익률,
                "holdings": [{stock_code, name, quantity, avg_price, current_price, profit_rate}, ...]
            }
        """
        tr_id = "VTTC8434R" if self.config.is_virtual else "TTTC8434R"
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-balance"
        headers = self._build_headers(tr_id)
        params = {
            "CANO": self.config.account_prefix,
            "ACNT_PRDT_CD": self.config.account_suffix,
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "",
            "INQR_DVSN": "02",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "00",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }

        resp = self._session.get(url, headers=headers, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        if data.get("rt_cd") != "0":
            logger.error("잔고 조회 실패: %s", data.get("msg1"))
            return {}

        holdings = []
        for item in data.get("output1", []):
            qty = int(item.get("hldg_qty", 0))
            if qty <= 0:
                continue
            holdings.append({
                "stock_code": item.get("pdno", ""),
                "name": item.get("prdt_name", ""),
                "quantity": qty,
                "avg_price": int(float(item.get("pchs_avg_pric", 0))),
                "current_price": int(item.get("prpr", 0)),
                "eval_amount": int(item.get("evlu_amt", 0)),
                "profit": int(item.get("evlu_pfls_amt", 0)),
                "profit_rate": float(item.get("evlu_pfls_rt", 0)),
            })

        output2 = data.get("output2", [{}])
        summary = output2[0] if output2 else {}
        return {
            "cash": int(summary.get("dnca_tot_amt", 0)),
            "total_eval": int(summary.get("tot_evlu_amt", 0)),
            "total_profit": int(summary.get("evlu_pfls_smtl_amt", 0)),
            "total_profit_rate": float(summary.get("tot_evlu_pfls_rt", 0)) if summary.get("tot_evlu_pfls_rt") else 0.0,
            "holdings": holdings,
        }

    def get_buyable_amount(self, stock_code: str, price: int) -> int:
        """특정 종목의 매수 가능 수량을 조회한다."""
        tr_id = "VTTC8908R" if self.config.is_virtual else "TTTC8908R"
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-psbl-order"
        headers = self._build_headers(tr_id)
        params = {
            "CANO": self.config.account_prefix,
            "ACNT_PRDT_CD": self.config.account_suffix,
            "PDNO": stock_code,
            "ORD_UNPR": str(price),
            "ORD_DVSN": "00",
            "CMA_EVLU_AMT_ICLD_YN": "Y",
            "OVRS_ICLD_YN": "N",
        }

        resp = self._session.get(url, headers=headers, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        if data.get("rt_cd") != "0":
            return 0

        output = data.get("output", {})
        return int(output.get("nrcvb_buy_qty", 0))
