#!/usr/bin/env python3
"""초기 .env 파일 생성 스크립트.

사용법:
    python setup_env.py
"""

import os

ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

def main():
    print("=" * 50)
    print("  한국투자증권 AI 자동매매 봇 - 초기 설정")
    print("=" * 50)
    print()

    if os.path.exists(ENV_PATH):
        # 기존 파일 읽어서 플레이스홀더인지 확인
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        if "your_app_key_here" not in content and "00000000-00" not in content:
            ans = input(".env 파일이 이미 존재합니다. 덮어쓰시겠습니까? (y/n): ").strip().lower()
            if ans != "y":
                print("취소되었습니다.")
                return

    print("한국투자증권 API 포털에서 발급받은 정보를 입력하세요.")
    print("(https://apiportal.koreainvestment.com)")
    print()

    app_key = input("APP KEY: ").strip()
    if not app_key:
        print("APP KEY를 입력해주세요.")
        return

    app_secret = input("APP SECRET: ").strip()
    if not app_secret:
        print("APP SECRET을 입력해주세요.")
        return

    account_no = input("계좌번호 (예: 50162777-01): ").strip()
    if not account_no:
        print("계좌번호를 입력해주세요.")
        return

    print()
    print("투자 모드 선택:")
    print("  1) 모의투자 (기본)")
    print("  2) 실전투자")
    mode_choice = input("선택 (1 또는 2): ").strip()
    is_real = mode_choice == "2"

    if is_real:
        base_url = "https://openapi.koreainvestment.com:9443"
        trade_mode = "real"
    else:
        base_url = "https://openapivts.koreainvestment.com:29443"
        trade_mode = "virtual"

    # 계좌 타입 추출
    parts = account_no.split("-")
    if len(parts) == 2:
        account_type = parts[1]
    else:
        account_type = "01"

    env_content = f"""KIS_BASE_URL={base_url}
KIS_APP_KEY={app_key}
KIS_APP_SECRET={app_secret}
KIS_ACCOUNT_NO={account_no}
KIS_ACCOUNT_TYPE={account_type}
TRADE_MODE={trade_mode}
MAX_INVESTMENT_RATIO=0.8
MAX_SINGLE_STOCK_RATIO=0.15
STOP_LOSS_RATIO=0.05
TAKE_PROFIT_RATIO=0.10
STRATEGY=ensemble
LOOKBACK_DAYS=60
REBALANCE_INTERVAL_MINUTES=30
"""

    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.write(env_content)

    print()
    print("=" * 50)
    print(f"  .env 파일 생성 완료!")
    print(f"  경로: {ENV_PATH}")
    print(f"  모드: {'실전투자' if is_real else '모의투자'}")
    print(f"  계좌: {account_no}")
    print("=" * 50)
    print()
    print("이제 'python run_web.py' 로 대시보드를 시작하세요.")


if __name__ == "__main__":
    main()
