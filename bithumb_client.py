"""
빗썸(Bithumb) Open API v2.1 REST 클라이언트

- Public API: 인증 불필요 (시세, 캔들, 호가 등)
- Private API: JWT 인증 필요 (잔고 조회, 주문 등)

공식 문서: https://apidocs.bithumb.com
  - 인증 방식: https://apidocs.bithumb.com/docs/인증-토큰-생성하기
  - 주문 요청: https://apidocs.bithumb.com/reference/주문-요청
  - 전체 자산 조회: https://apidocs.bithumb.com/reference/전체-자산-조회

주의:
- API 키 발급 시 반드시 '출금' 권한은 비활성화하고, 가능하면 IP를 화이트리스트에 등록하세요.
- 이 코드는 실거래 주문을 실제로 실행할 수 있습니다. 테스트 시에는 place_order() 호출부를
  주석 처리하거나 매우 작은 금액으로 먼저 검증하세요.
"""

import hashlib
import time
import uuid
from urllib.parse import urlencode

import jwt
import requests


class BithumbAPIError(Exception):
    """빗썸 API가 에러 응답을 반환했을 때 발생시키는 예외"""

    def __init__(self, status_code, error_body):
        self.status_code = status_code
        self.error_body = error_body
        super().__init__(f"[{status_code}] {error_body}")


class BithumbClient:
    BASE_URL = "https://api.bithumb.com"

    def __init__(self, access_key: str = None, secret_key: str = None, timeout: int = 10):
        """
        access_key / secret_key는 Private API(잔고 조회, 주문)를 쓸 때만 필요합니다.
        Public API(시세 조회 등)만 쓸 거라면 인자 없이 BithumbClient()로 생성해도 됩니다.
        """
        self.access_key = access_key
        self.secret_key = secret_key
        self.timeout = timeout
        self.session = requests.Session()

    # ------------------------------------------------------------------
    # 내부 유틸
    # ------------------------------------------------------------------
    def _build_jwt(self, query: dict = None) -> str:
        if not self.access_key or not self.secret_key:
            raise ValueError("Private API를 호출하려면 access_key/secret_key가 필요합니다.")

        payload = {
            "access_key": self.access_key,
            "nonce": str(uuid.uuid4()),
            "timestamp": round(time.time() * 1000),
        }

        if query:
            query_string = urlencode(query).encode()
            m = hashlib.sha512()
            m.update(query_string)
            payload["query_hash"] = m.hexdigest()
            payload["query_hash_alg"] = "SHA512"

        token = jwt.encode(payload, self.secret_key)
        return f"Bearer {token}"

    def _get(self, path: str, params: dict = None, auth: bool = False):
        url = self.BASE_URL + path
        headers = {"accept": "application/json"}
        if auth:
            headers["Authorization"] = self._build_jwt(params)

        resp = self.session.get(url, params=params, headers=headers, timeout=self.timeout)
        return self._handle_response(resp)

    def _post(self, path: str, body: dict):
        url = self.BASE_URL + path
        headers = {
            "Authorization": self._build_jwt(body),
            "Content-Type": "application/json; charset=utf-8",
        }
        resp = self.session.post(url, json=body, headers=headers, timeout=self.timeout)
        return self._handle_response(resp)

    def _delete(self, path: str, params: dict):
        url = self.BASE_URL + path
        headers = {"Authorization": self._build_jwt(params)}
        resp = self.session.delete(url, params=params, headers=headers, timeout=self.timeout)
        return self._handle_response(resp)

    @staticmethod
    def _handle_response(resp: requests.Response):
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except ValueError:
                body = resp.text
            raise BithumbAPIError(resp.status_code, body)
        if resp.text:
            return resp.json()
        return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def get_ticker(self, markets: str):
        """
        현재가(Ticker) 조회
        markets 예: "KRW-BTC" 또는 "KRW-BTC,KRW-ETH"
        """
        return self._get("/v1/ticker", params={"markets": markets})

    def get_candles_minutes(self, market: str, unit: int = 1, count: int = 200, to: str = None):
        """
        분봉 캔들 조회 (unit: 1, 3, 5, 10, 15, 30, 60, 240 중 하나, count 최대 200)
        응답은 최신 -> 과거 순으로 정렬되어 내려옵니다.
        """
        params = {"market": market, "count": count}
        if to:
            params["to"] = to
        return self._get(f"/v1/candles/minutes/{unit}", params=params)

    def get_candles_days(self, market: str, count: int = 200, to: str = None):
        """일봉 캔들 조회"""
        params = {"market": market, "count": count}
        if to:
            params["to"] = to
        return self._get("/v1/candles/days", params=params)

    # ------------------------------------------------------------------
    # Private API
    # ------------------------------------------------------------------
    def get_accounts(self):
        """보유 자산(잔고) 전체 조회"""
        return self._get("/v1/accounts", auth=True)

    def get_balance(self, currency: str = "KRW"):
        """특정 화폐의 주문가능 잔고만 뽑아서 반환 (편의 함수)"""
        accounts = self.get_accounts()
        for acc in accounts:
            if acc["currency"] == currency:
                return float(acc["balance"])
        return 0.0

    def place_order(
        self,
        market: str,
        side: str,
        order_type: str,
        price: str = None,
        volume: str = None,
        time_in_force: str = None,
        client_order_id: str = None,
    ):
        """
        주문 요청 (실거래 주문! 신중히 호출할 것)

        market: 예) "KRW-BTC"
        side: "bid"(매수) | "ask"(매도)
        order_type: "limit"(지정가) | "price"(시장가 매수) | "market"(시장가 매도) | "best"
        price: 지정가 주문의 단가, 혹은 시장가 매수 시 총 매수 금액(문자열로 전달)
        volume: 지정가/시장가 매도 시 수량(문자열로 전달)
        """
        body = {
            "market": market,
            "side": side,
            "order_type": order_type,
        }
        if price is not None:
            body["price"] = str(price)
        if volume is not None:
            body["volume"] = str(volume)
        if time_in_force:
            body["time_in_force"] = time_in_force
        if client_order_id:
            body["client_order_id"] = client_order_id

        return self._post("/v2/orders", body)

    def cancel_order(self, order_id: str = None, client_order_id: str = None):
        """주문 취소. order_id 또는 client_order_id 중 하나 이상 필요."""
        params = {}
        if order_id:
            params["order_id"] = order_id
        if client_order_id:
            params["client_order_id"] = client_order_id
        if not params:
            raise ValueError("order_id 또는 client_order_id 중 하나는 반드시 필요합니다.")
        return self._delete("/v2/order", params)


if __name__ == "__main__":
    # 간단한 동작 확인 (Public API는 키 없이도 바로 테스트 가능)
    client = BithumbClient()
    print("=== BTC 현재가 ===")
    print(client.get_ticker("KRW-BTC"))

    print("\n=== BTC 5분봉 최근 5개 ===")
    candles = client.get_candles_minutes("KRW-BTC", unit=5, count=5)
    for c in candles:
        print(c["candle_date_time_kst"], c["trade_price"])
