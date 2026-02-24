"""
[Program Description]
- Sigma Guard Tactical Console v10.3.0
- David님의 실전 매매(매수/매도) 기록을 DB에 반영하고 관리하는 통합 콘솔입니다.
- 주요 기능:
    1. buy: 신규/분할 매수 기록 및 평단가 갱신
    2. sell: 분할 매도 기록 및 실현 손익(수수료 차감) 계산
    3. list: 전체 매매 이력(trades) 및 현재 보유 잔고(holdings) 조회
"""

import argparse
import sys
from core.db_handler import DBHandler
from utils.logger import setup_custom_logger
from core.sigma_analyzer import SigmaAnalyzer
from config.settings import settings

# 로그 설정
logger = setup_custom_logger("Console")

def main():
    parser = argparse.ArgumentParser(description="Sigma Guard Tactical Console v10.3.0")
    subparsers = parser.add_subparsers(dest="command", help="실행할 명령을 선택하세요")

    # --- 1. buy 명령어 설정 ---
    # 예: python sg_console.py buy 005930.KS 10 72000 --stop 68000
    buy_parser = subparsers.add_parser("buy", help="매수 기록 추가")
    buy_parser.add_argument("ticker", type=str, help="종목 티커 (예: 005930.KS, NVDA)")
    buy_parser.add_argument("qty", type=float, help="매수 수량")
    buy_parser.add_argument("price", type=float, help="매수 가격")
    buy_parser.add_argument("--stop", type=float, required=True, help="최초 손절가 (Entry Stop)")
    buy_parser.add_argument("--date", type=str, default=None, help="매수 날짜 (YYYY-MM-DD, 기본값: 오늘)")

    # --- 2. sell 명령어 설정 ---
    # 예: python sg_console.py sell 005930.KS 5 78000
    sell_parser = subparsers.add_parser("sell", help="매도 기록 추가")
    sell_parser.add_argument("ticker", type=str, help="종목 티커")
    sell_parser.add_argument("qty", type=float, help="매도 수량")
    sell_parser.add_argument("price", type=float, help="매도 가격")
    sell_parser.add_argument("--date", type=str, default=None, help="매도 날짜 (YYYY-MM-DD, 기본값: 오늘)")

    # --- 3. list 명령어 설정 ---
    # 예: python sg_console.py list --type holdings
    list_parser = subparsers.add_parser("list", help="내역 조회")
    list_parser.add_argument("--type", choices=['trades', 'holdings'], default='trades', 
                             help="조회할 데이터 선택 (trades: 전체이력, holdings: 현재잔고)")

    # report 명령: python sg_console.py report
    report_parser = subparsers.add_parser("report", help="실전 매매 성과 및 시스템 예측력 분석")
    args = parser.parse_args()
    
    # 명령어 없이 실행했을 경우 도움말 출력
    if not args.command:
        parser.print_help()
        return

    db = DBHandler()

    # --- 명령어 실행 로직 ---
    
    if args.command == "buy":
        success, result = db.record_buy(args.ticker, args.qty, args.price, args.stop, args.date)
        if success:
            print(f"✅ 매수 기록 성공: {args.ticker} {args.qty}주")
            print(f"   (수수료 포함 총액: ₩{result:,.0f})")
        else:
            print(f"❌ 매수 실패: {result}")

    elif args.command == "sell":
        success, result = db.record_sell(args.ticker, args.qty, args.price, args.date)
        if success:
            print(f"💰 매도 기록 성공: {args.ticker} {args.qty}주")
            print(f"   (수수료 차감 실현 손익: ₩{result:,.0f})")
        else:
            print(f"❌ 매도 실패: {result}")

    elif args.command == "list":
        if args.type == 'trades':
            records = db.get_all_trades()
            if not records:
                print("📭 매매 이력이 없습니다.")
                return
                
            print(f"\n📜 [Trade History: 전체 매매 이력]")
            print(f"{'ID':<4} | {'날짜':<12} | {'티커':<10} | {'구분':<4} | {'수량':<6} | {'가격':<10} | {'총액/손익':<12}")
            print("-" * 75)
            for r in records:
                # 매도일 경우 손익을 함께 표시하거나 총액 표시
                val = r['total_amount'] if r['type'] == 'BUY' else r['profit']
                indicator = "₩" if r['type'] == 'BUY' else "P:"
                print(f"{r['id']:<4} | {r['trade_date']:<12} | {r['ticker']:<10} | {r['type']:<4} | "
                      f"{r['qty']:<6} | {r['price']:<10,.0f} | {indicator}{val:,.0f}")
        
        elif args.type == 'holdings':
            records = db.get_all_holdings()
            if not records:
                print("📭 현재 보유 중인 종목이 없습니다.")
                return

            print(f"\n🛡️ [Current Holdings: 현재 잔고 현황]")
            print(f"{'티커':<10} | {'수량':<6} | {'평단가':<10} | {'최초손절':<10} | {'최종업데이트':<12}")
            print("-" * 65)
            for r in records:
                print(f"{r['ticker']:<10} | {r['qty']:<6} | {r['avg_price']:<10,.0f} | "
                      f"{r['entry_stop']:<10,.0f} | {r['last_updated']:<12}")
    elif args.command == "report":
        analyzer = SigmaAnalyzer(db, settings.DATA_DIR)
        
        # 1. 실전 매매 성과 (DB 기반)
        stats = analyzer.get_trade_performance()
        if stats and isinstance(stats, dict):
            print(f"\n📊 [David's Real Trade Performance]")
            print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            print(f" • 총 매매: {stats['total_trades']}회 (승률: {stats['win_rate']:.1f}%)")
            print(f" • 수익: {stats['win_count']}승 / 손실: {stats['loss_count']}패")
            print(f" • 누적 순이익: ₩{stats['total_profit']:,.0f}")
            print(f" • 손익비(P/F): {stats['profit_factor']:.2f}")
            print(f" • 평균 수익률: {stats['avg_profit_pct']:.2f}%")
            print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        else:
            print(f"\n📭 실전 매매 기록이 부족하여 성과 통계를 산출할 수 없습니다.")

        # 2. 시스템 예측력 감사 (CSV 기반)
        audit_msg = analyzer.run_performance_audit()
        # 텔레그램용 HTML 태그 제거 후 출력
        clean_msg = audit_msg.replace("<b>", "").replace("</b>", "").replace("<br>", "\n")
        print(f"\n{clean_msg}")                

if __name__ == "__main__":
    main()