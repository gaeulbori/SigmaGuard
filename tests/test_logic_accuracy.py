import os
import sys
import yaml
import pandas as pd
import numpy as np
import yfinance as yf
import logging  # [추가] 표준 로깅 모듈
from datetime import datetime

# 1. 경로 설정
current_dir = os.path.dirname(os.path.abspath(__file__))
sg_root = os.path.dirname(current_dir)
work_root = os.path.dirname(sg_root)
common_root = os.path.join(work_root, "common")

for path in [sg_root, common_root]:
    if path not in sys.path:
        sys.path.insert(0, path)

from core.indicators import Indicators
from core.risk_engine import RiskEngine
from data.ledgers.ledger_handler import LedgerHandler
from utils.logger import setup_custom_logger

class SigmaAccuracyTester:
    def __init__(self):
        self.logger = setup_custom_logger("Logic_Validator")
        # 2. [추가] tests/logs/ 디렉토리에 파일 로깅 설정
        self._setup_file_logging()

        # [수정] LedgerHandler를 self.ledger로 명시적 초기화
        self.ledger = LedgerHandler()
        
        # 설정 로드
        self.config_yaml = self._load_main_config()
        self.watchlist = self.config_yaml.get('watchlist', [])
        
        self.indicators = Indicators()
        self.risk_engine = RiskEngine()
        
        self.test_data_dir = os.path.join(current_dir, "data")
        if not os.path.exists(self.test_data_dir):
            os.makedirs(self.test_data_dir)

    def _setup_file_logging(self):
        """실행 결과를 tests/logs/accuracy_test.log에 저장합니다."""
        log_dir = os.path.join(current_dir, "logs")
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
        
        log_file = os.path.join(log_dir, "accuracy_test.log")
        
        # 파일 핸들러 설정 (덮어쓰기 모드)
        file_handler = logging.FileHandler(log_file, mode='w', encoding='utf-8')
        file_handler.setFormatter(logging.Formatter('[%(asctime)s | %(levelname)s] %(message)s'))
        
        # 기존 로거에 핸들러 추가
        self.logger.addHandler(file_handler)
        self.logger.info(f"📝 테스트 로그 파일 기록 개시: {log_file}")

    def _load_main_config(self):
        yaml_path = os.path.join(common_root, "SG_config.yaml")
        if not os.path.exists(yaml_path):
            self.logger.error(f"❌ 설정 파일을 찾을 수 없습니다: {yaml_path}")
            sys.exit(1)
        with open(yaml_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _get_historical_macros(self, start_date, end_date):
        tickers = {"^VIX": "VIX_T", "^TNX": "US10Y_T", "DX-Y.NYB": "DXY_T"}
        data = yf.download(list(tickers.keys()), start=start_date, end=end_date, progress=False, auto_adjust=True)
        if isinstance(data.columns, pd.MultiIndex):
            data = data['Close']
        return data.rename(columns=tickers).ffill()

    def run_all_tests(self, start_date, end_date):
        self.logger.info(f"🚀 [Watchlist 전수 감사 시작] 기간: {start_date} ~ {end_date}")
        macro_df = self._get_historical_macros(start_date, end_date)
        
        for item in self.watchlist:
            ticker = item.get('ticker')
            name = item.get('name', ticker)
            bench = item.get('bench', '^KS200')
            
            csv_path = self.generate_full_historical_ledger(ticker, name, bench, start_date, end_date, macro_df)
            if csv_path:
                self.deep_analyze(csv_path)

    def generate_full_historical_ledger(self, ticker, name, bench, start_date, end_date, macro_df):
        self.logger.info(f"⏳ [{ticker}] 과거 데이터 생성 중...")
        
        df_full, bench_full = self.indicators.generate(ticker, period="max", bench=bench)
        if df_full is None or df_full.empty: return None
        
        df_full.index = pd.to_datetime(df_full.index)
        if bench_full is not None and not bench_full.empty:
            bench_full.index = pd.to_datetime(bench_full.index)
            
        test_range = df_full.loc[start_date:end_date].index
        full_records = []

        for current_date in test_range:
            ind_slice = df_full.loc[:current_date]
            bench_slice = bench_full.loc[:current_date] if bench_full is not None and not bench_full.empty else None
            
            latest = ind_slice.iloc[-1]
            b_latest = bench_slice.iloc[-1] if bench_slice is not None else None
            
            score, _, details = self.risk_engine.evaluate(ind_slice, bench_slice)
            alloc = self.risk_engine.apply_risk_management(latest, ind_slice)
            
            future_window = df_full.loc[current_date:].iloc[1:21]
            ret_20, min_ret, max_ret = np.nan, np.nan, np.nan
            if len(future_window) >= 1:
                p0 = latest['Close']
                ret_20 = ((future_window['Close'].iloc[-1] - p0) / p0) * 100
                min_ret = ((future_window['Low'].min() - p0) / p0) * 100
                max_ret = ((future_window['High'].max() - p0) / p0) * 100

            # [David's Standard] 53개 헤더 규격 및 자릿수 포맷팅 적용
            row = {
                "Audit_Date": current_date.strftime('%Y-%m-%d'),
                "Ticker": ticker, "Name": name,
                "Risk_Score": self.ledger._format_value(ticker, score, "score"),
                "Risk_Level": self.risk_engine._get_level(score),
                "Price_T": self.ledger._format_value(ticker, latest['Close'], "price"),
                
                "Sigma_T_Avg": self.ledger._format_value(ticker, latest.get('avg_sigma'), "sigma"),
                "Sigma_T_1y": self.ledger._format_value(ticker, latest.get('sig_1y'), "sigma"),
                "Sigma_T_2y": self.ledger._format_value(ticker, latest.get('sig_2y'), "sigma"),
                "Sigma_T_3y": self.ledger._format_value(ticker, latest.get('sig_3y'), "sigma"),
                "Sigma_T_4y": self.ledger._format_value(ticker, latest.get('sig_4y'), "sigma"),
                "Sigma_T_5y": self.ledger._format_value(ticker, latest.get('sig_5y'), "sigma"),
                
                "RSI_T": self.ledger._format_value(ticker, latest.get('RSI'), "indicator"),
                "MFI_T": self.ledger._format_value(ticker, latest.get('MFI'), "indicator"),
                "BBW_T": self.ledger._format_value(ticker, latest.get('bbw'), "math"),
                "R2_T": self.ledger._format_value(ticker, latest.get('R2'), "math"),
                "ADX_T": self.ledger._format_value(ticker, latest.get('ADX'), "indicator"),
                "Disp_T_120": self.ledger._format_value(ticker, latest.get('disp120'), "disparity"),
                
                "Ticker_B": bench,
                "Price_B": self.ledger._format_value(bench, b_latest['Close'], "price") if b_latest is not None else 0,
                "Sigma_B_Avg": self.ledger._format_value(bench, b_latest.get('avg_sigma'), "sigma") if b_latest is not None else 0,
                "RSI_B": self.ledger._format_value(bench, b_latest.get('RSI'), "indicator") if b_latest is not None else 0,
                "MFI_B": self.ledger._format_value(bench, b_latest.get('MFI'), "indicator") if b_latest is not None else 0,
                "ADX_B": self.ledger._format_value(bench, b_latest.get('ADX'), "indicator") if b_latest is not None else 0,
                "BBW_B": self.ledger._format_value(bench, b_latest.get('bbw'), "math") if b_latest is not None else 0,
                
                "Stop_Price": self.ledger._format_value(ticker, alloc['stop_loss'], "price"),
                "Risk_Gap_Pct": self.ledger._format_value(ticker, alloc['risk_pct'], "return"),
                "Invest_EI": round(alloc.get('ei', 0), 2),
                "Weight_Pct": alloc.get('weight', 0),
                "Expected_MDD": -5.0,
                "Livermore_Status": details.get('liv_status', 'N/A'),
                "Base_Raw_Score": round(details.get('base_raw', 0), 1),
                "Risk_Multiplier": round(details.get('multiplier', 1.0), 2),
                "Trend_Scenario": details.get('scenario', 'N/A'),
                "Score_Pos": round(details.get('p1', 0), 1),
                "Score_Pos_EMA": round(details.get('p1_ema', 0), 1),
                "Score_Ene": round(details.get('p2', 0), 1),
                "Score_Ene_EMA": round(details.get('p2_ema', 0), 1),
                "Score_Trap": round(details.get('p4', 0), 1),
                "Score_Trap_EMA": round(details.get('p4_ema', 0), 1),
                
                "VIX_T": self.ledger._format_value("", macro_df.loc[current_date, 'VIX_T'], "macro") if current_date in macro_df.index else 0,
                "US10Y_T": self.ledger._format_value("", macro_df.loc[current_date, 'US10Y_T'], "macro") if current_date in macro_df.index else 0,
                "DXY_T": self.ledger._format_value("", macro_df.loc[current_date, 'DXY_T'], "macro") if current_date in macro_df.index else 0,
                
                "MACD_Hist_T": self.ledger._format_value(ticker, latest.get('macd_h'), "math"),
                "MACD_Hist_B": self.ledger._format_value(bench, b_latest.get('macd_h'), "math") if b_latest is not None else 0,
                "ADX_Gap": round(details.get('discrepancy', 0), 1),
                "Disp_Limit": round(latest.get('disp120_limit', 0), 1),
                "BBW_Thr": round(latest.get('bbw_thr', 0.3), 4),
                "LIV_Discount": round(details.get('liv_discount', 0), 2),
                "SOP_Action": details.get('action', 'N/A'),
                "Ret_20d": self.ledger._format_value("", ret_20, "return"),
                "Min_Ret_20d": self.ledger._format_value("", min_ret, "return"),
                "Max_Ret_20d": self.ledger._format_value("", max_ret, "return")
            }
            full_records.append(row)

        path = os.path.join(self.test_data_dir, f"full_accuracy_{ticker.replace('.', '_')}.csv")
        pd.DataFrame(full_records).to_csv(path, index=False, encoding='utf-8-sig')
        return path

    def deep_analyze(self, csv_path):
        """리스크 레벨별 수익률의 기대 범위(Avg, Min, Max)를 정밀 분석합니다."""
        df = pd.read_csv(csv_path)
        
        # 데이터 타입 변환 및 결측치 제거
        for col in ['Ret_20d', 'Min_Ret_20d', 'Max_Ret_20d']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        
        df = df.dropna(subset=['Ret_20d'])
        if df.empty: return

        ticker = df['Ticker'].iloc[0]
        # 리스크 점수와 낙폭(Min_Ret) 간의 상관관계 (방어 성능 측정)
        corr_min = df['Risk_Score'].corr(df['Min_Ret_20d'])
        
        self.logger.info(f"")
        self.logger.info(f"============================================================")
        self.logger.info(f"📊 [Sigma Guard Deep Analytics: {ticker}]")
        self.logger.info(f"------------------------------------------------------------")
        self.logger.info(f"• 리스크-낙폭 상관계수: {corr_min:.4f} (낮을수록 하락 감지 정확함)")
        self.logger.info(f"• 레벨별 사후 20일 성과 (평균 [최저 ~ 최고]):")
        
        # 레벨별로 평균, 최저의 평균, 최고의 평균 산출
        stats = df.groupby('Risk_Level').agg({
            'Ret_20d': 'mean',
            'Min_Ret_20d': 'mean',
            'Max_Ret_20d': 'mean'
        })

        for lvl, row in stats.iterrows():
            avg_r = row['Ret_20d']
            min_r = row['Min_Ret_20d']
            max_r = row['Max_Ret_20d']
            
            # David님의 가독성을 위해 포맷팅 (평균 [최저 ~ 최고])
            self.logger.info(f"  - Level {lvl}:  {avg_r:>6.2f}%  [{min_r:>6.2f}% ~ {max_r:>6.2f}%]")
            
        self.logger.info(f"============================================================")

if __name__ == "__main__":
    tester = SigmaAccuracyTester()
    tester.run_all_tests(start_date="2025-01-01", end_date="2025-12-31")