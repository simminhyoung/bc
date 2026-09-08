"""
변동성 돌파 전략 (Larry Williams Volatility Breakout) 핵심 로직

목표가 = 당일 시가 + (전일 고가 - 전일 저가) * k

당일 고가가 목표가 이상으로 올라오면 매수 시그널로 보고,
보통 당일 종가(또는 익일 시가)에 청산하는 단기 전략입니다.

이 파일은 순수 계산 로직만 담당하고, 실제 매매/백테스트는
backtest.py, live_trader.py에서 이 로직을 가져다 씁니다.
"""

from dataclasses import dataclass


@dataclass
class DayCandle:
    """전략 계산에 필요한 최소 캔들 정보"""
    date: str
    open: float
    high: float
    low: float
    close: float


def calculate_target_price(today_open: float, prev_high: float, prev_low: float, k: float = 0.5) -> float:
    """
    변동성 돌파 목표가 계산

    k: 돌파 민감도 (0~1). 보통 0.3~0.7 사이에서 백테스트로 최적값을 찾음.
       k가 작을수록 매수 빈도가 높아지고, 클수록 강한 돌파에만 진입.
    """
    if k <= 0 or k >= 1:
        raise ValueError("k는 0과 1 사이 값이어야 합니다 (일반적으로 0.3~0.7 권장)")
    return today_open + (prev_high - prev_low) * k


def is_breakout(current_high_or_price: float, target_price: float) -> bool:
    """당일 가격(또는 고가)이 목표가 이상으로 올라왔는지 여부"""
    return current_high_or_price >= target_price


def calculate_position_size(available_krw: float, risk_per_trade_pct: float, entry_price: float, stop_loss_pct: float) -> float:
    """
    리스크 기반 포지션 사이징

    한 트레이드에서 잃을 수 있는 최대 금액을 자본 대비 risk_per_trade_pct로 제한합니다.
    예) 자본 100만원, risk_per_trade_pct=1%, stop_loss_pct=2%
        -> 최대 손실 허용액 = 10,000원
        -> 진입 수량 = 10,000 / (entry_price * 0.02)

    반환값: 매수할 코인 수량 (volume)
    """
    if not (0 < risk_per_trade_pct < 100):
        raise ValueError("risk_per_trade_pct는 0~100 사이 값이어야 합니다")
    if not (0 < stop_loss_pct < 100):
        raise ValueError("stop_loss_pct는 0~100 사이 값이어야 합니다")

    max_loss_amount = available_krw * (risk_per_trade_pct / 100)
    loss_per_coin = entry_price * (stop_loss_pct / 100)
    if loss_per_coin <= 0:
        return 0.0

    volume = max_loss_amount / loss_per_coin

    # 실제 매수에 필요한 총 금액이 보유 잔고를 넘지 않도록 캡
    max_affordable_volume = available_krw / entry_price
    return min(volume, max_affordable_volume)


def calculate_stop_loss_price(entry_price: float, stop_loss_pct: float) -> float:
    """손절 가격 계산 (entry_price 대비 -stop_loss_pct%)"""
    return entry_price * (1 - stop_loss_pct / 100)
