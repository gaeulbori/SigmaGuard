"""
[File Purpose]
- 기술 지표(Indicators)를 입력받아 통합 리스크 점수 및 SOP 등급을 산출하는 핵심 판단 엔진.
- David님의 v8.9.7 정통 로직(동적 임계값 및 30:50:20 가중치 체계)을 완벽히 계승함.

[Key Features]
- Multi-Factor Scoring: P1(위치:30), P2(에너지:50), P4(트랩:20) 배점 시스템.
- Dynamic Volatility Risk: BBW가 고정값이 아닌 100일 통계적 임계값(BBW_THR)을 넘었을 때만 리스크 가중.
- Confidence Multiplier: Slope(기울기)와 R2(신뢰도)에 따라 최종 점수를 할인/할증하는 2단계 필터링.
- SOP Grade: 81/66/46/26 점수 기준에 따른 기계적 대응 지침 제공.
"""

import numpy as np
from config.settings import settings
from utils.logger import setup_custom_logger

logger = setup_custom_logger("RiskEngine")

class RiskEngine:
    def __init__(self):
        # 1. v8.9.7 배점 설계 기준 (Total Raw: 100.0)
        self.W_POS_BASE = 30.0    # Part 1. 위치 (Sigma)
        self.W_ENERGY_BASE = 50.0 # Part 2. 에너지 (MACD, BBW, MFI)
        self.W_TRAP_BASE = 20.0   # Part 4. 저항/트랩 (이격도)
        
        # 2. 에너지 부문 세부 배점 (Raw 40점 만점 설계 -> 50점 스케일링용)
        self.ENERGY_MAX_RAW = 40.0
        self.MACD_REVERSAL_RISK = 10.0
        self.MACD_STABLE_LOW_RISK = 3.0
        self.BBW_EXPANSION_RISK = 12.0
        self.BBW_NORMAL_RISK = 5.0
        self.MFI_DIVERGENCE_RISK = 18.0
        self.MFI_STABLE_RISK = 8.0

        # 3. 임계치 기준값
        self.SIGMA_CRITICAL_LEVEL = 2.5
        self.SIGMA_BOTTOM_LIMIT = -2.0

    def evaluate(self, ind_df):
        """
        [v8.9.7] 통합 리스크 감사 실행
        - ind_df: Indicators 모듈에서 계산된 모든 지표 데이터프레임
        """
        try:
            if ind_df is None or ind_df.empty:
                return 0.0, "NODATA", {}

            latest = ind_df.iloc[-1]
            
            # 1단계: 부문별 기초 점수(Raw Score) 산출
            s_p1 = self._calc_position_risk(latest)
            s_p2 = self._calc_energy_risk(latest)
            s_p4 = self._calc_trap_risk(latest)
            
            base_raw = round(s_p1 + s_p2 + s_p4, 1)

            # 2단계: 동적 가중치(Multiplier) 적용 (v8.7.5 Linear Confidence Brake)
            multiplier, scenario = self._get_dynamic_multiplier(latest, base_raw)
            
            # 3단계: 최종 점수 확정 및 클리핑 (0~100)
            final_score = round(base_raw * multiplier, 1)
            final_score = np.clip(final_score, 0, 100)
            
            # 4단계: SOP 등급 및 조치 지침 확보
            grade_label, grade_num, action = self.get_sop_info(final_score)

            details = {
                "p1": s_p1, "p2": s_p2, "p4": s_p4,
                "base_raw": base_raw,
                "multiplier": multiplier,
                "scenario": scenario,
                "action": action
            }

            return final_score, grade_label, details

        except Exception as e:
            logger.error(f"❌ 리스크 엔진 평가 중 오류 발생: {e}")
            return 50.0, "ERROR", {}

    def _calc_position_risk(self, latest):
        """Part 1. 위치 리스크 (Sigma 기반)"""
        # avg_sigma가 2.5(임계치)에 도달할수록 배점 30점 만점에 수렴
        avg_sigma = latest.get('avg_sigma', 0.0)
        return round(np.clip(avg_sigma / self.SIGMA_CRITICAL_LEVEL, 0, 1) * self.W_POS_BASE, 1)

    def _calc_energy_risk(self, latest):
        """Part 2. 에너지 리스크 (MACD + BBW + MFI) - v8.9.7 정통 로직"""
        # 1. MACD 트렌드 리스크 (상승가속 시 저위험, 감속/하락가속 시 고위험)
        m_trend = latest.get('m_trend', "N/A")
        s_macd = self.MACD_REVERSAL_RISK if ("감속" in m_trend or "하락" in m_trend) else self.MACD_STABLE_LOW_RISK
        
        # 2. BBW 변동성 리스크 (동적 임계값 BBW_THR 대조)
        bbw = latest.get('bbw', 0.0)
        bbw_thr = latest.get('bbw_thr', 0.3) # Indicators에서 계산된 100일 통계값
        s_bbw = self.BBW_EXPANSION_RISK if bbw > bbw_thr else self.BBW_NORMAL_RISK
        
        # 3. MFI 수급 괴리 리스크 (MFI가 RSI보다 낮으면 자금 이탈로 간주)
        rsi = latest.get('rsi', 50.0)
        mfi = latest.get('mfi', 50.0)
        s_mfi = self.MFI_DIVERGENCE_RISK if mfi < rsi else self.MFI_STABLE_RISK
        
        # 40점 만점 설계된 Raw 합계를 50점 배점으로 스케일링
        s_energy_raw = s_macd + s_bbw + s_mfi
        return round(np.clip((s_energy_raw / self.ENERGY_MAX_RAW) * self.W_ENERGY_BASE, 0, self.W_ENERGY_BASE), 1)

    def _calc_trap_risk(self, latest):
        """Part 4. 저항/트랩 리스크 (이격도 및 기울기)"""
        # 120MA 기울기가 하락세면 구조적 붕괴로 간주하여 즉시 만점(20점)
        if latest.get('ma_slope') == "Falling":
            return self.W_TRAP_BASE

        curr_disp = latest.get('disp120', 100.0)
        limit_disp = latest.get('disp120_limit', 115.0) # 동적 임계치
        avg_disp = 105.0 # 장기 평균 이격도 바닥값
        
        # 이격도가 평균(105%)에서 임계치(115%+) 사이의 어디에 위치하는지 비율 산출
        risk_ratio = np.clip((curr_disp - avg_disp) / (limit_disp - avg_disp + 1e-10), 0, 1)
        return round(risk_ratio * self.W_TRAP_BASE, 1)

    def _get_dynamic_multiplier(self, latest, base_raw):
        """Part 3. 추세 품질 가중치 (Slope & R2 필터)"""
        slope = latest.get('slope', 0.0)
        r2 = latest.get('r2', 0.0)
        adx = latest.get('adx', 0.0)
        
        # 상수 설정 (v8.9.7 기준)
        ADX_MAX_REF = 40.0
        WEIGHT_R2 = 0.7
        WEIGHT_ADX = 0.3
        MAX_BULL_DISCOUNT = 0.40
        MAX_BEAR_SURCHARGE = 0.60
        BOTTOM_FISHING_MULT = 0.50  # ★ 바닥 낚시 50% 감면 특약
        SIGMA_BOTTOM_LIMIT = -2.0   # ★ 바닥 판단 시그마 임계치

        multiplier = 1.0
        scenario = "NORMAL"

        if slope > 0:
            # [시나리오 A] 상승 추세
            norm_adx = np.clip(adx / ADX_MAX_REF, 0, 1)
            quality_score = (r2 * WEIGHT_R2) + (norm_adx * WEIGHT_ADX)
            conf_factor = np.clip((80.0 - base_raw) / 40.0, 0, 1)
            multiplier = 1.0 - (quality_score * MAX_BULL_DISCOUNT * conf_factor)
            scenario = "BULLISH"
        else:
            # [시나리오 B] 하락 추세
            norm_adx_bear = np.clip(adx / ADX_MAX_REF, 0, 1)
            crash_intensity = (r2 * WEIGHT_R2) + (norm_adx_bear * WEIGHT_ADX)
            
            # --- [ David's Bottom Fishing 로직 복구 ] ---
            avg_sigma = latest.get('avg_sigma', 0.0)
            rsi = latest.get('rsi', 50.0)
            mfi = latest.get('mfi', 50.0)

            # 시그마가 낮고(과매도), 수급(MFI)이 가격(RSI)보다 강할 때
            if avg_sigma < SIGMA_BOTTOM_LIMIT and mfi > rsi:
                multiplier = BOTTOM_FISHING_MULT
                scenario = "BOTTOM_FISHING"
            else:
                # 일반 하락: 하락 강도에 따른 할증
                multiplier = 1.0 + (crash_intensity * MAX_BEAR_SURCHARGE)
                scenario = "BEARISH"
            
        return round(multiplier, 2), scenario

    def get_sop_info(self, score):
        """David's SOP 5단계 기준 정합성 매핑"""
        if score >= 81:
            return "LEVEL 5: DANGER (위험)", 5, "자산 보호: 50% 이상 익절 및 현금 확보 권고"
        elif score >= 66:
            return "LEVEL 4: WARNING (경고)", 4, "비중 축소: 리스크 위험 신호. 보유 물량 30% 익절"
        elif score >= 46:
            return "LEVEL 3: WATCH (관망)", 3, "추세 관찰: 과열 징후 발생. 신규 진입 금지"
        elif score >= 26:
            return "LEVEL 2: STABLE (안정)", 2, "안정 보유: 추세 건강 및 리스크 관리 범위 내"
        else:
            return "LEVEL 1: STRONG BUY (매수)", 1, "적극 매수: 리스크 최저, 비중 확대 추진"