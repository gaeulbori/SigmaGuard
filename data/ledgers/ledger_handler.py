"""
[File Purpose]
- 3단계 보완: 종목별 기술 지표 저장 및 20일 사후 성과(Ret_20d) 자동 결산 엔진.
- David님의 v8.9.7 표준 39개 헤더 규격 준수 및 전기 이월(Delta) 데이터 정합성 확보.

[Key Features]
- Post-Audit (사후 결산): 감사 20일 후 실제 수익률, 최고/최저 수익률을 yfinance로 추적하여 자동 기입.
- Delta Tracking: 오늘 데이터를 제외한 최신 과거 기록을 참조하여 리스크 변동폭(▲/▼) 산출 지원.
- KRW/USD Intelligent Formatting: 원화는 정수, 달러는 소수점 3자리로 통화별 맞춤형 기록.
"""

import os
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
from config.settings import settings
from utils.logger import setup_custom_logger

logger = setup_custom_logger("LedgerHandler")

class LedgerHandler:
    def __init__(self):
        self.data_dir = settings.DATA_DIR / "ledgers"
        if not self.data_dir.exists():
            self.data_dir.mkdir(parents=True, exist_ok=True)

        # v8.9.7+ 표준 39개 헤더 정의 (성과 분석 컬럼 포함)
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
        """[Audit Step] 당일 감사 결과를 장부에 기록 (Update or Insert)"""
        file_path = self._get_file_path(ticker)
        current_level = self._get_level(score)
        
        # [보정 1] 가격 매핑 로직 강화 (tech_b 참조 오류 수정)
        current_price_t = tech_t.get('Close') or tech_t.get('price') or 0.0
        current_price_b = (tech_b.get('Close') or tech_b.get('price') or 0.0) if tech_b else 0.0

        row_data = {
            "Audit_Date": market_date,
            "Ticker": ticker,
            "Name": name,
            "Risk_Score": round(score, 1),
            "Risk_Level": current_level,
            "Price_T": self._format_value(ticker, current_price_t, True),
            "Sigma_T_Avg": round(stat_t.get('avg_sigma', 0), 2),
            "Sigma_T_1y": round(stat_t.get('sig_1y', 0), 2),
            "Sigma_T_2y": round(stat_t.get('sig_2y', 0), 2),
            "Sigma_T_3y": round(stat_t.get('sig_3y', 0), 2),
            "Sigma_T_4y": round(stat_t.get('sig_4y', 0), 2),
            "Sigma_T_5y": round(stat_t.get('sig_5y', 0), 2),
            # [보정 2] 지표 대소문자 유연 대응
            "RSI_T": round(tech_t.get('RSI', tech_t.get('rsi', 0)), 1),
            "MFI_T": round(tech_t.get('MFI', tech_t.get('mfi', 0)), 1),
            "BBW_T": round(tech_t.get('bbw', tech_t.get('BBW', 0)), 4),
            "R2_T": round(tech_t.get('R2', tech_t.get('r2', 0)), 4),
            "ADX_T": round(tech_t.get('ADX', tech_t.get('adx', 0)), 1),
            "Disp_T_120": round(tech_t.get('disp120', tech_t.get('Disp120', 0)), 1),
            "Price_B": self._format_value(ticker, current_price_b, True) if tech_b else 0.0,
            "Sigma_B_Avg": round(stat_b['avg_sigma'], 2) if stat_b else 0.0,
            # 벤치마크 지표도 안전하게 get 처리
            "RSI_B": round(tech_b.get('RSI', tech_b.get('rsi', 0)), 1) if tech_b else 0.0,
            "MFI_B": round(tech_b.get('MFI', tech_b.get('mfi', 0)), 1) if tech_b else 0.0,
            "ADX_B": round(tech_b.get('ADX', tech_b.get('adx', 0)), 1) if tech_b else 0.0,
            "BBW_B": round(tech_b.get('bbw', tech_b.get('BBW', 0)), 4) if tech_b else 0.0,
            "Stop_Price": self._format_value(ticker, alloc.get('stop_loss', 0), True),
            "Risk_Gap_Pct": round(alloc.get('risk_pct', 0), 2),
            "Invest_EI": alloc.get('ei', 0),
            "Weight_Pct": alloc.get('weight', 0),
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
            
            # [v9.0.1 긴급 패치] 모든 숫자 컬럼을 float로 강제 변환하여 dtype 충돌 방지
            numeric_cols = [c for c in self.headers if c not in ["Audit_Date", "Ticker", "Name", "Trend_Scenario", "Livermore_Status"]]
            for col in numeric_cols:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')

            existing_idx = df.index[df['Audit_Date'] == market_date].tolist()
            if existing_idx:
                idx = existing_idx[0]
                # 기존 데이터 업데이트 시 사후 수익률 데이터가 있다면 보존
                for key, val in row_data.items():
                    df.at[idx, key] = val
            else:
                new_row_df = pd.DataFrame([row_data])
                df = pd.concat([df, new_row_df], ignore_index=True)
        else:
            df = pd.DataFrame([row_data])
            df = df.reindex(columns=self.headers)

        df.to_csv(file_path, index=False, encoding='utf-8-sig')
        logger.info(f"💾 [{ticker}] 장부 기록 완료: {market_date}")

    def update_forward_returns(self, ticker):
        """[Phase 3] 사후 성과 결산: 감사 20일 후의 실제 수익률 추적 및 기록"""
        file_path = self._get_file_path(ticker)
        if not file_path.exists(): return

        df = pd.read_csv(file_path)
        df['Audit_Date'] = pd.to_datetime(df['Audit_Date'])
        
        # 아직 결산되지 않았고(NaN), 감사일로부터 20일이 경과한 데이터 필터링
        mask = df['Ret_20d'].isna() & (df['Audit_Date'] <= datetime.now() - timedelta(days=20))
        target_rows = df[mask]

        if target_rows.empty: return

        logger.info(f"📈 [{ticker}] {len(target_rows)}건의 사후 수익률 결산 진행 중...")

        for idx, row in target_rows.iterrows():
            audit_date = row['Audit_Date']
            # T+20일까지의 시세 데이터 확보 (넉넉히 30일치 다운로드)
            try:
                hist = yf.download(ticker, start=audit_date, end=audit_date + timedelta(days=30), progress=False, auto_adjust=True)
                if not hist.empty:
                    # 감사일 이후 약 15거래일(실제 20일 분량) 슬라이싱
                    period_data = hist.iloc[:15]
                    
                    price_t0 = float(row['Price_T'])
                    price_t20 = float(period_data['Close'].iloc[-1])
                    max_p = float(period_data['High'].max())
                    min_p = float(period_data['Low'].min())

                    # 수익률 및 낙폭 기입
                    df.at[idx, 'Ret_20d'] = round(((price_t20 - price_t0) / price_t0) * 100, 2)
                    df.at[idx, 'Max_Ret_20d'] = round(((max_p - price_t0) / price_t0) * 100, 2)
                    df.at[idx, 'Min_Ret_20d'] = round(((min_p - price_t0) / price_t0) * 100, 2)
            except Exception as e:
                logger.error(f"❌ [{ticker}] {audit_date.date()} 결산 중 오류: {e}")

        # 날짜 포맷 복구 후 저장
        df['Audit_Date'] = df['Audit_Date'].dt.strftime('%Y-%m-%d')
        df.to_csv(file_path, index=False, encoding='utf-8-sig')
        logger.info(f"✅ [{ticker}] 사후 수익률 결산 완료")

    def get_previous_state(self, ticker):
        """[v8.9.7] 전기 이월 데이터 분석 (오늘 날짜 제외한 최신 기록)"""
        file_path = self._get_file_path(ticker)
        if not file_path.exists(): return None, None
        try:
            df = pd.read_csv(file_path)
            if df.empty: return None, None
            today_str = datetime.now().strftime("%Y-%m-%d")
            # 오늘 기록을 제외하여 '순수 과거' 대조군 형성
            past_df = df[df['Audit_Date'] != today_str]
            if past_df.empty: return None, None
            
            last_row = past_df.iloc[-1]
            return int(last_row['Risk_Level']), float(last_row['Risk_Score'])
        except Exception as e:
            logger.error(f"⚠️ [{ticker}] 과거 장부 분석 실패: {e}")
            return None, None