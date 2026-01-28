"""
[File Purpose]
- 실제 텔레그램 봇과의 통신 상태를 점검하고 메시지 발송 기능을 최종 확인.

[Key Features]
- Real-world Test: 실제 텔레그램 서버로 테스트 메시지를 발송하여 토큰/ID 유효성 확정.
- Path Sensitivity: 테스트 폴더 내에서도 시스템 모듈을 인식할 수 있도록 sys.path 수동 보정 로직 포함.

[Future Roadmap]
- Mock Testing: 인터넷 연결이 없는 환경에서도 로직을 검증할 수 있는 모킹(Mocking) 테스트 추가.
"""
"""
[File Purpose]
- utils/messenger.py의 텔레그램 전송 로직 및 메시지 처리 무결성 검증.
- 대량 데이터 전송 시의 자동 분할(Chunking) 및 예외 처리 로직을 감사함.
"""

import unittest
import sys
import os
from unittest.mock import patch, MagicMock

# [Path Fix] 프로젝트 루트(SG)를 검색 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.messenger import send_telegram

class TestMessengerAudit(unittest.TestCase):
    """[CPA Audit] 메신저 통신 엔진 및 데이터 포맷팅 정밀 감사"""

    def test_01_empty_message_defense(self):
        """검증 1: 빈 메시지나 공백 투입 시 전송을 차단하는가?"""
        print("\n🔍 [검증 1] 빈 메시지 방어 테스트 중...")
        with patch('requests.post') as mock_post:
            send_telegram("")
            send_telegram("   ")
            # 호출 자체가 일어나지 않아야 성공
            mock_post.assert_not_called()
        print("✅ 빈 메시지 무시 확인 완료")

    def test_02_message_chunking_logic(self):
        """검증 2: 텔레그램 글자 수 제한(4000자) 초과 시 분할 전송하는가?"""
        print("\n🔍 [검증 2] 대량 메시지 분할(Chunking) 테스트 중...")
        # 3500자씩 2덩어리, 총 7000자의 긴 메시지 생성
        long_message = "A" * 3500 + "\n\n" + "B" * 3500
        
        with patch('requests.post') as mock_post:
            # 가상의 성공 응답 설정
            mock_post.return_value.status_code = 200
            send_telegram(long_message)
            
            # 최소 2번 이상의 post 호출이 발생했는지 확인
            call_count = mock_post.call_count
            self.assertGreaterEqual(call_count, 2, f"❌ 메시지 분할 실패 (호출 횟수: {call_count})")
        print(f"✅ 메시지 분할 전송 확인 완료 (총 {call_count}회 분할)")

    def test_03_html_tag_safety(self):
        """검증 3: HTML 태그가 포함된 메시지가 정상 규격으로 전송되는가?"""
        print("\n🔍 [검증 3] HTML 포맷팅 안전성 테스트 중...")
        html_msg = "<b>강조</b> <code>코드</code>"
        
        with patch('requests.post') as mock_post:
            mock_post.return_value.status_code = 200
            send_telegram(html_msg)
            
            # 전송된 데이터에 parse_mode가 HTML로 설정되었는지 확인
            args, kwargs = mock_post.call_args
            payload = kwargs.get('json', {})
            self.assertEqual(payload.get('parse_mode'), 'HTML')
            self.assertIn("<b>강조</b>", payload.get('text'))
        print("✅ HTML 태그 전송 규격 확인 완료")

    def test_04_api_error_handling(self):
        """검증 4: 텔레그램 API 에러(401, 404 등) 발생 시 시스템이 생존하는가?"""
        print("\n🔍 [검증 4] API 에러 예외 처리 테스트 중...")
        with patch('requests.post') as mock_post:
            # 401 Unauthorized 에러 시뮬레이션
            mock_post.return_value.status_code = 401
            mock_post.return_value.text = "Unauthorized"
            
            try:
                send_telegram("Test Error")
                # 에러가 발생해도 프로그램이 crash되지 않아야 함
                success = True
            except Exception:
                success = False
            
            self.assertTrue(success, "❌ API 에러 발생 시 시스템이 크래시되었습니다.")
        print("✅ API 에러 예외 처리 확인 완료 (Graceful Failure)")

if __name__ == '__main__':
    unittest.main()