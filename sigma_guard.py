"""
[File Purpose]
- Phase 1~5 통합: 실전 매매 DB 연동 및 David's Fortress 리포트 자동화.
- 기능: 보유 종목 자동 감지, 실시간 수익률 계산, 이중 손절선(Entry vs Reco) 감사.

[Key Features]
- DB Integrated Audit: holdings 테이블의 종목을 watchlist와 병합하여 자동 전수 감사.
- Fortress Visualization: 리포트 하단에 David 전용 전략 자산 운용 현황(Fortress) 출력.
- Performance Feedback: DB 기반 실전 매매 통계와 CSV 기반 리스크 예측력을 통합 분석.
"""

import pandas as pd
from datetime import datetime

# 핵심 모듈 임포트
from core.indicators import Indicators
from core.risk_engine import RiskEngine
from core.sigma_analyzer import SigmaAnalyzer
from core.db_handler import DBHandler          # [v10.3.0 추가] SQLite 핸들러
from core.entry_exit_engine import EntryExitEngine  # [신규] 진입/청산 신호 엔진
from data.ledgers.ledger_handler import LedgerHandler
from utils.messenger import TelegramMessenger
from utils.logger import setup_custom_logger
from utils.visual_reporter import VisualReporter
from config.settings import settings
from utils.market_utils import get_regional_benchmark

logger = setup_custom_logger("SigmaGuard_Main")

class SigmaGuard:
    def __init__(self):
        # 1. 앱 정보 및 전역 설정 (settings 싱글톤에서 직접 참조)
        self.app_info    = settings.CONFIG.get('app_info', {})
        self.sys_settings = settings.CONFIG.get('settings', {})

        # 2. 로거 및 리포터 초기화
        self.logger = logger
        self.db = DBHandler()
        self.reporter = VisualReporter(self.logger)

        # 3. 핵심 엔진 초기화
        self.indicators = Indicators()
        self.risk_engine = RiskEngine()
        self.ledger = LedgerHandler()
        self.ee_engine = EntryExitEngine(db=self.db)  # [신규] 진입/청산 신호 엔진 (DB 연동)
        
        # [v10.3.0 수정] 분석기에 DB 핸들러 주입 (실전 성과 분석용)
        self.analyzer = SigmaAnalyzer(self.db, settings.DATA_DIR)

        # 4. [v9.0.0] SecretConfig를 메신저에 주입 (보안 연결)
        self.messenger = TelegramMessenger(
            token=settings.TELEGRAM_TOKEN,
            chat_id=settings.CHAT_ID
        )

        logger.info(f"🛡️ {self.app_info.get('version')} {self.app_info.get('edition')} 가동")
        logger.info(f"👤 Auditor: {self.app_info.get('author')} (OCI Ready)")

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
                return None, None

            latest = ind_df.iloc[-1]
            market_date = ind_df.index[-1].strftime('%Y-%m-%d')

            # 2. 과거 데이터 복원
            _, prev_score = self.ledger.get_previous_state(ticker, market_date)
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

            # 6. 리포트 및 결과 반환
            self.reporter.print_audit_report(
                item, market_date, latest, bench_latest, 
                score, prev_score, details, alloc, bt_res
            )
            
            return {
                "ticker":      ticker,
                "name":        name,
                "market_date": market_date,
                "price":       latest.get('Close', 0.0),
                "score":       score,
                "prev_score":  prev_score,
                "action_text": details.get('action', '관망'),
                "liv_status":  details.get('liv_status', 'N/A'),
                "disp":        latest.get('disp120', 100.0),
                "ei":          alloc.get('ei', 0.0),
                "stop":        alloc.get('stop_loss', 0.0),
                "weight":      alloc.get('weight', 0.0)
            }, ind_df  # ind_df를 함께 반환하여 진입/청산 신호 엔진에서 활용

        except Exception as e:
            logger.error(f"❌ [{ticker}] 감사 중 치명적 오류: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return None, None

    def execute_all_prev(self):
        watchlist = settings.watchlist
        audit_results_summary = []
        # [핵심] 변화 감지를 위한 카테고리 바구니
        new_stocks, risk_up, risk_down = [], [], []
        macro_snapshot = self.ledger._get_macro_snapshot() or {}

        for item in watchlist:
            audit_data, _ = self.run_audit(item, macro_snapshot)
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

    """
    [Program Explanation] test_entry_exit_pipeline
    1. Mock ind_df 주입: 실제 yfinance 호출 없이 각 신호가 확실히 발동되는 경계값 데이터를 생성합니다.
    2. EntryExitEngine 직접 호출: execute_all() 과 동일한 신호 감지 흐름을 재현합니다.
    3. 실제 텔레그램 발송: send_smart_message() 를 통해 실제 수신 여부를 검증합니다.
    """

    def test_entry_exit_pipeline(self):
        """[David's Diagnostic Mode] 진입/청산 신호 파이프라인 실제 텔레그램 발송 검증"""
        self.logger.info("🧪 EntryExitEngine 파이프라인 테스트 시작 (Mock Data 주입)")

        signal_msgs = []

        # ─────────────────────────────────────────────────────────────
        # 케이스 1: UNH — 진입 트리거 (전 조건 발동 Mock)
        # ─────────────────────────────────────────────────────────────
        self.logger.info("  [1/3] UNH 진입 트리거 Mock 생성 중...")

        # B: avg_sigma 상승, C: macd_h 음수 구간 반등, D: MFI 과매도 반등 → 조건 B·C·D 충족
        unh_ind_df = pd.DataFrame([
            {'avg_sigma': 0.3,  'macd_h': -0.50, 'MFI': 25.0},  # T-2
            {'avg_sigma': 0.4,  'macd_h': -0.40, 'MFI': 35.0},  # T-1 (prev)
            {'avg_sigma': 0.6,  'macd_h': -0.10, 'MFI': 43.0},  # T   (latest)
        ])
        unh_score      = 20.0   # 레벨 3 (조건 A 충족)
        unh_prev_score = 40.0   # 직전 점수 > 현재 점수 (조건 E 충족)
        unh_weight     = 15.0

        is_entry, conditions = self.ee_engine.check_entry_trigger(
            ticker='UNH', score=unh_score, details={},
            ind_df=unh_ind_df, prev_score=unh_prev_score
        )
        if is_entry:
            cond_str = "\n  - ".join(conditions)
            signal_msgs.append(
                f"📡 <b>[UNH] 진입 검토</b>\n"
                f"충족 조건:\n  - {cond_str}\n"
                f"현재 점수: {unh_score:.1f}\n"
                f"권고 비중: {unh_weight:.1f}%"
            )
            self.logger.info(f"     ✅ 진입 트리거 발동 (충족 조건 {len(conditions)}개)")
        else:
            self.logger.warning("     ⚠️ 진입 트리거 미발동 — Mock 데이터 점검 필요")

        # ─────────────────────────────────────────────────────────────
        # 케이스 2: B (Barrick) — 트레일링 스탑 발동 Mock
        # avg=28.5, current=37.05(+30%), trailing_high=44.0
        # ATR=1.5, USD mult=4.0(+20~50%) → stop=44.0-6.0=38.0 → current(37.05)<38.0 → 발동
        # ─────────────────────────────────────────────────────────────
        self.logger.info("  [2/3] B(Barrick) 트레일링 스탑 Mock 생성 중...")

        b_avg_price     = 28.5
        b_current_price = round(b_avg_price * 1.30, 2)   # +30.0% → $37.05

        b_ind_df = pd.DataFrame([
            {'atr': 1.5, 'MFI': 45.0, 'RSI': 56.0, 'macd_h': 0.30, 'ADX': 22.0},  # T-2
            {'atr': 1.5, 'MFI': 43.0, 'RSI': 57.0, 'macd_h': 0.15, 'ADX': 21.0},  # T-1
            {'atr': 1.5, 'MFI': 42.0, 'RSI': 58.0, 'macd_h': 0.05, 'ADX': 21.0},  # T
        ])

        b_holding = {
            'ticker':        'B',
            'qty':           6000,
            'avg_price':     b_avg_price,
            'entry_stop':    round(b_avg_price * 0.90, 2),
            'last_updated':  '2025-08-01',
            'trailing_high': 44.0,   # trail_stop = 44.0 - 1.5×4.0 = 38.0 > current(37.05)
            'currency':      'USD',
        }

        grade, profit_pct, details = self.ee_engine.check_trailing_stop(
            holding=b_holding, current_price=b_current_price, ind_df=b_ind_df
        )
        if grade == 3:
            signal_msgs.append(
                f"🔴 <b>[B] 트레일링 스탑 전량청산</b>\n"
                f"수익률: {profit_pct:+.1f}%  |  ATR배수: {details.get('atr_mult')}x\n"
                f"고점: ${details.get('trailing_high', 0):.2f}  |  "
                f"스탑가: ${details.get('trail_stop_price', 0):.2f}\n"
                f"⚡ 권고 매도비율: {details.get('sell_ratio', 0)*100:.0f}%"
            )
            self.logger.info(f"     ✅ 트레일링 스탑 발동 (수익 {profit_pct:+.1f}%)")
        else:
            self.logger.warning("     ⚠️ 트레일링 스탑 미발동 — Mock 데이터 점검 필요")

        # ─────────────────────────────────────────────────────────────
        # 케이스 3: SOXL — 시간 기반 청산 (90일 초과, 수익 +2%)
        # ─────────────────────────────────────────────────────────────
        self.logger.info("  [3/3] SOXL 시간 기반 청산 Mock 생성 중...")

        soxl_avg_price     = 45.0
        soxl_current_price = round(soxl_avg_price * 1.02, 2)   # +2.0% → $45.9
        # 95일 전 진입 가정 → T+90 기회비용 조건 발동
        soxl_entry_date = (datetime.now() - pd.Timedelta(days=95)).strftime('%Y-%m-%d')

        soxl_holding = {
            'ticker':       'SOXL',
            'qty':          100,
            'avg_price':    soxl_avg_price,
            'entry_stop':   soxl_avg_price * 0.90,
            'last_updated': soxl_entry_date
        }

        exit_signal = self.ee_engine.check_time_based_exit(
            holding=soxl_holding, current_price=soxl_current_price
        )
        if exit_signal:
            signal_msgs.append(
                f"⏰ <b>[SOXL] 시간 초과 청산 검토</b>\n"
                f"보유 기간: {exit_signal['elapsed_days']}일\n"
                f"현재 수익률: {exit_signal['profit_pct']:+.1f}%\n"
                f"사유: {exit_signal['reason']}"
            )
            self.logger.info(f"     ✅ 시간 청산 발동 ({exit_signal['reason']}, "
                             f"{exit_signal['elapsed_days']}일, {exit_signal['profit_pct']:+.1f}%)")
        else:
            self.logger.warning("     ⚠️ 시간 청산 미발동 — Mock 데이터 점검 필요")

        # ─────────────────────────────────────────────────────────────
        # 텔레그램 발송
        # ─────────────────────────────────────────────────────────────
        if signal_msgs:
            header = (
                f"🧪 <b>[TEST] 매매 신호 파이프라인 검증</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"Mock 데이터로 3개 케이스 강제 발동 결과:\n\n"
            )
            self.messenger.send_smart_message(header + "\n\n".join(signal_msgs))
            self.logger.info(f"🏁 신호 {len(signal_msgs)}건 텔레그램 발송 완료")
        else:
            self.logger.error("❌ 신호 0건 — Mock 데이터 또는 엔진 로직 점검 필요")

    def execute_all(self):
        """[v10.3.0 핵심 로직] 감시 종목과 보유 종목 통합 감사 실행"""
        # 1. 데이터 로드: Watchlist(YAML) + Holdings(DB)
        yaml_watchlist = settings.watchlist
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
        ind_cache = {}  # [신규] 티커별 ind_df 캐시 (진입/청산 신호 감지용)
        new_stocks, risk_up, risk_down = [], [], []
        macro_snapshot = self.ledger._get_macro_snapshot() or {}

        # 2. 전수 조사 실행
        for item in total_audit_list:
            audit_data, ind_df = self.run_audit(item, macro_snapshot)
            if audit_data:
                ticker = audit_data['ticker']
                audit_results_summary[ticker] = audit_data
                ind_cache[ticker] = ind_df  # [신규] ind_df 캐시 저장
                # 델타 알림 메시지 생성 및 분류
                msg = self.reporter.build_delta_alert_msg(audit_data)
                if msg:
                    prev = audit_data.get('prev_score')
                    if prev is None: new_stocks.append(msg)
                    elif audit_data['score'] > prev: risk_up.append(msg)
                    else: risk_down.append(msg)

        # 2.5 사후 결산(update_forward_returns) — 감사 루프 완료 후 일괄 처리
        # run_audit() 내부에서 호출하면 yfinance hang 시 전체 루프가 중단되므로 분리
        # time.sleep(1): 티커 간 간격으로 yfinance rate limit 회피 및 OCI 부하 분산
        import time
        for ticker in list(audit_results_summary.keys()):
            try:
                self.ledger.update_forward_returns(ticker)
            except Exception as e:
                logger.warning(f"⚠️ [{ticker}] 사후 결산 실패 (스킵): {e}")
            time.sleep(1)

        # 3. 리포트 출력 및 발송
        # (1) 터미널: 감시 종목 요약표
        self.reporter.print_audit_summary_table(list(audit_results_summary.values()))

        # (2) [v10.3.0] 터미널: David's Fortress 실전 자산 리포트
        total_capital = self.sys_settings.get('total_capital', 500000000)
        # 실시간 다중 환율 수급
        exchange_rates = self.indicators.get_exchange_rates()
        self.reporter.print_fortress_report(holdings, audit_results_summary, total_capital, self.risk_engine, exchange_rates)

        # (3) 텔레그램: 델타 알림 발송
        delta_body = self.reporter.assemble_delta_alerts(new_stocks, risk_up, risk_down)
        if delta_body:
            self.messenger.send_smart_message(delta_body)

        # [신규] 4. 진입/청산 신호 감지 및 텔레그램 발송
        signal_msgs  = []   # 진입트리거 · 시간청산 · 트레일링 1단계
        trail_action = []   # 트레일링 2~3단계 (별도 강조 발송)

        # 4-1. 진입 트리거: 감사 완료 종목 전체 대상
        # yaml_watchlist + holdings-only 티커 모두 포함 (total_audit_list 기준)
        # → DB에만 있는 보유 종목의 추가매수 신호도 놓치지 않음
        entry_checked = set()  # 중복 체크 방지
        for ticker, audit_data in audit_results_summary.items():
            if ticker in entry_checked:
                continue
            entry_checked.add(ticker)
            is_entry, conditions = self.ee_engine.check_entry_trigger(
                ticker=ticker,
                score=audit_data['score'],
                details={},
                ind_df=ind_cache.get(ticker),
                prev_score=audit_data.get('prev_score')
            )
            if is_entry:
                cond_str = "\n  - ".join(conditions)
                signal_msgs.append(
                    f"📡 <b>[{ticker}] 진입 검토</b>\n"
                    f"충족 조건:\n  - {cond_str}\n"
                    f"현재 점수: {audit_data['score']:.1f}\n"
                    f"권고 비중: {audit_data.get('weight', 0.0):.1f}%"
                )

        # 4-2. 청산 신호 감지: 보유 종목 대상 (entry_stop → 트레일링 → 리스크레벨 → 시간 순)
        for holding in holdings:
            ticker = holding['ticker']
            if ticker not in audit_results_summary:
                continue
            audit_data    = audit_results_summary[ticker]
            current_price = audit_data.get('price', 0.0)
            ind_df        = ind_cache.get(ticker)
            score         = audit_data.get('score', 0.0)

            # ── 신호 1: Entry Stop 손절 (최우선) ──────────────────────
            if self.ee_engine.check_entry_stop(holding, current_price):
                entry_stop = holding.get('entry_stop', 0.0)
                trail_action.append(
                    f"🛑 <b>[{ticker}] Entry Stop 손절</b>\n"
                    f"  현재가: {current_price:.2f}  |  손절가: {entry_stop:.2f}\n"
                    f"  ⚡ 권고 매도비율: 100%"
                )
                continue  # entry_stop 발동 시 다른 청산 신호 불필요

            # ── 신호 2: 트레일링 스탑 ─────────────────────────────────
            grade, profit_pct, details = self.ee_engine.check_trailing_stop(
                holding, current_price, ind_df
            )
            if grade == 3:
                atr_mult   = details.get('atr_mult', 0)
                trail_hi   = details.get('trailing_high', 0)
                stop_price = details.get('trail_stop_price', 0)
                currency   = details.get('currency', 'USD')
                trail_action.append(
                    f"🔴 <b>[{ticker}] 트레일링 스탑 전량청산</b>\n"
                    f"  수익률: {profit_pct:+.1f}%  |  {currency} ATR배수: {atr_mult}x\n"
                    f"  고점: {trail_hi:.2f}  |  스탑가: {stop_price:.2f}\n"
                    f"  ⚡ 권고 매도비율: 100%"
                )

            # ── 신호 3: 리스크 레벨 기반 청산 ────────────────────────
            risk_level = self.risk_engine.get_level(score)
            triggered, ratio, reason = self.ee_engine.check_risk_level_exit(risk_level)
            if triggered:
                trail_action.append(
                    f"⚠️ <b>[{ticker}] 리스크 레벨 청산 ({reason})</b>\n"
                    f"  현재 점수: {score:.1f}  |  레벨: {risk_level}\n"
                    f"  ⚡ 권고 매도비율: {ratio*100:.0f}%"
                )

            # ── 신호 4: 시간 기반 청산 ────────────────────────────────
            exit_signal = self.ee_engine.check_time_based_exit(holding, current_price)
            if exit_signal:
                signal_msgs.append(
                    f"⏰ <b>[{ticker}] 시간 초과 청산 검토</b>\n"
                    f"  보유 기간: {exit_signal['elapsed_days']}일\n"
                    f"  현재 수익률: {exit_signal['profit_pct']:+.1f}%\n"
                    f"  사유: {exit_signal['reason']}"
                )

        # 4-3. 신호 발송
        # (A) 트레일링 2~3단계 — 별도 강조 발송
        if trail_action:
            action_header = (
                f"🚨 <b>[긴급 매도 신호]</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
            )
            self.messenger.send_smart_message(action_header + "\n\n".join(trail_action))
            logger.info(f"🚨 트레일링 스탑 2~3단계 {len(trail_action)}건 긴급 발송")

        # (B) 진입트리거 · 시간청산 · 트레일링 1단계 통합 발송
        if signal_msgs:
            header = (
                f"🎯 <b>[매매 신호 감지]</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
            )
            self.messenger.send_smart_message(header + "\n\n".join(signal_msgs))
            logger.info(f"📡 매매 신호 {len(signal_msgs)}건 발송 완료")

        if not trail_action and not signal_msgs:
            logger.info("✅ 매매 신호 없음 (진입/청산 조건 미충족)")

        # 5. 성과 분석 자동 호출
        self.analyzer.run_performance_audit()
        logger.info("📊 시스템 예측력 검증 완료")

# 메인 실행부에서 테스트 모드 호출
if __name__ == "__main__":
    app = SigmaGuard()
    app.execute_all()               # 실제 운용 시
    #app.test_messaging_pipeline()  # 텔레그램 델타/대시보드 테스트 시
    #app.test_entry_exit_pipeline() # 매매 신호(진입/트레일링/시간청산) 테스트 시