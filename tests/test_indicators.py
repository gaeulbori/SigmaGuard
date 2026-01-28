"""
[File Purpose]
- core/indicators.py 모듈의 수학적 연산 정밀도 및 논리적 무결성 검증.
- 기술적 지표 산출 로직이 금융 통계 표준 및 시스템 안정성 기준을 준수하는지 감사함.

[Key Features]
- Linear Trend Validation: $R^2$ 산출 시 완벽한 직선 데이터($y=ax+b$)를 투입하여 1.0(또는 근사치)을 반환하는지 검증.
- Range Stability Audit: RSI, MFI 등 백분율 지표가 어떤 시장 상황에서도 0~100 범위를 유지하는지 확인.
- Logic Consistency Check: 볼린저 밴드의 상단(Upper)이 하단(Lower)보다 항상 크거나 같음을 논리적으로 증명.
- Edge Case Defense: 주가 변동이 없는 횡보장(Zero Division) 상황에서 시스템 다운(Crash) 없이 예외를 처리하는지 테스트.

[Implementation Details]
- Framework: Python 표준 unittest 라이브러리 활용.
- Data Mocking: Numpy를 이용해 선형 상승 및 횡보용 더미 데이터를 생성하여 환경 의존성 제거.
- Path Handling: 하부 폴더(tests/) 내에서도 상위 모듈(core/)을 인식하도록 sys.path 수동 조정 포함.
"""

import unittest
import pandas as pd
import numpy as np
import sys
import os

# [Path Fix] 프로젝트 루트(SG)를 검색 경로에 추가하여 모듈 간 연결 확보
# [Path Fix] 프로젝트 루트(SG)를 검색 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.indicators import calc_rsi, calc_mfi, calc_bollinger_bands, calc_r_squared

class TestIndicatorsAudit(unittest.TestCase):
    """[CPA Audit] 기술 지표 산출 엔진 수학적 정밀도 검증"""

    def setUp(self):
        """테스트용 기초 데이터(더미 데이터) 생성"""
        # 1. 완벽한 직선 상승 데이터 (R2 = 1.0 확인용)
        self.linear_up = pd.DataFrame({'Close': np.linspace(100, 200, 50)})
        
        # 2. 횡보 데이터 (RSI/MFI 50 근처 확인용)
        self.flat = pd.DataFrame({
            'High': [105]*50, 'Low': [95]*50, 'Close': [100]*50, 'Volume': [1000]*50
        })

    def test_r_squared_precision(self):
        """검증 1: R-Squared(R2)가 완벽한 직선 추세에서 1.0을 반환하는가?"""
        print("\n🔍 [검증 1] R2 선형성 테스트 중...")
        r2_series = calc_r_squared(self.linear_up, period=20)
        final_r2 = r2_series.iloc[-1]
        
        # 부동 소수점 오차를 감안하여 0.99 이상인지 확인
        self.assertGreaterEqual(final_r2, 0.99, f"❌ R2 계산 오류: 직선 추세인데 {final_r2} 반환")
        print(f"✅ R2 직선도 검증 완료: {final_r2:.4f}")

    def test_rsi_range_limit(self):
        """검증 2: RSI가 0~100 범위를 절대로 벗어나지 않는가?"""
        print("\n🔍 [검증 2] RSI 범위 안정성 테스트 중...")
        # 지속 상승 시
        rsi_up = calc_rsi(self.linear_up)
        # 0과 100 사이 확인
        self.assertTrue(rsi_up.dropna().between(0, 100).all(), "❌ RSI가 범위를 이탈했습니다.")
        print(f"✅ RSI 범위 안정성 확인 완료")

    def test_bollinger_bands_logic(self):
        """검증 3: 볼린저 밴드의 상단이 항상 하단보다 위에 있는가?"""
        print("\n🔍 [검증 3] 볼린저 밴드 논리 구조 테스트 중...")
        upper, lower, bbw = calc_bollinger_bands(self.linear_up)
        
        # [수정] 데이터가 있는(NaN이 아닌) 구간만 필터링하여 비교
        valid_indices = upper.notna() & lower.notna()
        actual_upper = upper[valid_indices]
        actual_lower = lower[valid_indices]
        
        logic_check = (actual_upper >= actual_lower).all()
        
        # 디버깅을 위해 최하단 값 확인
        min_diff = (actual_upper - actual_lower).min()
        self.assertTrue(logic_check, f"❌ 볼린저 밴드 역전 발생 (최소 차이: {min_diff})")
        print(f"✅ 볼린저 밴드 논리 구조 확인 완료 (최소 밴드폭: {min_diff:.4f})")

    def test_constant_data_handling(self):
        """검증 4: 주가 변동이 없을 때(Zero Division) 에러가 발생하지 않는가?"""
        print("\n🔍 [검증 4] 횡보 데이터(Zero Division) 방어 테스트 중...")
        try:
            r2_flat = calc_r_squared(self.flat)
            rsi_flat = calc_rsi(self.flat)
            # 에러 없이 실행되면 성공
            self.assertIsNotNone(r2_flat)
            print("✅ 횡보 데이터 예외 처리 완료 (분모 0 방어)")
        except ZeroDivisionError:
            self.fail("❌ ZeroDivisionError가 발생했습니다. 분모 0 방어 로직이 필요합니다.")

    def test_mfi_logic(self):
        """
        검증 5: MFI(Money Flow Index)의 범위 및 거래량 가중치 반영 확인
        - 가격과 거래량이 동시에 상승할 때 MFI가 강세(50 이상)를 보이는지 검증.
        - 지표가 0~100 사이의 유효한 범위를 유지하는지 확인.
        """
        print("\n🔍 [검증 5] MFI 수치 안정성 및 추세 반영 테스트 중...")
        
        # 1. 상승장 + 거래량 증가 데이터 생성 (MFI 상승 유도)
        data = {
            'High': [110 + i for i in range(30)],
            'Low': [100 + i for i in range(30)],
            'Close': [105 + i for i in range(30)],
            'Volume': [1000 + (i * 100) for i in range(30)]
        }
        df = pd.DataFrame(data)
        
        mfi = calc_mfi(df, period=14)
        valid_mfi = mfi.dropna()

        # [감사 포인트 1] 범위 안정성: 0 <= MFI <= 100
        self.assertTrue(valid_mfi.between(0, 100).all(), "❌ MFI가 범위를 이탈했습니다.")

        # [감사 포인트 2] 추세 적합성: 강한 상승 데이터에서 MFI는 50보다 커야 함
        last_mfi = valid_mfi.iloc[-1]
        self.assertGreater(last_mfi, 50, f"❌ 상승 추세임에도 MFI가 낮습니다 (현재값: {last_mfi:.2f})")
        
        print(f"✅ MFI 검증 완료 (최근 값: {last_mfi:.2f})")

    def test_mfi_zero_volume_defense(self):
        """
        검증 6: 거래량이 0인 구간에서의 MFI 방어 로직 확인
        - 거래량이 없을 때 분모가 0이 되어 발생하는 ZeroDivisionError 방지 여부.
        """
        print("\n🔍 [검증 6] MFI 거래량 0(Zero Volume) 방어 테스트 중...")
        
        # 거래량이 모두 0인 정적 데이터
        flat_data = {
            'High': [100]*30, 'Low': [100]*30, 'Close': [100]*30, 'Volume': [0]*30
        }
        df_flat = pd.DataFrame(flat_data)
        
        try:
            mfi_flat = calc_mfi(df_flat, period=14)
            self.assertIsNotNone(mfi_flat)
            print("✅ MFI 거래량 0 구간 예외 처리 완료")
        except Exception as e:
            self.fail(f"❌ MFI가 거래량 0 구간에서 에러를 발생시켰습니다: {e}")

if __name__ == '__main__':
    unittest.main()