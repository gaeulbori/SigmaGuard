"""
[File Purpose]
- 글로벌 시장별 메타데이터 및 기본 설정 유틸리티.
- 티커 접미사를 분석하여 국가별 벤치마크 및 지수 명칭을 반환합니다.
"""

def get_regional_benchmark(ticker):
    """
    [v10.4.6] 티커 기반 국가별 기본 벤치마크 자동 매칭
    - 한국(.KS, .KQ), 일본(.T), 중국(.SS, .SZ), 미국(기본)
    """
    t_up = ticker.upper()
    
    # 1. 한국 시장
    if any(t_up.endswith(s) for s in ['.KS', '.KQ']):
        return "^KS200", "KOSPI 200"
    
    # 2. 일본 시장
    elif t_up.endswith(".T"):
        return "^N225", "Nikkei 225"
    
    # 3. 중국 시장 (상해, 심천)
    elif any(t_up.endswith(s) for s in ['.SS', '.SZ']):
        return "000300.SS", "CSI 300"
    
    # 4. 기본값 (미국 S&P 500)
    else:
        return "SPY", "S&P 500"

def get_currency_code(ticker):
    """티커에 따른 통화 코드 반환 (향후 확장용)"""
    t_up = ticker.upper()
    if any(t_up.endswith(s) for s in ['.KS', '.KQ']): return "KRW"
    if t_up.endswith(".T"): return "JPY"
    if any(t_up.endswith(s) for s in ['.SS', '.SZ']): return "CNY"
    return "USD"