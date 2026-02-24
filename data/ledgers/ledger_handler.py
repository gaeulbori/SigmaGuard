"""
[File Purpose]
- 3단계 보완: 종목별 기술 지표 저장 및 20일 사후 성과(Ret_20d) 자동 결산 엔진.
- David님의 v8.9.7 표준 39개 헤더 규격 준수 및 전기 이월(Delta) 데이터 정합성 확보.

[Key Features]
- Post-Audit (사후 결산): 감사 20일 후 실제 수익률, 최고/최저 수익률을 yfinance로 추적하여 자동 기입.
- Delta Tracking: 오늘 데이터를 제외한 최신 과거 기록을 참조하여 리스크 변동폭(▲/▼) 산출 지원.
- KRW/USD Intelligent Formatting: 원화는 정수, 달러는 소수점 3자리로 통화별 맞춤형 기록.
"""

"""
[File Purpose]
- v9.5.0: 매크로 지표(VIX, US10Y, DXY) 자동 수집 및 장부 기록 엔진.
- David님의 v8.9.7 표준 규격에 거시 경제 상황 데이터 3종 추가 통합.
"""

import os
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
from config.settings import settings
from utils.logger import setup_custom_logger
from core.risk_engine import RiskEngine

logger = setup_custom_logger("LedgerHandler")

class LedgerHandler:
    def __init__(self):
        self.data_dir = settings.DATA_DIR / "ledgers"
        if not self.data_dir.exists():
            self.data_dir.mkdir(parents=True, exist_ok=True)
        self._risk_engine = RiskEngine()

        # 표준 53개 헤더 규격 (David's Master Spec)
        self.headers = [
            "Audit_Date", "Ticker", "Name", "Risk_Score", "Risk_Level", "Price_T",
            "Sigma_T_Avg", "Sigma_T_1y", "Sigma_T_2y", "Sigma_T_3y", "Sigma_T_4y", "Sigma_T_5y",
            "RSI_T", "MFI_T", "BBW_T", "R2_T", "ADX_T", "Disp_T_120",
            "Ticker_B", "Price_B", "Sigma_B_Avg", "RSI_B", "MFI_B", "ADX_B", "BBW_B",
            "Stop_Price", "Risk_Gap_Pct", "Invest_EI", "Weight_Pct", "Expected_MDD",
            "Livermore_Status", "Base_Raw_Score", "Risk_Multiplier", "Trend_Scenario",
            "Score_Pos", "Score_Pos_EMA", "Score_Ene", "Score_Ene_EMA", 
            "Score_Trap", "Score_Trap_EMA", "VIX_T", "US10Y_T", "DXY_T",
            "MACD_Hist_T", "MACD_Hist_B", "ADX_Gap", "Disp_Limit", "BBW_Thr", "LIV_Discount", "SOP_Action",
            "Ret_20d", "Min_Ret_20d", "Max_Ret_20d"
        ]

    def _get_macro_snapshot(self):
        """글로벌 매크로 지표 일괄 수집"""
        macro_tickers = {"^VIX": "VIX_T", "^TNX": "US10Y_T", "DX-Y.NYB": "DXY_T"}
        results = {"VIX_T": 0.0, "US10Y_T": 0.0, "DXY_T": 0.0}
        try:
            data = yf.download(list(macro_tickers.keys()), period="5d", progress=False, auto_adjust=True)            
            if not data.empty:
                for ticker, field in macro_tickers.items():
                    valid_series = data['Close'][ticker].dropna()
                    if not valid_series.empty:
                        results[field] = round(float(valid_series.iloc[-1]), 2)
        except Exception as e:
            logger.warning(f"⚠️ 매크로 수집 실패: {e}")
        return results

    def _get_file_path(self, ticker):
        return self.data_dir / f"sigma_guard_ledger_{ticker}.csv"

    def _get_level(self, score):
        return self._risk_engine.get_level(score)

    def _format_value(self, ticker, value, category="normal"):
        """[David's Refined Standard] 통화별/지표별 자릿수 정밀 제어"""
        if value is None or pd.isna(value): return 0.0
        try:
            val = float(value)
        except (ValueError, TypeError): return value

        is_krw = any(s in str(ticker) for s in ['.KS', '.KQ'])
        if category == "price":
            return int(round(val, 0)) if is_krw else round(val, 3)
        elif category == "score": return round(val, 1)
        elif category == "sigma": return round(val, 3)
        elif category in ["indicator", "disparity"]: return round(val, 1)
        elif category in ["math", "oscillator"]: return round(val, 4)
        elif category in ["macro", "return"]: return round(val, 2)
        return round(val, 3)

    def save_entry(self, ticker, name, market_date, latest, score, details, alloc, bt_res, macro_data, bench_latest=None, bench_ticker='N/A'):
        """[v9.8.6 Fix] FutureWarning 해결 및 데이터 무결성 보강"""
        file_path = self._get_file_path(ticker)
        
        # 1. 데이터 조립 (카테고리 기반 포맷팅 적용)
        row_data = {
            "Audit_Date": market_date,
            "Ticker": ticker,
            "Name": name,
            "Risk_Score": self._format_value(ticker, score, "score"),
            "Risk_Level": self._get_level(score),
            "Price_T": self._format_value(ticker, latest.get('Close', 0), "price"),
            "Sigma_T_Avg": self._format_value(ticker, latest.get('avg_sigma', 0), "sigma"),
            "Sigma_T_1y": self._format_value(ticker, latest.get('sig_1y', 0), "sigma"),
            "Sigma_T_2y": self._format_value(ticker, latest.get('sig_2y', 0), "sigma"),
            "Sigma_T_3y": self._format_value(ticker, latest.get('sig_3y', 0), "sigma"),
            "Sigma_T_4y": self._format_value(ticker, latest.get('sig_4y', 0), "sigma"),
            "Sigma_T_5y": self._format_value(ticker, latest.get('sig_5y', 0), "sigma"),
            "RSI_T": self._format_value(ticker, latest.get('RSI', 0), "indicator"),
            "MFI_T": self._format_value(ticker, latest.get('MFI', 0), "indicator"),
            "BBW_T": self._format_value(ticker, latest.get('bbw', 0), "math"),
            "R2_T": self._format_value(ticker, latest.get('R2', 0), "math"),
            "ADX_T": self._format_value(ticker, latest.get('ADX', 0), "indicator"),
            "Disp_T_120": self._format_value(ticker, latest.get('disp120', 0), "disparity"),
            "Ticker_B": bench_ticker,
            "Price_B": self._format_value(bench_ticker, bench_latest.get('Close', 0) if bench_latest is not None else 0, "price"),
            "Sigma_B_Avg": self._format_value(bench_ticker, bench_latest.get('avg_sigma', 0) if bench_latest is not None else 0, "sigma"),
            "RSI_B": self._format_value(bench_ticker, bench_latest.get('RSI', 0) if bench_latest is not None else 0, "indicator"),
            "MFI_B": self._format_value(bench_ticker, bench_latest.get('MFI', 0) if bench_latest is not None else 0, "indicator"),
            "ADX_B": self._format_value(bench_ticker, bench_latest.get('ADX', 0) if bench_latest is not None else 0, "indicator"),
            "BBW_B": self._format_value(bench_ticker, bench_latest.get('bbw', 0) if bench_latest is not None else 0, "math"),
            "Stop_Price": self._format_value(ticker, alloc.get('stop_loss', 0), "price"),
            "Risk_Gap_Pct": self._format_value(ticker, alloc.get('risk_pct', 0), "return"),
            "Invest_EI": round(alloc.get('ei', 0), 2),
            "Weight_Pct": alloc.get('weight', 0),
            "Expected_MDD": round(bt_res.get('avg_mdd', 0.0), 2),
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
            "VIX_T": self._format_value("", macro_data.get("VIX_T", 0), "macro"),
            "US10Y_T": self._format_value("", macro_data.get("US10Y_T", 0), "macro"),
            "DXY_T": self._format_value("", macro_data.get("DXY_T", 0), "macro"),
            "MACD_Hist_T": self._format_value(ticker, details.get('macd_h', 0.0), "math"),
            "MACD_Hist_B": self._format_value(bench_ticker, details.get('bench_macd_h', 0.0), "math"),
            "ADX_Gap": round(details.get('discrepancy', 0.0), 1),
            "Disp_Limit": round(latest.get('disp120_limit', 0.0), 1),
            "BBW_Thr": round(latest.get('bbw_thr', 0.3), 4),
            "LIV_Discount": round(details.get('liv_discount', 0.0), 2),
            "SOP_Action": details.get('action', 'N/A')
        }

        # 2. 파일 저장 및 타입 강제 (FutureWarning 방지)
        if file_path.exists():
            df = pd.read_csv(file_path)
            # 문자열 컬럼 강제 타입 지정
            str_cols = ["Audit_Date", "Ticker", "Name", "Trend_Scenario", "Livermore_Status", "SOP_Action", "Ticker_B"]
            for col in str_cols:
                if col in df.columns: df[col] = df[col].astype(object)
            
            # 숫자 컬럼 강제 타입 지정
            num_cols = [c for c in self.headers if c not in str_cols]
            for col in num_cols:
                if col in df.columns: df[col] = pd.to_numeric(df[col], errors='coerce')

            existing_idx = df.index[df['Audit_Date'] == market_date].tolist()
            if existing_idx:
                for key, val in row_data.items(): df.at[existing_idx[0], key] = val
            else:
                df = pd.concat([df, pd.DataFrame([row_data])], ignore_index=True)
        else:
            df = pd.DataFrame([row_data]).reindex(columns=self.headers)

        df.to_csv(file_path, index=False, encoding='utf-8-sig')

    def update_forward_returns(self, ticker):
        file_path = self._get_file_path(ticker)
        if not file_path.exists(): return
        df = pd.read_csv(file_path)
        df['Audit_Date'] = pd.to_datetime(df['Audit_Date'])
        mask = df['Ret_20d'].isna() & (df['Audit_Date'] <= datetime.now() - timedelta(days=20))
        target_rows = df[mask]
        if target_rows.empty: return
        for idx, row in target_rows.iterrows():
            try:
                audit_date = row['Audit_Date']
                hist = yf.download(ticker, start=audit_date, end=audit_date + timedelta(days=30), progress=False, auto_adjust=True)
                if not hist.empty:
                    period_data = hist.iloc[:15]
                    p0 = float(row['Price_T'])
                    df.at[idx, 'Ret_20d'] = round(((period_data['Close'].iloc[-1] - p0) / p0) * 100, 2)
                    df.at[idx, 'Max_Ret_20d'] = round(((period_data['High'].max() - p0) / p0) * 100, 2)
                    df.at[idx, 'Min_Ret_20d'] = round(((period_data['Low'].min() - p0) / p0) * 100, 2)
            except Exception: continue
        df['Audit_Date'] = df['Audit_Date'].dt.strftime('%Y-%m-%d')
        df.to_csv(file_path, index=False, encoding='utf-8-sig')

    def get_previous_state(self, ticker, current_market_date):
        """[Fix] 마켓 날짜 기준 진짜 어제 점수 확보 (Delta 오류 해결)"""
        file_path = self._get_file_path(ticker)
        if not file_path.exists(): return None, None
        try:
            df = pd.read_csv(file_path)
            if df.empty: return None, None
            # 현재 마켓 날짜보다 이전인 데이터 중 가장 최신 것
            past_df = df[df['Audit_Date'] < current_market_date]
            if past_df.empty: return None, None
            last = past_df.iloc[-1]
            return int(last['Risk_Level']), float(last['Risk_Score'])
        except Exception: return None, None

    def get_previous_sub_scores(self, ticker, current_market_date):
        """[Fix] 마켓 날짜 기준 이전 EMA 점수 확보 (평활화 무결성)"""
        file_path = self._get_file_path(ticker)
        if not file_path.exists(): return None
        try:
            df = pd.read_csv(file_path)
            if df.empty: return None
            past_df = df[df['Audit_Date'] < current_market_date]
            if past_df.empty: return None
            last = past_df.iloc[-1]
            return {
                'p1_ema': last.get('Score_Pos_EMA', last.get('Score_Pos', 0)),
                'p2_ema': last.get('Score_Ene_EMA', last.get('Score_Ene', 0)),
                'p4_ema': last.get('Score_Trap_EMA', last.get('Score_Trap', 0))
            }
        except Exception: return None        