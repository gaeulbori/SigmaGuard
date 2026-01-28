"""
[File Purpose]
- core/indicators.py 모듈의 수학적 연산 정밀도 및 논리적 무결성 검증.
- 기술적 지표 산출 로직이 금융 통계 표준 및 시스템 안정성 기준을 준수하는지 감사함.

[Key Features]
- Linear Trend Validation (검증 1): R2 산출 시 완벽한 직선 데이터에서 1.0 반환 확인.
- Range Stability Audit (검증 2, 5): RSI, MFI 등 백분율 지표의 0~100 범위 유지 확인.
- Logic Consistency Check (검증 3): 볼린저 밴드 상단이 하단보다 항상 위에 있음을 증명.
- Edge Case Defense (검증 4, 6, 8): 횡보장(Zero Division) 및 거래량 0 구간 방어력 테스트.
- Momentum & Energy Audit (검증 7, 9): ADX 추세 관성 및 이격도 산출 정밀도 검증.

[Implementation Details]
- Framework: Python 표준 unittest 라이브러리 활용.
- Data Mocking: Numpy를 이용해 선형 상승 및 횡보용 더미 데이터를 생성하여 환경 의존성 제거.
"""

import unittest
import pandas as pd
import numpy as np
import sys
import os

# [Path Fix] 프로젝트 루트(SG)를 검색 경로에 추가하여 모듈 간 연결 확보
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# [수정] 신규 추가된 함수들(calc_adx, calc_disparity) 임포트 포함
from core.indicators import (
    calc_rsi, calc_mfi, calc_bollinger_bands, 
    calc_r_squared, calc_adx, calc_disparity
)

class TestIndicatorsAudit(unittest.TestCase):
    """[CPA Audit] 기술 지표 산출 엔진 수학적 정밀도 검증"""

    def setUp(self):
        """테스트용 기초 데이터(더미 데이터) 생성"""
        # [수정] 고가가 저가보다 더 빠르게 상승하도록 설정하여 추세(DM) 유도
        self.linear_up = pd.DataFrame({
            'High': np.linspace(105, 215, 100), # 고가 상승폭 확대
            'Low': np.linspace(95, 195, 100),
            'Close': np.linspace(100, 200, 100),
            'Volume': [1000] * 100
        })
        
        # 횡보 데이터 (RSI/MFI 50 근처 확인용)
        self.flat = pd.DataFrame({
            'High': [105]*120, 'Low': [95]*120, 'Close': [100]*120, 'Volume': [1000]*120
        })
    def test_r_squared_precision(self):
        """검증 1: R-Squared(R2)가 완벽한 직선 추세에서 1.0을 반환하는가?"""
        print("\n🔍 [검증 1] R2 선형성 테스트 중...")
        r2_series = calc_r_squared(self.linear_up, period=20)
        final_r2 = r2_series.iloc[-1]
        self.assertGreaterEqual(final_r2, 0.99)
        print(f"✅ R2 직선도 검증 완료: {final_r2:.4f}")

    def test_rsi_range_limit(self):
        """검증 2: RSI가 0~100 범위를 절대로 벗어나지 않는가?"""
        print("\n🔍 [검증 2] RSI 범위 안정성 테스트 중...")
        rsi_up = calc_rsi(self.linear_up)
        self.assertTrue(rsi_up.dropna().between(0, 100).all())
        print(f"✅ RSI 범위 안정성 확인 완료")

    def test_bollinger_bands_logic(self):
        """검증 3: 볼린저 밴드의 상단이 항상 하단보다 위에 있는가?"""
        print("\n🔍 [검증 3] 볼린저 밴드 논리 구조 테스트 중...")
        # [수정] v8.9.7 로직에 맞춰 반환값 4개를 언패킹(Unpack)함
        upper, lower, bbw, bbw_thr = calc_bollinger_bands(self.linear_up)
        
        valid_indices = upper.notna() & lower.notna()
        actual_upper = upper[valid_indices]
        actual_lower = lower[valid_indices]
        
        logic_check = (actual_upper >= actual_lower).all()
        min_diff = (actual_upper - actual_lower).min()
        self.assertTrue(logic_check)
        print(f"✅ 볼린저 밴드 논리 구조 확인 완료 (최소 밴드폭: {min_diff:.4f})")

    def test_constant_data_handling(self):
        """검증 4: 주가 변동이 없을 때(Zero Division) 에러가 발생하지 않는가?"""
        print("\n🔍 [검증 4] 횡보 데이터(Zero Division) 방어 테스트 중...")
        try:
            r2_flat = calc_r_squared(self.flat)
            rsi_flat = calc_rsi(self.flat)
            self.assertIsNotNone(r2_flat)
            print("✅ 횡보 데이터 예외 처리 완료 (분모 0 방어)")
        except ZeroDivisionError:
            self.fail("❌ ZeroDivisionError 발생")

    def test_mfi_logic(self):
        """검증 5: MFI 수치 안정성 및 추세 반영 확인"""
        print("\n🔍 [검증 5] MFI 수치 안정성 및 추세 반영 테스트 중...")
        mfi = calc_mfi(self.linear_up, period=14)
        valid_mfi = mfi.dropna()
        self.assertTrue(valid_mfi.between(0, 100).all())
        self.assertGreater(valid_mfi.iloc[-1], 50)
        print(f"✅ MFI 검증 완료 (최근 값: {valid_mfi.iloc[-1]:.2f})")

    def test_mfi_zero_volume_defense(self):
        """검증 6: 거래량이 0인 구간에서의 MFI 방어 로직 확인"""
        print("\n🔍 [검증 6] MFI 거래량 0(Zero Volume) 방어 테스트 중...")
        flat_data = pd.DataFrame({
            'High': [100]*30, 'Low': [100]*30, 'Close': [100]*30, 'Volume': [0]*30
        })
        try:
            mfi_flat = calc_mfi(flat_data, period=14)
            self.assertIsNotNone(mfi_flat)
            print("✅ MFI 거래량 0 구간 예외 처리 완료")
        except Exception as e:
            self.fail(f"❌ MFI 에러 발생: {e}")

    def test_07_adx_momentum_logic(self):
        """검증 7: ADX(추세 강도)가 강력한 추세를 포착하는가?"""
        print("\n🔍 [검증 7] ADX 추세 관성 감지 테스트 중...")
        adx = calc_adx(self.linear_up, period=14)
        last_adx = adx.iloc[-1]
        self.assertGreater(last_adx, 20)
        print(f"✅ ADX 추세 감지 확인 (현재값: {last_adx:.2f})")

    def test_08_dynamic_bbw_threshold(self):
        """검증 8: 동적 BBW 임계값이 하한선(0.3)을 지키는가?"""
        print("\n🔍 [검증 8] 동적 BBW 임계값 및 Floor(0.3) 감사 중...")
        # [수정] 반환값 4개를 언패킹함
        _, _, _, bbw_thr = calc_bollinger_bands(self.flat)
        last_thr = bbw_thr.iloc[-1]
        self.assertGreaterEqual(last_thr, 0.3)
        print(f"✅ BBW 동적 임계값 하한선 검증 완료 (Threshold: {last_thr:.2f})")

    def test_09_disparity_calculation(self):
        """검증 9: 이격도(Disparity) 산출 정밀도 확인"""
        print("\n🔍 [검증 9] 이격도(Disparity) 산술 정밀도 감사 중...")
        disp = calc_disparity(self.linear_up, period=20)
        last_disp = disp.iloc[-1]
        # 선형 상승 데이터이므로 100%보다 커야 함
        self.assertGreater(last_disp, 100)
        print(f"✅ 이격도 산출 정밀도 확인 완료: {last_disp:.2f}%")

if __name__ == '__main__':
    unittest.main()