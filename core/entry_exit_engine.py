"""
[File Purpose]
- 진입 트리거, 트레일링 스탑, 시간 기반 청산 신호를 감지하는 엔진.
- SigmaGuard의 감사 루프(execute_all) 완료 후 실전 매매 의사결정을 보조하는 신호 생성.

[Signal Types]
- Entry Trigger  : 저위험 구간(레벨 1~3)에서 복수 조건 충족 시 진입 검토 신호
- Trailing Stop  : 수익 구간(+5% 이상)에서 고점 대비 낙폭 -3% 초과 시 청산 신호
- Time-based Exit: T+60일 손실 지속 또는 T+90일 수익 +5% 미만 시 청산 검토 신호
"""

from datetime import datetime
from utils.logger import setup_custom_logger

logger = setup_custom_logger("EntryExitEngine")


class EntryExitEngine:
    def __init__(self, db=None):
        # DB 핸들러 (trailing_high / trailing_stop 갱신용, 없으면 DB 갱신 생략)
        self.db = db

        # --- 진입 트리거 임계치 ---
        self.ENTRY_SCORE_MAX    = 31.0    # 레벨 1~3 해당 최대 점수 (score < 31)
        self.ENTRY_MIN_OPTIONAL = 2       # B~E 중 충족 필요 최소 조건 수

        # --- 트레일링 스탑 임계치 ---
        self.TRAIL_PROFIT_FLOOR = 5.0    # 활성화 최소 수익률 (%)

        # 수익률 구간별 ATR 배수 (보호 강도 차등)
        self.TRAIL_ATR_LOW  = 2.0        # 수익 +5~20% 구간
        self.TRAIL_ATR_MID  = 2.5        # 수익 +20~50% 구간
        self.TRAIL_ATR_HIGH = 3.0        # 수익 +50% 이상 구간

        # 축2 기준: 레벨 6 이상 (score >= 61)
        self.TRAIL_SCORE_THR = 61.0

        # --- 시간 기반 청산 임계치 ---
        self.TIME_LOSS_DAYS = 60          # 손실 장기화 판단 기준 경과일
        self.TIME_OPP_DAYS  = 90          # 기회비용 판단 기준 경과일
        self.TIME_OPP_PCT   = 5.0         # 기회비용 판단 최소 수익률 (%)

    def check_entry_trigger(self, ticker, score, details, ind_df, prev_score):
        """
        [진입 트리거 감지]
        - 조건 A (필수): score 레벨 1~3 (score < 31)
        - 조건 B: avg_sigma 전일 대비 상승 (바닥 반등 중)
        - 조건 C: macd_h 음수 구간에서 증가 전환
        - 조건 D: MFI 40 이하에서 반등
        - 조건 E: prev_score 존재 & 현재 score < prev_score (위험 감소 중)
        - A 필수 + B~E 중 2개 이상 충족 시 (True, 조건 목록) 반환
        """
        # 조건 A: 레벨 1~3 범위 여부 (필수 관문)
        if score >= self.ENTRY_SCORE_MAX:
            return False, []

        # ind_df 유효성 검증
        if ind_df is None or len(ind_df) < 3:
            logger.warning(f"⚠️ [{ticker}] 진입 트리거: ind_df 데이터 부족 (최소 3일 필요)")
            return False, []

        met_conditions = [f"A: 저위험 진입 구간 (점수 {score:.1f}, 레벨 1~3)"]
        optional_met = 0

        try:
            latest = ind_df.iloc[-1]
            prev   = ind_df.iloc[-2]

            # 조건 B: avg_sigma 전일 대비 상승 (바닥 반등 시그널)
            curr_sigma = latest.get('avg_sigma', 0.0)
            prev_sigma = prev.get('avg_sigma', 0.0)
            if curr_sigma > prev_sigma:
                met_conditions.append(
                    f"B: avg_sigma 상승 전환 ({prev_sigma:.2f} → {curr_sigma:.2f}, 바닥 반등)"
                )
                optional_met += 1

            # 조건 C: macd_h 음수 구간에서 증가 전환 (하락 모멘텀 약화)
            curr_macd_h = latest.get('macd_h', 0.0)
            prev_macd_h = prev.get('macd_h', 0.0)
            if curr_macd_h < 0 and curr_macd_h > prev_macd_h:
                met_conditions.append(
                    f"C: MACD 히스토그램 음수 구간 반등 ({prev_macd_h:.3f} → {curr_macd_h:.3f})"
                )
                optional_met += 1

            # 조건 D: MFI 40 이하에서 반등 (과매도 구간 수급 회복)
            curr_mfi = latest.get('MFI', 50.0)
            prev_mfi = prev.get('MFI', 50.0)
            if prev_mfi <= 40.0 and curr_mfi > prev_mfi:
                met_conditions.append(
                    f"D: MFI 과매도 구간 반등 ({prev_mfi:.1f} → {curr_mfi:.1f})"
                )
                optional_met += 1

            # 조건 E: 전일 대비 리스크 점수 개선 (위험 완화 추세)
            if prev_score is not None and score < prev_score:
                met_conditions.append(
                    f"E: 리스크 점수 개선 중 ({prev_score:.1f} → {score:.1f})"
                )
                optional_met += 1

        except Exception as e:
            logger.error(f"❌ [{ticker}] 진입 트리거 조건 계산 오류: {e}")
            return False, []

        if optional_met >= self.ENTRY_MIN_OPTIONAL:
            logger.info(
                f"📡 [{ticker}] 진입 트리거 감지 "
                f"(점수: {score:.1f}, 선택 조건 {optional_met}/4 충족)"
            )
            return True, met_conditions

        return False, []

    def check_trailing_stop(self, holding, current_price, ind_df=None,
                             score=None, score_history=None):
        """
        [트레일링 스탑 감지 — ATR 다축 등급 버전]

        수익률 구간별 ATR 배수:
          +5~20%  → ATR * 2.0
          +20~50% → ATR * 2.5
          +50%+   → ATR * 3.0

        3개 축 동시 판정:
          축1(가격): 현재가 < trailing_high - ATR*배수
          축2(점수): 레벨 6+(score≥61) AND 최근 3일 점수 연속 상승
          축3(수급): [MFI<RSI] · [MACD 3일 연속 감소] · [ADX 약화] 중 2개 이상

        등급:
          3단계 🔴 (축1+2+3): 전량 청산
          2단계 🟠 (축1+2)  : 분할 청산 (수익 50%+ → 30%, 미만 → 50%)
          1단계 🟡 (축1|2)  : 관찰만
          0      (나머지)  : 미발동

        반환: (grade: int, profit_pct: float, details: dict)
        """
        ticker    = holding.get('ticker', '?')
        avg_price = holding.get('avg_price', 0.0)

        # 방어 코딩: 단가 또는 현재가 0 처리
        if avg_price <= 0 or current_price <= 0:
            return 0, 0.0, {}

        profit_pct = ((current_price - avg_price) / avg_price) * 100

        # 활성화 조건 미달: 수익률 +5% 미만이면 트레일링 불필요
        if profit_pct < self.TRAIL_PROFIT_FLOOR:
            return 0, profit_pct, {}

        try:
            # ── ATR 획득 ──────────────────────────────────────────────
            atr = 0.0
            if ind_df is not None and not ind_df.empty and 'atr' in ind_df.columns:
                atr_raw = ind_df['atr'].iloc[-1]
                try:
                    atr = float(atr_raw)
                    if atr != atr:  # NaN 방어
                        atr = 0.0
                except (TypeError, ValueError):
                    atr = 0.0

            if atr <= 0:
                logger.warning(f"⚠️ [{ticker}] ATR 값 미확보 — 트레일링 스탑 비활성")
                return 0, profit_pct, {}

            # ── 수익률 구간별 ATR 배수 결정 ────────────────────────────
            if profit_pct >= 50.0:
                atr_mult = self.TRAIL_ATR_HIGH
            elif profit_pct >= 20.0:
                atr_mult = self.TRAIL_ATR_MID
            else:
                atr_mult = self.TRAIL_ATR_LOW

            # ── trailing_high 단방향 갱신 (DB 저장값 기준) ────────────
            existing_trail_high = holding.get('trailing_high', 0.0) or 0.0
            new_trail_high      = max(current_price, existing_trail_high)

            # 동적 스탑가: trailing_high - ATR * 배수
            trail_stop_price = new_trail_high - (atr * atr_mult)

            # 고점 대비 현재가 낙폭
            drawdown_pct = ((current_price - new_trail_high)
                            / (new_trail_high + 1e-10)) * 100

            # ── 축1: 가격 이탈 ────────────────────────────────────────
            axis1 = bool(current_price < trail_stop_price)

            # ── 축2: 리스크 점수 레벨 + 연속 상승 추세 ───────────────────
            # 레벨 6+(score≥61) AND score_history에서 현재까지 단조 증가 확인
            axis2 = False
            if score is not None and score >= self.TRAIL_SCORE_THR:
                if score_history and len(score_history) >= 2:
                    # score_history = [oldest, ..., newest] (현재값 제외)
                    rising_hist = all(
                        score_history[i] < score_history[i + 1]
                        for i in range(len(score_history) - 1)
                    )
                    axis2 = rising_hist and (score_history[-1] < score)
                # 이력 부족(< 2건) 시 연속 상승 미확인 → axis2=False 유지

            # ── 축3: 수급 약화 2/3 이상 ──────────────────────────────
            axis3_flags = {'mfi_rsi': False, 'macd': False, 'adx': False}
            if ind_df is not None and len(ind_df) >= 3:
                latest = ind_df.iloc[-1]
                prev   = ind_df.iloc[-2]
                prev2  = ind_df.iloc[-3]

                # 수급1: MFI < RSI (머니플로우 약화)
                axis3_flags['mfi_rsi'] = bool(
                    latest.get('MFI', 50.0) < latest.get('RSI', 50.0)
                )

                # 수급2: MACD 히스토그램 3일 연속 감소
                m0 = latest.get('macd_h', 0.0)
                m1 = prev.get('macd_h', 0.0)
                m2 = prev2.get('macd_h', 0.0)
                axis3_flags['macd'] = bool(m2 > m1 > m0)

                # 수급3: ADX 약화 (전일 대비 감소)
                axis3_flags['adx'] = bool(
                    latest.get('ADX', 0.0) < prev.get('ADX', 0.0)
                )

            axis3_count = sum(axis3_flags.values())
            axis3       = (axis3_count >= 2)

            # ── 등급 판정 ─────────────────────────────────────────────
            if   axis1 and axis2 and axis3: grade = 3  # 🔴 전량 청산
            elif axis1 and axis2:           grade = 2  # 🟠 분할 청산
            elif axis1 or  axis2:           grade = 1  # 🟡 관찰
            else:                           grade = 0  # 미발동

            # 분할 비율 (2단계 한정)
            sell_ratio = 0.0
            if grade == 3:
                sell_ratio = 1.0
            elif grade == 2:
                sell_ratio = 0.30 if profit_pct >= 50.0 else 0.50

            # ── DB 갱신 (수익 +5% 이상이면 trailing_high 항상 추적) ───
            if self.db:
                self.db.update_trailing_high(ticker, new_trail_high, trail_stop_price)

            details = {
                'axis1':            axis1,
                'axis2':            axis2,
                'axis3':            axis3,
                'axis3_flags':      axis3_flags,
                'atr':              atr,
                'atr_mult':         atr_mult,
                'trailing_high':    new_trail_high,
                'trail_stop_price': trail_stop_price,
                'drawdown_pct':     drawdown_pct,
                'sell_ratio':       sell_ratio,
            }

            if grade == 3:
                logger.info(
                    f"🔴 [{ticker}] 트레일링 스탑 3단계 (전량청산) "
                    f"수익: {profit_pct:+.1f}%, ATR: {atr:.2f}×{atr_mult}, "
                    f"스탑: ${trail_stop_price:.2f}, 낙폭: {drawdown_pct:+.1f}%"
                )
            elif grade == 2:
                logger.info(
                    f"🟠 [{ticker}] 트레일링 스탑 2단계 (분할청산 {sell_ratio*100:.0f}%) "
                    f"수익: {profit_pct:+.1f}%, ATR: {atr:.2f}×{atr_mult}"
                )
            elif grade == 1:
                logger.info(
                    f"🟡 [{ticker}] 트레일링 스탑 1단계 (관찰) "
                    f"수익: {profit_pct:+.1f}%, 축1={axis1}, 축2={axis2}"
                )

            return grade, profit_pct, details

        except Exception as e:
            logger.error(f"❌ [{ticker}] 트레일링 스탑 계산 오류: {e}")
            return 0, profit_pct, {}

    def check_time_based_exit(self, holding, current_price):
        """
        [시간 기반 청산 신호 감지]
        - T+60일 초과 & 수익률 0% 미만     → "손실 장기화" 청산 신호
        - T+90일 초과 & 수익률 +5% 미만    → "기회비용" 청산 신호
        - 조건 미달 시 None 반환

        반환 예시: {'reason': '손실 장기화', 'elapsed_days': 75, 'profit_pct': -3.2}
        """
        ticker           = holding.get('ticker', '?')
        avg_price        = holding.get('avg_price', 0.0)
        last_updated_str = holding.get('last_updated', '')

        # 방어 코딩: 필수 필드 누락 처리
        if avg_price <= 0 or not last_updated_str:
            return None

        # 날짜 파싱
        try:
            last_updated = datetime.strptime(last_updated_str, '%Y-%m-%d')
        except ValueError:
            logger.warning(
                f"⚠️ [{ticker}] last_updated 파싱 실패 (값: '{last_updated_str}')"
            )
            return None

        elapsed_days = (datetime.now() - last_updated).days
        profit_pct   = ((current_price - avg_price) / (avg_price + 1e-10)) * 100

        # T+60 초과 & 손실 구간 → 손실 장기화
        if elapsed_days > self.TIME_LOSS_DAYS and profit_pct < 0:
            logger.info(
                f"⏰ [{ticker}] 손실 장기화 청산 신호 "
                f"(경과: {elapsed_days}일, 수익률: {profit_pct:+.1f}%)"
            )
            return {
                'reason':       '손실 장기화',
                'elapsed_days': elapsed_days,
                'profit_pct':   round(profit_pct, 2)
            }

        # T+90 초과 & 수익 +5% 미만 → 기회비용
        if elapsed_days > self.TIME_OPP_DAYS and profit_pct < self.TIME_OPP_PCT:
            logger.info(
                f"⏰ [{ticker}] 기회비용 청산 신호 "
                f"(경과: {elapsed_days}일, 수익률: {profit_pct:+.1f}%)"
            )
            return {
                'reason':       '기회비용',
                'elapsed_days': elapsed_days,
                'profit_pct':   round(profit_pct, 2)
            }

        return None
