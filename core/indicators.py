"""
[File Purpose]
- 주가 데이터를 바탕으로 기술적 지표(RSI, MFI, BB, ADX, R2 등)를 산출하는 수학 엔진.
- [개선사항] 기존 독립 함수들을 Indicators 클래스로 통합하고, 실시간 시세 로드 및 리스크 엔진용 지표(Sigma, MACD) 보강.

[Key Features]
- Automation: yfinance를 통해 전 세계 시장 데이터를 자동으로 수집 및 전처리.
- v8.9.7 Alignment: David님의 핵심 로직인 Sigma(변동성 배수) 및 동적 BBW 임계치 산출 로직 완비.
- Reliability: 1e-10(Epsilon) 버퍼를 활용한 Zero-Division 방어로 시스템 안정성 확보.

[Implementation Details]
- Vectorized Calculation: Pandas와 NumPy의 벡터 연산을 활용해 수천 개의 행도 밀리초 단위로 처리.
- Class-based Architecture: SigmaGuard 메인 컨트롤러와의 인터페이스 일원화 (generate 메서드).
"""

import pandas as pd
import numpy as np
import yfinance as yf
from utils.logger import setup_custom_logger

logger = setup_custom_logger("Indicators")

class Indicators:
    def __init__(self):
        # 지표별 기본 기간 설정 (v8.9.7 기준)
        self.P_RSI = 14
        self.P_MFI = 14
        self.P_BB = 20
        self.P_ADX = 14
        self.P_R2 = 20
        self.P_DISP = 120
        self.P_SIGMA = 252 # 1년 거래일 기준

    def fetch_data(self, ticker, period="2y"):
        """실제 시장 데이터(OHLCV) 로드"""
        try:
            logger.info(f"📥 [{ticker}] 시세 데이터 로드 중... (기간: {period})")
            # yfinance를 통해 데이터 다운로드
            df = yf.download(ticker, period=period, interval="1d", progress=False, auto_adjust=True)
            
            if df.empty:
                logger.error(f"❌ [{ticker}] 데이터를 찾을 수 없습니다.")
                return None
            
            # 멀티인덱스 방지 및 컬럼 정리 (yfinance 버전에 따른 대응)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
                
            return df
        except Exception as e:
            logger.error(f"❌ 데이터 로드 오류: {e}")
            return None

    def generate(self, ticker):
        """
        [Main Pipeline] 원시 데이터를 받아 모든 기술 지표가 포함된 통합 DataFrame 반환
        """
        df = self.fetch_data(ticker)
        if df is None: return None

        # 1. David님 기존 로직: 기초 지표 산출
        df['RSI'] = self.calc_rsi(df, self.P_RSI)
        df['MFI'] = self.calc_mfi(df, self.P_MFI)
        df['ADX'] = self.calc_adx(df, self.P_ADX)
        df['R2'] = self.calc_r_squared(df, self.P_R2)
        df['disp120'] = self.calc_disparity(df, self.P_DISP)
        
        # 2. David님 기존 로직: 볼린저 밴드 및 동적 임계값
        upper, lower, bbw, bbw_thr = self.calc_bollinger_bands(df, self.P_BB)
        df['bbw'] = bbw
        df['bbw_thr'] = bbw_thr
        
        # 3. [추가] 리스크 엔진 필수 지표: Sigma 및 MACD 트렌드
        df['avg_sigma'] = self.calc_sigma(df, self.P_SIGMA)
        df['m_trend'] = self.calc_macd_trend(df)
        
        # 4. 추세 신뢰도용 기울기(Slope)
        df['slope'] = self.calc_slope(df, self.P_R2)

        # 결측치 제거 (이동평균 등으로 인해 발생하는 앞부분의 NaN 제거)
        return df.dropna()

    # --- 수학 연산 엔진 (기존 David님 코드 클래스 메서드로 전환) ---

    def calc_rsi(self, df, period):
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / (loss + 1e-10)
        return 100 - (100 / (1 + rs))

    def calc_mfi(self, df, period):
        typical_price = (df['High'] + df['Low'] + df['Close']) / 3
        money_flow = typical_price * df['Volume']
        change = typical_price.diff()
        pos_flow = pd.Series(0.0, index=df.index)
        neg_flow = pd.Series(0.0, index=df.index)
        pos_flow[change > 0] = money_flow[change > 0]
        neg_flow[change < 0] = money_flow[change < 0]
        mfr = pos_flow.rolling(window=period).sum() / (neg_flow.rolling(window=period).sum() + 1e-10)
        return 100 - (100 / (1 + mfr))

    def calc_bollinger_bands(self, df, period, std_dev=2):
        sma = df['Close'].rolling(window=period).mean()
        std = df['Close'].rolling(window=period).std()
        upper_band = sma + (std * std_dev)
        lower_band = sma - (std * std_dev)
        bbw = (upper_band - lower_band) / sma.replace(0, np.nan)
        
        # v8.9.7 동적 임계치 로직
        rolling_mean = bbw.rolling(window=100).mean()
        rolling_std = bbw.rolling(window=100).std()
        bbw_thr = (rolling_mean + 1.5 * (rolling_std + 1e-10)).fillna(0.3).clip(lower=0.3)
        return upper_band, lower_band, bbw, bbw_thr

    def calc_disparity(self, df, period):
        sma = df['Close'].rolling(window=period).mean()
        return (df['Close'] / (sma + 1e-10)) * 100

    def calc_adx(self, df, period):
        high, low, close = df['High'], df['Low'], df['Close']
        tr = pd.concat([high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        up_move, down_move = high.diff(), low.diff()
        pos_dm = np.where((up_move > down_move + 1e-10) & (up_move > 0), up_move, 0)
        neg_dm = np.where((down_move > up_move + 1e-10) & (down_move > 0), down_move, 0)
        pos_di = 100 * (pd.Series(pos_dm, index=df.index).rolling(window=period).mean() / (atr + 1e-10))
        neg_di = 100 * (pd.Series(neg_dm, index=df.index).rolling(window=period).mean() / (atr + 1e-10))
        dx = 100 * (pos_di - neg_di).abs() / (pos_di + neg_di + 1e-10)
        return dx.rolling(window=period).mean()

    def calc_r_squared(self, df, period):
        if len(df) < period: return pd.Series(0, index=df.index)
        x = np.arange(period)
        def get_r2(y_slice):
            if len(y_slice) < period: return 0
            slope, intercept = np.polyfit(x, y_slice, 1)
            y_pred = slope * x + intercept
            residuals = y_slice - y_pred
            ss_res, ss_tot = np.sum(residuals**2), np.sum((y_slice - np.mean(y_slice))**2)
            return 1 - (ss_res / (ss_tot + 1e-10))
        return df['Close'].rolling(window=period).apply(get_r2, raw=True)

    def calc_sigma(self, df, window):
        """[추가] David v8.9.7 Sigma 산출"""
        sma = df['Close'].rolling(window=window).mean()
        std = df['Close'].rolling(window=window).std()
        return (df['Close'] - sma) / (std + 1e-10)
    
    def calc_macd_trend(self, df):
        """[수정] MACD 히스토그램 기반 가속/감속 판정 - Series 반환"""
        exp1 = df['Close'].ewm(span=12, adjust=False).mean()
        exp2 = df['Close'].ewm(span=26, adjust=False).mean()
        macd = exp1 - exp2
        signal = macd.ewm(span=9, adjust=False).mean()
        hist = macd - signal
        
        # np.where 결과를 Pandas Series로 감싸서 인덱스 유지
        res = np.where(hist > hist.shift(1), "상승가속", "감속")
        return pd.Series(res, index=df.index)

    def calc_slope(self, df, period):
        """[추가] 선형 기울기 산출"""
        x = np.arange(period)
        def get_slope(y):
            if len(y) < period: return 0
            return np.polyfit(x, y, 1)[0]
        return df['Close'].rolling(window=period).apply(get_slope, raw=True)