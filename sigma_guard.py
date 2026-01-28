"""
[File Purpose]
- SigmaGuard(SG) 시스템의 통합 가동 및 전수 감사 프로세스 총괄.
- 검증된 Indicators, RiskEngine, LedgerHandler를 연결하여 실전 파이프라인 완성.

[Key Features]
- End-to-End Audit: 시세 로드부터 장부 기입까지의 전 과정 자동 수행.
- Data Mapping: Indicators 산출 지표를 RiskEngine과 Ledger 규격에 정밀 매핑.
- Reliability: 전일 상태(Previous State) 대조를 통해 연속성 있는 리스크 관리 지원.
"""

from core.indicators import Indicators
from core.risk_engine import RiskEngine
from data.ledgers.ledger_handler import LedgerHandler
from utils.logger import setup_custom_logger
from datetime import datetime

logger = setup_custom_logger("SigmaGuard_Main")

class SigmaGuard:
    def __init__(self):
        self.indicators = Indicators()
        self.risk_engine = RiskEngine()
        self.ledger = LedgerHandler()
        logger.info("🛡️ SigmaGuard 시스템이 가동되었습니다. (v8.9.7+ Engine)")

    def run_audit(self, ticker, name):
        """[Pipeline] 종목별 실전 감사 및 장부 업데이트"""
        try:
            logger.info(f"🔍 [{ticker}] {name} 감사 프로세스 개시")

            # 1. 전일 상태 조회
            prev_level, prev_score = self.ledger.get_previous_state(ticker)
            if prev_level:
                logger.info(f"   - 전일 확정 상태: Level {prev_level} (Score: {prev_score})")

            # 2. 실시간 시세 로드 및 지표 산출
            ind_df = self.indicators.generate(ticker)
            if ind_df is None or ind_df.empty:
                logger.error(f"   - [{ticker}] 시세 데이터 확보 실패로 감사를 중단합니다.")
                return

            # 3. 리스크 평가 실행
            final_score, grade_label, details = self.risk_engine.evaluate(ind_df)
            
            # 4. 장부 기입용 데이터 매핑 (Indicators 결과물 -> Ledger 규격)
            latest = ind_df.iloc[-1]
            market_date = latest.name.strftime('%Y-%m-%d')
            
            # Target 지표(T) 및 기초 데이터 패키징
            tech_t = {
                'price': latest['Close'], 
                'rsi': latest['RSI'], 
                'mfi': latest['MFI'],
                'bbw': latest['bbw'],
                'adx': latest['ADX'],
                'r2': latest['R2'],
                'disp120': latest['disp120']
            }
            stat_t = {
                'avg_sigma': latest['avg_sigma']
                # 필요 시 sig_1y ~ sig_5y 추가 연동 가능
            }
            
            # 할당 및 트레이딩 정보 (RiskEngine의 action 결과 포함)
            alloc = {
                'stop_loss': latest.get('Close', 0) * 0.9, # 임시: 현재가 -10%
                'risk_pct': 10.0,
                'ei': 0, 'weight': 0 
            }
            liv_status = details.get('action', 'N/A')

            # 5. 장부 영구 저장
            self.ledger.save_entry(
                ticker, name, market_date,
                tech_t, stat_t, None, None, # Target(T) 데이터 위주 기록
                final_score, details, alloc, {}, liv_status
            )

            current_level = self.risk_engine._get_level(final_score)
            logger.info(f"✅ [{ticker}] 감사 완료: 현재 Level {current_level} ({grade_label})")

        except Exception as e:
            logger.error(f"❌ [{ticker}] 감사 중 치명적 오류: {e}")

    def execute_all(self, universe):
        """유니버스 전 종목 순회 감사"""
        logger.info(f"🚀 총 {len(universe)}개 종목에 대한 전수 감사를 시작합니다.")
        for ticker, name in universe.items():
            self.run_audit(ticker, name)
        logger.info("🏁 오늘의 모든 자산 감사가 종료되었습니다.")

if __name__ == "__main__":
    app = SigmaGuard()
    
    # David님의 핵심 유니버스 설정
    my_universe = {
        "B": "Barrick Gold",            # 배릭 마이닝 (티커 B)
        "005930.KS": "Samsung Electronics", # 삼성전자
        "SOXL": "Direxion Daily Semi Bull 3X" # 그리드 매매 대상
    }
    
    app.execute_all(my_universe)