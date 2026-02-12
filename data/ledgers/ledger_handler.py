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

logger = setup_custom_logger("LedgerHandler")

class LedgerHandler:
    def __init__(self):
        self.data_dir = settings.DATA_DIR / "ledgers"
        if not self.data_dir.exists():
            self.data_dir.mkdir(parents=True, exist_ok=True)

        # v9.5.0 확장 헤더 정의 (매크로 지표 3개 추가: 총 49개 필드)
        self.headers = [
            "Audit_Date", "Ticker", "Name", "Risk_Score", "Risk_Level", "Price_T",
            "Sigma_T_Avg", "Sigma_T_1y", "Sigma_T_2y", "Sigma_T_3y", "Sigma_T_4y", "Sigma_T_5y",
            "RSI_T", "MFI_T", "BBW_T", "R2_T", "ADX_T", "Disp_T_120",
            "Ticker_B",
            "Price_B", "Sigma_B_Avg", "RSI_B", "MFI_B", "ADX_B", "BBW_B",
            "Stop_Price", "Risk_Gap_Pct", "Invest_EI", "Weight_Pct", "Expected_MDD",
            "Livermore_Status", "Base_Raw_Score", "Risk_Multiplier", "Trend_Scenario",
            "Score_Pos", "Score_Pos_EMA", # 기존 필드 옆에 EMA 추가
            "Score_Ene", "Score_Ene_EMA", 
            "Score_Trap", "Score_Trap_EMA",            
            # [v9.5.0 매크로 지표 필드]
            "VIX_T", "US10Y_T", "DXY_T",
            "MACD_Hist_T", "MACD_Hist_B", "ADX_Gap", "Disp_Limit", "BBW_Thr", "LIV_Discount", "SOP_Action",
            "Ret_20d", "Min_Ret_20d", "Max_Ret_20d"
        ]

    def _get_macro_snapshot(self):
        macro_tickers = {"^VIX": "VIX_T", "^TNX": "US10Y_T", "DX-Y.NYB": "DXY_T"}
        results = {"VIX_T": 0.0, "US10Y_T": 0.0, "DXY_T": 0.0}
        
        try:
            # period를 5d로 넉넉히 잡아 주말이나 휴장일 데이터 누락 방지
            # auto_adjust=True를 명시적으로 추가하여 경고 제거 및 데이터 정합성 유지
            data = yf.download(list(macro_tickers.keys()), period="5d", progress=False, auto_adjust=True)            
            if not data.empty:
                for ticker, field in macro_tickers.items():
                    # 해당 티커의 마지막 유효한(NaN이 아닌) 값을 추출
                    valid_series = data['Close'][ticker].dropna()
                    if not valid_series.empty:
                        results[field] = round(float(valid_series.iloc[-1]), 2)
        except Exception as e:
            logger.warning(f"⚠️ 매크로 데이터 정밀 수집 실패: {e}")
        
        return results

    def _get_file_path(self, ticker):
        return self.data_dir / f"sigma_guard_ledger_{ticker}.csv"

    def _get_level(self, score):
        """[v9.7.0 Sync] 리스크 엔진과 동일한 9단계 레벨 적용"""
        if score >= 91: return 9
        elif score >= 81: return 8
        elif score >= 71: return 7
        elif score >= 61: return 6
        elif score >= 41: return 5
        elif score >= 31: return 4
        elif score >= 21: return 3
        elif score >= 11: return 2
        else: return 1

    def _format_value(self, ticker, value, category="normal"):
        """
        [David's Refined Standard] 
        데이터의 성격(category)에 따라 자릿수 정밀도를 제어합니다.
        """
        if value is None or pd.isna(value): 
            return 0.0
        
        try:
            val = float(value)
        except (ValueError, TypeError):
            return value # 숫자가 아닌 경우 그대로 반환

        is_krw = any(s in ticker for s in ['.KS', '.KQ'])

        # 1. 가격 (KRW: 정수, USD: 3자리)
        if category == "price":
            return int(round(val, 0)) if is_krw else round(val, 3)
        
        # 2. 리스크 점수 (1자리)
        elif category == "score":
            return round(val, 1)
        
        # 3. 시그마 지표 (3자리)
        elif category == "sigma":
            return round(val, 3)
        
        # 4. 주요 기술 지표 (RSI, MFI, ADX, Disp - 1자리)
        elif category in ["indicator", "disparity"]:
            return round(val, 1)
        
        # 5. 수학적 변동성 및 추세 (R2, BBW, MACD_Hist - 4자리)
        elif category in ["math", "oscillator"]:
            return round(val, 4)
        
        # 6. 매크로 및 수익률 (VIX, 금리, Ret_20d - 2자리)
        elif category in ["macro", "return"]:
            return round(val, 2)
        
        # 7. 기본값 (3자리)
        return round(val, 3)

    def save_entry(self, ticker, name, market_date, latest, score, details, alloc, bt_res, bench_latest=None, bench_ticker='N/A'):
            """[v9.5.0] 고해상도 장부 기록 (매크로 지표 통합 버전)"""
            file_path = self._get_file_path(ticker)
            current_level = self._get_level(score)
            
            # 1. 시장 환경 매크로 데이터 수집
            macro_data = self._get_macro_snapshot()
            
            # 2. 가격 정보 추출
            current_price_t = latest.get('Close') or latest.get('price') or 0.0
            current_price_b = 0.0
            if bench_latest is not None:
                current_price_b = bench_latest.get('Close') or bench_latest.get('price') or 0.0

            # 3. 장부 데이터 조립 (Single Source of Truth)
            row_data = {
                "Audit_Date": market_date,
                "Ticker": ticker,
                "Name": name,
                "Risk_Score": round(score, 1),
                "Risk_Level": current_level,
                "Price_T": self._format_value(ticker, current_price_t, True),
                
                "Sigma_T_Avg": round(latest.get('avg_sigma', 0), 2),
                "Sigma_T_1y": round(latest.get('sig_1y', 0), 2),
                "Sigma_T_2y": round(latest.get('sig_2y', 0), 2),
                "Sigma_T_3y": round(latest.get('sig_3y', 0), 2),
                "Sigma_T_4y": round(latest.get('sig_4y', 0), 2),
                "Sigma_T_5y": round(latest.get('sig_5y', 0), 2),
                
                "RSI_T": round(latest.get('RSI', latest.get('rsi', 0)), 1),
                "MFI_T": round(latest.get('MFI', latest.get('mfi', 0)), 1),
                "BBW_T": round(latest.get('bbw', latest.get('BBW', 0)), 4),
                "R2_T": round(latest.get('R2', latest.get('r2', 0)), 4),
                "ADX_T": round(latest.get('ADX', latest.get('adx', 0)), 1),
                "Disp_T_120": round(latest.get('disp120', latest.get('Disp120', 0)), 1),
                "Ticker_B": bench_ticker,
                "Price_B": self._format_value(ticker, current_price_b, True),
                "Sigma_B_Avg": round(bench_latest.get('avg_sigma', 0), 2) if bench_latest is not None else 0.0,
                "RSI_B": round(bench_latest.get('RSI', bench_latest.get('rsi', 0)), 1) if bench_latest is not None else 0.0,
                "MFI_B": round(bench_latest.get('MFI', bench_latest.get('mfi', 0)), 1) if bench_latest is not None else 0.0,
                "ADX_B": round(bench_latest.get('ADX', bench_latest.get('adx', 0)), 1) if bench_latest is not None else 0.0,
                "BBW_B": round(bench_latest.get('bbw', 0), 4) if bench_latest is not None else 0.0,
                
                "Stop_Price": self._format_value(ticker, alloc.get('stop_loss', 0), True),
                "Risk_Gap_Pct": round(alloc.get('risk_pct', 0), 2),
                "Invest_EI": alloc.get('ei', 0),
                "Weight_Pct": alloc.get('weight', 0),
                "Expected_MDD": bt_res.get('avg_mdd', 0.0),
                "Livermore_Status": details.get('liv_status', 'N/A'),
                "Base_Raw_Score": details.get('base_raw', 0),
                "Risk_Multiplier": details.get('multiplier', 1.0),
                "Trend_Scenario": details.get('scenario', 'N/A'),
                "Score_Pos": details.get('p1', 0),
                "Score_Pos_EMA": details.get('p1_ema'),  # EMA 기록
                "Score_Ene": details.get('p2', 0),
                "Score_Ene_EMA": details.get('p2_ema'),  # EMA 기록
                "Score_Trap": details.get('p4', 0),
                "Score_Trap_EMA": details.get('p4_ema'),  # EMA 기록

                # [v9.5.0 신규 매크로 필드 매핑]
                "VIX_T": macro_data["VIX_T"],
                "US10Y_T": macro_data["US10Y_T"],
                "DXY_T": macro_data["DXY_T"],

                "MACD_Hist_T": round(details.get('macd_h', 0.0), 4),
                "MACD_Hist_B": round(details.get('bench_macd_h', 0.0), 4),
                "ADX_Gap": round(details.get('discrepancy', 0.0), 1),
                "Disp_Limit": round(latest.get('disp120_limit', 0.0), 1),
                "BBW_Thr": round(latest.get('bbw_thr', 0.3), 4),
                "LIV_Discount": round(details.get('liv_discount', 0.0), 2),
                "SOP_Action": details.get('action', 'N/A')
            }

            # 4. 파일 저장 로직 (기존 무결성 패치 유지)
            if file_path.exists():
                df = pd.read_csv(file_path)
                exclude_cols = ["Audit_Date", "Ticker", "Name", "Trend_Scenario", "Livermore_Status", "SOP_Action"]
                numeric_cols = [c for c in self.headers if c not in exclude_cols]
                for col in numeric_cols:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors='coerce')

                existing_idx = df.index[df['Audit_Date'] == market_date].tolist()
                if existing_idx:
                    idx = existing_idx[0]
                    for key, val in row_data.items():
                        df.at[idx, key] = val
                else:
                    df = pd.concat([df, pd.DataFrame([row_data])], ignore_index=True)
            else:
                df = pd.DataFrame([row_data]).reindex(columns=self.headers)

            df.to_csv(file_path, index=False, encoding='utf-8-sig')

    # ... (update_forward_returns, get_previous_state 등 기존 메서드 유지)

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

    def get_previous_sub_scores(self, ticker):
        """[v9.6.8] 직전 거래일의 세부 EMA 점수를 호출하여 평활화 기초값 제공"""
        file_path = self._get_file_path(ticker)
        if not file_path.exists(): return None
        try:
            df = pd.read_csv(file_path)
            if df.empty: return None
            # 오늘 기록을 제외한 최신 행 추출
            past_df = df[df['Audit_Date'] != datetime.now().strftime("%Y-%m-%d")]
            if past_df.empty: return None
            last = past_df.iloc[-1]
            return {
                'p1_ema': last.get('Score_Pos_EMA', last.get('Score_Pos', 0)),
                'p2_ema': last.get('Score_Ene_EMA', last.get('Score_Ene', 0)),
                'p4_ema': last.get('Score_Trap_EMA', last.get('Score_Trap', 0))
            }
        except Exception: return None        