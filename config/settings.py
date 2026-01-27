import os
import sys
import yaml
from pathlib import Path

class Settings:
    def __init__(self):
        self.SG_DIR = Path(__file__).resolve().parent.parent
        self.WORK_DIR = self.SG_DIR.parent
        self.COMMON_DIR = self.WORK_DIR / "common"
        
        self.DATA_DIR = self.SG_DIR / "data"
        self.LOG_DIR = self.SG_DIR / "logs"

        # 1. 보안 설정 로드
        self.SECRET_CONFIG = self._load_secret_config()
        
        # 2. 토큰 및 ID 추출 (David님의 실제 구조 반영)
        self.TELEGRAM_TOKEN = None
        self.CHAT_ID = None
        
        if self.SECRET_CONFIG:
            try:
                # [수정 포인트] 최신 Sigma Guard 접근 방식 적용
                self.TELEGRAM_TOKEN = self.SECRET_CONFIG.TELEGRAM['BOTS']['SG']
                self.CHAT_ID = self.SECRET_CONFIG.TELEGRAM['COMMON_CHAT_ID']
            except (AttributeError, KeyError) as e:
                print(f"⚠️ [Warning] SecretConfig에서 키를 추출하는 데 실패했습니다: {e}")

        # 3. YAML 설정 로드
        self.CONFIG = self._load_yaml_config()

    def _load_secret_config(self):
        if self.COMMON_DIR.exists():
            sys.path.append(str(self.COMMON_DIR))
            try:
                from config_manager import SecretConfig
                return SecretConfig
            except ImportError: return None
        return None

    def _load_yaml_config(self):
        yaml_path = self.COMMON_DIR / "SG_config.yaml"
        if yaml_path.exists():
            with open(yaml_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f)
        return {}

settings = Settings()