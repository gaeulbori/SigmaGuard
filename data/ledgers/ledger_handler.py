"""
[File Purpose]
- 종목별 기술 지표 및 확정된 리스크 레벨을 CSV 장부(Ledger)로 영구 저장 및 관리.

[Key Features]
- Future-Proofing: reindex를 사용하여 pandas의 FutureWarning(concat 관련) 해결.
- Audit Integrity: 역산 없이 장부 내 'Risk_Level'을 직접 참조하여 과거 판단 근거 보존.
"""

import os
import pandas as pd
import numpy as np
from datetime import datetime
from config.settings import settings
from utils.logger import setup_custom_logger

logger = setup_custom_logger("LedgerHandler")

class LedgerHandler:
    def __init__(self):
        self.data_dir = settings.DATA_DIR
        if not self.data_dir.exists():
            self.data_dir.mkdir(parents=True)

        # v8.9.7+ 표준 39개 헤더 정의
        self.headers = [
            "Audit_Date", "Ticker", "Name", "Risk_Score", "Risk_Level", "Price_T",
            "Sigma_T_Avg", "Sigma_T_1y", "Sigma_T_2y", "Sigma_T_3y", "Sigma_T_4y", "Sigma_T_5y",
            "RSI_T", "MFI_T", "BBW_T", "R2_T", "ADX_T", "Disp_T_120",
            "Price_B", "Sigma_B_Avg", "RSI_B", "MFI_B", "ADX_B", "BBW_B",
            "Stop_Price", "Risk_Gap_Pct", "Invest_EI", "Weight_Pct", "Expected_MDD",
            "Livermore_Status", "Base_Raw_Score", "Risk_Multiplier", "Trend_Scenario",
            "Score_Pos", "Score_Ene", "Score_Trap",
            "Ret_20d", "Min_Ret_20d", "Max_Ret_20d"
        ]

    def _get_file_path(self, ticker):
        return self.data_dir / f"sigma_guard_ledger_{ticker}.csv"

    def _get_level(self, score):
        if score >= 81: return 5
        elif score >= 66: return 4
        elif score >= 46: return 3
        elif score >= 26: return 2
        else: return 1

    def _format_value(self, ticker, value, is_price=False):
        if value is None or pd.isna(value): return 0.0
        is_krw = any(s in ticker for s in ['.KS', '.KQ'])
        if is_price and is_krw:
            return int(round(float(value), 0))
        return round(float(value), 3)

    def save_entry(self, ticker, name, market_date, tech_t, stat_t, tech_b, stat_b, score, details, alloc, bt_res, liv_status):
        file_path = self._get_file_path(ticker)
        current_level = self._get_level(score)
        
        row_data = {
            "Audit_Date": market_date,
            "Ticker": ticker,
            "Name": name,
            "Risk_Score": round(score, 1),
            "Risk_Level": current_level,
            "Price_T": self._format_value(ticker, tech_t['price'], True),
            "Sigma_T_Avg": round(stat_t['avg_sigma'], 2),
            "Sigma_T_1y": round(stat_t.get('sig_1y', 0), 2),
            "Sigma_T_2y": round(stat_t.get('sig_2y', 0), 2),
            "Sigma_T_3y": round(stat_t.get('sig_3y', 0), 2),
            "Sigma_T_4y": round(stat_t.get('sig_4y', 0), 2),
            "Sigma_T_5y": round(stat_t.get('sig_5y', 0), 2),
            "RSI_T": round(tech_t['rsi'], 1),
            "MFI_T": round(tech_t['mfi'], 1),
            "BBW_T": round(tech_t.get('bbw', 0), 4),
            "R2_T": round(tech_t.get('r2', 0), 4),
            "ADX_T": round(tech_t.get('adx', 0), 1),
            "Disp_T_120": round(tech_t.get('disp120', 0), 1),
            "Price_B": self._format_value(ticker, tech_b['price'], True) if tech_b else 0.0,
            "Sigma_B_Avg": round(stat_b['avg_sigma'], 2) if stat_b else 0.0,
            "RSI_B": round(tech_b['rsi'], 1) if tech_b else 0.0,
            "MFI_B": round(tech_b['mfi'], 1) if tech_b else 0.0,
            "ADX_B": round(tech_b['adx'], 1) if tech_b else 0.0,
            "BBW_B": round(tech_b.get('bbw', 0), 4) if tech_b else 0.0,
            "Stop_Price": self._format_value(ticker, alloc['stop_loss'], True),
            "Risk_Gap_Pct": round(alloc['risk_pct'], 2),
            "Invest_EI": alloc['ei'],
            "Weight_Pct": alloc['weight'],
            "Expected_MDD": bt_res.get('avg_mdd', 0.0),
            "Livermore_Status": liv_status,
            "Base_Raw_Score": details.get('base_raw', 0),
            "Risk_Multiplier": details.get('multiplier', 1.0),
            "Trend_Scenario": details.get('scenario', 'N/A'),
            "Score_Pos": details.get('p1', 0),
            "Score_Ene": details.get('p2', 0),
            "Score_Trap": details.get('p4', 0)
        }

        if file_path.exists():
            df = pd.read_csv(file_path)
            existing_idx = df.index[df['Audit_Date'] == market_date].tolist()
            if existing_idx:
                idx = existing_idx[0]
                for key, val in row_data.items():
                    df.at[idx, key] = val
            else:
                new_row_df = pd.DataFrame([row_data])
                df = pd.concat([df, new_row_df], ignore_index=True)
        else:
            # 신규 파일 생성 시 reindex를 사용하여 39개 컬럼 구조와 데이터를 동시에 확립
            df = pd.DataFrame([row_data])
            df = df.reindex(columns=self.headers)

        df.to_csv(file_path, index=False, encoding='utf-8-sig')
        logger.info(f"💾 [{ticker}] 장부 기록 완료: {market_date}")

    def get_previous_state(self, ticker):
        file_path = self._get_file_path(ticker)
        if not file_path.exists(): return None, None
        try:
            df = pd.read_csv(file_path)
            if df.empty: return None, None
            today_str = datetime.now().strftime("%Y-%m-%d")
            past_df = df[df['Audit_Date'] != today_str]
            if past_df.empty: return None, None
            last_row = past_df.iloc[-1]
            # 기록된 리스크 레벨과 점수를 직접 추출
            return int(last_row['Risk_Level']), float(last_row['Risk_Score'])
        except Exception as e:
            logger.error(f"⚠️ [{ticker}] 과거 장부 분석 실패: {e}")
            return None, None