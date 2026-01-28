"""
[File Purpose]
- core/risk_engine.py의 리스크 산출 로직 및 SOP 등급 판정 정밀 검증.
- v8.9.7의 핵심 로직(30:50:20 배점 및 동적 가중치)이 시나리오별로 정확히 작동하는지 감사함.

[Key Features]
- Normal Scenario: 안정적인 시장 지표 투입 시 LEVEL 1~2를 반환하는지 확인.
- Overheat (Bubble): 고시그마, 고RSI, BBW 확장 시 LEVEL 5(DANGER)를 정확히 포착하는지 검증.
- Crash (Panic): 하락 관성이 강하고 변동성이 터질 때 할증 가중치가 적용되는지 확인.
- Bottom Fishing: 하락장 중 시그마가 낮고 수급(MFI)이 유입될 때 할인 로직이 작동하는지 검증.

[Implementation Details]
- Mock Data: Indicators 모듈의 계산 결과와 동일한 규격의 DataFrame을 생성하여 투입.
- Edge Case: 데이터가 부족하거나 에러 발생 시 시스템이 안정적인 기본값(50점)을 내놓는지 확인.
"""

import unittest
import pandas as pd
import sys
import os

# [Path Fix] 프로젝트 루트(SG)를 검색 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.risk_engine import RiskEngine

class TestRiskEngineAudit(unittest.TestCase):
    """[CPA Audit] 리스크 엔진 의사결정 알고리즘 정밀 감사"""

    def setUp(self):
        """테스트용 리스크 엔진 객체 초기화"""
        self.engine = RiskEngine()

    def test_01_normal_stable_market(self):
        """검증 1: 평온한 시장에서 LEVEL 1(정상)을 유지하는가?"""
        print("\n🔍 [검증 1] 정상 시장(Stable) 시나리오 테스트 중...")
        data = {
            'avg_sigma': 0.2, 'rsi': 45.0, 'mfi': 50.0, 'bbw': 0.15, 'bbw_thr': 0.3,
            'm_trend': "상승가속", 'ma_slope': "Rising", 'disp120': 102.0, 'disp120_limit': 115.0,
            'slope': 0.01, 'r2': 0.8, 'adx': 25.0
        }
        df = pd.DataFrame([data])
        score, grade, _ = self.engine.evaluate(df)
        
        self.assertLess(score, 40, f"❌ 정상 시장인데 점수가 너무 높습니다: {score}")
        self.assertIn("LEVEL 1", grade)
        print(f"✅ 정상 시장 검증 완료: {score}점 ({grade})")

    def test_02_danger_bubble_market(self):
        """검증 2: 극심한 과열(Bubble) 시 LEVEL 5(DANGER)를 뱉어내는가?"""
        print("\n🔍 [검증 2] 과열 시장(Bubble) 시나리오 테스트 중...")
        data = {
            'avg_sigma': 2.8, 'rsi': 85.0, 'mfi': 82.0, 'bbw': 0.45, 'bbw_thr': 0.3,
            'm_trend': "상승감속", 'ma_slope': "Rising", 'disp120': 125.0, 'disp120_limit': 115.0,
            'slope': 0.05, 'r2': 0.4, 'adx': 45.0
        }
        df = pd.DataFrame([data])
        score, grade, _ = self.engine.evaluate(df)
        
        self.assertGreaterEqual(score, 81, f"❌ 과열 구간 포착 실패: {score}")
        self.assertIn("LEVEL 5", grade)
        print(f"✅ 과열 시장(DANGER) 포착 완료: {score}점 ({grade})")

    def test_03_bear_panic_surcharge(self):
        """검증 3: 하락장에서의 리스크 할증 로직이 작동하는가?"""
        print("\n🔍 [검증 3] 하락 패닉(Panic) 시나리오 테스트 중...")
        # 하락이 직선적이고(R2고) 관성이 강함(ADX고)
        data = {
            'avg_sigma': 1.0, 'rsi': 30.0, 'mfi': 25.0, 'bbw': 0.4, 'bbw_thr': 0.2,
            'm_trend': "하락가속", 'ma_slope': "Falling", 'disp120': 95.0, 'disp120_limit': 115.0,
            'slope': -0.05, 'r2': 0.85, 'adx': 40.0
        }
        df = pd.DataFrame([data])
        score, grade, details = self.engine.evaluate(df)
        
        self.assertGreater(details['multiplier'], 1.0, "❌ 하락장 할증 가중치가 적용되지 않았습니다.")
        print(f"✅ 하락 할증 검증 완료: 가중치 x{details['multiplier']}")

    def test_04_bottom_fishing_discount(self):
        """검증 4: 바닥권 수급 유입 시 할인 로직(David's Bottom Fishing)이 작동하는가?"""
        print("\n🔍 [검증 4] 바닥 다지기(Bottom Fishing) 시나리오 테스트 중...")
        # 하락 중이지만 시그마가 매우 낮고 MFI가 RSI보다 높음 (수급 유입)
        data = {
            'avg_sigma': -2.2, 'rsi': 20.0, 'mfi': 35.0, 'bbw': 0.1, 'bbw_thr': 0.3,
            'm_trend': "하락진정", 'ma_slope': "Falling", 'disp120': 85.0, 'disp120_limit': 115.0,
            'slope': -0.01, 'r2': 0.3, 'adx': 15.0
        }
        df = pd.DataFrame([data])
        score, grade, details = self.engine.evaluate(df)
        
        # 실제 v8.9.7 로직상 하락장 할인이 구현되어야 함
        self.assertLess(details['multiplier'], 1.0, f"❌ 바닥 낚시 할인 미적용: x{details['multiplier']}")
        print(f"✅ 바닥 낚시 할인 검증 완료: 가중치 x{details['multiplier']}")

    def test_05_sop_boundary_check(self):
        """검증 5: SOP 등급 경계값(81.0) 판정 정밀도 확인"""
        print("\n🔍 [검증 5] SOP 등급 경계값(81.0) 판정 테스트 중...")
        # [데이터 보정] 기초 점수가 81점이 나오도록 지표 상향
        data = {
            'avg_sigma': 2.5,     # s_p1 = 30.0
            'rsi': 85.0, 'mfi': 80.0, # s_mfi = 8.0
            'bbw': 0.4, 'bbw_thr': 0.3, # s_bbw = 12.0
            'm_trend': "하락가속",  # s_macd = 10.0 -> s_p2 = (30/40)*50 = 37.5
            'ma_slope': "Rising",
            'disp120': 111.75,    # s_p4 = 13.5 (110%~115% 사이 정밀 계산)
            'disp120_limit': 115.0,
            'slope': 0.0, 'r2': 0.0, 'adx': 0.0  # 가중치 1.0 유도
        }
        # 합계: 30.0 + 37.5 + 13.5 = 81.0
        df = pd.DataFrame([data])
        score, grade, _ = self.engine.evaluate(df)
        
        self.assertGreaterEqual(score, 81.0, f"❌ 점수가 81점에 미달함: {score}")
        self.assertIn("DANGER", grade, f"❌ 81.0점인데 DANGER 등급이 아닙니다: {grade}")
        print(f"✅ 경계값 판정 확인 완료: {score}점 -> {grade}")

    def test_06_confidence_brake_at_high_risk(self):
        """검증 6: 고리스크 구간에서 품질 할인(Brake)이 작동하는가?"""
        print("\n🔍 [검증 6] 고리스크 구간 할인 제동(Brake) 테스트 중...")
        # [데이터 보정] 기초 점수를 85점 이상으로 설정
        data = {
            'avg_sigma': 2.5,     # 30.0
            'rsi': 90.0, 'mfi': 85.0, # s_p2를 풀 가동하여 50.0점 만점 유도
            'bbw': 0.5, 'bbw_thr': 0.2, 
            'm_trend': "상승감속", 
            'ma_slope': "Rising",
            'disp120': 115.0,     # s_p4 = 20.0 (풀 점수)
            'disp120_limit': 115.0,
            'slope': 0.05, 'r2': 1.0, 'adx': 40.0 # [중요] 품질은 최고지만 할인은 없어야 함
        }
        # 기초 점수: 30 + 50 + 20 = 100.0 (80점 초과)
        df = pd.DataFrame([data])
        score, grade, details = self.engine.evaluate(df)
        
        # 80점을 넘었으므로 Multiplier는 1.0이어야 함 (할인 제동)
        self.assertEqual(details['multiplier'], 1.0, f"❌ 과열 구간에서 부당 할인이 발생했습니다: x{details['multiplier']}")
        print(f"✅ 할인 제동 장치 확인 완료: 가중치 x{details['multiplier']} (과열 시 할인 박탈)")

    def test_07_invalid_data_handling(self):
        """검증 7: 비정상 데이터(Empty) 투입 시 방어 로직 확인"""
        print("\n🔍 [검증 7] 비정상 데이터 방어 테스트 중...")
        score, grade, _ = self.engine.evaluate(pd.DataFrame())
        self.assertEqual(grade, "NODATA", "❌ 빈 데이터 투입 시 NODATA 처리가 되지 않았습니다.")
        print("✅ 비정상 데이터 방어 확인 완료")

if __name__ == '__main__':
    unittest.main()