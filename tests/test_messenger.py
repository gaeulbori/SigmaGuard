"""
[File Purpose]
- 실제 텔레그램 봇과의 통신 상태를 점검하고 메시지 발송 기능을 최종 확인.

[Key Features]
- Real-world Test: 실제 텔레그램 서버로 테스트 메시지를 발송하여 토큰/ID 유효성 확정.
- Path Sensitivity: 테스트 폴더 내에서도 시스템 모듈을 인식할 수 있도록 sys.path 수동 보정 로직 포함.

[Future Roadmap]
- Mock Testing: 인터넷 연결이 없는 환경에서도 로직을 검증할 수 있는 모킹(Mocking) 테스트 추가.
"""
import unittest
import sys
import os

# 경로 수동 설정 (config 및 utils 인식을 위함)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.messenger import messenger

class TestMessenger(unittest.TestCase):
    def test_send_hello_world(self):
        """실제 텔레그램 발송 테스트"""
        test_msg = (
            "🛡️ <b>Sigma Guard v2.0</b>\n"
            "━━━━━━━━━━━━━\n"
            "✅ <b>시스템 인프라 구축 완료</b>\n"
            "현재 V2 엔진이 정상적으로 보안 키를 로드하고 통신 채널을 확보했습니다.\n\n"
            "<i>- CPA David 전용 감사 시스템 -</i>"
        )
        print("\n🚀 [테스트] 텔레그램 발송 시도 중...")
        result = messenger.send_message(test_msg)
        self.assertTrue(result, "❌ 텔레그램 메시지 발송에 실패했습니다.")

if __name__ == '__main__':
    unittest.main()