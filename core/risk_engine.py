"""
[File Purpose]
- v9.4.9 Full Integrity Edition: 모든 누락된 메서드(Livermore, Risk Management 등)를 통합.
- 벤치마크 부재 시 ADX 괴리도 오차 수정 및 삼성전자 등 과이격 종목 진단 강화.
- David님의 v8.9.7 표준 배점 규격 완벽 준수.
"""

import numpy as np
import pandas as pd
from utils.logger import setup_custom_logger

logger = setup_custom_logger("RiskEngine")

class RiskEngine:
    def __init__(self):
        # 1. v8.9.7 표준 배점 설계 (Total Raw: 100.0)
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
        self.ACCOUNT_RISK_LIMIT = 0.008  # 총 자산 대비 단일 종목 손실 한도 (0.8%)
        self.MAX_WEIGHT = 20.0           # 단일 종목 최대 권고 비중 (20%)
        self.EI_BENCHMARK = 0.20         # 가성비(E.I) 기준 계수

        # RiskEngine.py 상단 또는 전역 변수 영역
        self.LV_GATE_SIGMA_MAX = 2.0    # 이 시그마를 넘으면 리버모어 할인을 박탈함 (통계적 광기)
        self.LV_GATE_R2_MIN    = 0.5    # 추세의 직선도가 이보다 낮으면 '가짜 돌파'로 간주
        self.LV_GATE_ADX_MIN   = 25     # 추세의 관성이 이보다 낮으면 단순 횡보 중 고점 갱신으로 판단
        self.LV_GATE_MFI_MIN   = 40     # 자금 유입이 이 수치 미만이면 '거래량 없는 상승'으로 간주

    def evaluate(self, ind_df, bench_df=None, prev_ema=None):
        """[v9.4.9] 통합 리스크 평가 엔진 - 모든 진단 로직의 중심"""
        try:
            if ind_df is None or ind_df.empty:
                return 0.0, "NODATA", {}

            latest = ind_df.iloc[-1]
            has_bench = bench_df is not None and not bench_df.empty
            b_latest = bench_df.iloc[-1] if has_bench else None
            
            # 1. 부문별 기초 점수 산출
            p1 = self._calc_position_risk(latest)
            p2 = self._calc_energy_risk(latest)
            p4 = self._calc_trap_risk(latest)

            alpha = 0.5  # 3일 평활화 계수
            if prev_ema:
                p1_ema = (p1 * alpha) + (prev_ema['p1_ema'] * (1 - alpha))
                p2_ema = (p2 * alpha) + (prev_ema['p2_ema'] * (1 - alpha))
                p4_ema = (p4 * alpha) + (prev_ema['p4_ema'] * (1 - alpha))
            else:
                p1_ema, p2_ema, p4_ema = p1, p2, p4

            # 최종 점수는 평활화된 EMA 값들의 합으로 산출
            base_raw_ema = round(p1_ema + p2_ema + p4_ema, 1)

            # [수정 지점] 세이프티 게이트가 적용된 검증된 리버모어 할인 로직 호출
            liv_status, liv_discount = self._get_validated_livermore_discount(ind_df, latest)
            #liv_status, liv_discount = self._calculate_livermore_logic(ind_df)

            multiplier, scenario = self._get_dynamic_multiplier(latest, base_raw_ema)            
            final_score = base_raw_ema * multiplier * (1.0 - liv_discount)
            final_score = np.clip(round(final_score, 1), 0, 100)
            

            # 2. 벤치마크 유무에 따른 괴리도 산출 (N/A 종목 보정)
            adx_t = latest.get('ADX', 0.0)
            discrepancy = round(adx_t - b_latest.get('ADX', 0.0), 1) if has_bench else 0.0
            # 3. 진단 문구 생성
            v1, v2, v4 = self._get_part_verdicts(p1, p2, p4, discrepancy, has_bench, latest)

            # 4. 데이터 패키징
            details = {
                "p1": p1, "p1_ema": round(p1_ema, 2), # 기존 p1은 Raw 유지
                "p2": p2, "p2_ema": round(p2_ema, 2), # 기존 p2는 Raw 유지
                "p4": p4, "p4_ema": round(p4_ema, 2), # 기존 p4는 Raw 유지
                "base_raw": base_raw_ema,             # 최종 합계는 EMA 기준                
                "multiplier": multiplier,
                "scenario": scenario,
                "liv_status": liv_status,
                "liv_discount": liv_discount,
                "price": latest.get('Close', 0.0),
                "bench_price": b_latest.get('Close', 0.0) if has_bench else 0.0,
                "macd_h": latest.get('macd_h', 0.0),
                "bench_macd_h": b_latest.get('macd_h', 0.0) if has_bench else 0.0,
                "discrepancy": discrepancy,
                "r2_comment": self._get_r2_interpretation(latest.get('R2', 0)),
                "adx_label": "STRONG" if adx_t >= 25 else "WEAK",
                "bbw_thr": latest.get('bbw_thr', 0.3),
                "v1_comment": v1, "v2_comment": v2, "v4_comment": v4,
                "supply_conclusion": "상승 에너지 고갈 및 수급 주의" if latest.get('MFI', 50) < latest.get('RSI', 50) and latest.get('RSI', 50) > 70 else "추세 관성 유지 중",
                "ma_status": "Rising" if latest.get('ma_slope') == "Rising" else "Falling"
            }

            grade_label, _, action = self.get_sop_info(final_score)
            details["action"] = action

            return float(final_score), grade_label, details

        except Exception as e:
            logger.error(f"❌ evaluate() 엔진 오류: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return 50.0, "ERROR", {}
        
    def _get_validated_livermore_discount(self, df, latest):
        """
        [v9.7.5] David's Livermore Safety Gate
        - 신고가 돌파의 '질(Quality)'을 4대 관문으로 검증하여 리스크 할인 적용 여부를 결정합니다.
        """
        # 1. 기초 리버모어 상태 획득
        status, base_discount = self._calculate_livermore_logic(df)
        
        if base_discount == 0:
            return status, 0.0

        # 2. Safety Gate 데이터 확보
        avg_sigma = latest.get('avg_sigma', 0)
        r2_val    = latest.get('R2', 0)
        adx_val   = latest.get('ADX', 0)
        mfi_val   = latest.get('MFI', 50)

        # [관문 A] 통계적 광기 (Sigma >= 2.0)
        if avg_sigma >= self.LV_GATE_SIGMA_MAX:
            return f"{status} (🚨광기구간 할인차단)", 0.0

        # [관문 B] 추세 신뢰도 미달 (R2 < 0.5)
        if r2_val < self.LV_GATE_R2_MIN:
            return f"{status} (⚠️추세품질 미달로 할인차단)", 0.0

        # [관문 C] 추세 관성 부족 (ADX < 25)
        if adx_val < self.LV_GATE_ADX_MIN:
            return f"{status} (📉추세관성 부족으로 할인차단)", 0.0

        # [관문 D] 수급 불일치 (MFI < 40)
        if mfi_val < self.LV_GATE_MFI_MIN:
            return f"{status} (⚖️수급불일치로 할인차단)", 0.0

        # 모든 관문 통과 시 할인 적용
        return f"{status} (✅추세확증 할인적용)", base_discount


    def apply_risk_management(self, latest, df_t):
        """[핵심] David's SOP 기반 정밀 자본 할당 (손절가/비중/EI)"""
        last_year = df_t['Close'].iloc[-252:]
        p_stat_floor = last_year.mean() - (2.0 * last_year.std())
        p_tech_floor = (latest.get('Close') / (latest.get('disp120', 100)/100)) * 0.92
        
        final_stop = max(p_stat_floor, p_tech_floor)
        curr_p = latest.get('Close') or 0.0
        
        risk_dist = (curr_p - final_stop) / (curr_p + 1e-10) if curr_p > final_stop else 0.10
        if curr_p <= final_stop: final_stop = curr_p * 0.90
            
        ei = round(self.EI_BENCHMARK / (risk_dist + 1e-10), 2)
        weight_raw = (self.ACCOUNT_RISK_LIMIT / (risk_dist + 1e-10)) * 100
        
        return {
            "stop_loss": round(final_stop, 2),
            "risk_pct": round(risk_dist * 100, 2),
            "ei": ei,
            "weight": round(min(weight_raw, self.MAX_WEIGHT), 1)
        }

    def _calculate_livermore_logic(self, df):
        """
        [v9.8.0] David's Conservative Livermore: 1년/반기 신고가 기반 확증
        - 단기 노이즈(20일/3일 상승) 제거
        - 252일(1년) 및 126일(반기) 구조적 돌파 시에만 리스크 할인 적용
        """
        if len(df) < 126: return "데이터 분석 기간 부족", 0.0
        
        close = df['Close']
        curr_price = close.iloc[-1]
        
        # 1. 장기 고점 데이터 확보 (과거 데이터 기준)
        period_1y = min(len(df)-1, 252)
        period_6m = min(len(df)-1, 126)
        
        high_1y = close.rolling(period_1y).max().iloc[-2]
        high_6m = close.rolling(period_6m).max().iloc[-2]
        
        # 2. 돌파 조건 판정
        is_1y_break = curr_price >= high_1y
        is_6m_break = curr_price >= high_6m

        # 3. 추세 안착 조건 (가짜 돌파 방지: 가격이 20일 이평선 위에 있는가)
        ma20 = close.rolling(20).mean().iloc[-1]
        is_supported = curr_price > ma20

        # 4. 위계적 할인율 적용
        if is_1y_break and is_supported:
            return "연간(1년) 신고가 확증", 0.30
        elif is_6m_break and is_supported:
            return "반기(6개월) 신고가 확증", 0.15
        elif is_1y_break or is_6m_break:
            # 돌파는 했으나 지지선 아래인 경우 (Spike 위험)
            return "중장기 돌파 시도 [안착 확인 필요]", 0.05
            
        return "구조적 추세 전환 대기 (박스권)", 0.0

    def _get_level(self, score):
        """[v9.7.0] 9단계 정밀 리스크 레벨 판정 (David's Antifragile Scale)"""
        if score >= 91: return 9   # Exit (100%)
        if score >= 81: return 8   # Aggressive Sell (70%)
        if score >= 71: return 7   # Active Sell (50%)
        if score >= 61: return 6   # Preemptive Sell (30%)
        if score >= 41: return 5   # Neutral / Hold
        if score >= 31: return 4   # Partial Entry (10-20%)
        if score >= 21: return 3   # Active Buy (40%)
        if score >= 11: return 2   # Concentration (70%)
        return 1                   # Full Betting (Max Weight)

    def get_sop_info(self, score):
        """[v9.7.0] 9단계 분할 매매 실행 지침 (Standard Operating Procedure)"""
        lvl = self._get_level(score)
        
        sop_map = {
            9: ("EXIT", "전량 회수: 리스크 극단치. 보유 물량 100% 매도 및 현금화"),
            8: ("DANGER", "공격적 익절: 위기 고조. 보유 물량 70% 익절 및 비중 축소"),
            7: ("WARNING", "적극적 익절: 과열 확연. 보유 물량 50% 익절 권고"),
            6: ("CAUTION", "예방적 감축: 경계 신호. 보유 물량 30% 익절 혹은 손절선 상향"),
            5: ("WATCH", "추세 관찰: 중립 구간. 기존 비중 유지 및 매크로 주시"),
            4: ("ENTRY", "분할 진입: 바닥 확인 중. 가용 자금의 10~20% 1차 투입"),
            3: ("ACCUMULATE", "적극 매집: 안정적 추세. 가용 자금의 40%까지 비중 확대"),
            2: ("CONCENTRATE", "비중 집중: 저평가 구간. 권고 비중의 70%까지 확대"),
            1: ("STRONG BUY", "적극 매수: 리스크 최저. 최대 권고 비중(20%) 풀 베팅")
        }
        
        label, action = sop_map.get(lvl, ("UNKNOWN", "데이터 분석 중"))
        return label, lvl, action

    def _get_part_verdicts(self, p1, p2, p4, discrepancy, has_bench, latest):
        """진단 문구 생성 로직"""
        v1 = "정상 범위 내 위치"
        if p1 >= 25: v1 = "[광기🚨] 역사적 고점 돌파 - 평균 회귀 위험 임계점"
        elif p1 >= 15: v1 = "[과열⚠️] 변동성 상단 안착 - 리스크 가중치 증가"
        
        v2 = "수급 및 자금 흐름 안정"
        if p2 >= 35: v2 = "🚨 수급 에너지 임계점 - 가격-자금 간 심각한 괴리 심화"
        elif has_bench and discrepancy > 15: v2 = f"⚠️ 지수 대비 과도한 관성 쏠림({discrepancy:+}) 경계"
        
        disp = latest.get('disp120', 100.0)
        limit = latest.get('disp120_limit', 115.0)
        v4 = "추세 관성 유지 중"
        if disp > limit: v4 = "🚨 구조적 한계선 돌파 (과이격) - 강력한 저항 및 급락 위험"
        elif disp > limit * 0.95: v4 = "⚠️ 구조적 저항선(Limit) 근접 - 돌파 확인 필요"
        return v1, v2, v4

    def perform_live_backtest(self, df, latest):
        """현재 지표 기반 기대 MDD 추정"""
        curr_rsi = latest.get('RSI', latest.get('rsi', 50))
        curr_sigma = latest.get('avg_sigma', 0)
        base_mdd = -15.0 if curr_sigma > 2.0 else -5.0
        recovery_days = 20 if curr_rsi > 70 else 10
        return {"avg_mdd": round(base_mdd, 1), "avg_days": int(recovery_days)}

    def _calc_position_risk(self, latest):
        avg_sigma = latest.get('avg_sigma', 0.0)
        return round(np.clip(avg_sigma / self.SIGMA_CRITICAL_LEVEL, 0, 1) * self.W_POS_BASE, 1)

    def _calc_energy_risk(self, latest):
        mfi, rsi = latest.get('mfi', 50.0), latest.get('rsi', 50.0)
        bbw, bbw_thr = latest.get('bbw', 0.0), latest.get('bbw_thr', 0.3)
        s_macd = self.MACD_REVERSAL_RISK if latest.get('macd_h', 0) < 0 else self.MACD_STABLE_LOW_RISK
        s_bbw = self.BBW_EXPANSION_RISK if bbw > bbw_thr else self.BBW_NORMAL_RISK
        s_mfi = self.MFI_DIVERGENCE_RISK if mfi < rsi else self.MFI_STABLE_RISK
        return round(np.clip(((s_macd + s_bbw + s_mfi) / self.ENERGY_MAX_RAW) * self.W_ENERGY_BASE, 0, self.W_ENERGY_BASE), 1)

    def _calc_trap_risk(self, latest):
        if latest.get('ma_slope') == "Falling": return self.W_TRAP_BASE
        curr_disp = latest.get('disp120', 100.0)
        limit_disp = latest.get('disp120_limit', 115.0)
        avg_disp = latest.get('disp120_avg', 105.0)
        risk_ratio = np.clip((curr_disp - avg_disp) / (limit_disp - avg_disp + 1e-10), 0, 1)
        return round(risk_ratio * self.W_TRAP_BASE, 1)

    def _get_dynamic_multiplier(self, latest, base_raw):
        slope, r2, adx = latest.get('slope', 0.0), latest.get('R2', 0.0), latest.get('ADX', 0.0)
        if slope > 0:
            quality = (r2 * 0.7) + (np.clip(adx / 40.0, 0, 1) * 0.3)
            return round(1.0 - (quality * 0.40 * np.clip((80.0 - base_raw) / 40.0, 0, 1)), 2), "BULLISH"
        return round(1.0 + (((r2 * 0.7) + (np.clip(adx / 40.0, 0, 1) * 0.3)) * 0.60), 2), "BEARISH"

    def _get_r2_interpretation(self, r2):
        if r2 >= 0.85: return "매우 직선적"
        if r2 >= 0.60: return "안정적 추세"
        return "추세 노이즈"
    
    def _get_detailed_energy_comment(self, mfi, rsi, macd_h):
        """[v9.5.6] 수급 지표의 정성적 해석 엔진"""
        # 1. MFI (자금 유입의 질)
        if mfi >= 70: mfi_desc = "자금 과열(유입 한계)"
        elif mfi <= 30: mfi_desc = "자금 고갈(관심 부족)"
        else: mfi_desc = "자금 흐름 보통"
        
        # 2. RSI (상승 에너지의 탄력)
        if rsi >= 70: rsi_desc = "매수 과열"
        elif rsi <= 30: rsi_desc = "매수 위축"
        else: rsi_desc = "탄력 적정"
        
        # 3. MACD Hist (추세의 엔진 가속도)
        if macd_h > 0:
            macd_desc = "상승 가속" 
        elif macd_h < 0:
            macd_desc = "하락 가속"
        else:
            macd_desc = "방향성 탐색"
            
        return f"MFI:{mfi_desc}, RSI:{rsi_desc}, MACD:{macd_desc}"

    # evaluate 메서드 내 details 딕셔너리에 추가
    # "energy_detail": self._get_detailed_energy_comment(mfi, rsi, macd_h)

    def _get_supply_intelligence(self, mfi, rsi):
        """[v9.5.7] RSI와 MFI의 상관관계를 분석하여 수급의 진정성 판별"""
        diff = mfi - rsi
        
        # 1. 수급 괴리 분석 (David님 제안 로직)
        if rsi > 60 and mfi < rsi:
            # 가격은 과열권인데 자금 유입이 못 따라오는 경우
            conclusion = "⚠️ 수급 불일치: 거래량 없는 상승 (신뢰도 낮음)"
            risk_hint = "상승 에너지 고갈 주의"
        elif mfi > 70 and rsi < 60:
            # 가격은 조용한데 자금이 강력하게 유입되는 경우 (매집 징후)
            conclusion = "✅ 수급 우위: 조용한 자금 유입 (매집 가능성)"
            risk_hint = "추세 전환 기대"
        elif mfi > 70 and rsi > 70:
            conclusion = "🚨 광기 구간: 가격과 자금 모두 극한의 과열"
            risk_hint = "강력한 조정 경계"
        elif diff > 10:
            conclusion = "🦾 수급 탄탄: 가격 대비 자금 유입 강함"
            risk_hint = "추세 지속성 높음"
        else:
            conclusion = "⚖️ 수급 균형: 가격과 자금 흐름 일치"
            risk_hint = "현재 추세 유지"
            
        return conclusion, risk_hint