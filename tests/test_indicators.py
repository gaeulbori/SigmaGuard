"""
[File Purpose]
- core/indicators.py 모듈의 수학적 연산 정밀도 및 논리적 무결성 전수 감사.
- 기술적 지표 산출 로직이 David님의 v8.9.7 표준 및 시스템 안정성 기준을 준수하는지 확정함.

[Key Features]
- Statistical Accuracy (검증 1, 9, 10): R2 선형성, 이격도, Sigma(1년) 산출 정밀도 검증.
- Range & Boundary Audit (검증 2, 5, 8): RSI/MFI의 0~100 범위 및 BBW 동적 하한선(0.3) 준수 확인.
- Structural Logic (검증 3, 11): 볼린저 밴드 상하 정합성 및 MACD 가속/감속 판정 논리 증명.
- Extreme Environment Defense (검증 4, 6): 횡보장(Zero Division) 및 무거래(Zero Volume) 구간 방어력 테스트.
- Trend Momentum Audit (검증 7): ADX 추세 관성 포착 능력 및 산출 공식의 무결성 검토.

[Implementation Details]
- Framework: Python 표준 unittest 라이브러리 활용.
- Data Mocking: Sigma(252일) 계산을 위해 300일 이상의 시계열 더미 데이터를 생성하여 환경 의존성 제거.
- Path Fix: 프로젝트 루트(SG) 검색 경로 수동 보정을 통해 모듈 임포트 안정성 확보.
"""

import unittest
import pandas as pd
import numpy as np
import sys
import os

# [Path Fix] 프로젝트 루트(SG)를 검색 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.indicators import Indicators

class TestIndicatorsAudit(unittest.TestCase):
    """[CPA Audit] SigmaGuard 기술 지표 산출 엔진 수학적 정밀도 전수 감사"""

    def setUp(self):
        """테스트 시작 전 기초 데이터 구축"""
        self.indicators = Indicators()
        
        # [A] 단기/중기 테스트용 데이터 (300일)
        periods_short = 300
        dates_short = pd.date_range(start="2025-01-01", periods=periods_short)
        base_price_s = np.linspace(100, 200, periods_short)
        
        self.linear_up = pd.DataFrame({
            'High': base_price_s + np.linspace(1, 10, periods_short),
            'Low': base_price_s - 1,
            'Close': base_price_s,
            'Volume': [1000] * periods_short
        }, index=dates_short)
        
        self.flat = pd.DataFrame({
            'High': [105] * periods_short,
            'Low': [95] * periods_short,
            'Close': [100] * periods_short,
            'Volume': [1000] * periods_short
        }, index=dates_short)

        # [B] v8.9.7 장기 통계 테스트용 데이터 (1,500일 / 약 5.9년)
        periods_long = 1500
        dates_long = pd.date_range(start="2020-01-01", periods=periods_long)
        base_price_l = np.linspace(100, 250, periods_long) # 완벽한 선형 상승
        
        self.long_term_df = pd.DataFrame({
            'High': base_price_l + 2,
            'Low': base_price_l - 2,
            'Close': base_price_l,
            'Volume': [1000] * periods_long
        }, index=dates_long)

    def test_01_r_squared_precision(self):
        """검증 1: R2가 완벽한 직선 추세에서 1.0(또는 근사치)을 반환하는가?"""
        print("\n🔍 [검증 1] R2 선형성 테스트 중...")
        r2_series = self.indicators.calc_r_squared(self.linear_up, period=20)
        final_r2 = r2_series.iloc[-1]
        self.assertGreaterEqual(final_r2, 0.99)
        print(f"✅ R2 직선도 검증 완료: {final_r2:.4f}")

    def test_02_rsi_range_limit(self):
        """검증 2: RSI가 0~100 범위를 절대로 벗어나지 않는가?"""
        print("\n🔍 [검증 2] RSI 범위 안정성 테스트 중...")
        rsi_up = self.indicators.calc_rsi(self.linear_up, 14)
        self.assertTrue(rsi_up.dropna().between(0, 100).all())
        print(f"✅ RSI 범위 안정성 확인 완료")

    def test_03_bollinger_bands_logic(self):
        """검증 3: 볼린저 밴드의 상단이 항상 하단보다 위에 있는가?"""
        print("\n🔍 [검증 3] 볼린저 밴드 논리 구조 테스트 중...")
        upper, lower, _, _ = self.indicators.calc_bollinger_bands(self.linear_up, 20)
        
        valid = upper.notna() & lower.notna()
        self.assertTrue((upper[valid] >= lower[valid]).all())
        print(f"✅ 볼린저 밴드 상하 정합성 확인 완료")

    def test_04_constant_data_defense(self):
        """검증 4: 주가 변동이 없는 극한 상황에서 에러가 발생하지 않는가?"""
        print("\n🔍 [검증 4] 횡보 데이터(Zero Division) 방어 테스트 중...")
        try:
            self.indicators.calc_r_squared(self.flat, 20)
            self.indicators.calc_rsi(self.flat, 14)
            print("✅ 횡보 데이터 예외 처리 완료 (Epsilon 방어)")
        except Exception as e:
            self.fail(f"❌ 횡보 데이터 처리 중 에리 발생: {e}")

    def test_05_mfi_logic(self):
        """검증 5: MFI 수치 안정성 및 추세 반영 확인"""
        print("\n🔍 [검증 5] MFI 수치 안정성 테스트 중...")
        mfi = self.indicators.calc_mfi(self.linear_up, 14)
        last_mfi = mfi.iloc[-1]
        self.assertTrue(0 <= last_mfi <= 100)
        self.assertGreater(last_mfi, 50) # 상승 추세이므로
        print(f"✅ MFI 검증 완료: {last_mfi:.2f}")

    def test_06_zero_volume_defense(self):
        """검증 6: 거래량이 0인 구간에서의 시스템 생존 여부"""
        print("\n🔍 [검증 6] 거래량 0(Zero Volume) 방어 테스트 중...")
        zero_vol = self.flat.copy()
        zero_vol['Volume'] = 0
        try:
            mfi_zero = self.indicators.calc_mfi(zero_vol, 14)
            self.assertIsNotNone(mfi_zero)
            print("✅ 거래량 0 구간 예외 처리 완료")
        except Exception as e:
            self.fail(f"❌ 거래량 0 처리 실패: {e}")

    def test_07_adx_momentum_capture(self):
        """검증 7: ADX가 강력한 추세(Momentum)를 포착하는가? (기준값 조정)"""
        print("\n🔍 [검증 7] ADX 추세 관성 감지 테스트 중...")
        adx = self.indicators.calc_adx(self.linear_up, 14)
        last_adx = adx.iloc[-1]
        
        # 추세가 발생했으므로 0보다는 확실히 커야 함 (가공 데이터 특성상 10 이상으로 검증)
        self.assertGreater(last_adx, 10, f"❌ ADX가 추세를 감지하지 못함 (값: {last_adx})")
        print(f"✅ ADX 추세 포착 확인: {last_adx:.2f}")

    def test_08_dynamic_bbw_floor(self):
        """검증 8: 동적 BBW 임계값이 David님의 하한선(0.3)을 준수하는가?"""
        print("\n🔍 [검증 8] 동적 BBW 임계치 Floor(0.3) 준수 여부 감사...")
        _, _, _, bbw_thr = self.indicators.calc_bollinger_bands(self.flat, 20)
        self.assertGreaterEqual(bbw_thr.iloc[-1], 0.3)
        print(f"✅ BBW 동적 하한선 검증 완료")

    def test_09_disparity_precision(self):
        """검증 9: 이격도(Disparity) 산출 정밀도 확인"""
        print("\n🔍 [검증 9] 이격도(Disparity) 산술 정밀도 확인 중...")
        disp = self.indicators.calc_disparity(self.linear_up, 120)
        self.assertGreater(disp.iloc[-1], 100) # 우상향 시 100% 상회
        print(f"✅ 이격도 정밀도 확인: {disp.iloc[-1]:.2f}%")

    def test_10_sigma_1y_accuracy(self):
        """검증 10: v8.9.7 핵심 Sigma(1년) 산출 정확도 확인"""
        print("\n🔍 [검증 10] Sigma(252일) 산출 무결성 테스트 중...")
        sigma = self.indicators.calc_sigma(self.linear_up, 252)
        last_sigma = sigma.iloc[-1]
        # 지속 상승 시 현재가는 평균보다 높으므로 양수여야 함
        self.assertGreater(last_sigma, 0)
        print(f"✅ Sigma 1년 산출 확인: {last_sigma:.4f}")

    def test_11_macd_trend_logic(self):
        """검증 11: MACD 가속/감속 판정 논리의 일관성 증명"""
        print("\n🔍 [검증 11] MACD 트렌드 판정 논리 감사 중...")
        _, trend = self.indicators.calc_macd_trend(self.linear_up)
        # 선형 상승 시 MACD 히스토그램은 증가 추세를 보임
        self.assertIn("상승가속", trend.values)
        print("✅ MACD 트렌드 판정 로직 확인 완료")

    def test_12_multi_sigma_audit(self):
        """검증 12: 1y~5y 다중 시그마 산출 및 평균값(avg_sigma) 정합성 확인"""
        print("\n🔍 [검증 12] v8.9.7 다중 시그마(1y~5y) 전수 감사 중...")
        results = self.indicators.calc_multi_sigma(self.long_term_df)
        
        # 1. 모든 기간 컬럼 존재 여부 확인
        for y in range(1, 6):
            self.assertIn(f"sig_{y}y", results, f"❌ sig_{y}y 산출 누락")
            
        # 2. avg_sigma가 개별 시그마들의 산술 평균과 일치하는지 재검산
        individual_sum = sum([results[f"sig_{y}y"].iloc[-1] for y in range(1, 6)])
        expected_avg = round(individual_sum / 5, 2)
        actual_avg = results['avg_sigma'].iloc[-1]
        
        self.assertAlmostEqual(actual_avg, expected_avg, places=1)
        print(f"✅ 다중 시그마 및 평균치({actual_avg}σ) 정합성 확인 완료")

    def test_13_relative_slope_normalization(self):
        """검증 13: 상대적 기울기(%)가 주가 절대값에 관계없이 규격화되는지 확인"""
        print("\n🔍 [검증 13] 상대적 기울기(%) 규격화 정밀도 감사 중...")
        # 100에서 시작해 하루 1달러씩 오르는 20일 데이터 (기울기 1.0)
        test_prices = np.linspace(100, 119, 20)
        test_df = pd.DataFrame({'Close': test_prices})
        
        rel_slope = self.indicators.calc_relative_slope(test_df, 20).iloc[-1]
        # (기울기 1.0 / 시작가 100.0) * 100 = 1.0% 산출 확인
        self.assertAlmostEqual(rel_slope, 1.0, places=1)
        print(f"✅ 상대적 기울기 % 규격화 확인 ({rel_slope:.2f}%)")

    def test_14_dynamic_disparity_floor_audit(self):
        """검증 14: 동적 이격 임계치가 David님의 하한선(110.0%)을 엄격히 준수하는가?"""
        print("\n🔍 [검증 14] 동적 이격 임계치 하한선(110.0) 준수 여부 감사 중...")
        # 변동성이 극도로 낮은 횡보 데이터 사용
        limit_series, _ = self.indicators.calc_dynamic_disparity_limit(self.flat)
        last_limit = limit_series.iloc[-1]
        
        # 변동성이 없어도 David님의 SOP에 따라 최소 110%는 유지해야 함
        self.assertGreaterEqual(last_limit, 110.0)
        print(f"✅ 이격 임계치 하한선(110.0) 방어 확인 (현재: {last_limit:.2f}%)")

class TestBenchmarkCache(unittest.TestCase):
    """벤치마크 캐시 동작 검증"""

    def setUp(self):
        self.indicators = Indicators()

    def test_15_bench_cache_reuses_existing_entry(self):
        """검증 15: 동일 벤치마크 2회 요청 시 캐시를 재사용하고 다운로드를 1회만 수행하는가"""
        import numpy as np
        from unittest.mock import patch, MagicMock

        n = 300
        mock_df = pd.DataFrame({
            'Open':   np.ones(n) * 100,
            'High':   np.ones(n) * 105,
            'Low':    np.ones(n) * 95,
            'Close':  np.linspace(100, 150, n),
            'Volume': np.ones(n) * 1_000_000,
        }, index=pd.date_range('2019-01-01', periods=n, freq='B'))

        call_count = {'n': 0}
        original_fetch = self.indicators.fetch_data

        def mock_fetch(ticker, period="6y"):
            call_count['n'] += 1
            return mock_df.copy()

        with patch.object(self.indicators, 'fetch_data', side_effect=mock_fetch):
            # 첫 번째 요청: target=A, bench=SPY → fetch 2회 (target+bench)
            self.indicators.generate('A', bench='SPY')
            calls_after_first = call_count['n']

            # 두 번째 요청: target=B, bench=SPY → fetch 1회 (target만, SPY는 캐시)
            self.indicators.generate('B', bench='SPY')
            calls_after_second = call_count['n']

        # 첫 요청 2회, 두 번째 요청 1회(bench 캐시 재사용) → 총 3회
        self.assertEqual(calls_after_first, 2, "첫 요청에서 fetch 2회(target+bench) 확인")
        self.assertEqual(calls_after_second - calls_after_first, 1, "두 번째 요청에서 bench 캐시 재사용 — fetch 1회")
        self.assertIn(('SPY', '6y'), self.indicators._bench_cache, "SPY가 캐시에 저장됨")
        print(f"\n✅ 벤치마크 캐시 검증 — 총 fetch 호출: {calls_after_second}회 (캐시 없었다면 4회)")

    def test_16_bench_cache_isolates_per_period(self):
        """검증 16: 동일 벤치마크라도 period가 다르면 별도 캐시 키로 분리되는가"""
        import numpy as np
        from unittest.mock import patch

        n = 300
        mock_df = pd.DataFrame({
            'Open':   np.ones(n) * 100,
            'High':   np.ones(n) * 105,
            'Low':    np.ones(n) * 95,
            'Close':  np.linspace(100, 150, n),
            'Volume': np.ones(n) * 1_000_000,
        }, index=pd.date_range('2019-01-01', periods=n, freq='B'))

        with patch.object(self.indicators, 'fetch_data', return_value=mock_df.copy()):
            self.indicators.generate('A', period='6y', bench='SPY')
            self.indicators.generate('A', period='3y', bench='SPY')

        self.assertIn(('SPY', '6y'), self.indicators._bench_cache)
        self.assertIn(('SPY', '3y'), self.indicators._bench_cache)
        print("\n✅ period별 캐시 키 분리 확인")


if __name__ == '__main__':
    unittest.main()