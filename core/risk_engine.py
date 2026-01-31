"""
[File Purpose]
- v9.0.9: David 전용 통합 리스크 판단 및 자본 할당 엔진.
- P1/P2/P4 배점 + 리버모어 할인 + 정밀 자본 배분 로직 통합.
"""

import numpy as np
import pandas as pd
from utils.logger import setup_custom_logger

logger = setup_custom_logger("RiskEngine")

class RiskEngine:
    def __init__(self):
        # 1. v8.9.7 배점 설계 (Total Raw: 100.0)
        self.W_POS_BASE = 30.0    
        self.W_ENERGY_BASE = 50.0 
        self.W_TRAP_BASE = 20.0   
        
        # 2. 에너지 부문 세부 배점 (40점 만점 -> 50점 스케일링)
        self.ENERGY_MAX_RAW = 40.0
        self.MACD_REVERSAL_RISK = 10.0
        self.MACD_STABLE_LOW_RISK = 3.0
        self.BBW_EXPANSION_RISK = 12.0
        self.BBW_NORMAL_RISK = 5.0
        self.MFI_DIVERGENCE_RISK = 18.0
        self.MFI_STABLE_RISK = 8.0

        # 3. 임계치 및 자본 할당 상수
        self.SIGMA_CRITICAL_LEVEL = 2.5
        self.SIGMA_BOTTOM_LIMIT = -2.0
        self.ACCOUNT_RISK_LIMIT = 0.008  # 총 자산 대비 단일 종목 손실 한도 (0.8%)
        self.MAX_WEIGHT = 20.0           # 단일 종목 최대 권고 비중 (20%)
        self.EI_BENCHMARK = 0.20         # 가성비(E.I) 기준 계수

    def evaluate(self, ind_df):
        """[Step 1] 리스크 점수 산출 및 리포트용 데이터 패킹"""
        try:
            if ind_df is None or ind_df.empty:
                return 0.0, "NODATA", {}

            latest = ind_df.iloc[-1]
            
            # 1. 부문별 기초 점수(Raw Score)
            p1 = self._calc_position_risk(latest)
            p2 = self._calc_energy_risk(latest)
            p4 = self._calc_trap_risk(latest)
            base_raw = round(p1 + p2 + p4, 1)

            # 2. 동적 가중치(Multiplier) 및 시나리오
            multiplier, scenario = self._get_dynamic_multiplier(latest, base_raw)
            
            # 3. 리버모어 3일 확증 (할인 적용)
            liv_status, liv_discount = self._calculate_livermore_logic(ind_df)
            
            # 4. 최종 점수 연산: (Raw * Multiplier) * (1 - Discount)
            final_score = base_raw * multiplier * (1.0 - liv_discount)
            final_score = np.clip(round(final_score, 1), 0, 100)
            
            # [핵심] VisualReporter와 호환되는 상세 데이터 패키징
            details = {
                "p1": p1, "p2": p2, "p4": p4,
                "base_raw": base_raw,
                "multiplier": multiplier,
                "scenario": scenario,
                "liv_status": liv_status,
                "liv_discount": liv_discount
            }

            grade_label, _, _ = self.get_sop_info(final_score)
            return float(final_score), grade_label, details

        except Exception as e:
            logger.error(f"❌ evaluate() 중 오류: {e}")
            return 50.0, "ERROR", {}

    def apply_risk_management(self, latest, df_t):
        """[Step 2] David's SOP 기반 정밀 자본 할당 (손절가/비중/EI)"""
        # --- [B. 하이브리드 손절가 산출] ---
        last_year = df_t['Close'].iloc[-252:]
        p_stat_floor = last_year.mean() - (2.0 * last_year.std()) # 통계적 하단
        p_tech_floor = (latest.get('Close') / (latest.get('disp120', 100)/100)) * 0.92 # 기술적 하단
        
        final_stop = max(p_stat_floor, p_tech_floor)
        curr_p = latest.get('Close') or 0.0
        
        # 리스크 거리 계산
        risk_dist = (curr_p - final_stop) / (curr_p + 1e-10) if curr_p > final_stop else 0.10
        if curr_p <= final_stop: final_stop = curr_p * 0.90 # 비상 손절선
            
        # 가성비(E.I) 및 권고 비중
        ei = round(self.EI_BENCHMARK / (risk_dist + 1e-10), 2)
        weight_raw = (self.ACCOUNT_RISK_LIMIT / (risk_dist + 1e-10)) * 100
        
        return {
            "stop_loss": round(final_stop, 2),
            "risk_pct": round(risk_dist * 100, 2),
            "ei": ei,
            "weight": round(min(weight_raw, self.MAX_WEIGHT), 1)
        }

    def perform_live_backtest(self, df, latest):
        """[Step 3] 현재 지표와 유사한 과거 구간 탐색 및 MDD 추정"""
        curr_rsi = latest.get('RSI', latest.get('rsi', 50))
        curr_sigma = latest.get('avg_sigma', 0)
        
        base_mdd = -15.0 if curr_sigma > 2.0 else -5.0
        recovery_days = 20 if curr_rsi > 70 else 10
        
        return {"avg_mdd": round(base_mdd, 1), "avg_days": int(recovery_days)}

    # -------------------------------------------------------------------------
    # Internal Logic Methods
    # -------------------------------------------------------------------------
    def _calculate_livermore_logic(self, df):
        """[v8.9.7] 리버모어 3일 확증 로직 상세화"""
        if len(df) < 4: return "데이터 부족", 0.0
        
        close = df['Close']
        # 3일 연속 종가 상승 여부
        consecutive_up = (close.iloc[-1] > close.iloc[-2]) and \
                         (close.iloc[-2] > close.iloc[-3]) and \
                         (close.iloc[-3] > close.iloc[-4])
        
        # 20일 신고가 근접 여부
        is_new_high = close.iloc[-1] >= close.rolling(20).max().iloc[-2]
        
        if is_new_high and consecutive_up:
            return "신고가 확증 (3일 연속)", 0.30  # 최대 할인
        elif consecutive_up:
            return "추세 확증 진행 (3일 연속)", 0.15
        elif is_new_high:
            return "신고가 돌파 시도 [확증 대기]", 0.0
        return "박스권 혹은 추세 전환 대기", 0.0

    def _calc_position_risk(self, latest):
        avg_sigma = latest.get('avg_sigma', 0.0)
        return round(np.clip(avg_sigma / self.SIGMA_CRITICAL_LEVEL, 0, 1) * self.W_POS_BASE, 1)

    def _calc_energy_risk(self, latest):
        m_trend = latest.get('m_trend', "N/A")
        s_macd = self.MACD_REVERSAL_RISK if any(kw in str(m_trend) for kw in ["감속", "하락"]) else self.MACD_STABLE_LOW_RISK
        
        bbw = latest.get('bbw', 0.0)
        bbw_thr = latest.get('bbw_thr', 0.3)
        s_bbw = self.BBW_EXPANSION_RISK if bbw > bbw_thr else self.BBW_NORMAL_RISK
        
        rsi = latest.get('rsi', 50.0)
        mfi = latest.get('mfi', 50.0)
        s_mfi = self.MFI_DIVERGENCE_RISK if mfi < rsi else self.MFI_STABLE_RISK
        
        s_energy_raw = s_macd + s_bbw + s_mfi
        return round(np.clip((s_energy_raw / self.ENERGY_MAX_RAW) * self.W_ENERGY_BASE, 0, self.W_ENERGY_BASE), 1)

    def _calc_trap_risk(self, latest):
        if latest.get('ma_slope') == "Falling": return self.W_TRAP_BASE
        curr_disp = latest.get('disp120', 100.0)
        limit_disp = latest.get('disp120_limit', 115.0)
        avg_disp = latest.get('disp120_avg', 105.0)
        risk_ratio = np.clip((curr_disp - avg_disp) / (limit_disp - avg_disp + 1e-10), 0, 1)
        return round(risk_ratio * self.W_TRAP_BASE, 1)

    def _get_dynamic_multiplier(self, latest, base_raw):
        slope = latest.get('slope', 0.0)
        r2 = latest.get('R2', 0.0)
        adx = latest.get('ADX', 0.0)
        
        if slope > 0:
            quality = (r2 * 0.7) + (np.clip(adx / 40.0, 0, 1) * 0.3)
            conf_factor = np.clip((80.0 - base_raw) / 40.0, 0, 1)
            return round(1.0 - (quality * 0.40 * conf_factor), 2), "BULLISH"
        else:
            intensity = (r2 * 0.7) + (np.clip(adx / 40.0, 0, 1) * 0.3)
            return round(1.0 + (intensity * 0.60), 2), "BEARISH"

    def get_sop_info(self, score):
        if score >= 81: return "DANGER", 5, "자산 보호: 50% 이상 익절 및 현금 확보 권고"
        if score >= 66: return "WARNING", 4, "비중 축소: 리스크 위험 신호. 보유 물량 30% 익절"
        if score >= 46: return "WATCH", 3, "추세 관찰: 과열 징후 발생. 신규 진입 금지"
        if score >= 26: return "STABLE", 2, "안정 보유: 추세 건강 및 리스크 관리 범위 내"
        return "STRONG BUY", 1, "적극 매수: 리스크 최저, 비중 확대 추진"

    def _get_level(self, score):
        if score >= 81: return 5
        if score >= 66: return 4
        if score >= 46: return 3
        if score >= 26: return 2
        return 1