"""
[File Purpose]
- 주가 데이터를 바탕으로 기술적 지표 및 5개년 통계 지표(Multi-Sigma, Dynamic Disparity)를 산출하는 수학 엔진.
- [v8.9.7 보완] 다중 시그마(1y~5y), 상대적 기울기(%), 동적 이격 임계치 로직을 통합하여 분석 정밀도 강화.

[Key Features]
- Multi-Dimensional Audit: 단기(1년)부터 장기(5년)까지의 시그마를 동시 산출하여 통계적 위치 정합성 확보.
- Normalized Momentum: 가격 절대값이 다른 종목 간 비교를 위해 기울기를 첫 가격 대비 %로 규격화.
- Dynamic Thresholds: 종목별 과거 5년 이격 데이터를 분석하여 개별적인 과열 임계치(Floor 110%) 설정.

[Implementation Details]
- Data Fetching: 5개년 통계 확보를 위해 기본 데이터 수집 기간을 6년(6y)으로 확장.
- Vectorized Math: Pandas/NumPy 기반 연산으로 시계열 데이터 전 구간의 지표를 고속 산출.
"""

import threading
import pandas as pd
import numpy as np
import yfinance as yf
from utils.logger import setup_custom_logger


def _yf_download_safe(ticker, timeout=20, **kwargs):
    """yf.download()를 daemon 스레드로 실행하여 timeout(초) 초과 시 TimeoutError 발생."""
    result = [None]
    exc = [None]

    def _worker():
        try:
            result[0] = yf.download(ticker, **kwargs)
        except Exception as e:
            exc[0] = e

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout=timeout)

    if t.is_alive():
        raise TimeoutError(f"yf.download({ticker}) timed out after {timeout}s")
    if exc[0]:
        raise exc[0]
    return result[0]

logger = setup_custom_logger("Indicators")

class Indicators:
    def __init__(self):
        # David v8.9.7 표준 파라미터 설정
        self.P_RSI = 14
        self.P_MFI = 14
        self.P_BB = 20
        self.P_ADX = 14
        self.P_R2 = 20
        self.P_DISP = 120
        self.P_SIGMA_BASE = 252  # 1년 거래일
        self._bench_cache = {}  # 벤치마크 캐시: {(ticker, period): processed_df} — SPY 등 반복 다운로드 방지

    def fetch_data(self, ticker, period="6y"):
        """[v8.9.7] 5년 통계 확보를 위한 6년치 데이터 로드"""
        try:
            #logger.info(f"📥 [{ticker}] 시세 데이터 로드 중... (기간: {period})")
            # auto_adjust=True로 수정하여 yfinance 경고 방지 및 실질 가격 반영
            df = _yf_download_safe(ticker, timeout=30, period=period, interval="1d", progress=False, auto_adjust=True)
            
            if df.empty:
                logger.error(f"❌ [{ticker}] 데이터를 찾을 수 없습니다.")
                return None
            
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
                
            return df
        except Exception as e:
            logger.error(f"❌ 데이터 로드 오류: {e}")
            return None

    """
    [File Purpose]
    - v9.0.9: 타겟과 벤치마크의 통합 산출 엔진.
    - 단일 호출로 (target_df, bench_df) 쌍을 반환하여 데이터 동기화 보장.
    """

    def generate(self, ticker, period="6y", bench=None):
        """타겟 종목과 벤치마크 지수의 지표를 동시에 산출"""

        # 1. 타겟 데이터 산출
        target_df = self._process_single_ticker(ticker, period)
        if target_df is None or target_df.empty:
            return None, None

        # 2. 벤치마크 데이터 산출 — 캐시 우선 사용 (SPY 등 반복 다운로드 방지)
        bench_df = pd.DataFrame()
        if bench:
            cache_key = (bench, period)
            if cache_key not in self._bench_cache:
                logger.info(f"   📥 [벤치마크 캐시 미스] {bench} 다운로드 (이후 캐시 재사용)")
                self._bench_cache[cache_key] = self._process_single_ticker(bench, period)
            raw_bench = self._bench_cache[cache_key]
            # [v9.0.9 핵심] 타겟 데이터의 날짜 인덱스에 맞춰 벤치마크 데이터 싱크 조절
            if raw_bench is not None and not raw_bench.empty:
                bench_df = raw_bench.reindex(target_df.index).ffill()

        return target_df, bench_df

    def _process_single_ticker(self, ticker, period):
        """(내부 함수) 개별 티커의 수집 및 지표 가공 로직"""
        
        df = self.fetch_data(ticker, period=period)
        if df is None or len(df) < self.P_DISP:
            return None

        # 1. 기초 기술 지표 (Vectorized)
        df['RSI'] = self.calc_rsi(df, self.P_RSI)
        df['MFI'] = self.calc_mfi(df, self.P_MFI)
        df['ADX'] = self.calc_adx(df, self.P_ADX)
        df['R2'] = self.calc_r_squared(df, self.P_R2)
        df['disp120'] = self.calc_disparity(df, self.P_DISP)
        
        # 2. 볼린저 밴드 및 동적 BBW 임계값
        _, _, bbw, bbw_thr = self.calc_bollinger_bands(df, self.P_BB)
        df['bbw'] = bbw
        df['bbw_thr'] = bbw_thr
        
        # 3. [1단계 핵심] 다중 시그마(1y~5y) 분석 및 평균 시그마 산출
        sigma_data = self.calc_multi_sigma(df)
        for col, series in sigma_data.items():
            df[col] = series
            
        # 4. [1단계 핵심] 동적 이격 임계치 및 상대적 기울기
        df['disp120_limit'], df['disp120_avg'] = self.calc_dynamic_disparity_limit(df)
        df['slope'] = self.calc_relative_slope(df, self.P_R2)
        
        # 5. 리스크 엔진 연동용 트렌드 지표 및 ATR
        df['macd_h'], df['m_trend'] = self.calc_macd_trend(df)
        df['atr'] = self.calc_atr(df, self.P_ADX)  # ATR-14 (트레일링 스탑 배수용)
        df['ma_slope'] = np.where(
            df['Close'].rolling(self.P_DISP).mean() > df['Close'].rolling(self.P_DISP).mean().shift(5), 
            "Rising", "Falling"
        )

        return df.dropna()

    def calc_sigma(self, df, window):
        """[Legacy/Utility] 특정 윈도우 기반 시그마 산출 (기존 테스트 호환용)"""
        sma = df['Close'].rolling(window=window).mean()
        std = df['Close'].rolling(window=window).std()
        return (df['Close'] - sma) / (std + 1e-10)

    # --- [v8.9.7 전용 고도화 메서드] ---

    """
    [File Purpose]
    - v9.0.7: 시그마 산출 공식의 Z-Score(표준화) 복구.
    - David v8.9.7 규격: (현재가 - 평균) / 표준편차
    - 신생 종목(BAM 등) 대응을 위한 min_periods=120 적용.
    """

    def calc_multi_sigma(self, df):
        """
        [v8.9.7 Logic Restoration]
        - 절대적 변동폭이 아닌, 평균으로부터의 표준편차 거리를 산출합니다.
        """
        # David님의 감사 기준인 Close(또는 price) 확보
        # (앞선 단계에서 rename을 했다면 'price', 안했다면 'Close'를 사용하세요)
        target_col = 'Close' if 'Close' in df.columns else 'price'
        
        # 최소 분석 관측치 (약 6개월)
        min_obs = 120 

        # 1. 연도별 Z-Score(Sigma) 산출 루프
        # 공식: (Price - MA) / Std
        for y in range(1, 6):
            window = 252 * y
            ma = df[target_col].rolling(window=window, min_periods=min_obs).mean()
            std = df[target_col].rolling(window=window, min_periods=min_obs).std()
            
            # v8.9.7 정통 수식 적용
            df[f'sig_{y}y'] = (df[target_col] - ma) / (std + 1e-10)
        
        # 2. 5개년 평균 시그마 산출
        # 개별 연도 데이터가 부족한 신생 종목은 가용한 연도끼리만 평균을 냅니다.
        sigma_cols = ['sig_1y', 'sig_2y', 'sig_3y', 'sig_4y', 'sig_5y']
        df['avg_sigma'] = df[sigma_cols].mean(axis=1, skipna=True)

        logger.info(f"   📊 [Sigma Audit] {target_col} 기반 5개년 다중 시그마 산출 완료")
        
        return df
    
    def calc_relative_slope(self, df, period):
        """
        주가 대비 상대적 % 기울기 산출
        $$RelativeSlope = \frac{Slope}{Price_{0}} \times 100$$
        """
        x = np.arange(period)
        def get_rel_slope(y):
            if len(y) < period: return 0
            slope, _ = np.polyfit(x, y, 1)
            return (slope / (y[0] + 1e-10)) * 100
        return df['Close'].rolling(window=period).apply(get_rel_slope, raw=True)

    def calc_dynamic_disparity_limit(self, df, window=1260):
        """5개년(1260일) 통계 기반 종목별 동적 이격 임계치 산출 (Min Floor 110%)"""
        disp_series = (df['Close'] / (df['Close'].rolling(self.P_DISP).mean() + 1e-10))
        
        avg_disp = disp_series.rolling(window=window, min_periods=self.P_DISP).mean()
        std_disp = disp_series.rolling(window=window, min_periods=self.P_DISP).std()
        
        # David 로직: 평균 + 2표준편차 (최소 110% 보장)
        limit = (avg_disp + (2.0 * std_disp)) * 100
        return limit.clip(lower=110.0), avg_disp * 100

    # --- [기초 수학 연산 엔진] ---

    def calc_rsi(self, df, period):
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / (loss + 1e-10)
        return 100 - (100 / (1 + rs))

    def calc_mfi(self, df, period):
        tp = (df['High'] + df['Low'] + df['Close']) / 3
        mf = tp * df['Volume']
        change = tp.diff()
        pos_flow = pd.Series(0.0, index=df.index)
        neg_flow = pd.Series(0.0, index=df.index)
        pos_flow[change > 0] = mf[change > 0]
        neg_flow[change < 0] = mf[change < 0]
        mfr = pos_flow.rolling(window=period).sum() / (neg_flow.rolling(window=period).sum() + 1e-10)
        return 100 - (100 / (1 + mfr))

    def calc_bollinger_bands(self, df, period, std_dev=2):
        sma = df['Close'].rolling(window=period).mean()
        std = df['Close'].rolling(window=period).std()
        upper = sma + (std * std_dev)
        lower = sma - (std * std_dev)
        bbw = (upper - lower) / sma.replace(0, np.nan)
        
        bbw_thr = (bbw.rolling(100).mean() + 1.5 * bbw.rolling(100).std()).fillna(0.3).clip(lower=0.3)
        return upper, lower, bbw, bbw_thr

    def calc_disparity(self, df, period):
        sma = df['Close'].rolling(window=period).mean()
        return (df['Close'] / (sma + 1e-10)) * 100

    def calc_atr(self, df, period=14):
        """[ATR] Average True Range 산출 — 트레일링 스탑 ATR 배수 계산에 활용
        TR = max(High-Low, |High-PrevClose|, |Low-PrevClose|)
        ATR = TR의 period일 이동평균
        """
        h, l, c = df['High'], df['Low'], df['Close']
        tr = pd.concat([h-l, (h-c.shift(1)).abs(), (l-c.shift(1)).abs()], axis=1).max(axis=1)
        return tr.rolling(window=period).mean()

    def calc_adx(self, df, period):
        h, l, c = df['High'], df['Low'], df['Close']
        tr = pd.concat([h-l, (h-c.shift(1)).abs(), (l-c.shift(1)).abs()], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        up, down = h.diff(), l.diff()
        pos_dm = np.where((up > down + 1e-10) & (up > 0), up, 0)
        neg_dm = np.where((down > up + 1e-10) & (down > 0), down, 0)
        pos_di = 100 * (pd.Series(pos_dm, index=df.index).rolling(period).mean() / (atr + 1e-10))
        neg_di = 100 * (pd.Series(neg_dm, index=df.index).rolling(period).mean() / (atr + 1e-10))
        dx = 100 * (pos_di - neg_di).abs() / (pos_di + neg_di + 1e-10)
        return dx.rolling(window=period).mean()

    def calc_r_squared(self, df, period):
        if len(df) < period: return pd.Series(0, index=df.index)
        x = np.arange(period)
        def get_r2(y_slice):
            if len(y_slice) < period: return 0
            slope, intercept = np.polyfit(x, y_slice, 1)
            y_pred = slope * x + intercept
            ss_res = np.sum((y_slice - y_pred)**2)
            ss_tot = np.sum((y_slice - np.mean(y_slice))**2)
            return 1 - (ss_res / (ss_tot + 1e-10))
        return df['Close'].rolling(window=period).apply(get_r2, raw=True)

    def calc_macd_trend(self, df):
        exp1 = df['Close'].ewm(span=12, adjust=False).mean()
        exp2 = df['Close'].ewm(span=26, adjust=False).mean()
        macd = exp1 - exp2
        signal = macd.ewm(span=9, adjust=False).mean()
        hist = macd - signal
        res = np.where(hist > hist.shift(1), "상승가속", "감속")
        return hist, pd.Series(res, index=df.index)

    def get_exchange_rates(self):
        """
        [v10.4.2] 다중 통화 실시간 환율 수급
        - USD/KRW, JPY/KRW, CNY/KRW 정보를 딕셔너리로 반환합니다.
        """
        # 통화별 야후 파이낸스 티커 매핑
        tickers = {
            "USD": "USDKRW=X",
            "JPY": "JPYKRW=X",
            "CNY": "CNYKRW=X"
        }
        
        rates = {"KRW": 1.0} # 기본 통화
        
        try:
            # 한 번의 호출로 모든 환율 데이터 수집
            data = _yf_download_safe(list(tickers.values()), timeout=20, period="5d", interval="1d", progress=False, auto_adjust=True)
            
            if not data.empty:
                for label, ticker in tickers.items():
                    try:
                        # 통화별 최신 종가 추출
                        current_rate = data['Close'][ticker].iloc[-1]
                        rates[label] = float(current_rate)
                    except:
                        # 개별 통화 실패 시 보수적 기본값 적용
                        default_rates = {"USD": 1350.0, "JPY": 9.0, "CNY": 185.0}
                        rates[label] = default_rates[label]
            
            #logger.info(f"🌐 환율 동기화 완료: USD:{rates['USD']:.1f}, JPY:{rates['JPY']:.1f}, CNY:{rates['CNY']:.1f}")
            return rates
            
        except Exception as e:
            logger.error(f"❌ 환율 수급 치명적 오류: {e}")
            return {"KRW": 1.0, "USD": 1350.0, "JPY": 9.0, "CNY": 185.0}