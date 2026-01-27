import unittest
import sys
import os

# [핵심 추가] 현재 파일(tests/test_config.py)의 상위 폴더(SG)를 시스템 경로에 추가
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from config.settings import settings

class TestConfigIntegrity(unittest.TestCase):
    """[CPA Audit] Sigma Guard v2.0 기초 자산(Keys) 검증"""

    def test_01_telegram_keys_validation(self):
        """검증 1: 텔레그램 토큰 및 채팅 ID 유효성 확인"""
        print("\n🔍 [검증 1] 텔레그램 보안 키 유효성 검사 중...")
        
        # settings.TELEGRAM_TOKEN이 SecretConfig.TELEGRAM['BOTS']['SG']를 잘 가져왔는지 확인
        self.assertIsNotNone(settings.TELEGRAM_TOKEN, "❌ TELEGRAM_TOKEN이 로드되지 않았습니다.")
        self.assertIsInstance(settings.TELEGRAM_TOKEN, str, "❌ 토큰은 문자열이어야 합니다.")
        
        # CHAT_ID 확인
        self.assertIsNotNone(settings.CHAT_ID, "❌ CHAT_ID가 로드되지 않았습니다.")
        print(f"✅ 텔레그램 연결 준비 완료 (Token: {str(settings.TELEGRAM_TOKEN)[:5]}*** / ID: {settings.CHAT_ID})")

    def test_02_yaml_watchlist_check(self):
        """검증 2: YAML 내 관심 종목 리스트 로드 확인"""
        print("\n🔍 [검증 2] YAML 설정 데이터 무결성 검사 중...")
        
        # [수정] 대문자 'WATCHLIST' -> 소문자 'watchlist'
        self.assertIn('watchlist', settings.CONFIG, "❌ YAML 설정에 'watchlist' 항목이 없습니다.")
        
        watchlist = settings.CONFIG.get('watchlist', [])
        self.assertGreater(len(watchlist), 0, "❌ 분석 대상 종목(watchlist)이 비어 있습니다.")
        
        # 샘플 종목 하나 출력해서 확인
        sample = watchlist[0]['name']
        print(f"✅ 분석 대상 유니버스 로드 완료 (종목 수: {len(watchlist)}, 샘플: {sample})")

if __name__ == '__main__':
    unittest.main()