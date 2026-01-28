"""
[File Purpose]
- 주가 데이터를 바탕으로 기술적 지표(RSI, MFI, BB, ADX, R2 등)를 산출하는 수학 엔진.
- 모든 함수는 Pandas DataFrame을 입력받아 계산된 시리즈 또는 값을 반환함.

[Key Features]
- Vectorized Calculation: 루프를 배제하고 Pandas/NumPy 연산을 사용하여 OCI 환경에서 빠른 처리 속도 보장.
- Decoupled Logic: 데이터 수집 로직과 완전히 분리되어 단위 테스트에 최적화됨.
"""
import pandas as pd
import numpy as np

def calc_rsi(df, period=14):
    """Relative Strength Index (RSI) 산출 - 분모 0 방어 적용"""
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    
    # 1e-10을 더해 분모가 0이 되는 상황 방지
    rs = gain / (loss + 1e-10)
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calc_mfi(df, period=14):
    """Money Flow Index (MFI) 산출 - 분모 0 방어 적용"""
    typical_price = (df['High'] + df['Low'] + df['Close']) / 3
    money_flow = typical_price * df['Volume']
    
    positive_flow = pd.Series(0.0, index=df.index)
    negative_flow = pd.Series(0.0, index=df.index)
    
    change = typical_price.diff()
    positive_flow[change > 0] = money_flow[change > 0]
    negative_flow[change < 0] = money_flow[change < 0]
    
    # 나눗셈 시 안전장치 추가
    mfr = positive_flow.rolling(window=period).sum() / (negative_flow.rolling(window=period).sum() + 1e-10)
    return 100 - (100 / (1 + mfr))

def calc_bollinger_bands(df, period=20, std_dev=2):
    """Bollinger Bands 및 BBW 산출 + 동적 임계값(Threshold) 계산"""
    sma = df['Close'].rolling(window=period).mean()
    std = df['Close'].rolling(window=period).std()
    
    upper_band = sma + (std * std_dev)
    lower_band = sma - (std * std_dev)
    
    # sma가 0일 경우 NaN으로 대체하여 나눗셈 에러 방지
    bbw = (upper_band - lower_band) / sma.replace(0, np.nan)
    
    # [David v8.9.7 로직 반영] 동적 임계치 계산
    BBW_WINDOW = 100
    BBW_STD_FACTOR = 1.5
    BBW_MIN_FLOOR = 0.3
    
    rolling_mean = bbw.rolling(window=BBW_WINDOW).mean()
    rolling_std = bbw.rolling(window=BBW_WINDOW).std()
    
    # 임계값 계산 및 최솟값 0.3 강제 적용
    bbw_thr = (rolling_mean + BBW_STD_FACTOR * (rolling_std + 1e-10)).replace(np.nan, BBW_MIN_FLOOR)
    bbw_thr = bbw_thr.clip(lower=BBW_MIN_FLOOR)
    
    return upper_band, lower_band, bbw, bbw_thr

def calc_disparity(df, period=120):
    """이동평균 이격도(Disparity) 산출 - 분모 0 방어 적용"""
    sma = df['Close'].rolling(window=period).mean()
    disparity = (df['Close'] / (sma + 1e-10)) * 100
    return disparity

def calc_adx(df, period=14):
    """
    Average Directional Index (ADX) 산출 - 추세 강도 측정
    - [Patch] 부동 소수점 오차 방지를 위해 비교 및 나눗셈 로직에 1e-10(Epsilon) 버퍼 적용
    """
    high, low, close = df['High'], df['Low'], df['Close']
    
    # 1. True Range (TR) 계산 및 분모 0 방어
    tr = pd.concat([high - low, 
                    (high - close.shift(1)).abs(), 
                    (low - close.shift(1)).abs()], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    
    up_move = high.diff()
    down_move = low.diff()
    
    # 2. [CPA 정밀 보강] 방향성 변화량(DM) 판별 로직
    # 단순히 up_move > down_move가 아니라, 미세 오차(1e-10)보다 더 큰 차이가 날 때만 인정
    pos_dm = np.where((up_move > down_move + 1e-10) & (up_move > 0), up_move, 0)
    neg_dm = np.where((down_move > up_move + 1e-10) & (down_move > 0), down_move, 0)
    
    # 3. DI 산출 및 나눗셈 안전장치
    # atr이 0인 경우를 대비해 1e-10을 더해 시스템 다운 방지
    pos_di = 100 * (pd.Series(pos_dm, index=df.index).rolling(window=period).mean() / (atr + 1e-10))
    neg_di = 100 * (pd.Series(neg_dm, index=df.index).rolling(window=period).mean() / (atr + 1e-10))
    
    # 4. DX 및 최종 ADX 산출
    # 분모(pos_di + neg_di)가 0이 되는 구간(완전 횡보)을 위해 1e-10 추가
    dx = 100 * (pos_di - neg_di).abs() / (pos_di + neg_di + 1e-10)
    adx = dx.rolling(window=period).mean()
    
    return adx

def calc_r_squared(df, period=20):
    """선형 회귀 결정계수(R2) 산출 - 추세의 선형성 측정"""
    if len(df) < period:
        return pd.Series(0, index=df.index)

    x = np.arange(period)
    
    def get_r2(y_slice):
        if len(y_slice) < period: return 0
        slope, intercept = np.polyfit(x, y_slice, 1)
        y_pred = slope * x + intercept
        
        residuals = y_slice - y_pred
        ss_res = np.sum(residuals**2)
        ss_tot = np.sum((y_slice - np.mean(y_slice))**2)
        
        # 분모가 0일 경우 방어
        if ss_tot == 0: return 0
        return 1 - (ss_res / ss_tot)

    r2_series = df['Close'].rolling(window=period).apply(get_r2, raw=True)
    return r2_series