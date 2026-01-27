David님, 새로운 시스템의 **'정관(Articles of Incorporation)'**이자 **'감사 매뉴얼'**이 될 `README.md` 초안을 작성했습니다. 지금까지 우리가 머리를 맞대고 논의한 OCI 최적화 전략, 멀티 브로커 확장성, 그리고 
---

# 🛡️ Sigma Guard v2.0: Quantitative Trading System

**Sigma Guard v2.0**은 CPA의 정밀한 감사 원칙을 트레이딩에 접목한 모듈형 퀀트 시스템입니다. 단일 파일 구조에서 벗어나 확장성, 안정성, 그리고 테스트 가능성을 극대화한 **'법인형 아키텍처'**를 지향합니다.

---

## 🏛️ 시스템 아키텍처 (Architectural Overview)

본 시스템은 각 부서(Module)가 독립적인 책임을 갖는 **계층형 구조**로 설계되었습니다.

### 📂 디렉토리 지도 (Directory Map)

* **`core/`**: 시스템의 '뇌'. 기술적 지표 계산 및 리스크 채점 로직 전담.
* **`data/`**: '장부 관리국'. CSV 감사 원장, 유니버스(KOSPI 200 등) 리스트 관리.
* **`trading/`**: '매매 집행국'. 가상 매매 및 멀티 브로커(KIS, 해외 등) 인터페이스.
* **`utils/`**: '비서실'. 텔레그램 알림 및 시스템 로깅 수행.
* **`config/`**: '중앙 통제실'. 보안 키 로드 및 전역 설정 관리.
* **`tests/`**: '감사실'. 각 모듈의 무결성을 검증하는 단위 테스트.
* **`logs/`**: '기록 보관소'. 운영 로그 저장.

---

## 🛠️ 핵심 설계 원칙 (Design Principles)

### 1. OCI Free Tier 최적화 (Lean Management)

* **자원 효율성**: 1GB RAM 환경을 고려하여 제너레이터 패턴 및 배치 처리를 통해 메모리 점유율 최소화.
* **로그 관리**: `TimedRotatingFileHandler`를 적용, **최근 30일치** 로그만 유지하고 자동 삭제하여 디스크 용량 방어.

### 2. 보안 및 설정 (Security Audit)

* **자산 격리**: 핵심 보안 키(Telegram, API Keys)는 프로젝트 외부의 `common/config_manager.py`에서 중앙 집중 관리.
* **유연한 설정**: `SG_config.yaml`을 통해 분석 대상(`watchlist`)과 운영 파라미터를 코드 수정 없이 조정.

### 3. 멀티 브로커 확장성 (Global Scalability)

* **인터페이스 기반 설계**: 추상 클래스(`BaseExecutor`)를 통해 국내(한투), 해외, 가상 매매 환경을 유연하게 교체 가능하도록 설계.

### 4. 테스트 주도 개발 (Test-Driven Foundation)

* 모든 핵심 로직은 `tests/` 내의 단위 테스트를 통과해야만 실제 매매 로직에 반영됨.

---

## 🚀 시작하기 (Getting Started)

### 1. 환경 설정

본 프로젝트는 상위 `common` 디렉토리를 참조하므로 다음과 같은 구조가 전제되어야 합니다.

```text
WORK/
├── common/             # SecretConfig 및 전역 YAML
└── SG/                 # 본 프로젝트 루트 (v2.0)

```

### 2. 단위 테스트 실행 (Audit Trail)

시스템 기동 전, 인프라의 무결성을 검증합니다.

```bash
# PYTHONPATH 설정 후 실행 (macOS/Linux)
export PYTHONPATH=$PYTHONPATH:.
python tests/test_config.py
python tests/test_messenger.py

```

---

## 📅 로드맵 (Current Progress & Roadmap)

* [] 프로젝트 기초 구조(Skeleton) 구축
* [] 중앙 설정 및 보안 모듈(`config`) 독립
* [] OCI 최적화 로깅 시스템(`utils/logger`) 구축
* [] 텔레그램 보고 체계(`utils/messenger`) 구축
* [] 기술 지표 연산 모듈(`core/indicators`) 이사
* [] 리스크 엔진(`core/risk_engine`) 고도화
* [] KOSPI 200 동적 유니버스 생성기 구현
* [] 가상/실제 매매 집행부(Executor) 개발

---

> **Note**: 본 시스템은 CPA David의 자산 관리 철학을 코드로 구현한 것이며, 모든 매매 로직은 단위 테스트를 통한 '적정' 의견을 받은 후 실행됩니다.

---