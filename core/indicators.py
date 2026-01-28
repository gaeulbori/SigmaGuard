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
    """Relative Strength Index (RSI) 산출"""
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calc_mfi(df, period=14):
    """Money Flow Index (MFI) 산출"""
    typical_price = (df['High'] + df['Low'] + df['Close']) / 3
    money_flow = typical_price * df['Volume']
    
    positive_flow = pd.Series(0.0, index=df.index)
    negative_flow = pd.Series(0.0, index=df.index)
    
    change = typical_price.diff()
    positive_flow[change > 0] = money_flow[change > 0]
    negative_flow[change < 0] = money_flow[change < 0]
    
    mfr = positive_flow.rolling(window=period).sum() / negative_flow.rolling(window=period).sum()
    return 100 - (100 / (1 + mfr))

def calc_bollinger_bands(df, period=20, std_dev=2):
    """Bollinger Bands (BB) 산출"""
    sma = df['Close'].rolling(window=period).mean()
    std = df['Close'].rolling(window=period).std()
    
    upper_band = sma + (std * std_dev)
    lower_band = sma - (std * std_dev)
    
    # [보완] sma가 0인 경우를 대비한 분모 0 방어 로직
    bbw = (upper_band - lower_band) / sma.replace(0, np.nan)
    
    return upper_band, lower_band, bbw

def calc_disparity(df, period=120):
    """이동평균 이격도(Disparity) 산출"""
    sma = df['Close'].rolling(window=period).mean()
    disparity = (df['Close'] / sma) * 100
    return disparity

def calc_adx(df, period=14):
    """Average Directional Index (ADX) 산출 - 추세 강도 측정"""
    # 기본적인 TR, DM 계산 로직 (간소화 버전)
    high = df['High']
    low = df['Low']
    close = df['Close']
    
    tr = pd.concat([high - low, 
                    (high - close.shift(1)).abs(), 
                    (low - close.shift(1)).abs()], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    
    up_move = high.diff()
    down_move = low.diff()
    
    pos_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
    neg_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)
    
    pos_di = 100 * (pd.Series(pos_dm, index=df.index).rolling(window=period).mean() / atr)
    neg_di = 100 * (pd.Series(neg_dm, index=df.index).rolling(window=period).mean() / atr)
    
    dx = 100 * (pos_di - neg_di).abs() / (pos_di + neg_di)
    adx = dx.rolling(window=period).mean()
    
    return adx

def calc_r_squared(df, period=20):
    """
    선형 회귀 결정계수(R2) 산출 - 추세의 선형성(직선도) 및 신뢰도 측정
    - 1.0에 가까울수록 추세가 매우 일정하고 정교함을 의미함.
    """
    if len(df) < period:
        return pd.Series(0, index=df.index)

    # 1. 독립변수 X (시간축: 0, 1, 2, ...) 생성
    x = np.arange(period)
    
    def get_r2(y_slice):
        if len(y_slice) < period: return 0
        # Numpy를 이용한 선형 회귀 연산
        slope, intercept = np.polyfit(x, y_slice, 1)
        y_pred = slope * x + intercept
        
        # R2 공식: 1 - (잔차 제곱합 / 총 제곱합)
        residuals = y_slice - y_pred
        ss_res = np.sum(residuals**2)
        ss_tot = np.sum((y_slice - np.mean(y_slice))**2)
        
        if ss_tot == 0: return 0 # 분모가 0인 경우 방어
        return 1 - (ss_res / ss_tot)

    # 2. Rolling Window를 적용하여 R2 시리즈 반환
    r2_series = df['Close'].rolling(window=period).apply(get_r2, raw=True)
    return r2_series