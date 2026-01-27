"""
[File Purpose]
- 시스템 운영 로그 기록 및 OCI 서버 용량 최적화 관리.

[Key Features]
- Retention Policy: TimedRotatingFileHandler를 통해 30일(1개월)이 지난 로그는 자동 삭제(OCI Free Tier 용량 보호).
- Dual Logging: 콘솔(실시간 모니터링)과 파일(사후 분석)에 동시 기록.
- Singleton-safe: 핸들러 중복 등록 방지 로직으로 중복 로그 출력 차단.

[Future Roadmap]
- Log Level Config: settings.py와 연동하여 상황에 따른 로그 상세도(DEBUG/INFO) 조절 기능.
- Error Alert: 특정 레벨(CRITICAL) 이상의 로그 발생 시 텔레그램 즉시 전송 연동.
"""
import logging
import os
from logging.handlers import TimedRotatingFileHandler
from config.settings import settings

def setup_custom_logger(name):
    """
    OCI 환경 최적화 로거 (30일 자동 삭제 정책 적용)
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    if logger.hasHandlers():
        return logger

    os.makedirs(settings.LOG_DIR, exist_ok=True)
    
    formatter = logging.Formatter(
        '[%(asctime)s | %(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 1. 콘솔 출력
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    # 2. 파일 출력 (TimedRotatingFileHandler 활용)
    # sigma_guard.log 파일이 생성되며, 자정마다 .YYYYMMDD 형식으로 백업됨
    log_filepath = settings.LOG_DIR / "sigma_guard.log"
    
    file_handler = TimedRotatingFileHandler(
        filename=str(log_filepath),
        when='midnight',
        interval=1,
        backupCount=30,      # ★ 30일 경과 시 자동 삭제
        encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger