"""
[File Purpose]
- Phase 1~5 통합: 실전 매매 DB 연동 및 David's Fortress 리포트 자동화.
- 기능: 보유 종목 자동 감지, 실시간 수익률 계산, 이중 손절선(Entry vs Reco) 감사.

[Key Features]
- DB Integrated Audit: holdings 테이블의 종목을 watchlist와 병합하여 자동 전수 감사.
- Fortress Visualization: 리포트 하단에 David 전용 전략 자산 운용 현황(Fortress) 출력.
- Performance Feedback: DB 기반 실전 매매 통계와 CSV 기반 리스크 예측력을 통합 분석.
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
from core.db_handler import DBHandler          # [v10.3.0 추가] SQLite 핸들러
from data.ledgers.ledger_handler import LedgerHandler
from utils.messenger import TelegramMessenger
from utils.logger import setup_custom_logger
from utils.visual_reporter import VisualReporter
from config.settings import settings
from utils.market_utils import get_regional_benchmark

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
        
        # 2. 데이터베이스 및 리포터 초기화
        self.db = DBHandler() # [v10.3.0] 실전 장부 DB 연결
        from utils.visual_reporter import VisualReporter
        self.reporter = VisualReporter(self.logger)

        # 3. 핵심 엔진 초기화
        self.indicators = Indicators()
        self.risk_engine = RiskEngine()
        self.ledger = LedgerHandler()
        
        # [v10.3.0 수정] 분석기에 DB 핸들러 주입 (실전 성과 분석용)
        self.analyzer = SigmaAnalyzer(self.db, settings.DATA_DIR)

        # 4. [v9.0.0] SecretConfig를 메신저에 주입 (보안 연결)
        self.messenger = TelegramMessenger(
            token=settings.TELEGRAM_TOKEN,
            chat_id=settings.CHAT_ID
        )

        logger.info(f"🛡️ {self.app_info.get('version')} {self.app_info.get('edition')} 가동")
        logger.info(f"👤 Auditor: {self.app_info.get('author')} (OCI Ready)")

    def _setup_environment(self):
        # OCI와 Local Mac 환경을 동시에 지원하는 후보 경로
        home = os.path.expanduser("~")
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

    def run_audit(self, item, macro_snapshot):
        """[v9.8.9 Fix] 벤치마크 빈 데이터셋 접근 오류(Out-of-Bounds) 완전 방어"""
        ticker = item.get('ticker')
        name = item.get('name', ticker)
        bench_ticker = item.get('bench', 'N/A')

        try:
            # 1. 데이터 수급 및 기초 검증
            y_to_a = self.sys_settings.get('years_to_analyze', 5)
            period = f"{y_to_a + 1}y"
            ind_df, bench_df = self.indicators.generate(ticker=ticker, period=period, bench=bench_ticker)
            
            if ind_df is None or ind_df.empty:
                logger.warning(f"⚠️ [{ticker}] 데이터 부족으로 'max' 재시도...")
                ind_df, bench_df = self.indicators.generate(ticker, period="max", bench=bench_ticker)

            if ind_df is None or len(ind_df) < 120:
                logger.error(f"   - [{ticker}] {name}: 분석 최소 기준 미달")
                return None

            latest = ind_df.iloc[-1]
            market_date = ind_df.index[-1].strftime('%Y-%m-%d')

            # 2. 과거 데이터 복원
            prev_level, prev_score = self.ledger.get_previous_state(ticker, market_date)            
            prev_ema = self.ledger.get_previous_sub_scores(ticker, market_date)

            # 3. [핵심 에러 방어] 벤치마크 유효성 정밀 검증
            # bench_df가 None이 아니고, 데이터가 1건이라도 있어야 iloc[-1]을 허용합니다.
            is_bench_valid = isinstance(bench_df, pd.DataFrame) and not bench_df.empty
            bench_latest = bench_df.iloc[-1] if is_bench_valid else None

            # 4. 리스크 엔진 가동
            score, grade_label, details = self.risk_engine.evaluate(ind_df, bench_df, prev_ema)            
            
            details.update({
                'name': name,
                'vix': macro_snapshot.get('VIX_T'),
                'dxy': macro_snapshot.get('DXY_T'),
                'us10y': macro_snapshot.get('US10Y_T'),
                'action_label': grade_label
            })

            alloc = self.risk_engine.apply_risk_management(latest, ind_df)
            bt_res = self.risk_engine.perform_live_backtest(ind_df, latest)

            # 5. [수정 포인트] 장부 저장 (직접 iloc[-1] 호출 대신 검증된 bench_latest 전달)
            self.ledger.save_entry(
                ticker=ticker, name=name, market_date=market_date,
                latest=latest, score=score, details=details,
                alloc=alloc, bt_res=bt_res, macro_data=macro_snapshot,
                bench_latest=bench_latest, # <- [중요] 여기서 다시 bench_df.iloc[-1]을 호출하지 않습니다.
                bench_ticker=bench_ticker
            )
            self.ledger.update_forward_returns(ticker)

            # 6. 리포트 및 결과 반환
            self.reporter.print_audit_report(
                item, market_date, latest, bench_latest, 
                score, prev_score, details, alloc, bt_res
            )
            
            return {
                "ticker": ticker,
                "name": name,
                "price": latest.get('Close', 0.0),
                "score": score,
                "prev_score": prev_score,
                "action_text": details.get('action', '관망'),
                "liv_status": details.get('liv_status', 'N/A'),
                "disp": latest.get('disp120', 100.0),
                "ei": alloc.get('ei', 0.0),
                "stop": alloc.get('stop_loss', 0.0),
                "weight": alloc.get('weight', 0.0)
            }

        except Exception as e:
            logger.error(f"❌ [{ticker}] 감사 중 치명적 오류: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return None

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

    def execute_all_prev(self):
        watchlist = self.config_yaml.get('watchlist', [])
        audit_results_summary = []
        # [핵심] 변화 감지를 위한 카테고리 바구니
        new_stocks, risk_up, risk_down = [], [], []
            # 2. 기초 데이터 및 매크로 확보
        macro_snapshot = self.ledger._get_macro_snapshot() or {}           

        for item in watchlist:
            audit_data = self.run_audit(item, macro_snapshot)
            if audit_data:
                audit_results_summary.append(audit_data)
                msg = self.reporter.build_delta_alert_msg(audit_data)
                if msg:
                    prev_score = audit_data.get('prev_score')
                    if prev_score is None: new_stocks.append(msg)
                    elif audit_data['score'] > prev_score: risk_up.append(msg)
                    elif audit_data['score'] < prev_score: risk_down.append(msg)

        # [추가 로그] 분류 결과 출력
        self.logger.info(f"📊 [메시지 분류 결과] 신규: {len(new_stocks)}, 상승: {len(risk_up)}, 하락: {len(risk_down)}")

        # 1. 터미널 요약 출력
        self.reporter.print_audit_summary_table(audit_results_summary)
        now = datetime.now()
        WEEKLY_REPORT_DAY = 5 # 토요일 (David 설정값)
        is_weekly_day = (now.weekday() == WEEKLY_REPORT_DAY)

        delta_body = self.reporter.assemble_delta_alerts(new_stocks, risk_up, risk_down)
        
        if is_weekly_day:
            self.logger.info("📅 오늘은 주간 리포트 발송일입니다.")
            weekly_msg = self.reporter.build_weekly_dashboard(audit_results_summary)
            final_msg = (delta_body + "\n" + weekly_msg) if delta_body else weekly_msg
        else:
            if delta_body:
                final_msg = delta_body
            else:
                # [David님을 위한 Heartbeat 추가] 변동이 없을 때 발송할 메시지
                self.logger.info("🔔 변동 사항 없음: 생존 신고 메시지 생성")
                total = len(audit_results_summary)
                final_msg = (
                    f"🛡️ <b>Sigma Guard Status: NORMAL</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"현재 전일 대비 리스크 점수 변동이 있는 종목이 없습니다.\n"
                    f"• 감시 대상: {total}개 종목\n"
                    f"• 장부 기록: 정상 업데이트 완료\n"
                    f"• 분석 시간: {now.strftime('%H:%M')} (KST)\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"안심하고 일과를 보내시기 바랍니다, David님."
                )

        if final_msg:
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

    def execute_all(self):
        """[v10.3.0 핵심 로직] 감시 종목과 보유 종목 통합 감사 실행"""
        # 1. 데이터 로드: Watchlist(YAML) + Holdings(DB)
        yaml_watchlist = self.config_yaml.get('watchlist', [])
        holdings = self.db.get_all_holdings() #
        
        # 보유 종목 티커 리스트 추출 및 중복 제거 합치기
        holding_tickers = [h['ticker'] for h in holdings]
        total_audit_list = yaml_watchlist.copy()
        
        # Watchlist에 없는 보유 종목 추가
        for h_ticker in holding_tickers:
            if not any(item['ticker'] == h_ticker for item in total_audit_list):
                default_bench, b_name = get_regional_benchmark(h_ticker)
                
                total_audit_list.append({
                    'ticker': h_ticker, 
                    'name': h_ticker, 
                    'bench': default_bench,
                    'bench_name': b_name
                })                

        audit_results_summary = {}
        new_stocks, risk_up, risk_down = [], [], []
        macro_snapshot = self.ledger._get_macro_snapshot() or {}           

        # 2. 전수 조사 실행
        for item in total_audit_list:
            audit_data = self.run_audit(item, macro_snapshot)
            if audit_data:
                audit_results_summary[audit_data['ticker']] = audit_data
                # 델타 알림 메시지 생성 및 분류
                msg = self.reporter.build_delta_alert_msg(audit_data)
                if msg:
                    prev = audit_data.get('prev_score')
                    if prev is None: new_stocks.append(msg)
                    elif audit_data['score'] > prev: risk_up.append(msg)
                    else: risk_down.append(msg)

        # 3. 리포트 출력 및 발송
        # (1) 터미널: 감시 종목 요약표
        self.reporter.print_audit_summary_table(list(audit_results_summary.values()))
        
        # (2) [v10.3.0] 터미널: David's Fortress 실전 자산 리포트
        total_capital = self.config_yaml.get('settings', {}).get('total_capital', 500000000)
        # 1. 실시간 다중 환율 수급
        exchange_rates = self.indicators.get_exchange_rates()        
        self.reporter.print_fortress_report(holdings, audit_results_summary, total_capital, self.risk_engine, exchange_rates)

        # (3) 텔레그램: 스마트 메시지 발송
        delta_body = self.reporter.assemble_delta_alerts(new_stocks, risk_up, risk_down)
        if delta_body:
            self.messenger.send_smart_message(delta_body)
        
        # 4. 성과 분석 자동 호출
        performance_msg = self.analyzer.run_performance_audit() # 리스크 예측력 감사
        logger.info(f"📊 시스템 예측력 검증 완료")

# 메인 실행부에서 테스트 모드 호출
if __name__ == "__main__":
    app = SigmaGuard()
    app.execute_all()  # 실제 운용 시
    #app.test_messaging_pipeline() # 텔레그램 테스트 시