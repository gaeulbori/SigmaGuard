import os

def init_sigma_guard_v2_pro():
    """
    [Sigma Guard v2.0] 프로젝트 뼈대 생성 및 모듈 최적화 스크립트
    대상: OCI Free Tier 환경 및 멀티 브로커 확장 대응
    """
    # 1. 부서 및 하부 조직(Sub-directories) 정의
    structure = {
        'core': [],                     # 리스크 엔진, 지표 계산, 리버모어
        'data': [                       # 데이터 창고 (분산 보관)
            'ledgers',                  # 종목별 CSV 감사 원장
            'universe',                 # KOSPI 200 등 종목 리스트
            'portfolio'                 # 가상 매매 계좌 및 슬롯 상태
        ],
        'trading': [                    # 매매 집행국
            'executors',                # KIS(국내), Global(해외), Virtual(가상)
            'strategies'                # 10개 슬롯 관리 및 매매 전략 로직
        ],
        'utils': [],                    # 텔레그램, 포맷터, 로거
        'config': [],                   # 설정 및 보안 키 로드
        'tests': [],                    # 단위 테스트 (PyTest)
        'logs': []                      # 운영 로그 전용
    }
    
    base_dir = os.getcwd()
    print(f"🚀 [Project Setup] '{base_dir}'에서 구조 조정을 시작합니다...")
    print("-" * 60)

    # 2. 디렉토리 순회 생성
    for main_folder, sub_folders in structure.items():
        # 메인 폴더 생성
        os.makedirs(main_folder, exist_ok=True)
        # 패키지 인식을 위한 __init__.py 생성
        with open(os.path.join(main_folder, "__init__.py"), "w", encoding="utf-8") as f:
            f.write(f"# {main_folder} package initialization\n")
        print(f"  [Main] /{main_folder}")

        # 하부 폴더 생성
        for sub in sub_folders:
            sub_path = os.path.join(main_folder, sub)
            os.makedirs(sub_path, exist_ok=True)
            with open(os.path.join(sub_path, "__init__.py"), "w", encoding="utf-8") as f:
                f.write(f"# {main_folder}/{sub} package initialization\n")
            print(f"    └─ [Sub] /{sub}")

    # 3. .gitignore 생성 (OCI 서버 및 Git 관리 최적화)
    gitignore_content = """
# Python Cache
__pycache__/
*.py[cod]
*$py.class

# Environment & Config
.env
.venv
venv/
config/local_settings.py

# Data & Logs (보안 및 용량 관리)
logs/*.log
data/ledgers/*.csv
data/portfolio/*.json

# OS files
.DS_Store
Thumbs.db
"""
    with open(".gitignore", "w", encoding="utf-8") as f:
        f.write(gitignore_content.strip())
    print("-" * 60)
    print("✅ [.gitignore] 생성 완료: 데이터 및 로그 유출 방지")
    print("✅ [Setup Complete] Sigma Guard v2.0 법인형 구조가 준비되었습니다.")

if __name__ == "__main__":
    init_sigma_guard_v2_pro()