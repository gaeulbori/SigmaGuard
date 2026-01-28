"""
[File Purpose]
- 시스템 전역 설정 및 보안 키 관리 허브.
- 로컬 PC와 OCI 서버 간의 경로 차이를 흡수하고, 상위 common 폴더의 자산을 안전하게 연결함.

[Key Features]
- Path Logic: 2단계 상위 디렉토리(parent.parent)를 추적하여 'common' 폴더 내 SecretConfig 및 YAML 로드.
- Key Mapping: SecretConfig 내의 복잡한 딕셔너리 구조(BOTS/SG 등)를 단순 속성(TELEGRAM_TOKEN)으로 변환.
- Case-Insensitive YAML: 대소문자 구분 없이 watchlist/WATCHLIST를 유연하게 로드.

[Future Roadmap]
- Multi-Broker Config: 한국투자증권(KIS) 및 해외 증권사 API 키 연동 로직 추가.
- Dev/Prod Toggle: 테스트 환경과 OCI 실구동 환경의 설정을 분리하는 플래그 도입.
"""
"""
[File Purpose]
- 시스템 전역 설정 및 보안 키 관리 허브.
- 로컬 PC와 OCI 서버 간의 경로 차이를 흡수하고, 상위 common 폴더의 자산을 안전하게 연결함.

[Key Features]
- Path Logic: 2단계 상위 디렉토리(parent.parent)를 추적하여 'common' 폴더 내 SecretConfig 및 YAML 로드.
- Key Mapping: SecretConfig 내의 복잡한 딕셔너리 구조를 단순 속성(TELEGRAM_TOKEN)으로 변환.
- Case-Insensitive Mapping: [수정] watchlist/WATCHLIST를 유연하게 로드하여 settings.watchlist로 제공.
"""
import os
import sys
import yaml
from pathlib import Path
class Settings:
    def __init__(self):
        # [기존 경로 로직 유지]
        self.SG_DIR = Path(__file__).resolve().parent.parent
        self.WORK_DIR = self.SG_DIR.parent
        self.COMMON_DIR = self.WORK_DIR / "common"
        
        self.DATA_DIR = self.SG_DIR / "data"
        self.LOG_DIR = self.SG_DIR / "logs"

        # 1. 보안 설정 로드
        self.SECRET_CONFIG = self._load_secret_config()
        
        # 2. 토큰 및 ID 추출
        self.TELEGRAM_TOKEN = None
        self.CHAT_ID = None
        
        if self.SECRET_CONFIG:
            try:
                self.TELEGRAM_TOKEN = self.SECRET_CONFIG.TELEGRAM['BOTS']['SG']
                self.CHAT_ID = self.SECRET_CONFIG.TELEGRAM['COMMON_CHAT_ID']
            except (AttributeError, KeyError) as e:
                print(f"⚠️ [Warning] SecretConfig에서 키를 추출하는 데 실패했습니다: {e}")

        # 3. YAML 설정 로드
        self.CONFIG = self._load_yaml_config()

        # 4. [핵심 수정] 단축 속성 매핑 (Shortcut Mapping)
        # 테스트 코드(test_config.py)에서 요구하는 속성들을 직접 연결합니다.
        
        # [대소문자 유연 로드] watchlist 또는 WATCHLIST 둘 다 지원
        self.watchlist = self.CONFIG.get('watchlist') or self.CONFIG.get('WATCHLIST') or []
        
        # [앱 정보 로드] 기본값 v8.8.8 (테스트 코드 기준)
        app_info = self.CONFIG.get('app_info', {})
        self.app_version = app_info.get('version', 'v8.8.8')
        
        # [세부 설정 로드] 소수점 정밀도 등
        sys_settings = self.CONFIG.get('settings', {})
        self.precision = sys_settings.get('precision', 4)

    def _load_secret_config(self):
        """common 디렉토리를 sys.path에 추가하고 SecretConfig 로드"""
        if self.COMMON_DIR.exists():
            if str(self.COMMON_DIR) not in sys.path:
                sys.path.append(str(self.COMMON_DIR))
            try:
                from config_manager import SecretConfig
                return SecretConfig
            except ImportError: 
                return None
        return None

    def _load_yaml_config(self):
        """SG_config.yaml 로드"""
        yaml_path = self.COMMON_DIR / "SG_config.yaml"
        if yaml_path.exists():
            with open(yaml_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        return {}

# 싱글톤 인스턴스 생성
settings = Settings()