"""
[File Purpose]
- David's Elite Watchlist Builder v1.9
- S&P 500(Top 200), NASDAQ 100, KOSPI 200 종목 집중 수집.
- 총 500개 내외의 정예 종목으로 리소스를 최적화합니다.
"""

import pandas as pd
import FinanceDataReader as fdr
import yaml
import requests
import io
import traceback

def fetch_with_header(url):
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        return pd.read_html(io.StringIO(response.text))
    except:
        return []

def get_clean_df(tables, min_rows=30):
    if not tables: return pd.DataFrame()
    df = max(tables, key=len).copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(-1)
    df.columns = [str(c).strip() for c in df.columns]
    return df.dropna(how='all').reset_index(drop=True)

def find_col_idx(df, keywords):
    for i, col in enumerate(df.columns):
        if any(key.lower() in str(col).lower() for key in keywords):
            return i
    return 0

def fetch_sp500_top200():
    print("🇺🇸 S&P 500 시총 상위 200개 선별 중...")
    # 1. 위키피디아에서 최신 구성 종목 리스트 확보
    tables = fetch_with_header("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")
    wiki_df = get_clean_df(tables)
    if wiki_df.empty: return []
    
    t_idx = find_col_idx(wiki_df, ['Symbol', 'Ticker'])
    s_idx = find_col_idx(wiki_df, ['Sector', 'Industry'])
    wiki_tickers = wiki_df.iloc[:, t_idx].tolist()

    # 2. FDR을 통해 미국 시장 시총 데이터 확보 (S&P 500 필터링)
    # 'S&P500' 지수 종목을 직접 가져와 시총순 정렬
    df_sp = fdr.StockListing('SP500')
    m_idx = find_col_idx(df_sp, ['MarketCap', 'MarCap'])
    
    # 시총 상위 200개 추출
    df_top200 = df_sp.sort_values(df_sp.columns[m_idx], ascending=False).head(200)
    
    return [{
        "ticker": str(row['Symbol']).replace('.', '-'), 
        "name": str(row['Name']), 
        "sector": str(row['Sector']), 
        "bench": "SPY", 
        "bench_name": "S&P 500"
    } for _, row in df_top200.iterrows()]

def fetch_nasdaq100():
    print("🇺🇸 NASDAQ 100 수집 중...")
    tables = fetch_with_header("https://en.wikipedia.org/wiki/Nasdaq-100")
    df = get_clean_df(tables)
    if df.empty: return []
    ti, ni = find_col_idx(df, ['Symbol', 'Ticker']), find_col_idx(df, ['Company', 'Security'])
    return [{"ticker": str(row.iloc[ti]), "name": str(row.iloc[ni]), "sector": "Technology", "bench": "QQQ", "bench_name": "NASDAQ 100"} for _, row in df.iterrows()]

def fetch_kospi200():
    print("🇰🇷 KOSPI 200 수집 중...")
    df = fdr.StockListing('KOSPI')
    ti, ni, si = find_col_idx(df, ['Code', 'Symbol']), find_col_idx(df, ['Name']), find_col_idx(df, ['Sector', 'Industry'])
    mi = find_col_idx(df, ['MarCap', 'MarketCap'])
    df_k = df.sort_values(df.columns[mi], ascending=False).head(200)
    return [{"ticker": f"{row.iloc[ti]}.KS", "name": str(row.iloc[ni]), "sector": str(row.iloc[si]) if pd.notna(row.iloc[si]) else "KOSPI200", "bench": "^KS200", "bench_name": "KOSPI 200"} for _, row in df_k.iterrows()]

def main():
    try:
        data = {
            "USA (S&P 500 Top 200)": fetch_sp500_top200(),
            "USA (NASDAQ 100)": fetch_nasdaq100(),
            "KOREA (KOSPI 200)": fetch_kospi200()
        }

        with open('SG_config.yaml', 'w', encoding='utf-8') as f:
            f.write("# =========================================================\n")
            f.write("# David's Elite Global Watchlist (Top 500 Strategy)\n")
            f.write(f"# Updated: {pd.Timestamp.now()}\n")
            f.write("# =========================================================\n\n")
            f.write("watchlist:\n")
            
            total_count = 0
            for region, stocks in data.items():
                if stocks:
                    f.write(f"\n  # --- {region} ({len(stocks)} stocks) ---\n")
                    stocks_yaml = yaml.dump(stocks, allow_unicode=True, sort_keys=False, default_flow_style=False)
                    indented_yaml = "  " + stocks_yaml.replace("\n", "\n  ").strip()
                    f.write(indented_yaml + "\n")
                    total_count += len(stocks)
            
        print(f"\n✨ 완료! 한/미 정예 {total_count}개 종목이 'SG_config.yaml'에 저장되었습니다.")
    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    main()