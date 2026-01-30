"""
[File Purpose]
- Phase 1~3 통합: v8.9.7 정통 리스크 감사 파이프라인 완성.
- 기능: 사후 수익률 결산(T+20), 리스크 델타(▲/▼) 추적, 지능형 자본 할당 보고.

[Key Features]
- Audit Delta: 전일 대비 리스크 점수 변동폭을 감지하여 조기 경보 수행.
- Performance Feedback: 전수 감사 후 등급별 성과 요약(SigmaAnalyzer) 자동 발행.
- 39-Header Mapping: 5개년 다중 시그마 및 리버모어 상태 등 모든 정밀 지표를 장부에 동기화.
"""

import os
import sys
import yaml
from pathlib import Path
from datetime import datetime

# 핵심 모듈 임포트
from core.indicators import Indicators
from core.risk_engine import RiskEngine
from core.sigma_analyzer import SigmaAnalyzer
from data.ledgers.ledger_handler import LedgerHandler
from utils.messenger import TelegramMessenger
from utils.logger import setup_custom_logger
from config.settings import settings

logger = setup_custom_logger("SigmaGuard_Main")

class SigmaGuard:
    def __init__(self):
        # 1. 환경 설정 초기화 (common 디렉토리 및 설정 로드)
        self.secret_config, self.config_yaml = self._setup_environment()
        
        # 2. 앱 정보 및 전역 설정 추출
        self.app_info = self.config_yaml.get('app_info', {})
        self.sys_settings = self.config_yaml.get('settings', {})
        
        # 3. 핵심 엔진 초기화
        self.indicators = Indicators()
        self.risk_engine = RiskEngine()
        self.ledger = LedgerHandler()
        
        # 4. [v9.0.0] SecretConfig를 메신저에 주입 (보안 연결)
        # SecretConfig에서 텔레그램 토큰과 ID를 가져오도록 설계됨
        self.messenger = TelegramMessenger(
            token=getattr(self.secret_config, "TELEGRAM_TOKEN", None),
            chat_id=getattr(self.secret_config, "CHAT_ID", None)
        )
        self.analyzer = SigmaAnalyzer(settings.DATA_DIR)

        logger.info(f"🛡️ {self.app_info.get('version')} {self.app_info.get('edition')} 가동")
        logger.info(f"👤 Auditor: {self.app_info.get('author')} (OCI Ready)")

    def _setup_environment(self):
        """[David's Legacy Logic] 공통 디렉토리 탐색 및 설정 로드"""
        home = os.path.expanduser("~")
        # OCI와 Local Mac 환경을 동시에 지원하는 후보 경로
        possible_common_paths = [
            os.path.join(home, "Documents/work/common"),
            os.path.join(home, "work/common")
        ]
        
        common_dir = None
        for path in possible_common_paths:
            if os.path.exists(path):
                common_dir = path
                if path not in sys.path:
                    sys.path.append(path)
                break
                
        if not common_dir:
            logger.error("❌ common 디렉토리를 찾을 수 없습니다. 경로를 확인하세요.")
            sys.exit(1)

        # 보안 설정 로드 (SecretConfig)
        try:
            from config_manager import SecretConfig
        except ImportError:
            logger.error("❌ common/config_manager.py 파일을 찾을 수 없습니다.")
            sys.exit(1)

        # YAML 설정 로드
        yaml_path = os.path.join(common_dir, "SG_config.yaml")
        if not os.path.exists(yaml_path):
            logger.error(f"❌ {yaml_path} 파일이 존재하지 않습니다.")
            sys.exit(1)
        
        with open(yaml_path, "r", encoding="utf-8") as f:
            config_yaml = yaml.safe_load(f)
            
        return SecretConfig, config_yaml

    # sigma_guard.py 내부의 관련 메서드 정밀 수정

    def run_audit(self, item):
        """[v9.0.0 Pipeline] 종목별 감사 집행 및 데이터 부족 대응"""
        ticker = item.get('ticker')
        name = item.get('name')
        bench = item.get('bench')

        try:
            # 1. 사후 결산 및 전일 상태 조회
            self.ledger.update_forward_returns(ticker)
            prev_level, prev_score = self.ledger.get_previous_state(ticker)

            # 2. 지표 산출 (BAM 같은 신규 종목은 'max'로 시도하거나 예외 처리)
            y_to_a = self.sys_settings.get('years_to_analyze', 5)
            period = f"{y_to_a + 1}y"
            ind_df = self.indicators.generate(ticker, period=period)
            
            # 데이터가 부족할 경우 'max'로 재시도하는 유연함 발휘
            if ind_df is None or ind_df.empty:
                logger.warning(f"⚠️ [{ticker}] {period} 데이터 부족으로 'max' 기간 재시도...")
                ind_df = self.indicators.generate(ticker, period="max")

            # [v9.0.5 핵심 보정] iloc[-1] 접근 전 데이터 무결성 전수 검사
            # 데이터가 아예 없거나, 분석 최소 기준(120일)에 미달하면 즉시 중단
            if ind_df is None or ind_df.empty or len(ind_df) < 120:
                logger.error(f"   - [{ticker}] {name}: 분석에 필요한 최소 데이터(120일) 부족")
                return

            # --- [추가 로그: 데이터 구조 감사] ---
            latest = ind_df.iloc[-1]
            #logger.info(f"📊 [{ticker}] 가공 전 최종 컬럼 확인: {ind_df.columns.tolist()}")
            # ----------------------------------

            if ind_df is None or len(ind_df) < 120:
                logger.error(f"   - [{ticker}] {name}: 분석에 필요한 최소 데이터(120일) 부족으로 감사 중단")
                return

            # 2. 리스크 평가 실행 (여기가 가장 유력한 에러 발생 지점입니다)
            try:
                score, grade_label, details = self.risk_engine.evaluate(ind_df)
            except KeyError as ke:
                logger.error(f"🚨 [RiskEngine KeyError] {ticker} 분석 중 '{ke}' 항목을 찾을 수 없습니다.")
                logger.error(f"   - 엔진이 요구하는 항목이 ind_df에 있는지 확인이 필요합니다.")
                raise ke # 상위 except로 던짐

            current_level = self.risk_engine._get_level(score)
            
            # 4. 장부 저장 (39개 헤더)
            market_date = ind_df.index[-1].strftime('%Y-%m-%d')
            self.ledger.save_entry(
                ticker, name, market_date,
                ind_df.iloc[-1], {"avg_sigma": ind_df['avg_sigma'].iloc[-1]},
                None, None, score, details, details, {}, details['liv_status']
            )

            # 5. [v9.0.0] 리포트 발송 조건 체크
            # 8개 인자를 정확히 전달함 (self, ticker, name, level, score, prev_score, details, bench)
            if current_level >= 3 or (prev_score and abs(score - prev_score) >= 3.0):
                self.send_report(ticker, name, current_level, score, prev_score, details, bench)            
            
            logger.info(f"✅ [{ticker}] 감사 완료: 현재 Level {current_level} ({score:.1f}점)")

        except Exception as e:
            logger.error(f"❌ [{ticker}] 감사 중 치명적 오류: {e}")

    # [핵심 수정] 파라미터 개수를 호출부(8개)와 정확히 일치시킴
    def send_report(self, ticker, name, level, score, prev_score, details, bench):
        """v9.0.0 David's Analytical Audit Report 포맷 (인자 7개 + self)"""
        delta_str = ""
        if prev_score is not None:
            diff = score - prev_score
            sign = "▲" if diff > 0 else "▼" if diff < 0 else "-"
            delta_str = f"({sign}{abs(diff):.1f})"
        else:
            delta_str = "(신규)"

        emoji = "🚨" if level >= 5 else "🔴" if level == 4 else "🟡" if level == 3 else "✅"
        bench_tag = f" [대조: {bench}]" if bench else ""

        message = (
            f"{emoji} **[{self.app_info.get('edition', 'Audit Edition')}]**\n"
            f"**{name}({ticker})**{bench_tag}\n"
            f"━━━━━━━━━━━━━━\n"
            f"• **상태**: {details.get('scenario', 'N/A')} (Lv.{level})\n"
            f"• **점수**: `{score:.1f}` 점 {delta_str}\n"
            f"━━━━━━━━━━━━━━\n"
            f"• **SOP 지침**: {details.get('action', '관망')}\n"
            f"• **권고 비중**: {details.get('weight_pct', 0)}% (E.I: {details.get('ei', 0)})\n"
            f"• **손절 가이드**: {details.get('stop_loss', 0):,}\n"
            f"━━━━━━━━━━━━━━\n"
            f"👤 Auditor: {self.app_info.get('author', 'David')} | {self.app_info.get('version', 'v9.0.0')}"
        )
        self.messenger.send_message(message)

    def execute_all(self):
        """Watchlist 전수 감사 집행"""
        watchlist = self.config_yaml.get('watchlist', [])
        logger.info(f"🚀 총 {len(watchlist)}개 종목 전수 감사 시작")
        
        for item in watchlist:
            self.run_audit(item)
        
        perf_summary = self.analyzer.run_performance_audit()
        self.messenger.send_message(perf_summary)
        logger.info("🏁 오늘의 자산 감사 종료")

if __name__ == "__main__":
    app = SigmaGuard()
    app.execute_all()