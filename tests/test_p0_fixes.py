"""
[File Purpose]
- P0 버그 수정 검증: sigma_guard.py 초기화 중복 및 risk_engine.py MFI/RSI 키 오류.
"""

import unittest
import sys
import os
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.risk_engine import RiskEngine
from core.db_handler import DBHandler


class TestP0Fix1_RiskEngineKeys(unittest.TestCase):
    """P0 Fix #2: _calc_energy_risk의 MFI/RSI 대문자 키 수정 검증"""

    def setUp(self):
        self.engine = RiskEngine()

    def _make_df(self, mfi, rsi, rows=5):
        """대문자 키 기반 Mock DataFrame 생성"""
        df = pd.DataFrame({
            'Close': [100.0] * rows,
            'High':  [101.0] * rows,
            'Low':   [99.0]  * rows,
            'Volume':[1000]  * rows,
        })
        df['MFI']          = float(mfi)
        df['RSI']          = float(rsi)
        df['avg_sigma']    = 0.5
        df['sig_1y']       = 0.5
        df['sig_2y']       = 0.5
        df['sig_3y']       = 0.5
        df['sig_4y']       = 0.5
        df['sig_5y']       = 0.5
        df['bbw']          = 0.1
        df['bbw_thr']      = 0.3
        df['macd_h']       = 0.0
        df['m_trend']      = "상승가속"
        df['ma_slope']     = "Rising"
        df['disp120']      = 100.0
        df['disp120_limit']= 115.0
        df['disp120_avg']  = 105.0
        df['slope']        = 0.01
        df['R2']           = 0.7
        df['ADX']          = 28.0
        return df

    def test_mfi_divergence_raises_score(self):
        """MFI < RSI(수급 불일치) 시 에너지 점수가 MFI > RSI(수급 안정)보다 높아야 한다."""
        print("\n🔍 [P0-1] MFI/RSI 대문자 키: 수급 불일치 vs 안정 점수 비교")

        df_divergence = self._make_df(mfi=35.0, rsi=75.0)   # MFI < RSI → 불일치
        df_stable     = self._make_df(mfi=65.0, rsi=45.0)   # MFI > RSI → 안정

        score_div, _, _  = self.engine.evaluate(df_divergence)
        score_stable, _, _ = self.engine.evaluate(df_stable)

        self.assertGreater(score_div, score_stable,
            f"❌ 수급불일치({score_div:.1f}) 점수가 안정({score_stable:.1f})보다 낮거나 같음. "
            "키 대소문자 버그가 수정되지 않았습니다.")
        print(f"✅ 수급불일치: {score_div:.1f}점  >  수급안정: {score_stable:.1f}점 (정상)")

    def test_mfi_rsi_default_not_used_when_data_exists(self):
        """실제 MFI/RSI 값이 기본값(50.0)이 아닌 실제 데이터를 사용하는지 확인."""
        print("\n🔍 [P0-2] MFI=20, RSI=80 극단값 → 기본값(50)이면 중립점수, 실제값이면 최고점수여야 함")

        df_extreme = self._make_df(mfi=20.0, rsi=80.0)   # 극단적 수급불일치
        df_neutral = self._make_df(mfi=50.0, rsi=50.0)   # 기본값과 동일

        score_extreme, _, _ = self.engine.evaluate(df_extreme)
        score_neutral, _, _ = self.engine.evaluate(df_neutral)

        self.assertGreater(score_extreme, score_neutral,
            f"❌ 극단값({score_extreme:.1f}) ≤ 기본값({score_neutral:.1f}). "
            "소문자 키 버그 시 차이가 없어야 하는데 P0 수정이 적용 안 된 것.")
        print(f"✅ 극단 불일치: {score_extreme:.1f}점  >  기본값: {score_neutral:.1f}점 (정상)")

    def test_energy_score_uses_uppercase_key(self):
        """_calc_energy_risk 내부적으로 uppercase 'MFI', 'RSI'를 읽는지 직접 검증"""
        print("\n🔍 [P0-3] _calc_energy_risk 내부 키 직접 검증")

        latest_upper = pd.Series({
            'MFI': 25.0, 'RSI': 80.0,
            'bbw': 0.1, 'bbw_thr': 0.3, 'macd_h': 0.0,
            'avg_sigma': 0.5, 'ma_slope': 'Rising',
            'disp120': 100.0, 'disp120_limit': 115.0, 'disp120_avg': 105.0,
            'slope': 0.01, 'R2': 0.7, 'ADX': 28.0,
        })
        latest_lower = pd.Series({
            'mfi': 25.0, 'rsi': 80.0,   # 소문자 (버그 재현)
            'MFI': 50.0, 'RSI': 50.0,   # 대문자는 중립값
            'bbw': 0.1, 'bbw_thr': 0.3, 'macd_h': 0.0,
            'avg_sigma': 0.5, 'ma_slope': 'Rising',
            'disp120': 100.0, 'disp120_limit': 115.0, 'disp120_avg': 105.0,
            'slope': 0.01, 'R2': 0.7, 'ADX': 28.0,
        })

        score_upper = self.engine._calc_energy_risk(latest_upper)
        score_lower = self.engine._calc_energy_risk(latest_lower)

        # 소문자 키만 있으면 MFI=50, RSI=50 (기본값) → stable score
        # 대문자 키를 올바르게 읽으면 MFI=25 < RSI=80 → divergence score (higher)
        self.assertGreater(score_upper, score_lower,
            f"❌ 대문자 키({score_upper:.1f}) ≤ 소문자 키({score_lower:.1f}). "
            "대문자 'MFI'/'RSI'를 올바르게 읽지 못하고 있습니다.")
        print(f"✅ 대문자 키(MFI/RSI): {score_upper:.1f}점  >  소문자 키: {score_lower:.1f}점 (정상)")


class TestP0Fix2_SigmaGuardInit(unittest.TestCase):
    """P0 Fix #1: sigma_guard.py __init__ 중복 초기화 제거 검증"""

    def test_analyzer_has_db_handler(self):
        """self.analyzer가 DBHandler를 갖고 있어야 한다 (덮어쓰기 버그 수정 확인)."""
        print("\n🔍 [P0-4] SigmaGuard.analyzer.db가 DBHandler 인스턴스인지 확인")
        from sigma_guard import SigmaGuard
        app = SigmaGuard()

        self.assertIsInstance(app.analyzer.db, DBHandler,
            "❌ analyzer.db가 DBHandler가 아님. "
            "SigmaAnalyzer(settings.DATA_DIR)로 덮어쓰는 버그가 남아 있습니다.")
        print(f"✅ analyzer.db = {type(app.analyzer.db).__name__} (정상)")

    def test_reporter_initialized_once(self):
        """self.reporter가 VisualReporter 단일 인스턴스여야 한다."""
        print("\n🔍 [P0-5] SigmaGuard.reporter가 올바르게 단일 초기화되는지 확인")
        from sigma_guard import SigmaGuard
        from utils.visual_reporter import VisualReporter
        app = SigmaGuard()

        self.assertIsInstance(app.reporter, VisualReporter,
            "❌ reporter가 VisualReporter 인스턴스가 아님.")
        print(f"✅ reporter = {type(app.reporter).__name__} (정상)")

    def test_messenger_uses_settings_token(self):
        """메신저 토큰이 settings에서 직접 로드되어야 한다."""
        print("\n🔍 [P0-6] TelegramMessenger 토큰이 settings에서 로드되는지 확인")
        from sigma_guard import SigmaGuard
        from config.settings import settings
        app = SigmaGuard()

        self.assertEqual(app.messenger.token, settings.TELEGRAM_TOKEN,
            "❌ messenger.token이 settings.TELEGRAM_TOKEN과 다름.")
        print(f"✅ messenger.token = settings.TELEGRAM_TOKEN (정상)")


if __name__ == '__main__':
    unittest.main(verbosity=2)
