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