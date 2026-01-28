"""
[File Purpose]
- Phase 1~3 통합: v8.9.7 정통 리스크 감사 파이프라인 완성.
- 기능: 사후 수익률 결산(T+20), 리스크 델타(▲/▼) 추적, 지능형 자본 할당 보고.

[Key Features]
- Audit Delta: 전일 대비 리스크 점수 변동폭을 감지하여 조기 경보 수행.
- Performance Feedback: 전수 감사 후 등급별 성과 요약(SigmaAnalyzer) 자동 발행.
- 39-Header Mapping: 5개년 다중 시그마 및 리버모어 상태 등 모든 정밀 지표를 장부에 동기화.
"""

from core.indicators import Indicators
from core.risk_engine import RiskEngine
from core.sigma_analyzer import SigmaAnalyzer
from data.ledgers.ledger_handler import LedgerHandler
from utils.messenger import TelegramMessenger
from utils.logger import setup_custom_logger
from config.settings import settings
from datetime import datetime

logger = setup_custom_logger("SigmaGuard_Main")

class SigmaGuard:
    def __init__(self):
        # 1. 핵심 엔진 초기화
        self.indicators = Indicators()
        self.risk_engine = RiskEngine()
        self.ledger = LedgerHandler()
        self.messenger = TelegramMessenger()
        self.analyzer = SigmaAnalyzer(settings.DATA_DIR)

        logger.info("🛡️ SigmaGuard v8.9.7 통합 엔진 가동 (CPA David Edition)")

    def run_audit(self, ticker, name):
        """[Pipeline] 종목별 실전 감사, 사후 결산 및 델타 보고"""
        try:
            # 1. [Phase 3] 사후 수익률 결산 (감사 20일 경과 데이터 처리)
            self.ledger.update_forward_returns(ticker)

            # 2. [Phase 3] 전일 상태 조회 (델타 계산용)
            prev_level, prev_score = self.ledger.get_previous_state(ticker)

            # 3. [Phase 1] 지표 산출 (5년 통계 기반)
            ind_df = self.indicators.generate(ticker)
            if ind_df is None or ind_df.empty:
                logger.error(f"❌ [{ticker}] 시세 데이터 확보 실패")
                return

            # 4. [Phase 2] 리스크 및 자본 할당 평가
            score, grade_label, details = self.risk_engine.evaluate(ind_df)
            current_level = self.risk_engine._get_level(score)
            
            # 5. [Phase 1~3] 장부 기입용 데이터 매핑
            latest = ind_df.iloc[-1]
            market_date = latest.name.strftime('%Y-%m-%d')
            
            # 기술 지표 패키징 (39개 헤더 대응)
            tech_t = {
                'price': latest['Close'], 'rsi': latest['RSI'], 'mfi': latest['MFI'],
                'bbw': latest['bbw'], 'bbw_thr': latest['bbw_thr'],
                'adx': latest['ADX'], 'r2': latest['R2'], 'disp120': latest['disp120']
            }
            # 5개년 시그마 통계 패키징
            stat_t = {
                'avg_sigma': latest['avg_sigma'],
                'sig_1y': latest['sig_1y'], 'sig_2y': latest['sig_2y'],
                'sig_3y': latest['sig_3y'], 'sig_4y': latest['sig_4y'], 'sig_5y': latest['sig_5y']
            }
            # 자본 할당 정보
            alloc = {
                'stop_loss': details['stop_loss'],
                'risk_pct': ( (latest['Close'] - details['stop_loss']) / latest['Close'] ) * 100,
                'ei': details['ei'],
                'weight': details['weight_pct']
            }

            # 6. 장부 영구 저장 (39-Header Standard)
            self.ledger.save_entry(
                ticker, name, market_date,
                tech_t, stat_t, None, None, # 기초지수 데이터는 필요시 추가
                score, details, alloc, {}, details['liv_status']
            )

            # 7. 텔레그램 리포트 발송 (Level 3 이상 또는 변동 발생 시)
            self.send_report(ticker, name, current_level, score, prev_score, details)
            
            logger.info(f"✅ [{ticker}] 감사 완료: 현재 Level {current_level} ({score}점)")

        except Exception as e:
            logger.error(f"❌ [{ticker}] 감사 중 치명적 오류: {e}")

    def send_report(self, ticker, name, level, score, prev_score, details):
        """[Visual Audit Report] CPA 스타일의 정밀 요약 보고"""
        
        # 델타(변동폭) 계산 및 이모지 설정
        delta_str = ""
        if prev_score is not None:
            diff = score - prev_score
            sign = "▲" if diff > 0 else "▼" if diff < 0 else "-"
            delta_str = f"({sign}{abs(diff):.1f})"
        else:
            delta_str = "(신규)"

        emoji = "🚨" if level >= 5 else "🔴" if level == 4 else "🟡" if level == 3 else "✅"
        
        message = (
            f"{emoji} **[SG 감사 보고서] {name}({ticker})**\n"
            f"━━━━━━━━━━━━━━\n"
            f"• **상태**: {details['scenario']} (Lv.{level})\n"
            f"• **점수**: `{score:.1f}` 점 {delta_str}\n"
            f"• **가중치**: x{details['multiplier']:.2f} ({details['liv_status']})\n"
            f"━━━━━━━━━━━━━━\n"
            f"• **SOP 지침**: {details['action']}\n"
            f"• **권고 비중**: {details['weight_pct']}% (E.I: {details['ei']})\n"
            f"• **손절가**: {details['stop_loss']:,} (예상 Risk: {((details['stop_loss']/details['p1'])-1)*100 if details['p1']>0 else 0:.1f}%)\n"
            f"━━━━━━━━━━━━━━\n"
            f"📅 기준일자: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )
        self.messenger.send_message(message)

    def execute_all(self, universe):
        """유니버스 전수 조사 및 성과 분석 요약"""
        logger.info(f"🚀 총 {len(universe)}개 종목 전수 감사 및 결산 시작")
        
        for ticker, name in universe.items():
            self.run_audit(ticker, name)
        
        # [Phase 3] 전수 조사 후 리스크 등급별 성과 요약 발송
        perf_summary = self.analyzer.run_performance_audit()
        self.messenger.send_message(perf_summary)
        
        logger.info("🏁 오늘의 자산 감사 및 성과 보고 종료")

if __name__ == "__main__":
    app = SigmaGuard()
    
    # David님의 핵심 감사 유니버스
    my_universe = {
        "B": "Barrick Gold",            # 배릭 마이닝 (티커 B)
        "005930.KS": "Samsung Electronics", 
        "SOXL": "Direxion Daily Semi Bull 3X"
    }
    
    app.execute_all(my_universe)