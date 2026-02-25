"""
[Program Description]
- EntryExitEngine 단위 테스트.
- 진입 트리거, 트레일링 스탑, 시간 기반 청산 신호의
  경계값(boundary) 및 핵심 분기(branch)를 검증합니다.

[Test Structure]
  TestEntryTrigger  : check_entry_trigger() — 4개 케이스
  TestTrailingStop  : check_trailing_stop() — 4개 케이스
  TestTimeBasedExit : check_time_based_exit() — 4개 케이스
"""

import unittest
import os
import sys
from datetime import datetime, timedelta

import pandas as pd
import numpy as np

# [Path Fix] 프로젝트 루트(SG)를 검색 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.entry_exit_engine import EntryExitEngine


# ─────────────────────────────────────────────
# 공통 헬퍼
# ─────────────────────────────────────────────

def make_ind_df(rows):
    """
    진입 트리거 테스트용 mock ind_df 생성.
    rows: [{'avg_sigma': ..., 'macd_h': ..., 'MFI': ...}, ...]
    """
    return pd.DataFrame(rows)


def make_atr_ind_df(rows):
    """
    트레일링 스탑 테스트용 mock ind_df 생성.
    rows: [{'atr': ..., 'MFI': ..., 'RSI': ..., 'macd_h': ..., 'ADX': ...}, ...]
    """
    return pd.DataFrame(rows)


def make_holding(avg_price, days_ago, ticker='TEST'):
    """
    보유 종목 mock dict 생성.
    days_ago 일 전에 매수한 것으로 세팅.
    """
    entry_date = (datetime.now() - timedelta(days=days_ago)).strftime('%Y-%m-%d')
    return {
        'ticker':       ticker,
        'qty':          10,
        'avg_price':    avg_price,
        'entry_stop':   avg_price * 0.9,
        'last_updated': entry_date
    }


# ─────────────────────────────────────────────
# 1. 진입 트리거 (check_entry_trigger)
# ─────────────────────────────────────────────

class TestEntryTrigger(unittest.TestCase):
    def setUp(self):
        self.engine = EntryExitEngine()
        # 기본 ind_df: 3행 — 조건 검사에 최소 필요한 길이
        # B, C, D를 모두 충족하는 "이상적 반등" 시나리오
        self.ind_all_pass = make_ind_df([
            {'avg_sigma': 0.3, 'macd_h': -0.5,  'MFI': 30.0},  # T-2
            {'avg_sigma': 0.4, 'macd_h': -0.4,  'MFI': 35.0},  # T-1 (prev)
            {'avg_sigma': 0.6, 'macd_h': -0.2,  'MFI': 42.0},  # T   (latest)
        ])

    def test_case1_all_conditions_met(self):
        """[진입-케이스1] A 충족 + B/C/D/E 모두 충족 → True 반환 및 5개 조건 목록 확인"""
        triggered, conditions = self.engine.check_entry_trigger(
            ticker='TEST', score=20.0, details={},
            ind_df=self.ind_all_pass,
            prev_score=35.0   # score(20) < prev_score(35) → 조건 E 충족
        )
        self.assertTrue(triggered, "모든 조건 충족 시 True여야 합니다")
        # A + B + C + D + E = 5개
        self.assertEqual(len(conditions), 5, f"조건 목록 5개 예상, 실제: {conditions}")
        print(f"✅ [진입-케이스1] triggered={triggered}, 조건 수={len(conditions)}")

    def test_case2_score_level4_fails_condition_a(self):
        """[진입-케이스2] score=35 (레벨 4, 조건 A 미달) → 즉시 False 반환"""
        triggered, conditions = self.engine.check_entry_trigger(
            ticker='TEST', score=35.0, details={},
            ind_df=self.ind_all_pass,
            prev_score=50.0
        )
        self.assertFalse(triggered, "레벨 4(score≥31) 는 조건 A 불충족으로 False여야 합니다")
        self.assertEqual(conditions, [], "조건 목록은 빈 리스트여야 합니다")
        print(f"✅ [진입-케이스2] triggered={triggered} (score=35, A 미달)")

    def test_case3_only_one_optional_insufficient(self):
        """[진입-케이스3] 조건 A 충족 + 선택 조건 B만 충족 (1개) → False 반환"""
        # B만 통과: sigma 상승 / macd_h는 양수(C 불충족) / MFI는 40 초과(D 불충족)
        # E도 불충족: prev_score=None
        ind_b_only = make_ind_df([
            {'avg_sigma': 0.4, 'macd_h': 0.3,  'MFI': 55.0},  # prev
            {'avg_sigma': 0.7, 'macd_h': 0.5,  'MFI': 60.0},  # latest — macd_h 양수라 C 불가
        ])
        triggered, conditions = self.engine.check_entry_trigger(
            ticker='TEST', score=25.0, details={},
            ind_df=ind_b_only,
            prev_score=None   # E 불충족
        )
        self.assertFalse(triggered, "선택 조건 1개(B만)는 2개 미달로 False여야 합니다")
        print(f"✅ [진입-케이스3] triggered={triggered} (선택 조건 1개 충족, 부족)")

    def test_case4_exactly_two_optionals_pass(self):
        """[진입-케이스4] 조건 A 충족 + 선택 조건 B·C 정확히 2개 충족 → True 반환"""
        # B: sigma 상승, C: macd_h 음수 구간 상승, D: MFI > 40(불충족), E: prev_score None(불충족)
        # 엔진 최솟값(3행) 충족을 위해 dummy T-2 행 포함
        ind_bc = make_ind_df([
            {'avg_sigma': 0.2, 'macd_h': -0.6, 'MFI': 55.0},  # T-2 (dummy, 범위 밖)
            {'avg_sigma': 0.3, 'macd_h': -0.5, 'MFI': 55.0},  # T-1 (prev)
            {'avg_sigma': 0.6, 'macd_h': -0.2, 'MFI': 60.0},  # T   (latest)
        ])
        triggered, conditions = self.engine.check_entry_trigger(
            ticker='TEST', score=18.0, details={},
            ind_df=ind_bc,
            prev_score=None   # E 불충족
        )
        self.assertTrue(triggered, "선택 조건 2개(B·C) 충족 시 True여야 합니다")
        # A + B + C = 3개 (D, E는 불충족)
        self.assertEqual(len(conditions), 3, f"조건 목록 3개 예상, 실제: {conditions}")
        print(f"✅ [진입-케이스4] triggered={triggered}, 조건={[c[0] for c in conditions]}")


# ─────────────────────────────────────────────
# 2. 트레일링 스탑 (check_trailing_stop) — ATR 다축 등급 버전
#
# 반환: (grade: int, profit_pct: float, details: dict)
#
# 케이스 설계:
#   케이스1: profit +3% → grade=0 (활성화 기준 미달)
#   케이스2: profit +12%, trailing_high=112, ATR=1.0, mult=2.0
#            stop=112-2=110, current=111 > 110 → axis1=False, score=50<61 → grade=0
#   케이스3: profit +25%, trailing_high=125, ATR=2.0, mult=2.5
#            stop=125-5=120, current=115 < 120 → axis1=True
#            score=70≥61, history=[55,65] → 연속상승 → axis2=True
#            MFI(40)<RSI(55) ✅ / MACD 연속감소 ✅ / ADX 감소 ✅ → axis3=True → grade=3
#   케이스4: profit +60%, trailing_high=165, ATR=3.0, mult=3.0
#            stop=165-9=156, current=155 < 156 → axis1=True
#            score=50 < 61 → axis2=False → grade=1 (관찰)
# ─────────────────────────────────────────────

class TestTrailingStop(unittest.TestCase):
    def setUp(self):
        # db=None: 단위 테스트에서는 DB 갱신 없이 로직만 검증
        self.engine = EntryExitEngine()
        self.holding_base = make_holding(avg_price=100.0, days_ago=30)

    def test_case1_profit_below_floor_grade0(self):
        """[트레일링-케이스1] 수익 +3% (활성화 기준 5% 미달) → grade=0, details={}"""
        ind = make_atr_ind_df([
            {'atr': 1.0, 'MFI': 40.0, 'RSI': 50.0, 'macd_h': 0.1, 'ADX': 20.0},
            {'atr': 1.0, 'MFI': 39.0, 'RSI': 49.0, 'macd_h': 0.0, 'ADX': 19.0},
            {'atr': 1.0, 'MFI': 38.0, 'RSI': 48.0, 'macd_h': -0.1, 'ADX': 18.0},
        ])
        grade, profit_pct, details = self.engine.check_trailing_stop(
            holding=self.holding_base, current_price=103.0, ind_df=ind
        )
        self.assertEqual(grade, 0, "+3% 수익은 활성화 조건(5%) 미달로 grade=0이어야 합니다")
        self.assertAlmostEqual(profit_pct, 3.0, places=1)
        self.assertEqual(details, {}, "활성화 조건 미달 시 details는 빈 dict여야 합니다")
        print(f"✅ [트레일링-케이스1] grade={grade}, profit={profit_pct:.1f}%")

    def test_case2_axis1_not_breached_grade0(self):
        """[트레일링-케이스2] profit +12%, trailing_high=112, ATR=1.0
        stop=112-2.0=110, current=111>110 → axis1=False → grade=0"""
        holding = {**self.holding_base, 'trailing_high': 112.0}
        # mult=2.0 (5~20% 구간): stop = 112 - 1.0*2.0 = 110.0
        ind = make_atr_ind_df([
            {'atr': 1.0, 'MFI': 55.0, 'RSI': 50.0, 'macd_h': 0.1, 'ADX': 22.0},
            {'atr': 1.0, 'MFI': 53.0, 'RSI': 48.0, 'macd_h': 0.0, 'ADX': 21.0},
            {'atr': 1.0, 'MFI': 50.0, 'RSI': 46.0, 'macd_h': -0.1, 'ADX': 20.0},
        ])
        grade, profit_pct, details = self.engine.check_trailing_stop(
            holding=holding, current_price=111.0, ind_df=ind, score=50.0
        )
        self.assertEqual(grade, 0, "현재가(111) > 스탑(110) → axis1=False → grade=0이어야 합니다")
        self.assertFalse(details.get('axis1'), "axis1=False 이어야 합니다")
        self.assertFalse(details.get('axis2'), "score=50<61 → axis2=False 이어야 합니다")
        print(f"✅ [트레일링-케이스2] grade={grade}, axis1={details.get('axis1')}, "
              f"stop={details.get('trail_stop_price'):.1f}")

    def test_case3_all_axes_triggered_grade3(self):
        """[트레일링-케이스3] profit +25%, 축1+2+3 모두 충족 → grade=3 (전량청산)
        avg=100, current=125(+25%), trailing_high=135, ATR=2.0, mult=2.5
        stop=135-5=130, current=125 < 130 → axis1=True
        score=70≥61, history=[55,65] → axis2=True
        MFI<RSI, MACD연속감소, ADX감소 → axis3=True"""
        # avg_price=100 (make_holding 기본값), trailing_high=135
        holding = {**self.holding_base, 'avg_price': 100.0, 'trailing_high': 135.0}
        # mult=2.5 (20~50%): stop = 135 - 2.0*2.5 = 130.0
        # current=125 → profit=+25% → 20~50% 구간 → mult=2.5
        ind = make_atr_ind_df([
            {'atr': 2.0, 'MFI': 40.0, 'RSI': 55.0, 'macd_h': 0.20, 'ADX': 25.0},  # T-2
            {'atr': 2.0, 'MFI': 42.0, 'RSI': 55.0, 'macd_h': 0.10, 'ADX': 23.0},  # T-1
            {'atr': 2.0, 'MFI': 40.0, 'RSI': 55.0, 'macd_h': 0.05, 'ADX': 21.0},  # T
        ])
        # score=70, history=[55,65] → 55<65<70 → axis2=True
        grade, profit_pct, details = self.engine.check_trailing_stop(
            holding=holding, current_price=125.0, ind_df=ind,
            score=70.0, score_history=[55.0, 65.0]
        )
        self.assertEqual(grade, 3, f"축1+2+3 모두 충족 → grade=3 예상, 실제: {grade}")
        self.assertTrue(details['axis1'], "axis1(가격이탈)=True 이어야 합니다")
        self.assertTrue(details['axis2'], "axis2(점수+추세)=True 이어야 합니다")
        self.assertTrue(details['axis3'], "axis3(수급약화)=True 이어야 합니다")
        self.assertAlmostEqual(details['sell_ratio'], 1.0, places=1,
                               msg="grade=3 → 전량청산(100%)")
        self.assertAlmostEqual(details['atr_mult'], 2.5, places=1)
        print(f"✅ [트레일링-케이스3] grade={grade}, profit={profit_pct:.1f}%, "
              f"stop=${details['trail_stop_price']:.1f}, 매도={details['sell_ratio']*100:.0f}%")

    def test_case4_axis1_only_grade1_observe(self):
        """[트레일링-케이스4] profit +60%, 축1만 충족, 축2 미충족 → grade=1 (관찰)
        trailing_high=165, ATR=3.0, mult=3.0 → stop=156, current=155 < 156
        score=50 < 61 → axis2=False → grade=1"""
        holding = {**self.holding_base, 'avg_price': 100.0, 'trailing_high': 165.0}
        # mult=3.0 (50%+): stop = 165 - 3.0*3.0 = 156.0
        ind = make_atr_ind_df([
            {'atr': 3.0, 'MFI': 48.0, 'RSI': 45.0, 'macd_h': 0.1, 'ADX': 20.0},
            {'atr': 3.0, 'MFI': 48.0, 'RSI': 45.0, 'macd_h': 0.1, 'ADX': 20.0},
            {'atr': 3.0, 'MFI': 48.0, 'RSI': 45.0, 'macd_h': 0.1, 'ADX': 20.0},
        ])
        grade, profit_pct, details = self.engine.check_trailing_stop(
            holding=holding, current_price=155.0, ind_df=ind, score=50.0
        )
        self.assertEqual(grade, 1, f"axis1만 충족 → grade=1(관찰) 예상, 실제: {grade}")
        self.assertTrue(details['axis1'], "axis1(가격이탈)=True 이어야 합니다")
        self.assertFalse(details['axis2'], "score=50<61 → axis2=False 이어야 합니다")
        self.assertAlmostEqual(details['sell_ratio'], 0.0, places=1,
                               msg="grade=1 → 관찰만 (매도비율 0)")
        print(f"✅ [트레일링-케이스4] grade={grade}, profit={profit_pct:.1f}%, "
              f"axis2={details['axis2']}")


# ─────────────────────────────────────────────
# 3. 시간 기반 청산 (check_time_based_exit)
# ─────────────────────────────────────────────

class TestTimeBasedExit(unittest.TestCase):
    def setUp(self):
        self.engine = EntryExitEngine()

    def test_case1_30days_loss_no_signal(self):
        """[시간청산-케이스1] 보유 30일, 손실 -5% → T+60 미달로 None 반환"""
        holding = make_holding(avg_price=100.0, days_ago=30)
        result = self.engine.check_time_based_exit(holding, current_price=95.0)
        self.assertIsNone(result, "30일 손실은 T+60 기준 미달로 None이어야 합니다")
        print(f"✅ [시간청산-케이스1] result={result} (30일 손실, 신호 없음)")

    def test_case2_65days_loss_triggers_stagnation(self):
        """[시간청산-케이스2] 보유 65일, 손실 -5% → '손실 장기화' 신호 반환"""
        holding = make_holding(avg_price=100.0, days_ago=65)
        result = self.engine.check_time_based_exit(holding, current_price=95.0)
        self.assertIsNotNone(result, "65일 손실은 '손실 장기화' 신호가 나와야 합니다")
        self.assertEqual(result['reason'], '손실 장기화')
        self.assertGreater(result['elapsed_days'], 60)
        self.assertLess(result['profit_pct'], 0)
        print(f"✅ [시간청산-케이스2] reason='{result['reason']}', "
              f"elapsed={result['elapsed_days']}일, profit={result['profit_pct']:.2f}%")

    def test_case3_95days_small_profit_triggers_opportunity_cost(self):
        """[시간청산-케이스3] 보유 95일, 수익 +3% (5% 미만) → '기회비용' 신호 반환"""
        holding = make_holding(avg_price=100.0, days_ago=95)
        result = self.engine.check_time_based_exit(holding, current_price=103.0)
        self.assertIsNotNone(result, "95일 소수익은 '기회비용' 신호가 나와야 합니다")
        self.assertEqual(result['reason'], '기회비용')
        self.assertGreater(result['elapsed_days'], 90)
        self.assertGreater(result['profit_pct'], 0)
        self.assertLess(result['profit_pct'], 5.0)
        print(f"✅ [시간청산-케이스3] reason='{result['reason']}', "
              f"elapsed={result['elapsed_days']}일, profit={result['profit_pct']:.2f}%")

    def test_case4_95days_large_profit_no_signal(self):
        """[시간청산-케이스4] 보유 95일, 수익 +10% (5% 이상) → None 반환 (청산 불필요)"""
        holding = make_holding(avg_price=100.0, days_ago=95)
        result = self.engine.check_time_based_exit(holding, current_price=110.0)
        self.assertIsNone(result, "95일 +10% 수익은 청산 조건 미달로 None이어야 합니다")
        print(f"✅ [시간청산-케이스4] result={result} (95일 +10% 수익, 신호 없음)")


if __name__ == '__main__':
    unittest.main(verbosity=2)
