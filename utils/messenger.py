"""
[File Purpose]
- 시스템 분석 결과 및 감사 리포트를 텔레그램으로 전달하는 전용 통로.
- [v1.2.0 수정] send_smart_message 로깅 강화 및 예외 처리 로직 통합.
"""

import requests
import json
from config.settings import settings
from utils.logger import setup_custom_logger

# 메신저 전용 로거 설정
logger = setup_custom_logger("Messenger")

class TelegramMessenger:
    def __init__(self, token=None, chat_id=None):
        # 1. 우선순위: 주입된 값 > settings.py 설정값
        self.token = token if token else settings.TELEGRAM_TOKEN
        self.chat_id = chat_id if chat_id else settings.CHAT_ID
        self.api_url = f"https://api.telegram.org/bot{self.token}/sendMessage"

    def _check_config(self):
        """설정 유효성 검사 (공통 내부 함수)"""
        if not self.token or not self.chat_id:
            logger.error("❌ 텔레그램 설정(Token/ID)이 누락되었습니다. common/config_manager.py를 확인하세요.")
            return False
        return True

    def send_message(self, text, parse_mode="HTML"):
        """기본 전송 메서드 (v8.9.7 정통 로직)"""
        if not self._check_config(): return False
        if not text or not text.strip():
            logger.warning("⚠️ 전송할 메시지 내용이 비어 있습니다.")
            return False

        MAX_LEN = 3500
        chunks = [text[i:i + MAX_LEN] for i in range(0, len(text), MAX_LEN)]
        
        return self._execute_send(chunks, parse_mode)

    def send_smart_message(self, message):
        """[v9.9.9] 대량 종목 대응형 스마트 분할 전송 (로깅 강화)"""
        if not self._check_config(): return False
        if not message or not message.strip():
            logger.warning("⚠️ [Smart] 전송할 메시지가 비어 있습니다.")
            return False
        
        MAX_LEN = 3500
        chunks = []

        # 1. 메시지 분할 로직 (단락 보존형)
        if len(message) <= MAX_LEN:
            chunks = [message]
        else:
            current_chunk = ""
            parts = [p.strip() for p in message.split('\n\n') if p.strip()]
            for part in parts:
                if len(current_chunk) + len(part) + 2 <= MAX_LEN:
                    current_chunk += part + '\n\n'
                else:
                    if current_chunk: chunks.append(current_chunk.strip())
                    current_chunk = part + '\n\n'
            if current_chunk: chunks.append(current_chunk.strip())

        logger.info(f"🚀 텔레그램 스마트 전송 개시 (총 {len(chunks)}개 파트 / {len(message)} 자)")
        return self._execute_send(chunks)

    def _execute_send(self, chunks, parse_mode="HTML"):
        """실제 HTTP 요청을 수행하고 결과를 상세히 로깅 (핵심 수정 지점)"""
        success_count = 0
        
        for i, chunk in enumerate(chunks):
            payload = {
                "chat_id": self.chat_id,
                "text": chunk,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True
            }

            try:
                # 타임아웃을 15초로 넉넉히 설정
                response = requests.post(self.api_url, json=payload, timeout=15)
                res_data = response.json()
                
                if res_data.get("ok"):
                    logger.info(f"   ✅ [Part {i+1}/{len(chunks)}] 전송 성공")
                    success_count += 1
                else:
                    # 텔레그램 API에서 에러를 반환한 경우 (예: 잘못된 Chat ID, 토큰 만료 등)
                    error_msg = res_data.get('description', '알 수 없는 오류')
                    logger.error(f"   ❌ [Part {i+1}/{len(chunks)}] API 오류: {error_msg}")
                    
            except requests.exceptions.RequestException as e:
                # 네트워크 관련 오류 (타임아웃, DNS 오류 등)
                logger.error(f"   ❌ [Part {i+1}/{len(chunks)}] 네트워크 예외 발생: {e}")

        return success_count == len(chunks)

# 싱글톤 인스턴스
messenger = TelegramMessenger()

def send_telegram(message: str):
    return messenger.send_message(message)