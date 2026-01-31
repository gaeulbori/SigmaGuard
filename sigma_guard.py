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
import pandas as pd
from pathlib import Path
from datetime import datetime

# 핵심 모듈 임포트
from core.indicators import Indicators
from core.risk_engine import RiskEngine
from core.sigma_analyzer import SigmaAnalyzer
from data.ledgers.ledger_handler import LedgerHandler
from utils.messenger import TelegramMessenger
from utils.logger import setup_custom_logger
from utils.visual_reporter import VisualReporter
from config.settings import settings

logger = setup_custom_logger("SigmaGuard_Main")

class SigmaGuard:
    def __init__(self):
        # 1. 환경 설정 초기화 (common 디렉토리 및 설정 로드)
        self.secret_config, self.config_yaml = self._setup_environment()
        
        # 2. 앱 정보 및 전역 설정 추출
        self.app_info = self.config_yaml.get('app_info', {})
        self.sys_settings = self.config_yaml.get('settings', {})
        
        # 2. 로거 먼저 생성 (이 부분이 VisualReporter보다 위에 있어야 합니다!)
        # 만약 setup_custom_logger를 사용하신다면:
        from utils.logger import setup_custom_logger
        self.logger = setup_custom_logger("SigmaGuard_Main") 
        
        # 3. 이제 생성된 self.logger를 리포터에 전달
        from utils.visual_reporter import VisualReporter
        self.reporter = VisualReporter(self.logger)

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
        self.reporter = VisualReporter(self.logger) # 리포터 임계

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

    def run_audit(self, item):
            """[v9.0.8 Pipeline] 데이터 공급망 최적화 및 장부 기록 통합"""
            ticker = item.get('ticker')
            name = item.get('name', ticker)
            bench_ticker = item.get('bench') # config에서 벤치마크 티커 확보

            try:
                # 1. 기초 데이터 확보 (대상 종목 및 벤치마크)
                y_to_a = self.sys_settings.get('years_to_analyze', 5)
                period = f"{y_to_a + 1}y"
                
                # [수정] 단 한 번의 호출로 타겟과 벤치마크 데이터를 모두 수급합니다.
                ind_df, bench_df = self.indicators.generate(
                    ticker=ticker, 
                    period=period,
                    bench=bench_ticker
                )

                # 데이터 부족 대응 (타겟 기준)
                if ind_df is None or ind_df.empty:
                    logger.warning(f"⚠️ [{ticker}] 데이터 부족으로 'max' 재시도...")
                    ind_df, bench_df = self.indicators.generate(ticker, period="max", bench=bench_ticker)

                if ind_df is None or len(ind_df) < 120:
                    logger.error(f"   - [{ticker}] {name}: 분석 최소 기준 미달")
                    return

                # 2. 분석용 핵심 포인터 설정 (latest)
                latest = ind_df.iloc[-1]
                bench_latest = bench_df.iloc[-1] if not bench_df.empty else None
                market_date = ind_df.index[-1].strftime('%Y-%m-%d')

                # 3. 리스크 엔진 가동 (분석/배분/시뮬레이션)
                # [A] 리스크 평가: score, grade_label, details(liv_status 포함) 도출
                score, grade_label, details = self.risk_engine.evaluate(ind_df)
                
                # [B] 자본 할당: 손절가, 가성비(EI), 권고 비중 산출
                alloc = self.risk_engine.apply_risk_management(latest, ind_df)
                
                # [C] 라이브 백테스트: 기대 MDD 및 회복 일수 산출
                bt_res = self.risk_engine.perform_live_backtest(ind_df, latest)

                # 4. 장부 저장 (latest 중심의 슬림한 호출)
                self.ledger.save_entry(
                    ticker=ticker,
                    name=name,
                    market_date=market_date,
                    latest=latest,
                    score=score,
                    details=details,
                    alloc=alloc,
                    bt_res=bt_res,
                    bench_latest=bench_latest
                )

                current_level = self.risk_engine._get_level(score)
                self.ledger.update_forward_returns(ticker)
                prev_level, prev_score = self.ledger.get_previous_state(ticker)

                #if current_level >= 3 or (prev_score and abs(score - prev_score) >= 3.0):
                #    self.send_report(ticker, name, current_level, score, prev_score, details, bench_ticker)            
                
                #logger.info(f"✅ [{ticker}] 감사 완료: 현재 Level {current_level} ({score:.1f}점)")

                # 5. 리포트 및 상태 업데이트
                # [Step 5] 신규 리포트 출력 (v9.0.9 규격)
                # 이제 모든 종목에 대해 이 상세 리포트가 출력됩니다.
                self.reporter.print_audit_report(
                    ticker, name, market_date, latest, bench_latest, 
                    score, prev_score, details, alloc, bt_res
                )

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