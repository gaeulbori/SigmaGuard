"""
[Program 상세 설명]
1. PreComputeEngine  : 워치리스트 전 종목의 지표와 리스크 점수를 워크-포워드 방식으로 사전 계산하여
                       data/sim_cache/{ticker}_computed.csv 에 캐싱합니다. (최초 1회)
2. PortfolioSimulator: KRW/USD 이중 포트폴리오를 날짜별로 순회하며 진입·청산 신호를 적용하고
                       일별 잔고를 data/sim_results/daily_log.csv 에 기록합니다.
3. PerformanceReporter: 시뮬레이션 결과를 SPY / KOSPI 벤치마크와 비교하고 신호별·파라미터별
                        민감도 분석을 포함한 종합 성과 리포트를 출력합니다.
"""

import os
import sys
import gc
import re
import logging
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime

warnings.filterwarnings("ignore")

# ── 경로 설정 ──────────────────────────────────────────────────────────────────
current_dir = os.path.dirname(os.path.abspath(__file__))   # tests/
sg_root     = os.path.dirname(current_dir)                  # SG/
work_root   = os.path.dirname(sg_root)                      # work/
common_root = os.path.join(work_root, "common")

for p in [sg_root, common_root]:
    if p not in sys.path:
        sys.path.insert(0, p)

from core.indicators import Indicators
from core.risk_engine import RiskEngine
from config.settings   import settings
from utils.logger       import setup_custom_logger

# ── 전역 경로 상수 ─────────────────────────────────────────────────────────────
CACHE_DIR   = os.path.join(sg_root, "data", "sim_cache")
RESULTS_DIR = os.path.join(sg_root, "data", "sim_results")
LOG_DIR     = os.path.join(sg_root, "logs")
for d in [CACHE_DIR, RESULTS_DIR, LOG_DIR]:
    os.makedirs(d, exist_ok=True)

# ── 시뮬레이션 파라미터 ────────────────────────────────────────────────────────
SIM_START        = "2020-01-01"
SIM_END          = "2024-12-31"
FETCH_START      = "2014-01-01"   # 5y 시그마 확보를 위한 선행 데이터
INIT_KRW         = 40_000_000     # KRW 초기 자금
INIT_USD         = 10_000.0       # USD 초기 자금
MAX_HOLDINGS     = 10             # 최대 동시 보유 종목
MAX_WEIGHT_PCT   = 3.0            # 종목당 최대 비중 (%)
ACCOUNT_RISK     = 0.008          # 단일 종목 최대 손실 허용 (0.8%)

# ── 시뮬레이션 레저 53컬럼 (sigma_guard_ledger 포맷 호환) ─────────────────────
SIM_LEDGER_COLS = [
    'Audit_Date', 'Ticker', 'Name', 'Risk_Score', 'Risk_Level',
    'Price_T', 'Sigma_T_Avg',
    'Sigma_T_1y', 'Sigma_T_2y', 'Sigma_T_3y', 'Sigma_T_4y', 'Sigma_T_5y',
    'RSI_T', 'MFI_T', 'BBW_T', 'R2_T', 'ADX_T', 'Disp_T_120',
    'Ticker_B', 'Price_B', 'Sigma_B_Avg', 'RSI_B', 'MFI_B', 'ADX_B', 'BBW_B',
    'Stop_Price', 'Risk_Gap_Pct', 'Invest_EI', 'Weight_Pct', 'Expected_MDD',
    'Livermore_Status', 'Base_Raw_Score', 'Risk_Multiplier', 'Trend_Scenario',
    'Score_Pos', 'Score_Pos_EMA', 'Score_Ene', 'Score_Ene_EMA',
    'Score_Trap', 'Score_Trap_EMA',
    'VIX_T', 'US10Y_T', 'DXY_T', 'MACD_Hist_T', 'MACD_Hist_B',
    'ADX_Gap', 'Disp_Limit', 'BBW_Thr', 'LIV_Discount', 'SOP_Action',
    'Ret_20d', 'Min_Ret_20d', 'Max_Ret_20d',
]

# ── 통화 구분 유틸 ─────────────────────────────────────────────────────────────
def _get_currency(ticker: str) -> str:
    """티커 접미사로 통화 분류 → 'KRW' 또는 'USD'"""
    if ticker.endswith(".KS") or ticker.endswith(".KQ"):
        return "KRW"
    return "USD"   # .T(JPY), .SS/.SZ/.HK(CNY/HKD) 모두 USD로 근사

def _safe_ticker_name(ticker: str) -> str:
    """파일명으로 사용할 수 있도록 특수문자를 '_'로 치환"""
    return re.sub(r'[^A-Za-z0-9.\-]', '_', ticker)


# ══════════════════════════════════════════════════════════════════════════════
# [Step 1] PreComputeEngine
# ══════════════════════════════════════════════════════════════════════════════
class PreComputeEngine:
    """
    SG_config.yaml 워치리스트 전 종목의 기술적 지표와 리스크 점수를
    워크-포워드(Walk-Forward) 방식으로 일별 사전 계산 후 CSV 캐싱.

    캐시 컬럼:
      Date, Close, Score, Risk_Level,
      avg_sigma, RSI, MFI, ADX, R2, bbw, bbw_thr,
      macd_h, atr, disp120, disp120_limit, slope, ma_slope,
      sig_1y~5y, p1, p2, p4
    """

    # 저장할 지표 컬럼 목록 (indicators._process_single_ticker 산출 컬럼 기준)
    IND_COLS = [
        'Close', 'avg_sigma', 'RSI', 'MFI', 'ADX', 'R2',
        'bbw', 'bbw_thr', 'macd_h', 'atr',
        'disp120', 'disp120_limit', 'disp120_avg', 'slope', 'ma_slope',
        'sig_1y', 'sig_2y', 'sig_3y', 'sig_4y', 'sig_5y',
    ]

    def __init__(self):
        self.logger     = setup_custom_logger("PreComputeEngine")
        self._setup_file_log()
        self.indicators = Indicators()
        self.risk_engine = RiskEngine()

    def _setup_file_log(self):
        fh = logging.FileHandler(
            os.path.join(LOG_DIR, "sigma_guard_sim.log"), mode='w', encoding='utf-8'
        )
        fh.setFormatter(logging.Formatter('[%(asctime)s | %(levelname)s] %(name)s | %(message)s'))
        self.logger.addHandler(fh)

    # ── 공개 API ──────────────────────────────────────────────────────────────
    def run(self, force: bool = False):
        """
        전 워치리스트 사전 계산.
        :param force: True 이면 기존 캐시 무시하고 재계산
        """
        watchlist = settings.watchlist
        total     = len(watchlist)
        self.logger.info(f"🔧 [PreComputeEngine] 사전 계산 개시 — 총 {total}종목 (force={force})")

        ok, skip, fail = 0, 0, 0
        for idx, item in enumerate(watchlist, 1):
            ticker = item.get('ticker', '')
            bench  = item.get('bench') or None
            if not ticker:
                continue

            cache_path = os.path.join(CACHE_DIR, f"{_safe_ticker_name(ticker)}_computed.csv")
            if os.path.exists(cache_path) and not force:
                self.logger.info(f"  ⏭  [{idx:>3}/{total}] {ticker:>15} — 캐시 존재, 스킵")
                skip += 1
                continue

            success = self._compute_ticker(ticker, bench, cache_path, idx, total)
            if success:
                ok += 1
            else:
                fail += 1

        self.logger.info(
            f"✅ [PreComputeEngine] 완료 — 계산:{ok} / 스킵:{skip} / 실패:{fail}"
        )

    # ── 내부 메서드 ───────────────────────────────────────────────────────────
    def _compute_ticker(self, ticker: str, bench, cache_path: str,
                        idx: int, total: int) -> bool:
        """단일 종목의 워크-포워드 점수 계산 및 캐시 저장"""
        try:
            self.logger.info(f"  🔍 [{idx:>3}/{total}] {ticker:>15} — 지표 산출 중...")

            # 1. 전체 기간 지표 계산 (Look-ahead 없음: 과거 데이터 전체 사용)
            ind_df, bench_df = self.indicators.generate(ticker, period="10y", bench=bench)

            if ind_df is None or ind_df.empty:
                self.logger.warning(f"  ⚠️  [{ticker}] 데이터 없음 — 스킵")
                return False

            # 2. 시뮬레이션 기간 내 날짜 목록 추출
            sim_mask  = (ind_df.index >= SIM_START) & (ind_df.index <= SIM_END)
            sim_dates = ind_df.index[sim_mask]

            if len(sim_dates) == 0:
                self.logger.warning(f"  ⚠️  [{ticker}] 시뮬레이션 구간 데이터 없음 — 스킵")
                return False

            # 3. 워크-포워드 점수 계산 (EMA 상태 유지)
            results  = []
            prev_ema = None

            for date in sim_dates:
                # 현재 날짜까지의 슬라이스만 사용 → 미래 데이터 차단
                ind_slice   = ind_df[:date]
                bench_slice = bench_df[:date] if (bench_df is not None and not bench_df.empty) else None

                if len(ind_slice) < 30:
                    continue   # 초기 NaN 구간 스킵

                score, _, details = self.risk_engine.evaluate(
                    ind_slice, bench_slice, prev_ema
                )
                level = self.risk_engine.get_level(score)

                # EMA 상태 갱신 (다음 날로 전달)
                if details:
                    prev_ema = {
                        'p1_ema': details.get('p1_ema', details.get('p1', 0)),
                        'p2_ema': details.get('p2_ema', details.get('p2', 0)),
                        'p4_ema': details.get('p4_ema', details.get('p4', 0)),
                    }

                # 해당 날짜의 지표값 추출
                row = ind_df.loc[date]
                record = {'Date': date.strftime('%Y-%m-%d')}
                for col in self.IND_COLS:
                    record[col] = row.get(col, np.nan) if hasattr(row, 'get') else getattr(row, col, np.nan)

                record['Score']        = round(float(score), 2)
                record['Risk_Level']   = int(level)
                record['p1']           = round(float(details.get('p1',      0)),    2) if details else 0.0
                record['p2']           = round(float(details.get('p2',      0)),    2) if details else 0.0
                record['p4']           = round(float(details.get('p4',      0)),    2) if details else 0.0
                record['p1_ema']       = round(float(details.get('p1_ema',  0)),    2) if details else 0.0
                record['p2_ema']       = round(float(details.get('p2_ema',  0)),    2) if details else 0.0
                record['p4_ema']       = round(float(details.get('p4_ema',  0)),    2) if details else 0.0
                record['scenario']     = details.get('scenario',     '')                if details else ''
                record['liv_discount'] = round(float(details.get('liv_discount', 0)), 4) if details else 0.0
                record['sop_action']   = details.get('action',       '')                if details else ''
                results.append(record)

            if not results:
                self.logger.warning(f"  ⚠️  [{ticker}] 유효 결과 없음 — 스킵")
                return False

            # 4. CSV 저장
            pd.DataFrame(results).to_csv(cache_path, index=False, encoding='utf-8')
            self.logger.info(
                f"  💾 [{ticker}] 저장 완료 — {len(results)}일, {cache_path}"
            )
            return True

        except Exception as e:
            self.logger.error(f"  ❌ [{ticker}] 계산 오류: {e}")
            return False
        finally:
            # OCI 메모리 보호: 처리 후 즉시 해제
            del ind_df, bench_df
            gc.collect()


# ══════════════════════════════════════════════════════════════════════════════
# [Step 2] PortfolioSimulator
# ══════════════════════════════════════════════════════════════════════════════
class PortfolioSimulator:
    """
    사전 계산된 캐시 데이터를 기반으로 날짜별 KRW/USD 이중 포트폴리오를 시뮬레이션.

    청산 우선순위:
      1. entry_stop 손절 (즉시)
      2. 트레일링 스탑 2/3단계
      3. 시간 기반 청산 (T+60 손실 / T+90 수익 5% 미만)
      4. 리스크 레벨 8 이상 (70% 또는 100% 청산)

    진입 조건:
      - 보유 종목 수 < MAX_HOLDINGS
      - 가용 현금 존재
      - check_entry_trigger 발동
      - 동일 종목 미보유
      진입 우선순위: 점수 낮은 순 (리스크 최저 우선)
    """

    # ── ATR 파라미터 (파라미터 민감도 분석용 기본값) ───────────────────────────
    ATR_LOW  = 2.0    # 수익 +5~20% 구간
    ATR_MID  = 2.5    # 수익 +20~50% 구간
    ATR_HIGH = 3.0    # 수익 +50%+ 구간
    TRAIL_PROFIT_FLOOR  = 5.0     # 트레일링 스탑 활성화 최소 수익률(%)
    ENTRY_SCORE_MAX     = 31.0    # 진입 허용 최대 점수
    ENTRY_MIN_OPTIONAL  = 2       # B~E 충족 최소 개수
    TIME_LOSS_DAYS      = 60
    TIME_OPP_DAYS       = 90
    TIME_OPP_PCT        = 5.0

    def __init__(self, atr_low=None, atr_mid=None, atr_high=None, entry_min=None,
                 market_filter=None, max_holdings=None, max_weight_pct=None):
        self.logger      = setup_custom_logger("PortfolioSimulator")
        self.risk_engine = RiskEngine()

        # 파라미터 민감도 오버라이드 지원
        self.atr_low        = atr_low       or self.ATR_LOW
        self.atr_mid        = atr_mid       or self.ATR_MID
        self.atr_high       = atr_high      or self.ATR_HIGH
        self.entry_min      = entry_min     or self.ENTRY_MIN_OPTIONAL
        self.max_holdings   = max_holdings  or MAX_HOLDINGS
        self.max_weight_pct = max_weight_pct if max_weight_pct is not None else MAX_WEIGHT_PCT

        # ── 환율 캐시 ──────────────────────────────────────────────────────────
        self.fx_krw = self._load_fx("USDKRW=X")

        # ── 시장 방향 필터 (SPY / ^KS200 MA200) ───────────────────────────────
        self.market_filter = market_filter if market_filter is not None else self._load_market_filter()

        # ── 포트폴리오 상태 ────────────────────────────────────────────────────
        self.cash_krw = float(INIT_KRW)
        self.cash_usd = float(INIT_USD)

        # holdings[ticker] = {qty, avg_price, entry_price, entry_date, entry_stop, trailing_high}
        self.holdings: dict[str, dict] = {}

        # 일별 로그 누적
        self.daily_log: list[dict] = []
        # 완료된 거래 기록
        self.closed_trades: list[dict] = []

    # ── 환율 ──────────────────────────────────────────────────────────────────
    def _load_fx(self, ticker: str) -> pd.Series:
        """USDKRW 일별 환율 로드 (시뮬레이션 기간 + 버퍼)"""
        try:
            df = yf.download(ticker, start="2019-01-01", end="2025-01-01",
                             interval="1d", progress=False, auto_adjust=True)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            return df['Close'].ffill().bfill()
        except Exception as e:
            self.logger.warning(f"⚠️ 환율 로드 실패 ({ticker}): {e} — 기본값 1400 사용")
            return pd.Series(dtype=float)

    def _get_fx_rate(self, date) -> float:
        if self.fx_krw.empty:
            return 1400.0
        try:
            return float(self.fx_krw.asof(date))
        except Exception:
            return 1400.0

    # ── 시장 필터 ─────────────────────────────────────────────────────────────
    def _load_market_filter(self) -> dict:
        """
        SPY(USD) 및 ^KS200(KRW)의 MA200 상/하 여부를 날짜별로 사전 로드.
        반환: {'USD': pd.Series[bool], 'KRW': pd.Series[bool]}
        """
        result = {}
        for label, ticker in [('USD', 'SPY'), ('KRW', '^KS200')]:
            try:
                df = yf.download(ticker, start="2018-01-01", end="2025-12-31",
                                 interval="1d", progress=False, auto_adjust=True)
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                close = df['Close'].ffill().dropna()
                ma200 = close.rolling(200, min_periods=50).mean()
                result[label] = (close >= ma200).ffill()
                self.logger.info(f"  📊 시장 필터 로드 완료 [{ticker}]")
            except Exception as e:
                self.logger.warning(f"⚠️ 시장 필터 로드 실패 ({ticker}): {e} — 필터 비활성화")
                result[label] = pd.Series(dtype=bool)
        return result

    def _is_market_ok(self, currency: str, date) -> bool:
        """해당 통화권 지수가 MA200 위에 있으면 True (필터 미로드 시 진입 허용)"""
        series = self.market_filter.get(currency)
        if series is None or series.empty:
            return True
        try:
            val = series.asof(date)
            return True if pd.isna(val) else bool(val)
        except Exception:
            return True

    # ── 캐시 로드 ─────────────────────────────────────────────────────────────
    def _load_all_caches(self) -> dict[str, pd.DataFrame]:
        """
        모든 ticker의 캐시 CSV를 Date 인덱스 DataFrame으로 로드.
        반환: {ticker: df}
        """
        cache_map: dict[str, pd.DataFrame] = {}
        watchlist  = settings.watchlist

        for item in watchlist:
            ticker = item.get('ticker', '')
            if not ticker:
                continue
            path = os.path.join(CACHE_DIR, f"{_safe_ticker_name(ticker)}_computed.csv")
            if not os.path.exists(path):
                continue
            try:
                df = pd.read_csv(path, parse_dates=['Date'])
                df.set_index('Date', inplace=True)
                df.sort_index(inplace=True)
                cache_map[ticker] = df
            except Exception as e:
                self.logger.warning(f"⚠️ 캐시 로드 실패 [{ticker}]: {e}")

        self.logger.info(f"📂 캐시 로드 완료 — {len(cache_map)}종목")
        return cache_map

    # ── 공개 API ──────────────────────────────────────────────────────────────
    def run(self):
        cache_map = self._load_all_caches()
        if not cache_map:
            self.logger.error("❌ 캐시 파일 없음 — PreComputeEngine.run()을 먼저 실행하세요.")
            return

        # 시뮬레이션 기간 내 전체 거래일 집합
        all_dates = sorted(set(
            d for df in cache_map.values()
            for d in df[SIM_START:SIM_END].index
        ))

        self.logger.info(
            f"📈 [PortfolioSimulator] 시뮬레이션 개시 "
            f"({SIM_START} ~ {SIM_END}, {len(all_dates)}거래일)"
        )
        self.logger.info(
            f"   초기자금: KRW ₩{INIT_KRW:,.0f} / USD ${INIT_USD:,.0f}"
        )

        for date in all_dates:
            self._process_day(date, cache_map)

        # ── 결과 저장 ──────────────────────────────────────────────────────────
        log_path = os.path.join(RESULTS_DIR, "daily_log.csv")
        pd.DataFrame(self.daily_log).to_csv(log_path, index=False, encoding='utf-8')

        trades_path = os.path.join(RESULTS_DIR, "closed_trades.csv")
        pd.DataFrame(self.closed_trades).to_csv(trades_path, index=False, encoding='utf-8')

        self._save_sim_ledger(cache_map)

        self.logger.info(
            f"💾 시뮬레이션 완료 — "
            f"거래: {len(self.closed_trades)}건 | "
            f"일별로그: {log_path}"
        )

    # ── 하루 처리 ─────────────────────────────────────────────────────────────
    def _process_day(self, date, cache_map: dict):
        fx_rate = self._get_fx_rate(date)

        # ── 1. 청산 신호 우선 처리 ────────────────────────────────────────────
        exit_signals = []
        for ticker, h in list(self.holdings.items()):
            row = self._get_row(cache_map, ticker, date)
            if row is None:
                continue

            curr_price = float(row.get('Close', 0) or 0)
            if curr_price <= 0:
                continue

            reason, ratio = self._check_exit_signals(ticker, h, row, curr_price, cache_map, date)
            if reason and ratio > 0:
                exit_signals.append((ticker, curr_price, reason, ratio))

        # 청산 집행
        for ticker, price, reason, ratio in exit_signals:
            self._execute_exit(ticker, price, ratio, reason, date)

        # ── 2. 진입 신호 체크 ─────────────────────────────────────────────────
        # 조건: 총 보유 종목 수 < MAX_HOLDINGS
        if len(self.holdings) < self.max_holdings:
            entry_candidates = []
            for ticker in cache_map:
                if ticker in self.holdings:
                    continue
                # 시장 필터: SPY/KS200 MA200 이하 시 신규 진입 차단
                currency = _get_currency(ticker)
                if not self._is_market_ok(currency, date):
                    continue
                row = self._get_row(cache_map, ticker, date)
                if row is None:
                    continue

                score = float(row.get('Score', 99) or 99)
                if score >= self.ENTRY_SCORE_MAX:
                    continue

                # 전날 점수 (조건 E용)
                prev_row   = self._get_prev_row(cache_map, ticker, date)
                prev_score = float(prev_row.get('Score', 99)) if prev_row is not None else None

                is_entry, conditions = self._check_entry_trigger(score, row, prev_row, prev_score)
                if is_entry:
                    entry_candidates.append((score, ticker, row, conditions))

            # 점수 낮은 순 (리스크 최저) 우선
            entry_candidates.sort(key=lambda x: x[0])

            for _, ticker, row, conditions in entry_candidates:
                if len(self.holdings) >= self.max_holdings:
                    break
                curr      = float(row.get('Close', 0) or 0)
                currency  = _get_currency(ticker)
                pf_value  = self._portfolio_value(currency, cache_map, date)
                avail     = self.cash_krw if currency == "KRW" else self.cash_usd
                if avail <= 0:
                    continue

                # 투입 비중: min(risk_based_weight, max_weight_pct)
                weight_pct = self._calc_entry_weight(row)
                invest_amt = pf_value * (min(weight_pct, self.max_weight_pct) / 100.0)
                invest_amt = min(invest_amt, avail)

                if invest_amt < curr:  # 최소 1주 매수 가능한지 확인
                    continue

                qty        = invest_amt / curr
                stop_loss  = self._calc_stop_loss(row, curr)
                self._execute_entry(ticker, curr, qty, stop_loss, date, currency, conditions)

        # ── 3. 일별 잔고 기록 ─────────────────────────────────────────────────
        self._record_daily(date, cache_map, fx_rate)

    # ── 청산 신호 판단 ─────────────────────────────────────────────────────────
    def _check_exit_signals(self, ticker, h, row, curr_price, cache_map, date):
        """
        반환: (reason: str | None, ratio: float)
        ratio = 청산 비율 (0.0 ~ 1.0)
        """
        avg_price = float(h.get('avg_price', 0) or 0)
        if avg_price <= 0:
            return None, 0.0

        profit_pct = ((curr_price - avg_price) / avg_price) * 100.0

        # ── 신호 1: entry_stop 손절 ────────────────────────────────────────────
        entry_stop = float(h.get('entry_stop', 0) or 0)
        if entry_stop > 0 and curr_price < entry_stop:
            return "entry_stop", 1.0

        # ── 신호 2: 리스크 레벨 8/9 ──────────────────────────────────────────
        level = int(row.get('Risk_Level', 0) or 0)
        if level >= 9:
            return "risk_lv9", 1.0
        if level >= 8:
            return "risk_lv8", 0.70

        # ── 신호 3: 트레일링 스탑 ─────────────────────────────────────────────
        if profit_pct >= self.TRAIL_PROFIT_FLOOR:
            atr = float(row.get('atr', 0) or 0)
            if atr > 0:
                grade, sell_ratio = self._calc_trailing_grade(
                    ticker, h, row, curr_price, atr, profit_pct, cache_map, date
                )
                if grade >= 2 and sell_ratio > 0:
                    reason = f"trail_grade{grade}"
                    return reason, sell_ratio
                # trailing_high 갱신 (grade 0~1)
                new_high = max(curr_price, float(h.get('trailing_high', 0) or 0))
                h['trailing_high'] = new_high

        # ── 신호 4: 시간 기반 청산 ────────────────────────────────────────────
        entry_date_str = h.get('entry_date', '')
        if entry_date_str:
            try:
                entry_dt  = datetime.strptime(entry_date_str, '%Y-%m-%d')
                current_dt = datetime.strptime(date.strftime('%Y-%m-%d'), '%Y-%m-%d')
                elapsed    = (current_dt - entry_dt).days

                if elapsed > self.TIME_LOSS_DAYS and profit_pct < 0:
                    return "time_loss", 1.0
                if elapsed > self.TIME_OPP_DAYS and profit_pct < self.TIME_OPP_PCT:
                    return "time_opp", 1.0
            except (ValueError, AttributeError):
                pass

        return None, 0.0

    def _calc_trailing_grade(self, ticker, h, row, curr_price, atr, profit_pct,
                              cache_map, date) -> tuple[int, float]:
        """ATR 다축 트레일링 스탑 등급 계산 (PortfolioSimulator 내부 복제 버전)"""
        # ATR 배수 결정
        if profit_pct >= 50.0:
            mult = self.atr_high
        elif profit_pct >= 20.0:
            mult = self.atr_mid
        else:
            mult = self.atr_low

        # trailing_high 갱신
        old_high = float(h.get('trailing_high', 0) or 0)
        new_high = max(curr_price, old_high)
        h['trailing_high'] = new_high

        trail_stop = new_high - atr * mult

        # 축1: 가격 이탈
        axis1 = bool(curr_price < trail_stop)

        # 축2: 점수 레벨 6+(≥61) + 직전 2일 연속 상승
        score  = float(row.get('Score', 0) or 0)
        axis2  = False
        if score >= 61.0:
            hist2 = self._get_score_history(cache_map, ticker, date, n=2)
            if len(hist2) >= 2:
                rising_hist = all(hist2[i] < hist2[i+1] for i in range(len(hist2)-1))
                axis2 = rising_hist and (hist2[-1] < score)

        # 축3: 수급 약화 2/3 이상
        prev_row  = self._get_prev_row(cache_map, ticker, date)
        prev2_row = self._get_prev_row(cache_map, ticker, date, offset=2)
        axis3     = False
        if prev_row is not None and prev2_row is not None:
            mfi0 = float(row.get('MFI', 50) or 50)
            rsi0 = float(row.get('RSI', 50) or 50)
            m0   = float(row.get('macd_h', 0)      or 0)
            m1   = float(prev_row.get('macd_h', 0)  or 0)
            m2   = float(prev2_row.get('macd_h', 0) or 0)
            adx0 = float(row.get('ADX', 0)          or 0)
            adx1 = float(prev_row.get('ADX', 0)     or 0)
            flags = {
                'mfi_rsi': mfi0 < rsi0,
                'macd':    m2 > m1 > m0,
                'adx':     adx0 < adx1,
            }
            axis3 = sum(flags.values()) >= 2

        # 등급 및 분할 비율
        if   axis1 and axis2 and axis3: grade = 3
        elif axis1 and axis2:           grade = 2
        elif axis1 or  axis2:           grade = 1
        else:                           grade = 0

        sell_ratio = 0.0
        if grade == 3:
            sell_ratio = 1.0
        elif grade == 2:
            sell_ratio = 0.30 if profit_pct >= 50.0 else 0.50

        return grade, sell_ratio

    # ── 진입 트리거 판단 ──────────────────────────────────────────────────────
    def _check_entry_trigger(self, score, row, prev_row, prev_score) -> tuple[bool, list]:
        """check_entry_trigger 로직 — 캐시 데이터 기반 복제"""
        if score >= self.ENTRY_SCORE_MAX:
            return False, []

        if row is None or prev_row is None:
            return False, []

        optional = 0
        met = [f"A: 저위험 진입 구간 (점수 {score:.1f})"]

        # B: avg_sigma 전일 대비 상승
        s0 = float(row.get('avg_sigma', 0)      or 0)
        s1 = float(prev_row.get('avg_sigma', 0) or 0)
        if s0 > s1:
            optional += 1
            met.append(f"B: avg_sigma 상승 ({s1:.2f}→{s0:.2f})")

        # C: macd_h 음수 구간 증가 전환
        m0 = float(row.get('macd_h', 0)      or 0)
        m1 = float(prev_row.get('macd_h', 0) or 0)
        if m0 < 0 and m0 > m1:
            optional += 1
            met.append(f"C: MACD히스토 음수 반등 ({m1:.3f}→{m0:.3f})")

        # D: MFI 40 이하 반등
        mfi0 = float(row.get('MFI', 50)      or 50)
        mfi1 = float(prev_row.get('MFI', 50) or 50)
        if mfi1 <= 40.0 and mfi0 > mfi1:
            optional += 1
            met.append(f"D: MFI 과매도 반등 ({mfi1:.1f}→{mfi0:.1f})")

        # E: 전일 대비 점수 개선
        if prev_score is not None and score < prev_score:
            optional += 1
            met.append(f"E: 점수 개선 ({prev_score:.1f}→{score:.1f})")

        return optional >= self.entry_min, met

    # ── 진입 비중 계산 ────────────────────────────────────────────────────────
    def _calc_entry_weight(self, row) -> float:
        """
        apply_risk_management 로직 단순화 버전.
        stop_loss ← disp120 기반 tech floor (92% 룰)
        weight    ← ACCOUNT_RISK / risk_dist (캡: MAX_WEIGHT_PCT)
        """
        close   = float(row.get('Close', 0) or 0)
        disp120 = float(row.get('disp120', 100) or 100)
        if close <= 0:
            return 1.0

        # 기술적 손절 기준 (이격도 기반 지지선의 92%)
        tech_floor  = (close / (disp120 / 100.0)) * 0.92
        risk_dist   = (close - tech_floor) / (close + 1e-10)
        risk_dist   = max(risk_dist, 0.05)   # 최소 5% 리스크 거리 보장

        weight_raw  = (ACCOUNT_RISK / risk_dist) * 100.0
        return round(min(weight_raw, self.max_weight_pct), 2)

    def _calc_stop_loss(self, row, curr_price: float) -> float:
        """진입 시점의 손절가 계산 (disp120 기반 tech floor)"""
        disp120 = float(row.get('disp120', 100) or 100)
        if disp120 <= 0:
            return curr_price * 0.90
        return round((curr_price / (disp120 / 100.0)) * 0.92, 4)

    # ── 거래 집행 ─────────────────────────────────────────────────────────────
    def _execute_entry(self, ticker, price, qty, stop_loss, date, currency, conditions=None):
        invest = price * qty
        if currency == "KRW":
            self.cash_krw -= invest
        else:
            self.cash_usd -= invest

        self.holdings[ticker] = {
            'ticker':           ticker,
            'qty':              qty,
            'avg_price':        price,
            'entry_price':      price,
            'entry_date':       date.strftime('%Y-%m-%d'),
            'entry_stop':       stop_loss,
            'trailing_high':    price,
            'currency':         currency,
            'entry_conditions': ','.join(conditions) if conditions else '',
        }
        self.logger.debug(
            f"  ➡️  BUY  [{ticker}] {qty:.4f}주 @ {price:.2f} "
            f"(stop={stop_loss:.2f}, invest={invest:.0f}{currency})"
        )
        self._log_signal(date, ticker, "BUY", price, None, 0.0, 0, 0.0, "entry_trigger")

    def _execute_exit(self, ticker, price, ratio, reason, date):
        if ticker not in self.holdings:
            return
        h         = self.holdings[ticker]
        qty_sell  = h['qty'] * ratio
        revenue   = qty_sell * price
        currency  = h.get('currency', 'USD')
        avg_price = float(h.get('avg_price', 0) or 0)
        profit    = (price - avg_price) * qty_sell
        profit_p  = ((price - avg_price) / (avg_price + 1e-10)) * 100.0
        hold_days = 0
        try:
            entry_dt = datetime.strptime(h['entry_date'], '%Y-%m-%d')
            cur_dt   = datetime.strptime(date.strftime('%Y-%m-%d'), '%Y-%m-%d')
            hold_days = (cur_dt - entry_dt).days
        except Exception:
            pass

        if currency == "KRW":
            self.cash_krw += revenue
        else:
            self.cash_usd += revenue

        # 완료 거래 기록
        self.closed_trades.append({
            'Date':             date.strftime('%Y-%m-%d'),
            'Ticker':           ticker,
            'Exit_Reason':      reason,
            'Entry_Date':       h.get('entry_date', ''),
            'Entry_Conditions': h.get('entry_conditions', ''),
            'Entry_Price':      avg_price,
            'Exit_Price':       price,
            'Qty':              qty_sell,
            'Profit':           round(profit, 4),
            'Profit_Pct':       round(profit_p, 2),
            'Hold_Days':        hold_days,
            'Currency':         currency,
        })

        self.logger.debug(
            f"  ⬅️  SELL [{ticker}] {ratio*100:.0f}% @ {price:.2f} "
            f"수익: {profit_p:+.1f}% ({reason})"
        )
        self._log_signal(date, ticker, f"SELL_{reason}", avg_price, price,
                         profit_p, hold_days, ratio, reason)

        # 잔량 처리
        remaining = h['qty'] - qty_sell
        if remaining < 1e-6:
            del self.holdings[ticker]
        else:
            h['qty'] = remaining

    # ── 유틸 ──────────────────────────────────────────────────────────────────
    def _get_row(self, cache_map, ticker, date):
        """캐시에서 특정 날짜의 행 반환 (없으면 None)"""
        df = cache_map.get(ticker)
        if df is None or date not in df.index:
            return None
        return df.loc[date]

    def _get_prev_row(self, cache_map, ticker, date, offset: int = 1):
        """캐시에서 date 기준 offset일 이전 행 반환"""
        df = cache_map.get(ticker)
        if df is None:
            return None
        subset = df[:date]
        if len(subset) <= offset:
            return None
        return subset.iloc[-(offset + 1)]

    def _get_score_history(self, cache_map, ticker, date, n: int = 2) -> list:
        """date 이전 n일치 점수 이력 반환 (오래된 순)"""
        df = cache_map.get(ticker)
        if df is None:
            return []
        past = df[df.index < date]
        if past.empty:
            return []
        recent = past.tail(n)
        return [float(s) for s in recent['Score'].tolist()]

    def _portfolio_value(self, currency, cache_map, date) -> float:
        """특정 통화의 현재 총 포트폴리오 가치"""
        cash = self.cash_krw if currency == "KRW" else self.cash_usd
        stock_val = 0.0
        for ticker, h in self.holdings.items():
            if h.get('currency') != currency:
                continue
            row = self._get_row(cache_map, ticker, date)
            if row is not None:
                stock_val += float(row.get('Close', 0) or 0) * h['qty']
        return cash + stock_val

    def _record_daily(self, date, cache_map, fx_rate):
        """일별 포트폴리오 잔고 기록"""
        def _stock_val(currency_filter):
            total = 0.0
            for t, h in self.holdings.items():
                if (h.get('currency') == 'KRW') != (currency_filter == 'KRW'):
                    continue
                row = self._get_row(cache_map, t, date)
                if row is not None:
                    total += float(row.get('Close', 0) or 0) * h['qty']
            return total

        krw_stock = _stock_val('KRW')
        usd_stock = _stock_val('USD')
        total_krw = self.cash_krw + krw_stock
        total_usd = self.cash_usd + usd_stock
        fx        = fx_rate if fx_rate and fx_rate > 0 else 1400.0
        total_combined_usd = total_usd + total_krw / fx
        self.daily_log.append({
            'Date':               date.strftime('%Y-%m-%d'),
            'Signal':             'DAILY_SNAPSHOT',
            'Signal_Reason':      f'Holdings={len(self.holdings)}',
            'Cash_KRW':           round(self.cash_krw, 0),
            'Stock_KRW':          round(krw_stock, 0),
            'Portfolio_KRW':      round(total_krw, 0),
            'Cash_USD':           round(self.cash_usd, 2),
            'Stock_USD':          round(usd_stock, 2),
            'Portfolio_USD':      round(total_usd, 2),
            'Portfolio_Total_USD': round(total_combined_usd, 2),
            'FX_Rate':            round(fx_rate, 1),
            'Holdings':           len(self.holdings),
        })

    def _save_sim_ledger(self, cache_map: dict, path: str = None):
        """
        시뮬레이션 기간(SIM_START~SIM_END) 전 종목×전 날짜의 53컬럼 레저를 CSV로 저장.
        sigma_guard_ledger 포맷과 컬럼 구조 동일 (SIM_LEDGER_COLS 참조).
        """
        path = path or os.path.join(RESULTS_DIR, "sim_ledger.csv")
        rows = []
        for ticker, df in cache_map.items():
            sim_df = df[SIM_START:SIM_END]
            for date, row in sim_df.iterrows():
                rows.append({
                    'Audit_Date':      date.strftime('%Y-%m-%d'),
                    'Ticker':          ticker,
                    'Name':            '',
                    'Risk_Score':      row.get('Score',         np.nan),
                    'Risk_Level':      row.get('Risk_Level',    np.nan),
                    'Price_T':         row.get('Close',         np.nan),
                    'Sigma_T_Avg':     row.get('avg_sigma',     np.nan),
                    'Sigma_T_1y':      row.get('sig_1y',        np.nan),
                    'Sigma_T_2y':      row.get('sig_2y',        np.nan),
                    'Sigma_T_3y':      row.get('sig_3y',        np.nan),
                    'Sigma_T_4y':      row.get('sig_4y',        np.nan),
                    'Sigma_T_5y':      row.get('sig_5y',        np.nan),
                    'RSI_T':           row.get('RSI',           np.nan),
                    'MFI_T':           row.get('MFI',           np.nan),
                    'BBW_T':           row.get('bbw',           np.nan),
                    'R2_T':            row.get('R2',            np.nan),
                    'ADX_T':           row.get('ADX',           np.nan),
                    'Disp_T_120':      row.get('disp120',       np.nan),
                    'Ticker_B':        '',
                    'Price_B':         np.nan,
                    'Sigma_B_Avg':     np.nan,
                    'RSI_B':           np.nan,
                    'MFI_B':           np.nan,
                    'ADX_B':           np.nan,
                    'BBW_B':           np.nan,
                    'Stop_Price':      np.nan,
                    'Risk_Gap_Pct':    np.nan,
                    'Invest_EI':       np.nan,
                    'Weight_Pct':      np.nan,
                    'Expected_MDD':    np.nan,
                    'Livermore_Status': np.nan,
                    'Base_Raw_Score':  np.nan,
                    'Risk_Multiplier': np.nan,
                    'Trend_Scenario':  row.get('scenario',      row.get('ma_slope', '')),
                    'Score_Pos':       row.get('p1',            np.nan),
                    'Score_Pos_EMA':   row.get('p1_ema',        np.nan),
                    'Score_Ene':       row.get('p2',            np.nan),
                    'Score_Ene_EMA':   row.get('p2_ema',        np.nan),
                    'Score_Trap':      row.get('p4',            np.nan),
                    'Score_Trap_EMA':  row.get('p4_ema',        np.nan),
                    'VIX_T':           np.nan,
                    'US10Y_T':         np.nan,
                    'DXY_T':           np.nan,
                    'MACD_Hist_T':     row.get('macd_h',        np.nan),
                    'MACD_Hist_B':     np.nan,
                    'ADX_Gap':         np.nan,
                    'Disp_Limit':      row.get('disp120_limit', np.nan),
                    'BBW_Thr':         row.get('bbw_thr',       np.nan),
                    'LIV_Discount':    row.get('liv_discount',  np.nan),
                    'SOP_Action':      row.get('sop_action',    ''),
                    'Ret_20d':         np.nan,
                    'Min_Ret_20d':     np.nan,
                    'Max_Ret_20d':     np.nan,
                })

        if rows:
            ledger_df = pd.DataFrame(rows, columns=SIM_LEDGER_COLS)
            ledger_df.to_csv(path, index=False, encoding='utf-8')
            self.logger.info(f"💾 sim_ledger 저장 완료: {path} ({len(rows)}행)")
        else:
            self.logger.warning("⚠️ sim_ledger 저장 건너뜀 — 데이터 없음")

    def _log_signal(self, date, ticker, signal, entry_p, exit_p, profit_p,
                    hold_days, ratio, reason):
        self.daily_log.append({
            'Date':          date.strftime('%Y-%m-%d'),
            'Ticker':        ticker,
            'Signal':        signal,
            'Entry_Price':   round(entry_p, 4),
            'Exit_Price':    round(exit_p, 4) if exit_p else None,
            'Profit_Pct':    round(profit_p, 2),
            'Hold_Days':     hold_days,
            'Sell_Ratio':    ratio,
            'Signal_Reason': reason,
            'Portfolio_KRW': None,
            'Portfolio_USD': None,
        })


# ══════════════════════════════════════════════════════════════════════════════
# [Step 3] PerformanceReporter
# ══════════════════════════════════════════════════════════════════════════════
class PerformanceReporter:
    """
    시뮬레이션 결과 분석 리포터.
    벤치마크(SPY / KOSPI 200) 대비 성과, 매매 통계, 신호별 효과,
    ATR 파라미터 민감도 분석을 출력합니다.
    """

    def __init__(self):
        self.logger = setup_custom_logger("PerformanceReporter")
        self._setup_file_log()

    def _setup_file_log(self):
        fh = logging.FileHandler(
            os.path.join(LOG_DIR, "sigma_guard_sim.log"), mode='a', encoding='utf-8'
        )
        fh.setFormatter(logging.Formatter('[%(asctime)s | %(levelname)s] %(name)s | %(message)s'))
        self.logger.addHandler(fh)

    # ── 공개 API ──────────────────────────────────────────────────────────────
    def run(self, daily_path: str = None, trades_path: str = None, cache_map: dict = None):
        """
        :param daily_path:  일별 로그 CSV 경로 (None이면 기본 전체 경로 사용)
        :param trades_path: 완료 거래 CSV 경로 (None이면 기본 전체 경로 사용)
        :param cache_map:   민감도 분석용 캐시맵 (None이면 디스크에서 자동 로드)
        """
        daily_path  = daily_path  or os.path.join(RESULTS_DIR, "daily_log.csv")
        trades_path = trades_path or os.path.join(RESULTS_DIR, "closed_trades.csv")

        if not os.path.exists(daily_path):
            self.logger.error("❌ daily_log.csv 없음 — PortfolioSimulator.run()을 먼저 실행하세요.")
            return

        daily  = pd.read_csv(daily_path, parse_dates=['Date'])
        trades = pd.read_csv(trades_path, parse_dates=['Date']) if os.path.exists(trades_path) else pd.DataFrame()

        # 포트폴리오 일별 잔고 스냅샷 행 추출 (신호 행과 분리)
        daily_pf = daily[daily['Portfolio_KRW'].notna()].copy()
        daily_pf.sort_values('Date', inplace=True)
        daily_pf.set_index('Date', inplace=True)

        # cache_map 미제공 시 디스크에서 자동 로드 (전체 파이프라인 지원)
        if cache_map is None:
            self.logger.info("📂 cache_map 자동 로드 중 (민감도 분석용)...")
            _sim_tmp = PortfolioSimulator.__new__(PortfolioSimulator)
            _sim_tmp.logger = self.logger
            cache_map = _sim_tmp._load_all_caches()

        self._print_portfolio_perf(daily_pf)
        self._print_trade_stats(trades)
        self._print_signal_analysis(trades)
        self._print_sensitivity(cache_map=cache_map)

    # ── 1. 포트폴리오 성과 ────────────────────────────────────────────────────
    def _print_portfolio_perf(self, daily_pf):
        self.logger.info("━" * 70)
        self.logger.info("📊 [1/4] 포트폴리오 전체 성과")
        self.logger.info("━" * 70)

        # 벤치마크 로드
        spy   = self._fetch_bench("SPY",    SIM_START, SIM_END)
        ks200 = self._fetch_bench("^KS200", SIM_START, SIM_END)

        for label, col in [
            ("KRW 포트폴리오",  "Portfolio_KRW"),
            ("USD 포트폴리오",  "Portfolio_USD"),
            ("통합 포트폴리오", "Portfolio_Total_USD"),
        ]:
            if col not in daily_pf.columns or daily_pf[col].dropna().empty:
                continue

            pf = daily_pf[col].dropna()
            ret   = (pf.iloc[-1] - pf.iloc[0]) / pf.iloc[0] * 100
            mdd   = self._calc_mdd(pf)
            sharpe = self._calc_sharpe(pf)
            self.logger.info(
                f"  {label}: 수익률 {ret:+.2f}% | MDD {mdd:.2f}% | 샤프 {sharpe:.2f}"
            )

        # vs 벤치마크
        for label, bseries in [("vs SPY", spy), ("vs KOSPI200", ks200)]:
            if bseries is None or bseries.empty:
                continue
            bench_ret = (bseries.iloc[-1] - bseries.iloc[0]) / bseries.iloc[0] * 100
            bench_mdd = self._calc_mdd(bseries)
            self.logger.info(
                f"  {label}: B&H 수익률 {bench_ret:+.2f}% | MDD {bench_mdd:.2f}%"
            )

    # ── 2. 매매 통계 ─────────────────────────────────────────────────────────
    def _print_trade_stats(self, trades):
        self.logger.info("━" * 70)
        self.logger.info("📊 [2/4] 매매 통계")
        self.logger.info("━" * 70)

        if trades.empty:
            self.logger.info("  거래 데이터 없음")
            return

        sells = trades[trades['Exit_Price'].notna() & (trades['Exit_Price'] > 0)]
        if sells.empty:
            self.logger.info("  완료 거래 없음")
            return

        total  = len(sells)
        wins   = sells[sells['Profit_Pct'] > 0]
        losses = sells[sells['Profit_Pct'] < 0]
        win_r  = len(wins) / total * 100 if total > 0 else 0.0
        avg_win  = wins['Profit_Pct'].mean()   if not wins.empty else 0.0
        avg_loss = losses['Profit_Pct'].mean() if not losses.empty else 0.0
        pl_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else float('inf')
        avg_hold = sells['Hold_Days'].mean() if 'Hold_Days' in sells.columns else 0.0

        self.logger.info(f"  총 거래 수 : {total}건")
        self.logger.info(f"  승률       : {win_r:.1f}%")
        self.logger.info(f"  손익비     : {pl_ratio:.2f}")
        self.logger.info(f"  평균 보유  : {avg_hold:.1f}일")

        # Top 5 수익
        self.logger.info("  [최대 수익 Top 5]")
        top5 = sells.nlargest(5, 'Profit_Pct')[['Ticker','Profit_Pct','Hold_Days']]
        for _, r in top5.iterrows():
            self.logger.info(f"    {r['Ticker']:>15} {r['Profit_Pct']:+.2f}% ({r['Hold_Days']:.0f}일)")

        # Top 5 손실
        self.logger.info("  [최대 손실 Top 5]")
        bot5 = sells.nsmallest(5, 'Profit_Pct')[['Ticker','Profit_Pct','Hold_Days']]
        for _, r in bot5.iterrows():
            self.logger.info(f"    {r['Ticker']:>15} {r['Profit_Pct']:+.2f}% ({r['Hold_Days']:.0f}일)")

    # ── 3. 신호별 성과 분석 ────────────────────────────────────────────────────
    def _print_signal_analysis(self, trades):
        self.logger.info("━" * 70)
        self.logger.info("📊 [3/4] 청산 신호별 효과 분석")
        self.logger.info("━" * 70)

        if trades.empty or 'Exit_Reason' not in trades.columns:
            return

        sells = trades[trades['Exit_Price'].notna() & (trades['Exit_Price'] > 0)]
        if sells.empty:
            return

        for reason, grp in sells.groupby('Exit_Reason'):
            cnt    = len(grp)
            avg_p  = grp['Profit_Pct'].mean()
            win_r  = (grp['Profit_Pct'] > 0).mean() * 100
            self.logger.info(
                f"  {reason:<20} {cnt:>4}건 | 평균수익 {avg_p:+.2f}% | 승률 {win_r:.0f}%"
            )

        # 진입 트리거 조건별 평균 수익률
        self.logger.info("  [진입 트리거 조건별 평균 수익률]")
        if 'Entry_Conditions' in sells.columns:
            for cond_key, cond_label in [
                ('B:', 'B(시그마 상승)'),
                ('C:', 'C(MACD 반등)'),
                ('D:', 'D(MFI 반등)'),
                ('E:', 'E(점수 개선)'),
            ]:
                mask = sells['Entry_Conditions'].str.contains(cond_key, na=False)
                grp  = sells[mask]
                if not grp.empty:
                    self.logger.info(
                        f"    {cond_label:<16} {len(grp):>4}건 | "
                        f"평균수익 {grp['Profit_Pct'].mean():+.2f}% | "
                        f"승률 {(grp['Profit_Pct'] > 0).mean()*100:.0f}%"
                    )
        else:
            self.logger.info("    Entry_Conditions 컬럼 없음 — 분석 건너뜀")

    # ── 4. ATR 파라미터 민감도 분석 ─────────────────────────────────────────
    def _print_sensitivity(self, cache_map=None):
        self.logger.info("━" * 70)
        self.logger.info("📊 [4/4] ATR 배수 & 진입 조건 파라미터 민감도 분석")
        self.logger.info("━" * 70)

        if cache_map is None:
            self.logger.info("  ※ cache_map 미제공 — 민감도 분석 건너뜀")
            return

        configs = [
            ("기본  (ATR×2/2.5/3, entry≥2)",   dict(atr_low=2.0, atr_mid=2.5, atr_high=3.0, entry_min=2)),
            ("타이트(ATR×1.5/2/2.5, entry≥2)", dict(atr_low=1.5, atr_mid=2.0, atr_high=2.5, entry_min=2)),
            ("루즈  (ATR×2.5/3/4, entry≥2)",    dict(atr_low=2.5, atr_mid=3.0, atr_high=4.0, entry_min=2)),
            ("엄격진입(ATR×2/2.5/3, entry≥3)",  dict(atr_low=2.0, atr_mid=2.5, atr_high=3.0, entry_min=3)),
        ]

        # 시장 필터 1회 사전 로드 (4개 설정 공유 → 중복 다운로드 방지)
        _mf_tmp = PortfolioSimulator.__new__(PortfolioSimulator)
        _mf_tmp.logger = self.logger
        shared_market_filter = _mf_tmp._load_market_filter()

        all_dates = sorted(set(
            d for df in cache_map.values()
            for d in df[SIM_START:SIM_END].index
        ))

        self.logger.info(
            f"  {'설정':<36} {'거래':>5} {'승률':>6} {'평균수익':>9} {'손익비':>7}"
        )
        self.logger.info(f"  {'─'*36} {'─'*5} {'─'*6} {'─'*9} {'─'*7}")

        for label, params in configs:
            sim = PortfolioSimulator(**params, market_filter=shared_market_filter)
            for date in all_dates:
                sim._process_day(date, cache_map)

            ct = sim.closed_trades
            if not ct:
                self.logger.info(f"  {label:<36}   0건  —  거래 없음")
                continue

            ct_df  = pd.DataFrame(ct)
            sells  = ct_df[ct_df['Exit_Price'].notna() & (ct_df['Exit_Price'] > 0)]
            total  = len(sells)
            win_r  = (sells['Profit_Pct'] > 0).mean() * 100 if total > 0 else 0.0
            avg_p  = sells['Profit_Pct'].mean()           if total > 0 else 0.0
            wins   = sells[sells['Profit_Pct'] > 0]
            losses = sells[sells['Profit_Pct'] < 0]
            avg_win  = wins['Profit_Pct'].mean()   if not wins.empty   else 0.0
            avg_loss = losses['Profit_Pct'].mean() if not losses.empty else 0.0
            pl_ratio = abs(avg_win / avg_loss)     if avg_loss != 0    else float('inf')

            self.logger.info(
                f"  {label:<36} {total:>5}건 {win_r:>5.0f}% {avg_p:>+9.2f}% {pl_ratio:>7.2f}"
            )

    # ── 수학 유틸 ─────────────────────────────────────────────────────────────
    @staticmethod
    def _calc_mdd(series: pd.Series) -> float:
        peak = series.cummax()
        dd   = (series - peak) / (peak + 1e-10) * 100
        return round(dd.min(), 2)

    @staticmethod
    def _calc_sharpe(series: pd.Series, risk_free: float = 0.03) -> float:
        daily_ret = series.pct_change().dropna()
        if daily_ret.std() == 0:
            return 0.0
        ann_ret = daily_ret.mean() * 252
        ann_std = daily_ret.std() * (252 ** 0.5)
        return round((ann_ret - risk_free) / (ann_std + 1e-10), 2)

    @staticmethod
    def _fetch_bench(ticker: str, start: str, end: str) -> pd.Series | None:
        try:
            df = yf.download(ticker, start=start, end=end,
                             interval="1d", progress=False, auto_adjust=True)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            return df['Close'].ffill().dropna() if not df.empty else None
        except Exception:
            return None


# ══════════════════════════════════════════════════════════════════════════════
# [메인 실행]
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Sigma Guard Performance Simulator")
    parser.add_argument("--step",      type=int, default=0,
                        help="실행 단계 (1=PreCompute, 2=Simulate, 3=Report, 0=전체)")
    parser.add_argument("--recompute", action="store_true",
                        help="캐시 강제 재계산")
    parser.add_argument("--ticker",    type=str, default=None,
                        help="단독 종목 테스트 (예: --ticker B)")
    args = parser.parse_args()

    # ── 단독 종목 테스트 모드 ──────────────────────────────────────────────────
    if args.ticker:
        ticker_test = args.ticker
        safe_name   = _safe_ticker_name(ticker_test)
        currency_test = _get_currency(ticker_test)
        symbol        = '$' if currency_test == 'USD' else '₩'
        init_pf       = INIT_USD if currency_test == 'USD' else INIT_KRW

        print(f"\n🧪 단독 종목 테스트: {ticker_test}", flush=True)
        print(f"   기간: {SIM_START} ~ {SIM_END}")
        print("=" * 70, flush=True)

        # ── [Step 1] 지표 생성 + 캐시 저장 ───────────────────────────
        print(f"\n  📡 [Step 1] {ticker_test} 지표 생성 및 캐시 저장...", flush=True)
        ind  = Indicators()
        reng = RiskEngine()
        ind_df, bench_df = ind.generate(ticker_test, period="10y", bench=None)

        if ind_df is None or ind_df.empty:
            print(f"  ❌ [{ticker_test}] 데이터 없음")
            sys.exit(1)

        sim_mask  = (ind_df.index >= SIM_START) & (ind_df.index <= SIM_END)
        sim_dates = ind_df.index[sim_mask]
        print(f"  시뮬 기간 거래일: {len(sim_dates)}일")

        df_res_full = []
        prev_ema    = None
        for date in sim_dates:
            ind_slice   = ind_df[:date]
            bench_slice = bench_df[:date] if (bench_df is not None and not bench_df.empty) else None
            if len(ind_slice) < 30:
                continue
            score, _, details = reng.evaluate(ind_slice, bench_slice, prev_ema)
            level = reng.get_level(score)
            if details:
                prev_ema = {
                    'p1_ema': details.get('p1_ema', details.get('p1', 0)),
                    'p2_ema': details.get('p2_ema', details.get('p2', 0)),
                    'p4_ema': details.get('p4_ema', details.get('p4', 0)),
                }
            row_val = ind_df.loc[date]
            r = {'Date': date.strftime('%Y-%m-%d')}
            for col in PreComputeEngine.IND_COLS:
                r[col] = row_val.get(col, np.nan) if hasattr(row_val, 'get') else np.nan
            r.update({
                'Score':        round(float(score), 2),
                'Risk_Level':   int(level),
                'p1':           round(float(details.get('p1',      0)),    2) if details else 0.0,
                'p2':           round(float(details.get('p2',      0)),    2) if details else 0.0,
                'p4':           round(float(details.get('p4',      0)),    2) if details else 0.0,
                'p1_ema':       round(float(details.get('p1_ema',  0)),    2) if details else 0.0,
                'p2_ema':       round(float(details.get('p2_ema',  0)),    2) if details else 0.0,
                'p4_ema':       round(float(details.get('p4_ema',  0)),    2) if details else 0.0,
                'scenario':     details.get('scenario',     '')                if details else '',
                'liv_discount': round(float(details.get('liv_discount', 0)), 4) if details else 0.0,
                'sop_action':   details.get('action',       '')                if details else '',
            })
            df_res_full.append(r)

        del ind_df, bench_df
        gc.collect()

        if not df_res_full:
            print(f"  ❌ [{ticker_test}] 유효 결과 없음")
            sys.exit(1)

        df_cache   = pd.DataFrame(df_res_full)
        cache_path = os.path.join(CACHE_DIR, f"{safe_name}_computed.csv")
        df_cache.to_csv(cache_path, index=False, encoding='utf-8')

        # 최근 20일 미리보기
        sample = df_cache.tail(20)
        print(f"\n  최근 20일 점수 샘플:")
        print(f"  {'Date':<12} {'Close':>10} {'Score':>7} {'Lv':>3} {'p1':>6} {'p2':>6} {'p4':>6}")
        print(f"  {'-'*58}")
        for _, r in sample.iterrows():
            print(
                f"  {r['Date']:<12} {r['Close']:>10.2f} "
                f"{r['Score']:>7.2f} {int(r['Risk_Level']):>3} "
                f"{r['p1']:>6.2f} {r['p2']:>6.2f} {r['p4']:>6.2f}"
            )

        lv_dist = df_cache['Risk_Level'].value_counts().sort_index()
        lv_str  = " / ".join(f"Lv{int(k)}({int(v)}일)" for k, v in lv_dist.items())
        print(f"\n  전체 요약 ({len(df_cache)}일)")
        print(f"  {'─'*60}")
        print(f"  {'점수 평균':<10}: {df_cache['Score'].mean():.2f}")
        print(f"  {'점수 범위':<10}: {df_cache['Score'].min():.2f} ~ {df_cache['Score'].max():.2f}")
        print(f"  {'LV 분포':<10}: {lv_str}")
        print(f"  {'캐시 저장':<10}: {cache_path} ({len(df_cache)}행)")

        # ── [Step 2] 단독 종목 포트폴리오 시뮬레이션 ─────────────────
        print(f"\n  📈 [Step 2] 포트폴리오 시뮬레이션 ({ticker_test} 단독)...", flush=True)

        sim = PortfolioSimulator()

        # 캐시 직접 주입 (단독 종목)
        cache_df        = df_cache.copy()
        cache_df.index  = pd.to_datetime(cache_df['Date'])
        cache_df.sort_index(inplace=True)
        cache_map_single = {ticker_test: cache_df}

        all_dates = sorted(cache_df[SIM_START:SIM_END].index)
        print(f"  시뮬레이션 거래일: {len(all_dates)}일")

        for date in all_dates:
            sim._process_day(date, cache_map_single)

        # 단독 종목 전용 결과 파일 경로
        log_path_single     = os.path.join(RESULTS_DIR, f"daily_log_{safe_name}.csv")
        trades_path_single  = os.path.join(RESULTS_DIR, f"closed_trades_{safe_name}.csv")
        ledger_path_single  = os.path.join(RESULTS_DIR, f"sim_ledger_{safe_name}.csv")
        pd.DataFrame(sim.daily_log).to_csv(log_path_single, index=False, encoding='utf-8')
        pd.DataFrame(sim.closed_trades).to_csv(trades_path_single, index=False, encoding='utf-8')
        sim._save_sim_ledger(cache_map_single, path=ledger_path_single)

        # 최종 잔고: 일별 스냅샷의 마지막 행 (미청산 포지션 포함)
        snap_rows = [r for r in sim.daily_log if r.get('Portfolio_KRW') is not None]
        if snap_rows and currency_test == 'USD':
            final_pf = float(snap_rows[-1].get('Portfolio_USD', init_pf))
        elif snap_rows:
            final_pf = float(snap_rows[-1].get('Portfolio_KRW', init_pf))
        else:
            final_pf = init_pf

        ret_pct = (final_pf - init_pf) / init_pf * 100
        print(f"  완료 거래: {len(sim.closed_trades)}건")
        print(f"  최종 잔고: {symbol}{final_pf:,.2f}  (수익률 {ret_pct:+.2f}%)")
        print(f"  미청산 포지션: {len(sim.holdings)}건")
        print(f"  거래 로그: {log_path_single}")

        # ── [Step 3] 성과 리포트 ──────────────────────────────────────
        print(f"\n  📊 [Step 3] 성과 리포트...", flush=True)
        print("=" * 70, flush=True)

        reporter = PerformanceReporter()
        reporter.run(
            daily_path  = log_path_single,
            trades_path = trades_path_single,
            cache_map   = cache_map_single,
        )

        print(f"\n✅ [{ticker_test}] Step 1~3 전체 완료", flush=True)

    else:
        # ── 전체 파이프라인 실행 ──────────────────────────────────────
        run_all   = (args.step == 0)
        run_step1 = run_all or (args.step == 1)
        run_step2 = run_all or (args.step == 2)
        run_step3 = run_all or (args.step == 3)

        if run_step1:
            pre = PreComputeEngine()
            pre.run(force=args.recompute)

        if run_step2:
            sim = PortfolioSimulator()
            sim.run()

        if run_step3:
            reporter = PerformanceReporter()
            reporter.run()
