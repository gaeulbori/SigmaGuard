"""
[File Purpose]
- 진입 트리거, 트레일링 스탑, 시간 기반 청산, entry_stop 손절, 리스크레벨 청산 신호를 감지하는 엔진.
- SigmaGuard의 감사 루프(execute_all) 완료 후 실전 매매 의사결정을 보조하는 신호 생성.
- 시뮬레이션(performance_simulator.py) 로직과 동기화됨.

[Signal Types]
- Entry Trigger    : 저위험 구간(레벨 1~3)에서 복수 조건 충족 시 진입 검토 신호
- Entry Stop       : 진입 시 설정한 손절가 이탈 시 즉시 전량 청산
- Trailing Stop    : 수익 구간(+5% 이상)에서 trail_stop(고점-ATR×배수) 이탈 시 전량 청산
                     USD: ATR×3/4/5, KRW: ATR×6/8/10 (수익 구간별)
- Risk Level Exit  : 리스크 레벨 9→전량, 레벨 8→70% 청산
- Time-based Exit  : T+60일 손실 지속 또는 T+90일 수익 +5% 미만 시 청산 검토 신호
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

        # 수익률 구간별 ATR 배수 — USD 기준 (시뮬 동기화)
        self.TRAIL_ATR_LOW  = 3.0        # USD +5~20% 구간
        self.TRAIL_ATR_MID  = 4.0        # USD +20~50% 구간
        self.TRAIL_ATR_HIGH = 5.0        # USD +50%+ 구간

        # KRW 전용 ATR 배수 (추세 지속형, USD 대비 느슨하게)
        self.TRAIL_ATR_LOW_KRW  = 6.0   # KRW +5~20% 구간
        self.TRAIL_ATR_MID_KRW  = 8.0   # KRW +20~50% 구간
        self.TRAIL_ATR_HIGH_KRW = 10.0  # KRW +50%+ 구간

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
        [트레일링 스탑 감지 — 단순 trail_stop 이탈 방식 (시뮬 동기화)]

        수익률 구간별 ATR 배수 (통화별):
          USD: +5~20% → ×3.0 / +20~50% → ×4.0 / +50%+ → ×5.0
          KRW: +5~20% → ×6.0 / +20~50% → ×8.0 / +50%+ → ×10.0

        판정:
          trail_stop = trailing_high - ATR × 배수
          현재가 < trail_stop → grade=3 (전량 청산)
          그 외              → grade=0 (미발동)

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

            # ── 통화별 ATR 배수 결정 ────────────────────────────────
            currency = holding.get('currency', 'USD')
            if currency == 'KRW':
                if profit_pct >= 50.0:
                    atr_mult = self.TRAIL_ATR_HIGH_KRW
                elif profit_pct >= 20.0:
                    atr_mult = self.TRAIL_ATR_MID_KRW
                else:
                    atr_mult = self.TRAIL_ATR_LOW_KRW
            else:
                if profit_pct >= 50.0:
                    atr_mult = self.TRAIL_ATR_HIGH
                elif profit_pct >= 20.0:
                    atr_mult = self.TRAIL_ATR_MID
                else:
                    atr_mult = self.TRAIL_ATR_LOW

            # ── trailing_high 단방향 갱신 (DB 저장값 기준) ────────────
            existing_trail_high = holding.get('trailing_high', 0.0) or 0.0
            new_trail_high      = max(current_price, existing_trail_high)

            # 동적 스탑가: trailing_high - ATR × 배수
            trail_stop_price = new_trail_high - (atr * atr_mult)

            # 고점 대비 현재가 낙폭
            drawdown_pct = ((current_price - new_trail_high)
                            / (new_trail_high + 1e-10)) * 100

            # ── DB 갱신 (수익 +5% 이상이면 trailing_high 항상 추적) ───
            if self.db:
                self.db.update_trailing_high(ticker, new_trail_high, trail_stop_price)

            # ── 이탈 판정 (단순 전량 청산) ────────────────────────────
            grade = 3 if current_price < trail_stop_price else 0

            details = {
                'atr':              atr,
                'atr_mult':         atr_mult,
                'currency':         currency,
                'trailing_high':    new_trail_high,
                'trail_stop_price': trail_stop_price,
                'drawdown_pct':     drawdown_pct,
                'sell_ratio':       1.0 if grade == 3 else 0.0,
            }

            if grade == 3:
                logger.info(
                    f"🔴 [{ticker}] 트레일링 스탑 발동 (전량청산) "
                    f"수익: {profit_pct:+.1f}%, {currency} ATR: {atr:.2f}×{atr_mult}, "
                    f"스탑: {trail_stop_price:.2f}, 낙폭: {drawdown_pct:+.1f}%"
                )

            return grade, profit_pct, details

        except Exception as e:
            logger.error(f"❌ [{ticker}] 트레일링 스탑 계산 오류: {e}")
            return 0, profit_pct, {}

    def check_entry_stop(self, holding, current_price):
        """
        [Entry Stop 손절 감지]
        - 진입 시 설정한 손절가(entry_stop) 이탈 시 즉시 전량 청산 신호
        - 반환: bool (True = 손절 발동)
        """
        entry_stop = holding.get('entry_stop', 0.0) or 0.0
        if entry_stop > 0 and current_price < entry_stop:
            ticker = holding.get('ticker', '?')
            logger.info(
                f"🛑 [{ticker}] Entry Stop 손절 발동 "
                f"(현재가: {current_price:.2f} < 손절가: {entry_stop:.2f})"
            )
            return True
        return False

    def check_risk_level_exit(self, risk_level):
        """
        [리스크 레벨 기반 청산 감지]
        - 레벨 9 (score ≥ 91): 전량 청산 (100%)
        - 레벨 8 (score ≥ 81): 70% 청산
        - 그 외: 미발동
        - 반환: (triggered: bool, ratio: float, reason: str)
        """
        level = int(risk_level or 0)
        if level >= 9:
            return True, 1.0, "risk_lv9"
        if level >= 8:
            return True, 0.70, "risk_lv8"
        return False, 0.0, ""

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
