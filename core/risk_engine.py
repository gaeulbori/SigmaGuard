"""
[File Purpose]
- 기술 지표(Indicators)를 입력받아 통합 리스크 점수 및 SOP 등급을 산출하는 핵심 판단 엔진.
- [v8.9.7 통합] 30:50:20 배점 체계 + 리버모어 3일 확증 + 정밀 자본 할당 로직 완성.

[Key Features]
- Multi-Factor Scoring: P1(위치:30), P2(에너지:50), P4(트랩:20) 배점 시스템.
- Livermore Confirm: 3일 연속 추세 유지 시 리스크를 할인(15~30%)하는 보수적 감사 적용.
- Capital Allocation: 리스크 거리($Risk_{dist}$)와 가성비($E.I$)를 역산하여 단일 종목 0.8% 리스크 한도 내 비중 결정.
- Dynamic Multiplier: Slope(기울기)와 R2(신뢰도) 기반의 2단계 필터링(Linear Confidence Brake).
"""

import numpy as np
import pandas as pd
from config.settings import settings
from utils.logger import setup_custom_logger

logger = setup_custom_logger("RiskEngine")

class RiskEngine:
    def __init__(self):
        # 1. v8.9.7 배점 설계 기준 (Total Raw: 100.0)
        self.W_POS_BASE = 30.0    
        self.W_ENERGY_BASE = 50.0 
        self.W_TRAP_BASE = 20.0   
        
        # 2. 에너지 부문 세부 배점 (Raw 40점 -> 50점 스케일링)
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
        self.ACCOUNT_RISK_LIMIT = 0.008  # 총 자산 대비 단일 종목 최대 손실 한도 (0.8%)
        self.MAX_WEIGHT = 20.0           # 단일 종목 최대 권고 비중 (20%)
        self.EI_BENCHMARK = 0.20         # 가성비(E.I) 기준 계수

    def evaluate(self, ind_df):
        """[v8.9.7] 통합 리스크 감사 및 자본 할당 실행"""
        try:
            if ind_df is None or ind_df.empty:
                return 0.0, "NODATA", {}

            latest = ind_df.iloc[-1]
            
            # 1단계: 부문별 기초 점수(Raw Score) 산출
            s_p1 = self._calc_position_risk(latest)
            s_p2 = self._calc_energy_risk(latest)
            s_p4 = self._calc_trap_risk(latest)
            base_raw = round(s_p1 + s_p2 + s_p4, 1)

            # 2단계: 동적 가중치(Multiplier) 적용
            multiplier, scenario = self._get_dynamic_multiplier(latest, base_raw)
            
            # 3단계: [신규] 리버모어 3일 확증 로직 적용 (할인 적용)
            liv_status, liv_discount = self._calculate_livermore_logic(ind_df)
            
            # 최종 점수 확정 (가중치 적용 후 리버모어 할인)
            final_score = base_raw * multiplier
            if liv_discount > 0:
                final_score = final_score * (1.0 - liv_discount)
                scenario += f" (+LIV 할인 {int(liv_discount*100)}%)"
            
            final_score = np.clip(round(final_score, 1), 0, 100)
            
            # 4단계: [신규] 자본 할당 및 포지션 사이징 산출
            alloc = self._apply_capital_allocation(latest, ind_df)
            
            # 5단계: SOP 등급 및 조치 지침 확보
            grade_label, grade_num, action = self.get_sop_info(final_score)

            details = {
                "p1": s_p1, "p2": s_p2, "p4": s_p4,
                "base_raw": base_raw,
                "multiplier": multiplier,
                "scenario": scenario,
                "liv_status": liv_status,
                "action": action,
                "stop_loss": alloc['stop_loss'],
                "weight_pct": alloc['weight'],
                "ei": alloc['ei']
            }

            return float(final_score), grade_label, details

        except Exception as e:
            logger.error(f"❌ 리스크 엔진 평가 중 오류 발생: {e}")
            return 50.0, "ERROR", {}

    def _calc_position_risk(self, latest):
        """Part 1. 위치 리스크 (Multi-Sigma 기반)"""
        avg_sigma = latest.get('avg_sigma', 0.0)
        return round(np.clip(avg_sigma / self.SIGMA_CRITICAL_LEVEL, 0, 1) * self.W_POS_BASE, 1)

    def _calc_energy_risk(self, latest):
        """Part 2. 에너지 리스크 (MACD + BBW + MFI)"""
        m_trend = latest.get('m_trend', "N/A")
        s_macd = self.MACD_REVERSAL_RISK if ("감속" in m_trend or "하락" in m_trend) else self.MACD_STABLE_LOW_RISK
        
        bbw = latest.get('bbw', 0.0)
        bbw_thr = latest.get('bbw_thr', 0.3)
        s_bbw = self.BBW_EXPANSION_RISK if bbw > bbw_thr else self.BBW_NORMAL_RISK
        
        rsi = latest.get('rsi', 50.0)
        mfi = latest.get('mfi', 50.0)
        s_mfi = self.MFI_DIVERGENCE_RISK if mfi < rsi else self.MFI_STABLE_RISK
        
        s_energy_raw = s_macd + s_bbw + s_mfi
        return round(np.clip((s_energy_raw / self.ENERGY_MAX_RAW) * self.W_ENERGY_BASE, 0, self.W_ENERGY_BASE), 1)

    def _calc_trap_risk(self, latest):
        """Part 4. 저항/트랩 리스크 (이격도 및 기울기)"""
        if latest.get('ma_slope') == "Falling":
            return self.W_TRAP_BASE

        curr_disp = latest.get('disp120', 100.0)
        limit_disp = latest.get('disp120_limit', 115.0)
        avg_disp = latest.get('disp120_avg', 105.0)
        
        risk_ratio = np.clip((curr_disp - avg_disp) / (limit_disp - avg_disp + 1e-10), 0, 1)
        return round(risk_ratio * self.W_TRAP_BASE, 1)

    def _get_dynamic_multiplier(self, latest, base_raw):
        """Part 3. 추세 품질 가중치 (Slope & R2 필터)"""
        slope = latest.get('slope', 0.0)
        r2 = latest.get('R2', 0.0)
        adx = latest.get('ADX', 0.0)
        
        multiplier = 1.0
        scenario = "NORMAL"

        if slope > 0:
            quality_score = (r2 * 0.7) + (np.clip(adx / 40.0, 0, 1) * 0.3)
            conf_factor = np.clip((80.0 - base_raw) / 40.0, 0, 1)
            multiplier = 1.0 - (quality_score * 0.40 * conf_factor)
            scenario = "BULLISH"
        else:
            avg_sigma = latest.get('avg_sigma', 0.0)
            if avg_sigma < self.SIGMA_BOTTOM_LIMIT and latest.get('mfi', 0) > latest.get('rsi', 0):
                multiplier = 0.50
                scenario = "BOTTOM_FISHING"
            else:
                crash_intensity = (r2 * 0.7) + (np.clip(adx / 40.0, 0, 1) * 0.3)
                multiplier = 1.0 + (crash_intensity * 0.60)
                scenario = "BEARISH"
            
        return round(multiplier, 2), scenario

    def _calculate_livermore_logic(self, df):
        """[v8.9.7] 리버모어 3일 확증 로직"""
        if len(df) < 4: return "데이터 부족", 0.0
        close = df['Close']
        consecutive_up = (close.iloc[-1] > close.iloc[-2]) and \
                         (close.iloc[-2] > close.iloc[-3]) and \
                         (close.iloc[-3] > close.iloc[-4])
        
        is_new_high = close.iloc[-1] >= close.rolling(20).max().iloc[-2]
        
        if is_new_high and consecutive_up:
            return "신고가 확증 (3일 연속)", 0.30
        elif consecutive_up:
            return "추세 확증 진행 (3일 연속)", 0.15
        return "확증 대기", 0.0

    def _apply_capital_allocation(self, latest, df):
        """리스크 거리 기반 정밀 자본 할당"""
        curr_p = latest['Close']
        stat_floor = df['Close'].tail(252).mean() - (2.0 * df['Close'].tail(252).std())
        tech_floor = (curr_p / (latest.get('disp120', 100)/100)) * 0.92
        
        final_stop = max(stat_floor, tech_floor)
        risk_dist = (curr_p - final_stop) / (curr_p + 1e-10)
        
        ei = round(self.EI_BENCHMARK / (risk_dist + 1e-10), 2)
        weight = (self.ACCOUNT_RISK_LIMIT / (risk_dist + 1e-10)) * 100
        
        return {
            'stop_loss': round(final_stop, 2),
            'weight': round(min(weight, self.MAX_WEIGHT), 1),
            'ei': ei
        }

    def get_sop_info(self, score):
        """David's SOP 5단계 기준 정합성 매핑"""
        if score >= 81:
            return "LEVEL 5: DANGER (위험)", 5, "자산 보호: 50% 이상 익절 및 현금 확보 권고"
        elif score >= 66:
            return "LEVEL 4: WARNING (경고)", 4, "비중 축소: 리스크 위험 신호. 보유 물량 30% 익절"
        elif score >= 46:
            return "LEVEL 3: WATCH (관찰)", 3, "추세 관찰: 과열 징후 발생. 신규 진입 금지"
        elif score >= 26:
            return "LEVEL 2: STABLE (안정)", 2, "안정 보유: 추세 건강 및 리스크 관리 범위 내"
        else:
            return "LEVEL 1: STRONG BUY (매수)", 1, "적극 매수: 리스크 최저, 비중 확대 추진"

    def _get_level(self, score):
        if score >= 81: return 5
        elif score >= 66: return 4
        elif score >= 46: return 3
        elif score >= 26: return 2
        else: return 1