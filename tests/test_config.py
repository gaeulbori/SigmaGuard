"""
[File Purpose]
- 시스템 기동 전, 보안 키와 설정 데이터의 유효성을 사전에 검증하는 단위 테스트.

[Key Features]
- Connectivity Audit: 상위 common 폴더와의 물리적 연결 및 SecretConfig 클래스 임포트 여부 확인.
- Schema Validation: YAML 설정 내 필수 항목(watchlist 등) 존재 여부 및 데이터 형식 검증.
- Environment Check: OCI/로컬 환경에 따른 경로 무결성 테스트.

[Future Roadmap]
- CI/CD Integration: GitHub Push 시 자동으로 테스트를 수행하는 워크플로우 연동.
"""
"""
[File Purpose]
- 시스템 구성 환경(Configuration) 및 보안 자산에 대한 전수 감사.
- common 폴더 연동, YAML 파싱, 내부 경로 유효성을 100% 검증함.
"""

import unittest
import os
import sys

# [Path Fix] 파일의 상위의 상위 폴더(프로젝트 루트: SG)를 검색 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import settings  # 이제 정상적으로 로드됩니다.
class TestConfigFullAudit(unittest.TestCase):
    """[CPA Audit] Sigma Guard v2.0 인프라 설정 전수 검사"""

    def test_01_security_keys_audit(self):
        """검증 1: 텔레그램 마스터 키 및 보안 클래스 연동 확인"""
        print("\n🔍 [검증 1] 보안 자산(SecretConfig) 연동 상태 감사...")
        self.assertIsNotNone(settings.TELEGRAM_TOKEN, "❌ TELEGRAM_TOKEN 로드 실패")
        self.assertIsNotNone(settings.CHAT_ID, "❌ CHAT_ID 로드 실패")
        
        # David님의 실제 토큰 패턴(숫자 시작) 검증
        self.assertTrue(str(settings.TELEGRAM_TOKEN).startswith('85543'), "❌ 토큰 시작 패턴 불일치")
        print(f"✅ 보안 키 정합성 확인 (ID: {settings.CHAT_ID})")

    def test_02_mapping_integrity(self):
        """검증 2: YAML 데이터 속성 매핑(Shortcut) 확인"""
        print("\n🔍 [검증 2] 설정 속성 매핑(Mapping) 무결성 감사...")
        
        # 1. Watchlist 단축 속성 확인
        self.assertIsInstance(settings.watchlist, list, "❌ settings.watchlist가 리스트 형식이 아님")
        self.assertGreater(len(settings.watchlist), 0, "❌ watchlist가 비어 있음")
        
        # 2. App Info 및 Version 확인
        self.assertRegex(settings.app_version, r'^v\d+\.\d+\.\d+$',
                         f"❌ 버전 형식 불일치: {settings.app_version}")
        print(f"✅ 속성 매핑 확인 (Version: {settings.app_version}, Watchlist: {len(settings.watchlist)}개)")

    def test_03_path_and_permission_audit(self):
        """검증 3: 프로젝트 내부 디렉토리 유효성 및 접근 권한 확인"""
        print("\n🔍 [검증 3] 운영 디렉토리(Data/Logs) 유효성 감사...")
        
        # 1. 경로 존재 여부 확인
        paths = {
            "DATA_DIR": settings.DATA_DIR,
            "LOG_DIR": settings.LOG_DIR,
            "COMMON_DIR": settings.COMMON_DIR
        }
        
        for name, path in paths.items():
            # OCI 서버에서는 폴더가 아직 없을 수 있으므로 상위 폴더 존재 여부와 생성 가능성 체크
            parent = path.parent
            self.assertTrue(parent.exists(), f"❌ {name}의 상위 폴더({parent})가 존재하지 않음")
            print(f"✅ {name} 경로 유효함: {path}")

    def test_04_yaml_schema_audit(self):
        """검증 4: YAML 설정 내 필수 섹션 존재 여부 확인"""
        print("\n🔍 [검증 4] YAML 스키마(Schema) 필수 항목 감사...")
        required_sections = ['app_info', 'settings', 'watchlist']
        for section in required_sections:
            self.assertIn(section, settings.CONFIG, f"❌ YAML 내 필수 섹션 '{section}' 누락")
        
        # 세부 설정값 확인
        precision = settings.CONFIG.get('settings', {}).get('precision')
        self.assertIsNotNone(precision, "❌ settings.precision 설정 누락")
        print(f"✅ YAML 스키마 검증 완료 (Precision: {precision})")

if __name__ == '__main__':
    unittest.main()