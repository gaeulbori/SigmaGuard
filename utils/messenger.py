"""
[File Purpose]
- 시스템 분석 결과 및 감사 리포트를 외부(텔레그램)로 전달하는 전용 통로.
- v9.0.0: OCI 및 로컬 환경의 SecretConfig에서 보안 토큰을 직접 주입받을 수 있도록 생성자(Constructor) 개선.

[Key Features]
- Flexible Initialization: 파라미터로 토큰을 받으면 최우선 적용, 없을 경우 settings.py 기본값 로드.
- Message Chunking: 텔레그램 4,096자 제한을 고려하여 3,500자 단위로 자동 분할 전송(v8.9.7 정통 로직).
- JSON Stability: requests의 json 파라미터를 사용하여 특수문자 및 유니코드(한글) 전송 안정성 확보.
- Singleton Compatibility: 기존 테스트 코드와의 호환성을 위해 싱글톤 객체 및 래퍼 함수 유지.

[Future Roadmap]
- Media Support: 분석 차트(PNG) 및 감사 조서(CSV) 파일 전송 기능 추가 예정.
"""

import requests
from config.settings import settings
from utils.logger import setup_custom_logger

# 메신저 전용 로거 설정
logger = setup_custom_logger("Messenger")

class TelegramMessenger:
    def __init__(self, token=None, chat_id=None):
        """
        보안 설정을 외부에서 주입(Dependency Injection)받거나, 
        주입값이 없을 경우 settings.py의 기본 설정을 사용함.
        """
        # 1. 우선순위: 주입된 값 > settings.py 설정값
        self.token = token if token else settings.TELEGRAM_TOKEN
        self.chat_id = chat_id if chat_id else settings.CHAT_ID
        
        # 2. 토큰을 기반으로 API URL 확정
        self.api_url = f"https://api.telegram.org/bot{self.token}/sendMessage"

    def send_message(self, text, parse_mode="HTML"):
        """
        메시지 발송 (자동 분할 및 HTML 포맷 지원)
        - David님의 v8.9.7 대량 리포트 전송 규격 준수.
        """
        if not self.token or not self.chat_id:
            logger.error("❌ 텔레그램 설정(Token/ID)이 누락되어 발송이 불가능합니다.")
            return False

        if not text or not text.strip():
            logger.warning("⚠️ 전송할 메시지 내용이 비어 있습니다.")
            return False

        # [v8.9.7 필수 로직] 텔레그램 글자수 제한(4,096자) 방어를 위한 Chunking
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
                # json=payload를 사용하여 데이터 인코딩 안정성 확보
                response = requests.post(self.api_url, json=payload, timeout=10)
                response.raise_for_status()
                logger.info(f"✅ 텔레그램 메시지 발송 성공 (파트 {i+1}/{len(chunks)})")
            except Exception as e:
                logger.error(f"❌ 텔레그램 발송 오류 (파트 {i+1}): {e}")
                success = False
        
        return success
    
    def send_smart_message(self, message):
        """[v9.9.9] 대량 종목 대응형 스마트 분할 전송"""
        if not message.strip(): return
        
        MAX_LEN = 3500 # 텔레그램 안전 여유분 포함
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"

        # 1. 메시지 분할 로직 (기존 v8.9.1 이식)
        chunks = []
        if len(message) <= MAX_LEN:
            chunks = [message]
        else:
            current_chunk = ""
            parts = [p.strip() for p in message.split('\n\n') if p.strip()]
            for part in parts:
                if len(current_chunk) + len(part) + 2 <= MAX_LEN:
                    current_chunk += part + '\n\n'
                else:
                    chunks.append(current_chunk.strip())
                    current_chunk = part + '\n\n'
            if current_chunk: chunks.append(current_chunk.strip())

        # 2. 각 청크 전송
        for chunk in chunks:
            payload = {
                "chat_id": self.chat_id,
                "text": chunk,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            }
            requests.post(url, json=payload, timeout=15)    

# ------------------------------------------------------------
# 1. 기본 인스턴스 생성 (settings.py 기반 싱글톤)
# ------------------------------------------------------------
messenger = TelegramMessenger()

# ------------------------------------------------------------
# 2. [핵심] 테스트 코드 및 레거시 모듈 호환용 래퍼 함수
# ------------------------------------------------------------
def send_telegram(message: str):
    """
    기존 테스트 코드(test_messenger.py) 등에서 
    객체 생성 없이 즉시 호출할 수 있는 표준 인터페이스.
    """
    return messenger.send_message(message)