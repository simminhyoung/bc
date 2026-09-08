"""
변동성 돌파 전략 - 실전 매매 실행 스크립트

이 스크립트는 "한 번 실행하면 현재 상태를 확인하고 필요한 매매를 한 번 수행한 뒤 종료"하는
방식으로 설계되었습니다. Render Cron Job처럼 주기적으로(예: 5~10분마다) 이 스크립트를
반복 실행하는 구조에 맞춘 것입니다.

상태(오늘 이미 매수했는지, 매수가/손절가가 얼마인지)는 state.json 파일에 저장합니다.
⚠️ Cron Job 환경에 따라 파일이 실행마다 초기화될 수 있습니다 (Render 무료 플랜은 영구
   디스크가 없으면 재배포/재시작 시 파일이 사라질 수 있음). 실전 투입 전 반드시 확인하세요.

동작 순서 (실행할 때마다):
1. 오늘 날짜 기준으로 상태 파일을 확인 (날짜가 바뀌었으면 상태 초기화)
2. 아직 매수 안 했다면: 목표가 계산 -> 현재가가 목표가 이상이면 매수
3. 이미 매수했다면: 손절가 이하로 떨어졌는지 확인 -> 손절가 이하면 즉시 매도
4. 장 마감 시각(예: 23:50 KST)이 지났고 포지션이 남아있으면 종가 청산

⚠️ DRY_RUN=True (기본값)일 때는 실제 주문을 넣지 않고 로그만 남깁니다.
   실제로 주문을 넣으려면 DRY_RUN을 False로 바꾸세요. (반드시 소액으로 먼저 테스트!)
"""

import json
import os
from datetime import datetime, timezone, timedelta

from bithumb_client import BithumbClient, BithumbAPIError
from config import BITHUMB_ACCESS_KEY, BITHUMB_SECRET_KEY
from strategy import (
    calculate_target_price,
    is_breakout,
    calculate_position_size,
    calculate_stop_loss_price,
)

# ---------------------------------------------------------------
# 매매 설정 - 본인 상황에 맞게 조정하세요
# ---------------------------------------------------------------
MARKET = "KRW-BTC"
K = 0.5                      # 변동성 돌파 민감도 (백테스트로 사전에 검증할 것)
RISK_PER_TRADE_PCT = 1.0     # 트레이드당 최대 손실 허용 비율 (자본 대비 %)
STOP_LOSS_PCT = 2.0          # 손절 기준 (%)
MAX_KRW_PER_TRADE = 100_000  # 소액 매매 목표에 맞춘 1회 최대 투입 금액 캡
DAY_END_HOUR_KST = 23        # 이 시각 이후엔 종가 청산 시도 (23시 50분 이후)
DAY_END_MINUTE_KST = 50

DRY_RUN = True  # ⚠️ 실제 주문을 넣으려면 False로 변경 (반드시 소액 테스트 후)

STATE_FILE = os.path.join(os.path.dirname(__file__), "state.json")
KST = timezone(timedelta(hours=9))


def log(msg: str):
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now} KST] {msg}")


def load_state() -> dict:
    today_str = datetime.now(KST).strftime("%Y-%m-%d")

    if not os.path.exists(STATE_FILE):
        return {"date": today_str, "position": None}

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    if state.get("date") != today_str:
        # 날짜가 바뀌었으면 포지션 정보 초기화 (전날 포지션은 종가 청산 로직에서 처리되어야 함)
        return {"date": today_str, "position": None}

    return state


def save_state(state: dict):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def is_near_day_end() -> bool:
    now = datetime.now(KST)
    return (now.hour, now.minute) >= (DAY_END_HOUR_KST, DAY_END_MINUTE_KST)


def main():
    if not BITHUMB_ACCESS_KEY or not BITHUMB_SECRET_KEY:
        log("❌ API 키가 설정되지 않았습니다. .env / Render 환경변수를 확인하세요.")
        return

    client = BithumbClient(access_key=BITHUMB_ACCESS_KEY, secret_key=BITHUMB_SECRET_KEY)
    state = load_state()

    try:
        ticker = client.get_ticker(MARKET)[0]
        current_price = ticker["trade_price"]
        today_open = ticker["opening_price"]
    except BithumbAPIError as e:
        log(f"❌ 현재가 조회 실패: {e}")
        return

    position = state.get("position")

    # ------------------------------------------------------------
    # 케이스 1: 포지션 보유 중 -> 손절/종가청산 체크
    # ------------------------------------------------------------
    if position:
        buy_price = position["buy_price"]
        volume = position["volume"]
        stop_loss_price = position["stop_loss_price"]

        if current_price <= stop_loss_price:
            log(f"🔻 손절 조건 충족 (현재가 {current_price:,.0f} <= 손절가 {stop_loss_price:,.0f})")
            _sell(client, volume, reason="손절")
            state["position"] = None
            save_state(state)
            return

        if is_near_day_end():
            log(f"🕚 장 마감 임박, 종가 청산 (현재가 {current_price:,.0f})")
            _sell(client, volume, reason="종가청산")
            state["position"] = None
            save_state(state)
            return

        pnl_pct = (current_price - buy_price) / buy_price * 100
        log(f"포지션 보유 중: 매수가 {buy_price:,.0f} / 현재가 {current_price:,.0f} "
            f"({pnl_pct:+.2f}%) / 손절가 {stop_loss_price:,.0f}")
        return

    # ------------------------------------------------------------
    # 케이스 2: 포지션 없음 -> 매수 조건 체크
    # ------------------------------------------------------------
    try:
        candles = client.get_candles_days(MARKET, count=2)
    except BithumbAPIError as e:
        log(f"❌ 캔들 조회 실패: {e}")
        return

    if len(candles) < 2:
        log("❌ 전일 캔들 데이터가 부족합니다.")
        return

    prev_day = candles[0]  # 최신순 정렬이므로 [0]이 전일(가장 최근 완성된 봉)
    target_price = calculate_target_price(
        today_open=today_open,
        prev_high=prev_day["high_price"],
        prev_low=prev_day["low_price"],
        k=K,
    )

    log(f"목표가: {target_price:,.0f} / 현재가: {current_price:,.0f}")

    if not is_breakout(current_price, target_price):
        log("매수 조건 미충족 (아직 목표가 미도달)")
        return

    # 매수 조건 충족 -> 포지션 사이징 후 매수
    try:
        krw_balance = client.get_balance("KRW")
    except BithumbAPIError as e:
        log(f"❌ 잔고 조회 실패: {e}")
        return

    available_krw = min(krw_balance, MAX_KRW_PER_TRADE)
    volume = calculate_position_size(
        available_krw=available_krw,
        risk_per_trade_pct=RISK_PER_TRADE_PCT,
        entry_price=current_price,
        stop_loss_pct=STOP_LOSS_PCT,
    )

    if volume <= 0:
        log("❌ 계산된 매수 수량이 0 이하입니다. 잔고나 설정을 확인하세요.")
        return

    stop_loss_price = calculate_stop_loss_price(current_price, STOP_LOSS_PCT)

    log(f"🔼 매수 조건 충족! 수량: {volume:.8f}, 예상 금액: {volume*current_price:,.0f}원, "
        f"손절가: {stop_loss_price:,.0f}")

    order = _buy(client, volume, current_price)
    if order is not None or DRY_RUN:
        state["position"] = {
            "buy_price": current_price,
            "volume": volume,
            "stop_loss_price": stop_loss_price,
        }
        save_state(state)


def _buy(client: BithumbClient, volume: float, price: float):
    if DRY_RUN:
        log(f"[DRY RUN] 실제 매수 대신 로그만 남깁니다. (수량: {volume:.8f}, 가격: {price:,.0f})")
        return None

    order = client.place_order(
        market=MARKET,
        side="bid",
        order_type="price",       # 시장가 매수 (총 매수 금액 기준)
        price=str(round(volume * price)),
    )
    log(f"✅ 매수 주문 접수: {order}")
    return order


def _sell(client: BithumbClient, volume: float, reason: str):
    if DRY_RUN:
        log(f"[DRY RUN] 실제 매도({reason}) 대신 로그만 남깁니다. (수량: {volume:.8f})")
        return None

    order = client.place_order(
        market=MARKET,
        side="ask",
        order_type="market",      # 시장가 매도 (수량 기준)
        volume=str(volume),
    )
    log(f"✅ 매도 주문 접수 ({reason}): {order}")
    return order


if __name__ == "__main__":
    main()
