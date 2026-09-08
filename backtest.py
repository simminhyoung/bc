"""
변동성 돌파 전략 백테스트

빗썸 Public API에서 일봉 데이터를 받아와, 과거에 이 전략을 썼다면
어떤 성과가 나왔을지 시뮬레이션합니다.

⚠️ 백테스트 결과가 좋다고 실전에서도 그대로 재현된다는 보장은 없습니다.
   (과최적화, 슬리피지, 유동성 부족 등 백테스트가 반영 못 하는 변수가 많음)
   여러 k값과 여러 기간(상승장/하락장/횡보장)으로 반드시 교차 검증하세요.

실행:
    python backtest.py
"""

import pandas as pd

from bithumb_client import BithumbClient
from strategy import calculate_target_price, is_breakout

# ---------------------------------------------------------------
# 백테스트 설정
# ---------------------------------------------------------------
MARKET = "KRW-BTC"
CANDLE_COUNT = 200          # 최대 200개 (빗썸 API 1회 요청 제한)
K_VALUES_TO_TEST = [0.3, 0.4, 0.5, 0.6, 0.7]  # 여러 k값 비교
FEE_RATE = 0.0004           # 편도 수수료율 (0.04%). 본인 수수료 등급에 맞게 수정하세요.


def fetch_daily_candles(market: str, count: int) -> pd.DataFrame:
    """일봉 데이터를 받아와 오래된 순 -> 최신 순으로 정렬된 DataFrame으로 반환"""
    client = BithumbClient()
    raw = client.get_candles_days(market, count=count)

    df = pd.DataFrame(raw)
    df = df.rename(columns={
        "candle_date_time_kst": "date",
        "opening_price": "open",
        "high_price": "high",
        "low_price": "low",
        "trade_price": "close",
    })
    df = df[["date", "open", "high", "low", "close"]]
    df = df.sort_values("date").reset_index(drop=True)  # 오래된 -> 최신 순
    return df


def run_backtest(df: pd.DataFrame, k: float, fee_rate: float = FEE_RATE) -> pd.DataFrame:
    """
    변동성 돌파 전략 시뮬레이션

    규칙:
    - 목표가 = 당일 시가 + (전일 고가 - 전일 저가) * k
    - 당일 고가가 목표가 이상이면 목표가에 매수 체결된 것으로 가정
    - 당일 종가에 매도 (당일 청산 전략)
    - 매수/매도 각각 수수료 차감
    """
    results = []

    for i in range(1, len(df)):
        prev = df.iloc[i - 1]
        today = df.iloc[i]

        target_price = calculate_target_price(today["open"], prev["high"], prev["low"], k=k)
        bought = is_breakout(today["high"], target_price)

        if not bought:
            results.append({
                "date": today["date"], "target_price": target_price,
                "bought": False, "buy_price": None, "sell_price": None,
                "return_pct": 0.0,
            })
            continue

        buy_price = target_price
        sell_price = today["close"]

        gross_return = (sell_price - buy_price) / buy_price
        net_return = gross_return - (fee_rate * 2)  # 매수+매도 수수료

        results.append({
            "date": today["date"], "target_price": target_price,
            "bought": True, "buy_price": buy_price, "sell_price": sell_price,
            "return_pct": net_return * 100,
        })

    return pd.DataFrame(results)


def summarize(result_df: pd.DataFrame, k: float) -> dict:
    """백테스트 결과 요약 (승률, 누적수익률, MDD 등)"""
    traded = result_df[result_df["bought"]]
    n_trades = len(traded)

    if n_trades == 0:
        return {"k": k, "trades": 0, "win_rate": None, "cum_return_pct": 0.0, "mdd_pct": 0.0}

    win_rate = (traded["return_pct"] > 0).mean() * 100

    # 복리로 누적 수익률 계산 (매매 없는 날은 수익률 0으로 취급)
    daily_returns = result_df["return_pct"] / 100
    cum_curve = (1 + daily_returns).cumprod()
    cum_return_pct = (cum_curve.iloc[-1] - 1) * 100

    # MDD (최대 낙폭)
    running_max = cum_curve.cummax()
    drawdown = (cum_curve - running_max) / running_max
    mdd_pct = drawdown.min() * 100

    return {
        "k": k,
        "trades": n_trades,
        "win_rate": round(win_rate, 1),
        "cum_return_pct": round(cum_return_pct, 2),
        "mdd_pct": round(mdd_pct, 2),
    }


def main():
    print(f"'{MARKET}' 최근 {CANDLE_COUNT}일 일봉 데이터를 가져오는 중...")
    df = fetch_daily_candles(MARKET, CANDLE_COUNT)
    print(f"데이터 기간: {df['date'].iloc[0]} ~ {df['date'].iloc[-1]} ({len(df)}일)\n")

    print("=" * 65)
    print(f"{'k값':>6} | {'매매횟수':>8} | {'승률(%)':>8} | {'누적수익률(%)':>14} | {'MDD(%)':>8}")
    print("=" * 65)

    summaries = []
    for k in K_VALUES_TO_TEST:
        result_df = run_backtest(df, k)
        summary = summarize(result_df, k)
        summaries.append(summary)
        print(f"{k:>6} | {summary['trades']:>8} | {str(summary['win_rate']):>8} | "
              f"{summary['cum_return_pct']:>14} | {summary['mdd_pct']:>8}")

    print("=" * 65)
    print("\n⚠️ 주의: 이 결과는 과거 데이터 기준이며, 슬리피지/유동성/체결 실패 등은")
    print("   반영되지 않았습니다. 실전 투입 전 반드시 페이퍼 트레이딩으로 재검증하세요.")

    best = max(summaries, key=lambda s: s["cum_return_pct"])
    print(f"\n이 기간 기준 최고 성과 k값: {best['k']} (누적수익률 {best['cum_return_pct']}%)")
    print("단, k값을 과거 데이터에 억지로 맞추는 과최적화를 항상 경계하세요.")


if __name__ == "__main__":
    main()
