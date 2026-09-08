"""
빗썸 API 연동 테스트 스크립트

1. Public API 테스트: 키 없이 바로 실행 가능
2. Private API 테스트: .env에 발급받은 키를 넣은 뒤 실행

실행: python test_connection.py
"""

from bithumb_client import BithumbClient, BithumbAPIError
from config import BITHUMB_ACCESS_KEY, BITHUMB_SECRET_KEY


def test_public_api():
    print("=" * 50)
    print("[1] Public API 테스트 (인증 불필요)")
    print("=" * 50)

    client = BithumbClient()

    ticker = client.get_ticker("KRW-BTC")
    price = ticker[0]["trade_price"]
    change_rate = ticker[0]["signed_change_rate"] * 100
    print(f"BTC 현재가: {price:,.0f}원 (전일 대비 {change_rate:+.2f}%)")

    candles = client.get_candles_minutes("KRW-BTC", unit=1, count=3)
    print("\n최근 1분봉 3개:")
    for c in candles:
        print(f"  {c['candle_date_time_kst']}  종가 {c['trade_price']:,.0f}원")


def test_private_api():
    print("\n" + "=" * 50)
    print("[2] Private API 테스트 (인증 필요)")
    print("=" * 50)

    if not BITHUMB_ACCESS_KEY or not BITHUMB_SECRET_KEY:
        print("BITHUMB_ACCESS_KEY / BITHUMB_SECRET_KEY가 설정되지 않았습니다.")
        print(".env 파일을 만들고 키를 채운 뒤 다시 실행하세요. (.env.example 참고)")
        return

    client = BithumbClient(access_key=BITHUMB_ACCESS_KEY, secret_key=BITHUMB_SECRET_KEY)

    try:
        accounts = client.get_accounts()
        print("보유 자산:")
        for acc in accounts:
            balance = float(acc["balance"])
            if balance > 0:
                print(f"  {acc['currency']}: {balance}")
    except BithumbAPIError as e:
        print(f"API 에러 발생: {e}")
        print("- API 키가 올바른지, IP 화이트리스트 설정이 맞는지 확인하세요.")


if __name__ == "__main__":
    test_public_api()
    test_private_api()
