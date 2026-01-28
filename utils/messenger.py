"""
[File Purpose]
- 시스템 분석 결과 및 알림 메시지를 외부(텔레그램)로 전달하는 전용 통로.

[Key Features]
- Config Integration: settings.py에 검증된 토큰과 ID를 사용하여 객체 생성 시 자동 연결.
- HTML Support: 태그 기반 포맷팅(Bold, Italic 등)을 지원하여 가시성 높은 리포트 발송 가능.
- Error Handling: 네트워크 오류나 API 제한 발생 시 Logger를 통한 예외 기록.

[Future Roadmap]
- Rate Limiting: 200개 이상의 종목 알림 시 텔레그램 API 제한(429 Error)을 방지하는 큐(Queue) 시스템.
- Media Support: 분석 차트(이미지)나 데이터 파일(CSV)을 직접 전송하는 기능 확장.
"""
"""
[File Purpose]
- 시스템 분석 결과 및 알림 메시지를 외부(텔레그램)로 전달하는 전용 통로.

[Key Features]
- Message Chunking: [추가] 텔레그램 4,096자 제한을 넘지 않도록 3,500자 단위 자동 분할.
- HTML Support: 태그 기반 포맷팅 지원.
- Error Handling: 네트워크 오류 시 예외 기록 및 Graceful Failure.
"""
import requests
from config.settings import settings
from utils.logger import setup_custom_logger

# 메신저 전용 로거 설정
logger = setup_custom_logger("Messenger")

class TelegramMessenger:
    def __init__(self):
        self.token = settings.TELEGRAM_TOKEN
        self.chat_id = settings.CHAT_ID
        self.api_url = f"https://api.telegram.org/bot{self.token}/sendMessage"

    def send_message(self, text, parse_mode="HTML"):
        """메시지 발송 (자동 분할 및 HTML 포맷 지원)"""
        if not self.token or not self.chat_id:
            logger.error("❌ 텔레그램 설정(Token/ID)이 누락되었습니다.")
            return False

        if not text or not text.strip():
            logger.warning("⚠️ 전송할 메시지 내용이 비어 있습니다.")
            return False

        # [David v8.9.7 필수 로직] 메시지 분할 전송 (Chunking)
        MAX_LEN = 3500
        chunks = [text[i:i + MAX_LEN] for i in range(0, len(text), MAX_LEN)]
        
        success = True
        for i, chunk in enumerate(chunks):
            payload = {
                "chat_id": self.chat_id,
                "text": chunk,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True
            }

            try:
                # json=payload를 사용하여 데이터 전송의 안정성 확보
                response = requests.post(self.api_url, json=payload, timeout=10)
                response.raise_for_status()
                logger.info(f"✅ 텔레그램 메시지 발송 성공 (파트 {i+1}/{len(chunks)})")
            except Exception as e:
                logger.error(f"❌ 텔레그램 발송 오류 (파트 {i+1}): {e}")
                success = False
        
        return success

# 1. 편의를 위한 싱글톤 객체 생성
messenger = TelegramMessenger()

# 2. [핵심] 테스트 코드 및 외부 모듈과의 호환성을 위한 래퍼 함수
def send_telegram(message: str):
    """테스트 코드(test_messenger.py)에서 호출하는 표준 인터페이스"""
    return messenger.send_message(message)