"""
[Program Description]
- EntryExitEngine 통합 테스트: 실제 yfinance 데이터 + 실제 보유 정보를 사용하여
  UNH / B / SOXL 3종목 각각에 대해 진입 트리거 / 트레일링 스탑 / 시간 청산을 전부 체크합니다.
- RiskEngine.evaluate()로 실제 리스크 점수를 산출하여 entry trigger를 검증합니다.

[보유 정보]
  B    : avg_price=28.5,  qty=6000, last_updated=2025-08-01
  SOXL : avg_price=45.0,  qty=500,  last_updated=2025-08-01
  UNH  : avg_price=284.0, qty=31,   last_updated=2026-02-04
"""

import unittest
import sys
import os
from datetime import datetime

# [Path Fix] 프로젝트 루트(SG)를 검색 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.indicators import Indicators
from core.risk_engine import RiskEngine
from core.entry_exit_engine import EntryExitEngine


# ─────────────────────────────────────────────
# 실제 보유 정보 (David's Portfolio)
# ─────────────────────────────────────────────

HOLDINGS = {
    'B': {
        'ticker':        'B',
        'qty':           6000,
        'avg_price':     28.5,
        'entry_stop':    round(28.5 * 0.9, 2),
        'last_updated':  '2025-08-01',
        'trailing_high': 0.0,   # setUpClass에서 실제 52주 고점으로 갱신됨
    },
    'SOXL': {
        'ticker':        'SOXL',
        'qty':           500,
        'avg_price':     45.0,
        'entry_stop':    round(45.0 * 0.9, 2),
        'last_updated':  '2025-08-01',
        'trailing_high': 0.0,   # setUpClass에서 실제 52주 고점으로 갱신됨
    },
    'UNH': {
        'ticker':        'UNH',
        'qty':           31,
        'avg_price':     284.0,
        'entry_stop':    round(284.0 * 0.9, 2),
        'last_updated':  '2026-02-04',
        'trailing_high': 0.0,
    },
}


class TestEntryExitIntegration(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        """
        클래스 전체에서 공유할 ind_df / score를 한 번만 수급하여 API 호출 최소화.
        각 test 메서드는 이 캐시를 참조합니다.
        """
        cls.engine     = EntryExitEngine()
        cls.indicators = Indicators()
        cls.risk_engine = RiskEngine()

        print("\n" + "=" * 60)
        print("  EntryExitEngine 통합 테스트 (실제 시장 데이터)")
        print(f"  실행 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)

        # 3종목 데이터 일괄 수급
        cls.ind_cache   = {}   # {ticker: ind_df}
        cls.score_cache = {}   # {ticker: float}
        cls.price_cache = {}   # {ticker: float}

        for ticker in HOLDINGS:
            ind_df, _ = cls.indicators.generate(ticker=ticker, period="2y")
            if ind_df is not None and not ind_df.empty:
                cls.ind_cache[ticker]   = ind_df
                score, _, _details      = cls.risk_engine.evaluate(ind_df)
                cls.score_cache[ticker] = score
                cls.price_cache[ticker] = float(ind_df.iloc[-1].get('Close', 0))

                # 실제 52주 고점을 trailing_high로 설정 (현실적인 시나리오 재현)
                trail_high_52w = float(ind_df['Close'].tail(252).max())
                HOLDINGS[ticker]['trailing_high'] = trail_high_52w

                # ATR 확인 (atr 컬럼 존재 여부)
                atr_now = float(ind_df['atr'].iloc[-1]) if 'atr' in ind_df.columns else 0.0

                print(f"  ✅ [{ticker}] 데이터 수급 완료 — "
                      f"현재가: ${cls.price_cache[ticker]:,.2f}, "
                      f"리스크 점수: {score:.1f}, "
                      f"ATR: {atr_now:.2f}, "
                      f"52주 고점: ${trail_high_52w:.2f}")
            else:
                print(f"  ❌ [{ticker}] 데이터 수급 실패")

    # ─────────────────────────────────────────
    # 공통 헬퍼: 3종 신호 체크 + 출력
    # ─────────────────────────────────────────

    def _run_all_checks(self, ticker, prev_score=None):
        """
        3종 신호(진입 트리거 / 트레일링 스탑 / 시간 청산)를 순서대로 실행하고
        결과를 콘솔에 상세 출력합니다.
        반환: (is_entry, is_trailing, exit_signal)
        """
        holding       = HOLDINGS[ticker]
        ind_df        = self.ind_cache.get(ticker)
        score         = self.score_cache.get(ticker, 50.0)
        current_price = self.price_cache.get(ticker, 0.0)

        if ind_df is None or ind_df.empty:
            self.skipTest(f"[{ticker}] ind_df 수급 실패 — 네트워크 환경 확인 필요")

        avg_price    = holding['avg_price']
        qty          = holding['qty']
        last_updated = datetime.strptime(holding['last_updated'], '%Y-%m-%d')
        elapsed_days = (datetime.now() - last_updated).days
        profit_pct   = ((current_price - avg_price) / avg_price) * 100
        position_val = qty * current_price
        unrealized   = (current_price - avg_price) * qty

        latest   = ind_df.iloc[-1]
        level    = self.risk_engine.get_level(score)
        high_20d = ind_df['Close'].iloc[-20:].max()

        # ── 섹션 헤더 ──────────────────────────────
        print(f"\n{'━'*55}")
        print(f"  🏦 [{ticker}] 신호 감지 리포트")
        print(f"{'━'*55}")
        print(f"  보유 정보")
        print(f"    평균 단가   : ${avg_price:,.2f}  |  수량: {qty:,}주")
        print(f"    진입일      : {holding['last_updated']}  |  경과: {elapsed_days}일")
        print(f"  시장 현황")
        print(f"    현재가      : ${current_price:,.2f}")
        print(f"    미실현 손익 : ${unrealized:,.0f}  ({profit_pct:+.2f}%)")
        print(f"    평가 금액   : ${position_val:,.0f}")
        print(f"    리스크 점수 : {score:.1f}  (레벨 {level})")
        print(f"    avg_sigma   : {latest.get('avg_sigma', 0):.3f}")
        print(f"    MFI         : {latest.get('MFI', 0):.1f}  |  "
              f"MACD_h: {latest.get('macd_h', 0):.4f}")
        print(f"    20일 고점   : ${high_20d:,.2f}  |  "
              f"고점 대비: {((current_price-high_20d)/high_20d*100):+.2f}%")

        # ── 1. 진입 트리거 ──────────────────────────
        is_entry, conditions = self.engine.check_entry_trigger(
            ticker=ticker, score=score, details={},
            ind_df=ind_df, prev_score=prev_score
        )
        print(f"\n  📡 진입 트리거")
        if is_entry:
            print(f"    → ✅ 발동  (선택 조건 {len(conditions)-1}/4 충족)")
            for c in conditions:
                print(f"       • {c}")
        else:
            gate = "레벨 4+ (A 관문 차단)" if score >= self.engine.ENTRY_SCORE_MAX else "선택 조건 부족"
            print(f"    → ⛔ 미발동  ({gate})")

        # ── 2. 트레일링 스탑 (ATR 다축 등급) ──────────────────────
        # holding의 trailing_high는 setUpClass에서 실제 52주 고점으로 갱신됨
        grade, t_profit, details = self.engine.check_trailing_stop(
            holding=holding, current_price=current_price,
            ind_df=ind_df, score=score
        )
        trail_hi   = details.get('trailing_high', holding.get('trailing_high', 0.0) or 0.0)
        stop_price = details.get('trail_stop_price', 0.0)
        atr_val    = details.get('atr', 0.0)
        atr_mult   = details.get('atr_mult', 0.0)
        drawdown   = details.get('drawdown_pct', 0.0)

        print(f"\n  🔴 트레일링 스탑 (ATR 다축 등급)")
        print(f"    ATR         : {atr_val:.3f}  |  배수: {atr_mult}x  "
              f"(수익구간: {'+5~20%' if atr_mult==2.0 else '+20~50%' if atr_mult==2.5 else '+50%+' if atr_mult==3.0 else 'N/A'})")
        print(f"    52주 고점   : ${trail_hi:.2f}  →  동적 스탑가: ${stop_price:.2f}")
        if profit_pct < self.engine.TRAIL_PROFIT_FLOOR:
            print(f"    → ⚪ 비활성  (수익률 {profit_pct:+.2f}% — "
                  f"활성화 기준 +{self.engine.TRAIL_PROFIT_FLOOR:.0f}% 미달)")
        else:
            ax1 = '✅' if details.get('axis1') else '⛔'
            ax2 = '✅' if details.get('axis2') else '⛔'
            ax3 = '✅' if details.get('axis3') else '⛔'
            grade_emoji = {0: '✅ 미발동', 1: '🟡 1단계(관찰)',
                           2: '🟠 2단계(분할)', 3: '🔴 3단계(전량)'}[grade]
            print(f"    축1(가격): {ax1}  축2(점수): {ax2}  축3(수급): {ax3}")
            print(f"    낙폭      : {drawdown:+.2f}%  →  {grade_emoji}")
            if grade >= 2:
                sell_pct = details.get('sell_ratio', 0) * 100
                print(f"    ⚡ 권고 매도비율: {sell_pct:.0f}%")

        # ── 3. 시간 기반 청산 ────────────────────────
        exit_signal = self.engine.check_time_based_exit(
            holding=holding, current_price=current_price
        )
        print(f"\n  ⏰ 시간 기반 청산  (경과 {elapsed_days}일)")
        if exit_signal:
            print(f"    → ⏰ 발동  사유: {exit_signal['reason']}")
            print(f"       경과: {exit_signal['elapsed_days']}일 / "
                  f"수익률: {exit_signal['profit_pct']:+.2f}%")
        else:
            reasons = []
            if elapsed_days <= self.engine.TIME_LOSS_DAYS:
                reasons.append(f"T+{self.engine.TIME_LOSS_DAYS}일 미달 ({elapsed_days}일)")
            elif profit_pct >= 0:
                reasons.append("손실 없음")
            if elapsed_days <= self.engine.TIME_OPP_DAYS:
                reasons.append(f"T+{self.engine.TIME_OPP_DAYS}일 미달")
            elif profit_pct >= self.engine.TIME_OPP_PCT:
                reasons.append(f"수익 {profit_pct:+.1f}% ≥ 기준 +{self.engine.TIME_OPP_PCT:.0f}%")
            print(f"    → ✅ 미발동  ({' / '.join(reasons) if reasons else '조건 미달'})")

        print(f"{'━'*55}")
        return is_entry, grade, exit_signal

    # ─────────────────────────────────────────
    # 테스트 1: UNH
    # ─────────────────────────────────────────

    def test_01_unh_all_signals(self):
        """[UNH] 3종 신호 전체 체크 — avg_price=284.0, qty=31, 진입일=2026-02-04"""
        is_entry, trail_grade, exit_signal = self._run_all_checks('UNH')

        # 타입 보장
        self.assertIsInstance(is_entry,    bool)
        self.assertIsInstance(trail_grade, int)
        self.assertIn(trail_grade, [0, 1, 2, 3], "trail_grade는 0~3 사이여야 합니다")

        # 진입 트리거 발동 시 일관성 검증
        if is_entry:
            score = self.score_cache['UNH']
            self.assertLess(score, self.engine.ENTRY_SCORE_MAX,
                            "진입 트리거 발동 시 score < 31 이어야 합니다")

        # 트레일링 스탑 발동 시 일관성 검증 (grade 1 이상)
        if trail_grade >= 1:
            profit = ((self.price_cache['UNH'] - HOLDINGS['UNH']['avg_price'])
                      / HOLDINGS['UNH']['avg_price'] * 100)
            self.assertGreaterEqual(profit, self.engine.TRAIL_PROFIT_FLOOR,
                                    "트레일링 스탑은 수익 +5% 이상에서만 활성화되어야 합니다")

        # 시간 청산 발동 시 사유 검증
        if exit_signal:
            self.assertIn(exit_signal['reason'], ['손실 장기화', '기회비용'])

    # ─────────────────────────────────────────
    # 테스트 2: B (Barrick Gold)
    # ─────────────────────────────────────────

    def test_02_barrick_all_signals(self):
        """[B] 3종 신호 전체 체크 — avg_price=28.5, qty=6000, 진입일=2025-08-01"""
        is_entry, trail_grade, exit_signal = self._run_all_checks('B')

        self.assertIsInstance(is_entry,    bool)
        self.assertIsInstance(trail_grade, int)
        self.assertIn(trail_grade, [0, 1, 2, 3])

        if trail_grade >= 1:
            profit = ((self.price_cache['B'] - HOLDINGS['B']['avg_price'])
                      / HOLDINGS['B']['avg_price'] * 100)
            self.assertGreaterEqual(profit, self.engine.TRAIL_PROFIT_FLOOR,
                                    "트레일링 스탑은 수익 +5% 이상에서만 활성화")

        if exit_signal:
            self.assertIn(exit_signal['reason'], ['손실 장기화', '기회비용'])
            profit = ((self.price_cache['B'] - HOLDINGS['B']['avg_price'])
                      / HOLDINGS['B']['avg_price'] * 100)
            if profit >= 0:
                self.assertNotEqual(exit_signal['reason'], '손실 장기화',
                                    "수익 포지션에서 '손실 장기화' 신호는 불가합니다")

    # ─────────────────────────────────────────
    # 테스트 3: SOXL
    # ─────────────────────────────────────────

    def test_03_soxl_all_signals(self):
        """[SOXL] 3종 신호 전체 체크 — avg_price=45.0, qty=500, 진입일=2025-08-01"""
        is_entry, trail_grade, exit_signal = self._run_all_checks('SOXL')

        self.assertIsInstance(is_entry,    bool)
        self.assertIsInstance(trail_grade, int)
        self.assertIn(trail_grade, [0, 1, 2, 3])

        if trail_grade >= 1:
            profit = ((self.price_cache['SOXL'] - HOLDINGS['SOXL']['avg_price'])
                      / HOLDINGS['SOXL']['avg_price'] * 100)
            self.assertGreaterEqual(profit, self.engine.TRAIL_PROFIT_FLOOR,
                                    "트레일링 스탑은 수익 +5% 이상에서만 활성화")

        if exit_signal:
            self.assertIn(exit_signal['reason'], ['손실 장기화', '기회비용'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
