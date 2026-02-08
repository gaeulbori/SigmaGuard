"""
[Program 상세 설명]
1. Clean Logging: logging.FileHandler의 mode를 'w'로 설정하여 실행 시마다 기존 로그를 엎어 씁니다.
2. B&H MDD Audit: 전략의 MDD뿐만 아니라 '단순 보유 시 겪었을 최대 낙폭'을 산출하여 나란히 비교합니다.
3. Comparative Analytics: 수익률과 MDD를 대조하여 리스크 관리의 실질적 효용성을 검증합니다.
"""

import os
import sys
import yaml
import pandas as pd
import numpy as np
import logging
from datetime import datetime

# [Path Fix] David's Multi-Project Structure
current_dir = os.path.dirname(os.path.abspath(__file__)) # tests
sg_root = os.path.dirname(current_dir)                 # SG
work_root = os.path.dirname(sg_root)                   # work
common_root = os.path.join(work_root, "common")        # common

for path in [sg_root, common_root]:
    if path not in sys.path:
        sys.path.insert(0, path)

from core.indicators import Indicators
from core.risk_engine import RiskEngine
from utils.logger import setup_custom_logger

class SigmaSimulator:
    def __init__(self, config_name="SG_sim_config.yaml"):
        # 1. 기본 로거 설정
        self.logger = setup_custom_logger("Performance_Simulator")
        # 2. 파일 로깅 설정 (덮어쓰기 모드 반영)
        self._setup_file_logging()
        
        # 3. 설정 로드
        self.config_path = os.path.join(common_root, config_name)
        with open(self.config_path, "r", encoding="utf-8") as f:
            self.sim_config = yaml.safe_load(f)
        
        self.indicators = Indicators()
        self.risk_engine = RiskEngine()
        self.settings = self.sim_config['simulation_settings']
        self.exec_logic = self.settings['execution_logic']

    def _setup_file_logging(self):
        """[Update] 실행 시마다 로그를 엎어 쓰도록 mode='w' 적용"""
        log_dir = os.path.join(sg_root, "logs")
        if not os.path.exists(log_dir): os.makedirs(log_dir)
        log_file = os.path.join(log_dir, "sigma_guard_sim.log")
        
        # mode='w'는 기존 내용을 지우고 새로 작성합니다.
        file_handler = logging.FileHandler(log_file, mode='w', encoding='utf-8')
        file_handler.setFormatter(logging.Formatter('[%(asctime)s | %(levelname)s] %(message)s'))
        self.logger.addHandler(file_handler)
        self.logger.info(f"📝 시뮬레이션 로그 덮어쓰기 개시: {log_file}")

    def _get_currency(self, ticker):
        return "KRW" if ticker.endswith(".KS") else "USD"

    def run(self):
        self.logger.info(f"🚀 [{self.settings['name']}] 실전 잔고 시뮬레이션 개시")
        
        for item in self.sim_config['test_watchlist']:
            ticker = item['ticker']
            currency = self._get_currency(ticker)
            initial_cash = self.settings['capital'][f"{currency.lower()}_initial"]
            
            df_full, bench_full = self.indicators.generate(ticker, period="max", bench=item['bench'])
            df_test = df_full[self.settings['start_date']:self.settings['end_date']]
            
            cash = initial_cash
            shares = 0
            history = []

            self.logger.info(f"🔍 {ticker} ({currency}) 시뮬레이션 상세 장부 기록:")
            self.logger.info(f"{'Date':<12} | {'Lv':<2} | {'Price':>8} | {'Shares':>8} | {'Stock Value':>12} | {'Cash':>12} | {'Total (Equity)':>15}")
            self.logger.info("-" * 90)

            for current_date in df_test.index:
                ind_slice = df_full[:current_date]
                bench_slice = bench_full[:current_date] if bench_full is not None else None
                
                score, _, _ = self.risk_engine.evaluate(ind_slice, bench_slice)
                level = self.risk_engine._get_level(score)
                price = ind_slice['Close'].iloc[-1]
                
                # 1. 평가 전 총 자산 계산
                total_equity = cash + (shares * price)
                
                # 2. 리밸런싱 집행 (David's SOP Target Weight)
                target_weight = self.exec_logic.get(f"level_{level}", 0.5)
                target_value = total_equity * target_weight
                
                # 매매 집행 (이론적 수량 조정)
                shares = target_value / price
                cash = total_equity - (shares * price)
                
                # 3. 항목별 세부 데이터 확정
                stock_value = shares * price
                date_str = current_date.strftime('%Y-%m-%d')
                
                # 상세 로그 출력
                self.logger.info(
                    f"{date_str:<12} | "
                    f"{level:<2} | "
                    f"{price:>8,.2f} | "
                    f"{shares:>8.2f} | "
                    f"{stock_value:>12,.0f} | "
                    f"{cash:>12,.0f} | "
                    f"{total_equity:>15,.0f}"
                )

                history.append({
                    "date": current_date, "price": price, 
                    "score": score, "equity": total_equity
                })

            self._report_comparative_performance(ticker, currency, initial_cash, history)

    def _report_comparative_performance(self, ticker, curr, initial, history):
        """[핵심] 전략 vs 단순보유 MDD 정밀 비교 리포트"""
        df = pd.DataFrame(history)
        
        # 1. 전략(Strategy) 지표
        strat_final = df['equity'].iloc[-1]
        strat_ret = (strat_final - initial) / initial * 100
        df['strat_peak'] = df['equity'].cummax()
        df['strat_dd'] = (df['equity'] - df['strat_peak']) / df['strat_peak']
        strat_mdd = df['strat_dd'].min() * 100

        # 2. 단순보유(Buy & Hold) 지표
        bnh_start_p = df['price'].iloc[0]
        bnh_end_p = df['price'].iloc[-1]
        bnh_ret = (bnh_end_p - bnh_start_p) / bnh_start_p * 100
        df['bnh_peak'] = df['price'].cummax()
        df['bnh_dd'] = (df['price'] - df['bnh_peak']) / df['bnh_peak']
        bnh_mdd = df['bnh_dd'].min() * 100

        self.logger.info(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        self.logger.info(f"📊 [{ticker}] 전략 성과 분석 보고서 ({curr})")
        self.logger.info(f"   • 수익률 대조 | 전략: {strat_ret:>7.2f}% vs 단순보유: {bnh_ret:>7.2f}%")
        self.logger.info(f"   • 위험도 대조 | 전략 MDD: {strat_mdd:>5.2f}% vs 단순보유 MDD: {bnh_mdd:>5.2f}%")
        
        # 방어 효율성 계산
        mdd_saved = bnh_mdd - strat_mdd # 전략 MDD가 -10%고 B&H가 -30%면 20%p 개선
        self.logger.info(f"   🛡️ 리스크 방어 효과: {mdd_saved:.2f}%p 하락폭 절감")
        self.logger.info(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

if __name__ == "__main__":
    simulator = SigmaSimulator()
    simulator.run()