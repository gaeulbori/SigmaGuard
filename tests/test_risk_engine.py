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
        
        # 기본값 설정
        default_inds = {
            'avg_sigma': 0.0, 'rsi': 50.0, 'mfi': 55.0, 
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
            'avg_sigma': 0.2, 'rsi': 45.0, 'mfi': 50.0, 
            'slope': 0.01, 'R2': 0.8, 'ADX': 25.0
        }
        df = self.create_scenario_df([100]*5, inds)
        score, grade, _ = self.engine.evaluate(df)
        
        self.assertLess(score, 46, f"❌ 정상 시장인데 점수가 너무 높습니다: {score}")
        self.assertIn("LEVEL", grade)
        print(f"✅ 정상 시장 검증 완료: {score}점 ({grade})")

    def test_02_danger_bubble_market(self):
        """검증 2: 극심한 과열(Bubble) 시 LEVEL 5(DANGER)를 포착하는가?"""
        print("\n🔍 [검증 2] 과열 시장(Bubble) 시나리오 테스트 중...")
        inds = {
            'avg_sigma': 2.8, 'rsi': 85.0, 'mfi': 82.0, 'bbw': 0.45, 'bbw_thr': 0.3,
            'm_trend': "상승감속", 'disp120': 125.0, 'disp120_limit': 115.0,
            'slope': 0.05, 'R2': 0.4, 'ADX': 45.0
        }
        df = self.create_scenario_df([100]*5, inds)
        score, grade, _ = self.engine.evaluate(df)
        
        self.assertGreaterEqual(score, 81, f"❌ 과열 구간 포착 실패: {score}")
        self.assertIn("LEVEL 5", grade)
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

    def test_04_bottom_fishing_discount(self):
        """검증 4: 바닥 다지기(Bottom Fishing) 시 50% 할인 특약이 작동하는가?"""
        print("\n🔍 [검증 4] 바닥 다지기 시나리오 테스트 중...")
        inds = {
            'avg_sigma': -2.2, 'slope': -0.01, # 과매도 상태의 하락장
            'mfi': 60.0, 'rsi': 40.0           # 수급 유입 (MFI > RSI)
        }
        df = self.create_scenario_df([100]*5, inds)
        _, _, details = self.engine.evaluate(df)
        
        self.assertEqual(details['multiplier'], 0.5)
        self.assertEqual(details['scenario'], "BOTTOM_FISHING")
        print(f"✅ 바닥 낚시 할인 검증 완료: 가중치 x{details['multiplier']}")

    def test_05_livermore_3day_confirm(self):
        """검증 5: 리버모어 3일 연속 상승 시 확증 할인(30%)이 적용되는가?"""
        print("\n🔍 [검증 5] 리버모어 3일 확증 할인 테스트 중...")
        # 3일 연속 종가 상승 데이터 생성
        prices = [100, 102, 104, 106, 108] 
        inds = {'slope': 0.02, 'R2': 0.95}
        df = self.create_scenario_df(prices, inds)
        
        score, _, details = self.engine.evaluate(df)
        self.assertIn("LIV 할인", details['scenario'])
        self.assertIn("3일 연속", details['liv_status'])
        print(f"✅ 리버모어 확증 할인 확인: {details['liv_status']}")

    def test_06_position_sizing_safety_cap(self):
        """검증 6: 포지션 사이징이 0.8% 리스크 한도를 준수하며 20% 캡(Cap)을 지키는가?"""
        print("\n🔍 [검증 6] 자본 할당 및 20% 비중 제한 테스트 중...")
        # 손절선이 매우 가까워 비중이 크게 산출되는 상황 유도
        # Price: 100, Stop: 99.5 -> Risk_dist: 0.5%
        # Weight = 0.8% / 0.5% = 160% -> 20%로 캡핑되어야 함
        inds = {'disp120': 100.1} 
        df = self.create_scenario_df([100]*252, inds) # 1년치 평균 계산용
        
        _, _, details = self.engine.evaluate(df)
        self.assertLessEqual(details['weight_pct'], 20.0)
        self.assertGreater(details['ei'], 0)
        print(f"✅ 포지션 사이징 20% 캡 및 가성비(E.I: {details['ei']}) 확인")

    def test_07_confidence_brake_at_high_risk(self):
        """검증 7: 과열 구간(Raw 80점 초과)에서 품질 할인을 중단(Brake)하는가?"""
        print("\n🔍 [검증 7] 고리스크 구간 할인 제동(Brake) 테스트 중...")
        # 기초 점수가 80점을 넘도록 지표 설정
        inds = {
            'avg_sigma': 2.5,  # p1: 30.0
            'm_trend': "감속", 'bbw': 0.5, 'bbw_thr': 0.2, # p2: 풀 점수 유도
            'disp120': 115.0, 'disp120_limit': 115.0,       # p4: 20.0
            'slope': 0.05, 'R2': 1.0, 'ADX': 40.0           # 품질은 최상이지만 할인은 없어야 함
        }
        df = self.create_scenario_df([100]*5, inds)
        score, _, details = self.engine.evaluate(df)
        
        # base_raw >= 80일 때 Multiplier는 1.0이어야 함 (할인 제동)
        self.assertEqual(details['multiplier'], 1.0)
        print(f"✅ 할인 제동 장치 확인 완료: 가중치 x{details['multiplier']}")

    def test_08_invalid_data_handling(self):
        """검증 8: 비정상 데이터 투입 시 시스템 방어 로직 확인"""
        print("\n🔍 [검증 8] 비정상 데이터(Empty) 방어 테스트 중...")
        score, grade, _ = self.engine.evaluate(pd.DataFrame())
        self.assertEqual(grade, "NODATA")
        print("✅ 비정상 데이터 방어 확인 완료")

if __name__ == '__main__':
    unittest.main()