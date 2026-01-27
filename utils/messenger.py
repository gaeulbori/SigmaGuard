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
import requests
from config.settings import settings
from utils.logger import setup_custom_logger

# 메신저 전용 로거 설정
logger = setup_custom_logger("Messenger")

class TelegramMessenger:
    """
    [CPA David 전용 보고관]
    검증된 보안 키를 사용하여 텔레그램 알림을 전담함
    """
    def __init__(self):
        # settings에서 이미 검증된 키들을 가져옴
        self.token = settings.TELEGRAM_TOKEN
        self.chat_id = settings.CHAT_ID
        self.api_url = f"https://api.telegram.org/bot{self.token}/sendMessage"

    def send_message(self, text, parse_mode="HTML"):
        """메시지 발송 (HTML 포맷 지원)"""
        if not self.token or not self.chat_id:
            logger.error("❌ 텔레그램 설정(Token/ID)이 누락되어 메시지를 보낼 수 없습니다.")
            return False

        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode
        }

        try:
            response = requests.post(self.api_url, data=payload, timeout=10)
            response.raise_for_status() # 4xx, 5xx 에러 발생 시 예외 발생
            logger.info("✅ 텔레그램 메시지 발송 성공")
            return True
        except Exception as e:
            logger.error(f"❌ 텔레그램 발송 중 오류 발생: {e}")
            return False

# 편의를 위한 싱글톤 객체 생성
messenger = TelegramMessenger()