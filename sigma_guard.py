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
        """[v9.2.0 Integration] 데이터 공급망 최적화 및 고해상도 리포트 대응"""
        ticker = item.get('ticker')
        name = item.get('name', ticker)
        bench_ticker = item.get('bench', 'N/A') # config에서 벤치마크 티커 확보

        try:
            # [수정] 매크로 데이터를 먼저 수집하여 details에 병합
            macro_data = self.ledger._get_macro_snapshot() or {}           
            # 1. 기초 데이터 확보 (대상 종목 및 벤치마크)
            # 1. 분석 전 기초 잔액(Prev EMA) 및 매크로 상황 확보
            prev_ema = self.ledger.get_previous_sub_scores(ticker)

            y_to_a = self.sys_settings.get('years_to_analyze', 5)
            period = f"{y_to_a + 1}y"
            
            # [최적화] 타겟과 벤치마크 데이터를 동시에 수급
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

            has_bench = False
            if bench_df is not None:
                try:
                    # bench_df가 DataFrame인지와 데이터가 있는지 동시에 검증
                    if isinstance(bench_df, pd.DataFrame) and not bench_df.empty:
                        has_bench = True
                except:
                    has_bench = False
            # 2. 분석용 핵심 포인터 설정 (latest)
            latest = ind_df.iloc[-1]
            bench_latest = bench_df.iloc[-1] if has_bench else None
            market_date = ind_df.index[-1].strftime('%Y-%m-%d')

            # 3. 리스크 엔진 가동 (분석/배분/시뮬레이션)
            # ---------------------------------------------------------
            # [A] [수정] 리스크 평가: 이제 bench_df를 함께 전달하여 괴리도를 분석합니다.
            # ---------------------------------------------------------
            # 2. 리스크 엔진 가동 (과거 EMA 주입)
            score, grade_label, details = self.risk_engine.evaluate(ind_df, bench_df, prev_ema)            
            
            # 리포트 출력 시 이름(Name)을 사용하기 위해 details에 주입
            details['name'] = name

            # [핵심] 수집된 매크로와 리포트용 라벨을 details에 주입
            details.update({
                'vix': macro_data.get('VIX_T'),
                'dxy': macro_data.get('DXY_T'),
                'us10y': macro_data.get('US10Y_T'),
                'action_label': grade_label  # 'DANGER' 등이 리포트 상단에 찍힘
            })

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

            # 5. [수정] 고해상도 리포트 출력 (v9.2.0 규격)
            # ---------------------------------------------------------
            # bench_ticker를 명시적으로 전달하여 리포트 헤더에 출력되게 합니다.
            # ---------------------------------------------------------
            self.reporter.print_audit_report(
                item, market_date, latest, bench_latest, 
                score, prev_score, details, alloc, bt_res
            )
            # [핵심] 요약 테이블을 위해 결과 데이터 반환
            return {
                "ticker": ticker,
                "name": name,                                # 종목명 추가
                "price": latest.get('Close', 0.0),           # 현재가 추가
                "score": score,
                "prev_score": prev_score,
                "action_text": details.get('action', '관망'), # 상세 지침 포함                
                "liv_status": details.get('liv_status', 'N/A'),
                "disp": latest.get('disp120', 100.0),
                "ei": alloc.get('ei', 0.0),                  # EI 추가
                "stop": alloc.get('stop_loss', 0.0),         # 손절가 추가
                "weight": alloc.get('weight', 0.0)
            }

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
        watchlist = self.config_yaml.get('watchlist', [])
        audit_results_summary = []
        # [핵심] 변화 감지를 위한 카테고리 바구니
        new_stocks, risk_up, risk_down = [], [], []
        alert_messages = [] # [추가] 알림 메시지 보관함

        for item in watchlist:
            audit_data = self.run_audit(item)
            if audit_data:
                audit_results_summary.append(audit_data)
                # [v9.9.9 추가] 델타 알림 생성 및 취합
                msg = self.reporter.build_delta_alert_msg(audit_data)
                if msg:
                    prev_score = audit_data.get('prev_score')
                    if prev_score is None: new_stocks.append(msg)
                    elif audit_data['score'] > prev_score: risk_up.append(msg)
                    else: risk_down.append(msg)                    
        
        # 1. 터미널 요약 출력
        self.reporter.print_audit_summary_table(audit_results_summary)
        # 2. [v9.9.9 추가] 텔레그램 통합 알림 발송
        # 2. 요일별 알림 발송 전략 (v8.9.7 이식)
        now = datetime.now()
        WEEKLY_REPORT_DAY = 5 # 토요일 (David 설정값)
        is_weekly_day = (now.weekday() == WEEKLY_REPORT_DAY)

        delta_body = self.reporter.assemble_delta_alerts(new_stocks, risk_up, risk_down)
        
        if is_weekly_day:
            weekly_msg = self.reporter.build_weekly_dashboard(audit_results_summary)
            final_msg = (delta_body + "\n" + weekly_msg) if delta_body else weekly_msg
        else:
            final_msg = delta_body # 평일엔 변동 사항만 전송

        if final_msg:
            # 텔레그램 스마트 분할 전송
            self.messenger.send_smart_message(final_msg)
        

    """
    [Program Explanation]
    1. Mock Data 생성: 실제 마켓 데이터 없이도 신규(None), 상승(+25.0), 완화(-25.0) 케이스를 강제로 생성합니다.
    2. Logic Bypass: 날짜(요일) 제한을 해제하여 주간 대시보드가 즉시 발송되도록 강제 설정합니다.
    3. Smart Sending: v8.9.1의 분할 전송 기술이 HTML 태그를 깨뜨리지 않고 잘 보내는지 검증합니다.
    """

    def test_messaging_pipeline(self):
        """[David's Diagnostic Mode] 텔레그램 발송 케이스별 강제 테스트"""
        self.logger.info("🧪 텔레그램 메시지 파이프라인 테스트 시작 (Mock Data 주입)")
        
        # 1. 테스트용 가상 데이터 구성 (신규 / 상승 / 완화 / 대시보드용)
        test_results = [
            {
                "ticker": "NEW_TEST", "name": "테스트_신규", "score": 45.0, 
                "prev_score": None, "action_text": "적극 매집: 신규 진입 적기", "weight": 10.0
            },
            {
                "ticker": "UP_TEST", "name": "테스트_위험상승", "score": 85.0, 
                "prev_score": 60.0, "action_text": "공격적 익절: 자산 보호 우선", "weight": 5.0
            },
            {
                "ticker": "DOWN_TEST", "name": "테스트_리스크완화", "score": 30.0, 
                "prev_score": 55.0, "action_text": "안정 보유: 리스크 관리 범위 내", "weight": 15.0
            }
        ]

        # 2. 알림 카테고리 분류 (기존 execute_all 로직 재현)
        new_stocks, risk_up, risk_down = [], [], []
        
        for data in test_results:
            # Reporter를 통해 텔레그램용 HTML 메시지 생성
            msg = self.reporter.build_delta_alert_msg(data)
            if msg:
                if data['prev_score'] is None:
                    new_stocks.append(msg)
                elif data['score'] > data['prev_score']:
                    risk_up.append(msg)
                else:
                    risk_down.append(msg)

        # 3. 메시지 조립 및 강제 발송
        # assemble_delta_alerts는 카테고리를 합쳐줍니다.
        delta_body = self.reporter.assemble_delta_alerts(new_stocks, risk_up, risk_down)
        
        # 주간 대시보드 생성 (요일 무시하고 강제 생성)
        dashboard = self.reporter.build_weekly_dashboard(test_results)
        
        # 통합 메시지 구성
        final_msg = f"🧪 <b>[TEST MODE] 파이프라인 검증 보고</b>\n\n"
        if delta_body:
            final_msg += delta_body + "\n"
        final_msg += dashboard

        # 4. 최종 전송 (스마트 분할 기술 적용)
        self.messenger.send_smart_message(final_msg)
        self.logger.info("🏁 테스트 메시지가 텔레그램으로 발송되었습니다.")

# 메인 실행부에서 테스트 모드 호출
if __name__ == "__main__":
    app = SigmaGuard()
    app.execute_all()  # 실제 운용 시
    #app.test_messaging_pipeline() # 텔레그램 테스트 시