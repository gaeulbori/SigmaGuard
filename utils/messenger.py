"""
[File Purpose]
- [v9.9.0] HTML 오버헤드 대응 및 대용량 주간 리포트 분할 전송 안정화.
- 텔레그램 글자 수 제한(4096자)을 고려하여 안전 임계치(3000자) 적용.
"""

import requests
import json
import time
from config.settings import settings
from utils.logger import setup_custom_logger

logger = setup_custom_logger("Messenger")

class TelegramMessenger:
    def __init__(self, token=None, chat_id=None):
        self.token = token if token else settings.TELEGRAM_TOKEN
        self.chat_id = chat_id if chat_id else settings.CHAT_ID
        self.api_url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        # [수정] HTML 태그 포함을 고려한 안전 임계치 설정
        self.SAFE_LIMIT = 3000 

    def _check_config(self):
        if not self.token or not self.chat_id:
            logger.error("❌ 텔레그램 설정 누락: CHAT_ID 혹은 TOKEN을 확인하세요.")
            return False
        return True

    def send_message(self, text, parse_mode="HTML"):
        """기본 전송 메서드 (단순 절단 방식)"""
        if not self._check_config() or not text: return False
        
        # 단순 글자 수 기반 분할
        chunks = [text[i:i + self.SAFE_LIMIT] for i in range(0, len(text), self.SAFE_LIMIT)]
        return self._execute_send(chunks, parse_mode)

    def send_smart_message(self, message):
        """[v9.9.0] 단락 보존 및 강제 분할 결합형 (주간 리포트 대응)"""
        if not self._check_config() or not message: return False
        
        raw_chunks = self._split_smartly(message)
        
        logger.info(f"🚀 텔레그램 스마트 전송 개시 (총 {len(raw_chunks)}개 파트 / {len(message)} 자)")
        return self._execute_send(raw_chunks)

    def _split_smartly(self, message):
        """[v9.9.1] HTML 태그 무결성을 보존하는 지능형 분할 로직"""
        chunks = []
        # 텔레그램에서 주로 사용하는 태그 리스트
        tags_to_track = ['b', 'i', 'code', 'pre', 'u', 'strong', 'em']
        
        remaining_text = message
        while len(remaining_text) > 0:
            if len(remaining_text) <= self.SAFE_LIMIT:
                chunks.append(remaining_text)
                break
            
            # 1. 안전한 분할 지점 찾기 (가장 가까운 줄바꿈)
            split_idx = remaining_text.rfind('\n', 0, self.SAFE_LIMIT)
            if split_idx == -1: split_idx = self.SAFE_LIMIT
            
            current_chunk = remaining_text[:split_idx]
            next_part = remaining_text[split_idx:]
            
            # 2. 열린 태그 추적 및 닫기 보정
            open_tags = []
            for tag in tags_to_track:
                start_count = current_chunk.count(f'<{tag}>')
                end_count = current_chunk.count(f'</{tag}>')
                if start_count > end_count:
                    open_tags.append(tag)
            
            # 현재 덩어리 뒤에 닫지 않은 태그들 강제로 닫기 (역순)
            for tag in reversed(open_tags):
                current_chunk += f'</{tag}>'
            
            chunks.append(current_chunk)
            
            # 다음 덩어리 앞에 닫았던 태그들 다시 열어주기
            reopen_prefix = ""
            for tag in open_tags:
                reopen_prefix += f'<{tag}>'
            
            remaining_text = reopen_prefix + next_part.lstrip()
            
        return chunks

    def _execute_send(self, chunks, parse_mode="HTML"):
        """실제 전송 수행 (연속 전송 시 과부하 방지 0.5초 대기 추가)"""
        success_count = 0
        
        for i, chunk in enumerate(chunks):
            payload = {
                "chat_id": self.chat_id,
                "text": chunk,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True
            }

            try:
                response = requests.post(self.api_url, json=payload, timeout=15)
                res_data = response.json()
                
                if res_data.get("ok"):
                    logger.info(f"   ✅ [Part {i+1}/{len(chunks)}] 전송 성공")
                    success_count += 1
                else:
                    error_msg = res_data.get('description', '알 수 없는 오류')
                    logger.error(f"   ❌ [Part {i+1}/{len(chunks)}] API 오류: {error_msg}")
                
                # [v9.9.0 추가] 텔레그램 스팸 방지를 위한 미세 지연
                if len(chunks) > 1:
                    time.sleep(0.5)
                    
            except Exception as e:
                logger.error(f"   ❌ [Part {i+1}/{len(chunks)}] 네트워크 예외: {e}")

        return success_count == len(chunks)

# 싱글톤 인스턴스
messenger = TelegramMessenger()

def send_telegram(message: str):
    return messenger.send_smart_message(message)