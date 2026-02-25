"""
[Program Description]
1. DBHandler: SQLite 연결을 유지하여 :memory: 및 파일 DB의 정합성을 보장합니다.
2. record_buy: 매수 시 평단가를 갱신하고 'active' 상태로 기록합니다.
3. record_sell: 매도 시 수량을 차감하고, 평단가 대비 실현 손익과 수수료를 계산하여 기록합니다.
"""
import sqlite3
import os
import threading
import logging
from datetime import datetime

_logger = logging.getLogger("DBHandler")

class DBHandler:
    def __init__(self, db_path="data/db/sg_fortress.db"):
        self.db_path = db_path
        self.lock = threading.Lock()
        # 연결을 유지하여 메모리 DB 휘발 방지 및 성능 향상
        db_dir = os.path.dirname(self.db_path)
        if db_dir: os.makedirs(db_dir, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._initialize_db()

    def _initialize_db(self):
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute('''CREATE TABLE IF NOT EXISTS holdings (
                ticker TEXT PRIMARY KEY, qty REAL DEFAULT 0, avg_price REAL DEFAULT 0,
                entry_stop REAL, last_updated TEXT,
                trailing_high REAL DEFAULT 0, trailing_stop REAL DEFAULT 0
            )''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT, type TEXT,
                qty REAL, price REAL, fee REAL, total_amount REAL,
                profit REAL DEFAULT 0, profit_percent REAL DEFAULT 0, trade_date TEXT, status TEXT
            )''')
            # 기존 DB 마이그레이션 (trailing 컬럼이 없는 구버전 대응)
            self._migrate_holdings_table(cursor)
            self.conn.commit()

    def _migrate_holdings_table(self, cursor):
        """[마이그레이션] holdings 테이블에 trailing_high / trailing_stop 컬럼 추가."""
        cursor.execute("PRAGMA table_info(holdings)")
        existing_cols = {row[1] for row in cursor.fetchall()}

        if 'trailing_high' not in existing_cols:
            cursor.execute("ALTER TABLE holdings ADD COLUMN trailing_high REAL DEFAULT 0")
            _logger.info("🔧 DB 마이그레이션: holdings.trailing_high 컬럼 추가 완료")

        if 'trailing_stop' not in existing_cols:
            cursor.execute("ALTER TABLE holdings ADD COLUMN trailing_stop REAL DEFAULT 0")
            _logger.info("🔧 DB 마이그레이션: holdings.trailing_stop 컬럼 추가 완료")

    def record_buy(self, ticker, qty, price, stop_loss, date=None):
        trade_date = date or datetime.now().strftime('%Y-%m-%d')
        fee = self._calculate_fee(ticker, qty * price)
        total_cost = (qty * price) + fee # 수수료 포함 지출

        with self.lock:
            try:
                cursor = self.conn.cursor()
                cursor.execute("SELECT qty, avg_price FROM holdings WHERE ticker = ?", (ticker,))
                row = cursor.fetchone()
                
                if row:
                    curr_qty, curr_avg = row
                    new_qty = curr_qty + qty
                    new_avg = ((curr_qty * curr_avg) + total_cost) / new_qty
                    cursor.execute("UPDATE holdings SET qty=?, avg_price=?, last_updated=? WHERE ticker=?", 
                                   (new_qty, new_avg, trade_date, ticker))
                else:
                    cursor.execute("INSERT INTO holdings (ticker, qty, avg_price, entry_stop, last_updated) VALUES (?, ?, ?, ?, ?)",
                                   (ticker, qty, total_cost/qty, stop_loss, trade_date))

                cursor.execute("INSERT INTO trades (ticker, type, qty, price, fee, total_amount, trade_date, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                               (ticker, 'BUY', qty, price, fee, total_cost, trade_date, 'active'))
                self.conn.commit()
                return True, total_cost
            except Exception as e:
                self.conn.rollback()
                return False, str(e)

    def record_sell(self, ticker, qty, price, date=None):
        """[Phase 1 완성] 매도 기록 및 실현 손익 계산"""
        trade_date = date or datetime.now().strftime('%Y-%m-%d')
        sell_revenue = qty * price
        fee = self._calculate_fee(ticker, sell_revenue)
        net_revenue = sell_revenue - fee # 수수료 제외 수입

        with self.lock:
            try:
                cursor = self.conn.cursor()
                cursor.execute("SELECT qty, avg_price FROM holdings WHERE ticker = ?", (ticker,))
                row = cursor.fetchone()
                
                if not row or row[0] < qty:
                    return False, "보유 수량이 부족합니다."

                curr_qty, avg_price = row
                # 실현 손익 계산: (매도가 - 평단가) * 수량 - 매도수수료
                profit = (price - avg_price) * qty - fee
                profit_percent = (profit / (avg_price * qty)) * 100

                # 1. 잔고 업데이트
                new_qty = curr_qty - qty
                if new_qty == 0:
                    cursor.execute("DELETE FROM holdings WHERE ticker = ?", (ticker,))
                else:
                    cursor.execute("UPDATE holdings SET qty=?, last_updated=? WHERE ticker=?", (new_qty, trade_date, ticker))

                # 2. 매도 기록 추가 (DMT_BOT 방식: 한 줄에 손익 표기)
                cursor.execute('''INSERT INTO trades (ticker, type, qty, price, fee, total_amount, profit, profit_percent, trade_date, status) 
                                  VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                               (ticker, 'SELL', qty, price, fee, net_revenue, profit, profit_percent, trade_date, 'completed'))
                
                self.conn.commit()
                return True, profit
            except Exception as e:
                self.conn.rollback()
                return False, str(e)

    def _calculate_fee(self, ticker, amount):
        if ticker.endswith(".KS") or ticker.endswith(".KQ"): return amount * 0.00015
        if ticker.endswith(".SS") or ticker.endswith(".SZ"): return amount * 0.002
        return amount * 0.001

    def calculate_new_avg(self, old_qty, old_avg, new_qty, new_price):
        """수수료 제외 순수 이동평균 단가 산출 유틸리티 (금융수학 검증용)"""
        if old_qty + new_qty == 0: return 0
        return ((old_qty * old_avg) + (new_qty * new_price)) / (old_qty + new_qty)

    def update_trailing_high(self, ticker, new_high, new_stop):
        """
        [트레일링 고점 및 스탑 DB 갱신]
        - trailing_high : max(new_high, 기존값) — 단방향 상승만 허용
        - trailing_stop : new_stop > 기존값일 때만 갱신 (스탑은 올리기만 함)
        - entry_stop    : 절대 수정하지 않음
        반환: (True, 적용된_trailing_stop) 또는 (False, 오류메시지)
        """
        with self.lock:
            try:
                cursor = self.conn.cursor()
                cursor.execute(
                    "SELECT trailing_high, trailing_stop FROM holdings WHERE ticker = ?",
                    (ticker,)
                )
                row = cursor.fetchone()
                if not row:
                    return False, f"[{ticker}] holdings에 존재하지 않는 종목입니다."

                curr_trail_high = row[0] or 0.0
                curr_trail_stop = row[1] or 0.0

                # trailing_high: 단방향 상승 (최고점만 갱신)
                updated_high = max(new_high, curr_trail_high)

                if new_stop > curr_trail_stop:
                    # trailing_stop 상향: 두 필드 동시 갱신
                    cursor.execute(
                        "UPDATE holdings SET trailing_high = ?, trailing_stop = ? WHERE ticker = ?",
                        (updated_high, new_stop, ticker)
                    )
                    self.conn.commit()
                    _logger.info(
                        f"📈 [{ticker}] 트레일링 갱신: "
                        f"high=${updated_high:.2f}, stop=${new_stop:.2f}"
                    )
                    return True, new_stop
                else:
                    # trailing_stop 유지, trailing_high만 갱신 (가격이 오른 경우)
                    if updated_high > curr_trail_high:
                        cursor.execute(
                            "UPDATE holdings SET trailing_high = ? WHERE ticker = ?",
                            (updated_high, ticker)
                        )
                        self.conn.commit()
                    return True, curr_trail_stop

            except Exception as e:
                self.conn.rollback()
                _logger.error(f"❌ [{ticker}] update_trailing_high 오류: {e}")
                return False, str(e)

    def get_all_trades(self):
        """저장된 모든 매매 이력을 최신순으로 가져옵니다."""
        with self.lock:
            try:
                cursor = self.conn.cursor()
                cursor.execute("SELECT * FROM trades ORDER BY trade_date DESC, id DESC")
                columns = [column[0] for column in cursor.description]
                rows = cursor.fetchall()
                return [dict(zip(columns, row)) for row in rows]
            except Exception as e:
                _logger.error(f"trades 조회 오류: {e}")
                return []

    def get_all_holdings(self):
        """현재 보유 중인 모든 종목 정보를 가져옵니다."""
        with self.lock:
            try:
                cursor = self.conn.cursor()
                cursor.execute("SELECT * FROM holdings")
                columns = [column[0] for column in cursor.description]
                rows = cursor.fetchall()
                return [dict(zip(columns, row)) for row in rows]
            except Exception as e:
                _logger.error(f"holdings 조회 오류: {e}")
                return []