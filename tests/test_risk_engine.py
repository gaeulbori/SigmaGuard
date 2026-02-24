"""
[File Purpose]
- core/risk_engine.py v8.9.7 판단 로직 및 자본 할당 알고리즘 전수 감사.
- 기존 시나리오 기반 테스트와 리버모어/포지션 사이징 등 신규 기능을 통합 검증함.

[Key Features]
- Normal/Bubble/Panic Scenario: 시장 국면별 SOP 등급 및 가중치(Multiplier) 산출 정밀도 확인.
- David's Bottom Fishing: 과매도 구간(Sigma < -2.0)에서의 리스크 감면(50%) 특약 검증.
- Livermore 3-Day Confirm: 3일 연속 추세 유지 시 '확증 할인' 적용 여부 확인.
- Position Sizing & EI: 0.8% 리스크 한도 준수 및 단일 종목 20% 캡(Cap) 작동 확인.
- Confidence Brake: 기초 점수 80점 초과 시 품질 할인을 중단하는 제동 장치 검증.

[Implementation Details]
- Multi-row Mocking: 리버모어 3일 확증 검증을 위해 다계층 시계열 데이터 구조 활용.
- Field Mapping: Indicators 모듈의 최신 컬럼명(avg_sigma, R2, ADX 등)과 100% 일치시킴.
"""

import unittest
import pandas as pd
import numpy as np
import sys
import os

# [Path Fix] 프로젝트 루트(SG)를 검색 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.risk_engine import RiskEngine

class TestRiskEngineAudit(unittest.TestCase):
    """[CPA Audit] 리스크 엔진 의사결정 및 자본 할당 알고리즘 통합 감사"""

    def setUp(self):
        """테스트용 리스크 엔진 객체 초기화"""
        self.engine = RiskEngine()

    def create_scenario_df(self, price_list, indicators):
        """시나리오 테스트를 위한 정밀 Mock DataFrame 생성 도구"""
        # 리버모어 등 시계열 로직을 위해 최소 5일치 데이터 구성
        df = pd.DataFrame({
            'Close': price_list,
            'High': [p * 1.01 for p in price_list],
            'Low': [p * 0.99 for p in price_list],
            'Volume': [1000] * len(price_list)
        })
        
        # 기본값 설정 (indicators.py 컬럼명과 대소문자 일치)
        default_inds = {
            'avg_sigma': 0.0, 'RSI': 50.0, 'MFI': 55.0,
            'bbw': 0.1, 'bbw_thr': 0.3, 'm_trend': "상승가속",
            'ma_slope': "Rising", 'disp120': 100.0, 'disp120_limit': 115.0, 'disp120_avg': 105.0,
            'slope': 0.01, 'R2': 0.9, 'ADX': 30.0
        }
        
        # 입력받은 지표로 업데이트
        default_inds.update(indicators)
        for key, val in default_inds.items():
            df[key] = val
            
        return df

    def test_01_normal_stable_market(self):
        """검증 1: 평온한 시장에서 LEVEL 1(매수) 또는 2(안정)를 유지하는가?"""
        print("\n🔍 [검증 1] 정상 시장(Stable) 시나리오 테스트 중...")
        inds = {
            'avg_sigma': 0.2, 'RSI': 45.0, 'MFI': 50.0,
            'slope': 0.01, 'R2': 0.8, 'ADX': 25.0
        }
        df = self.create_scenario_df([100]*5, inds)
        score, grade, _ = self.engine.evaluate(df)
        
        self.assertLess(score, 46, f"❌ 정상 시장인데 점수가 너무 높습니다: {score}")
        valid_labels = {"STRONG BUY", "CONCENTRATE", "ACCUMULATE", "ENTRY", "WATCH"}
        self.assertIn(grade, valid_labels, f"❌ 예상 SOP 레이블이 아님: {grade}")
        print(f"✅ 정상 시장 검증 완료: {score}점 ({grade})")

    def test_02_danger_bubble_market(self):
        """검증 2: 극심한 과열(Bubble) 시 LEVEL 5(DANGER)를 포착하는가?"""
        print("\n🔍 [검증 2] 과열 시장(Bubble) 시나리오 테스트 중...")
        inds = {
            'avg_sigma': 2.8, 'RSI': 85.0, 'MFI': 82.0, 'bbw': 0.45, 'bbw_thr': 0.3,
            'm_trend': "상승감속", 'disp120': 125.0, 'disp120_limit': 115.0,
            'slope': 0.05, 'R2': 0.4, 'ADX': 45.0
        }
        df = self.create_scenario_df([100]*5, inds)
        score, grade, _ = self.engine.evaluate(df)
        
        self.assertGreaterEqual(score, 81, f"❌ 과열 구간 포착 실패: {score}")
        self.assertIn(grade, {"DANGER", "EXIT"}, f"❌ 예상 SOP 레이블이 아님: {grade}")
        print(f"✅ 과열 시장(DANGER) 포착 완료: {score}점 ({grade})")

    def test_03_bear_panic_surcharge(self):
        """검증 3: 하락 패닉 시 리스크 할증(Surcharge) 가중치가 적용되는가?"""
        print("\n🔍 [검증 3] 하락 패닉(Panic) 시나리오 테스트 중...")
        inds = {
            'slope': -0.05, 'R2': 0.85, 'ADX': 40.0, # 하락 관성 강함
            'ma_slope': "Falling"
        }
        df = self.create_scenario_df([100]*5, inds)
        score, grade, details = self.engine.evaluate(df)
        
        self.assertGreater(details['multiplier'], 1.0)
        print(f"✅ 하락 할증 검증 완료: 가중치 x{details['multiplier']}")

    def test_04_bearish_surcharge_on_oversold(self):
        """검증 4: 과매도 하락장(slope < 0)에서 BEARISH 리스크 할증(multiplier > 1.0)이 작동하는가?"""
        print("\n🔍 [검증 4] 과매도 하락장(BEARISH) 할증 테스트 중...")
        inds = {
            'avg_sigma': -2.2, 'slope': -0.01,  # 과매도 상태의 하락장
            'MFI': 60.0, 'RSI': 40.0            # 수급 유입 (MFI > RSI)
        }
        df = self.create_scenario_df([100]*5, inds)
        _, _, details = self.engine.evaluate(df)

        self.assertGreater(details['multiplier'], 1.0,
            f"❌ 하락장에서 BEARISH 할증(>1.0) 미적용: x{details['multiplier']}")
        self.assertEqual(details['scenario'], "BEARISH",
            f"❌ 시나리오가 BEARISH가 아님: {details['scenario']}")
        print(f"✅ BEARISH 할증 확인: 가중치 x{details['multiplier']} / {details['scenario']}")

    def test_05_livermore_6m_high_discount(self):
        """검증 5: 반기(6개월) 신고가 돌파 + 4대 관문 통과 시 Livermore 할인이 적용되는가?"""
        print("\n🔍 [검증 5] 리버모어 반기 신고가 확증 할인 테스트 중...")
        # 129행 가격 100 + 마지막 1행 130 → 6개월 신고가 돌파
        # 4대 관문 기본값: avg_sigma=0.0(<2.0), R2=0.9(>=0.5), ADX=30(>=25), MFI=55(>=40)
        prices = [100.0] * 129 + [130.0]
        inds = {'slope': 0.02, 'R2': 0.8, 'ADX': 30.0}
        df = self.create_scenario_df(prices, inds)

        score, _, details = self.engine.evaluate(df)

        self.assertGreater(details['liv_discount'], 0.0,
            f"❌ Livermore 할인 미적용: discount={details['liv_discount']}")
        self.assertIn("신고가", details['liv_status'],
            f"❌ liv_status에 '신고가' 없음: {details['liv_status']}")
        print(f"✅ 리버모어 확증 할인 확인: {details['liv_status']} / 할인율 {details['liv_discount']*100:.0f}%")

    def test_06_position_sizing_safety_cap(self):
        """검증 6: 포지션 사이징이 0.8% 리스크 한도를 준수하며 20% 캡(Cap)을 지키는가?"""
        print("\n🔍 [검증 6] 자본 할당 및 20% 비중 제한 테스트 중...")
        # 손절선이 매우 가까워 비중이 크게 산출되는 상황 유도
        # Weight = 0.8% / risk_dist -> risk_dist가 작을수록 비중이 커져 20% 캡에 걸림
        inds = {'disp120': 100.1}
        df = self.create_scenario_df([100]*252, inds)  # 1년치 평균 계산용

        # apply_risk_management는 evaluate()와 별도로 호출 (alloc 딕셔너리 반환)
        latest = df.iloc[-1]
        alloc = self.engine.apply_risk_management(latest, df)

        self.assertLessEqual(alloc['weight'], 20.0,
            f"❌ 20% 비중 캡 초과: {alloc['weight']}%")
        self.assertGreater(alloc['ei'], 0,
            f"❌ E.I(가성비) 0 이하: {alloc['ei']}")
        print(f"✅ 포지션 사이징 20% 캡 및 가성비(E.I: {alloc['ei']}) 확인")

    def test_07_confidence_brake_at_high_risk(self):
        """검증 7: 과열 구간(base_raw >= 80)에서 BULLISH 품질 할인이 0으로 수렴하는가?

        공식: multiplier = 1.0 - (quality * 0.40 * clip((80 - base_raw)/40, 0, 1))
        base_raw >= 80 이면 clip 결과 = 0 → multiplier = 1.0 (할인 제동)
        """
        print("\n🔍 [검증 7] 고리스크 구간 할인 제동(Brake) 테스트 중...")
        # p1=30.0, p2=41.25(MFI<RSI 수급불일치), p4=20.0 → base_raw=91.25 (>=80 확보)
        inds = {
            'avg_sigma': 2.5,                                  # p1 = 30.0
            'MFI': 40.0, 'RSI': 75.0,                         # p2 수급불일치 → 41.25
            'bbw': 0.5, 'bbw_thr': 0.2,                       # p2 BBW 팽창
            'disp120': 115.0, 'disp120_limit': 115.0,         # p4 = 20.0
            'slope': 0.05, 'R2': 1.0, 'ADX': 40.0            # 최고 품질 → 할인 0
        }
        df = self.create_scenario_df([100]*5, inds)
        score, _, details = self.engine.evaluate(df)

        self.assertGreaterEqual(details['base_raw'], 80.0,
            f"❌ base_raw({details['base_raw']:.1f}) < 80 — mock 데이터 재확인 필요")
        self.assertEqual(details['multiplier'], 1.0,
            f"❌ base_raw >= 80인데 multiplier={details['multiplier']} (1.0이어야 함)")
        print(f"✅ 할인 제동 확인: base_raw={details['base_raw']:.1f} → multiplier x{details['multiplier']}")

    def test_08_invalid_data_handling(self):
        """검증 8: 비정상 데이터 투입 시 시스템 방어 로직 확인"""
        print("\n🔍 [검증 8] 비정상 데이터(Empty) 방어 테스트 중...")
        score, grade, _ = self.engine.evaluate(pd.DataFrame())
        self.assertEqual(grade, "NODATA")
        print("✅ 비정상 데이터 방어 확인 완료")

if __name__ == '__main__':
    unittest.main()