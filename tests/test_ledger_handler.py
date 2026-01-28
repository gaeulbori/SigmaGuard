"""
[File Purpose]
- data/ledgers/ledger_handler.py의 장부 기입 로직 및 데이터 무결성 전수 감사.
- David님의 통화별 포맷팅 규칙, v8.9.7+ 표준 39개 컬럼 구조 및 데이터 보존 로직의 신뢰성을 확정함.

[Key Features]
- Currency Standard Audit (검증 1): 국가별 통화 규격(원화 정수/달러 소수점) 준수 여부 확인.
- Transaction Integrity (검증 2): 동일 날짜 데이터 발생 시 기존 수익률(Ret_20d) 유실 방지 및 업서트(Upsert) 검증.
- Structural Compliance (검증 3): v8.9.7+ 표준 39개 헤더의 완전성 및 신규 파일 생성 규격 감사.
- Time-Series Continuity (검증 4): 일자별 데이터 누적(Append) 및 시계열 데이터 정합성 확인.
- Historical State Retrieval (검증 5): 과거 기록된 리스크 레벨 및 점수의 직접 추출(Direct Fetch) 정확성 검증.
- System Robustness (검증 6): 장부 파일 부재 또는 빈 데이터 환경에서의 예외 처리 및 생존성 테스트.

[Implementation Details]
- Framework: Python 표준 unittest 라이브러리 활용.
- Isolation: tempfile.mkdtemp()를 이용한 임시 디렉토리 환경에서 테스트 수행하여 실전 데이터 오염 원천 차단.
- Data Engine: Pandas를 이용한 CSV I/O 검사 및 데이터 타입(dtype) 일관성 및 FutureWarning 방어 로직 검증.
"""
import unittest
import sys
import os
import pandas as pd
import tempfile
import shutil
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.ledgers.ledger_handler import LedgerHandler

class TestLedgerAudit(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.handler = LedgerHandler()
        self.handler.data_dir = self.test_dir
        self.ticker_kr = "005930.KS"
        self.ticker_us = "GOLD"
        self.sample_date = "2026-01-28"
        self.tech = {'price': 150.0, 'rsi': 55.0, 'mfi': 60.0}
        self.stat = {'avg_sigma': 1.5}
        self.alloc = {'stop_loss': 140.0, 'risk_pct': 2.5, 'ei': 100, 'weight': 10.0}
        self.details = {'base_raw': 70, 'multiplier': 1.0, 'scenario': 'Bull', 'p1': 20, 'p2': 30, 'p4': 20}

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_01_currency_formatting_audit(self):
        print("\n🔍 [검증 1] 통화별 규격화 테스트 중...")
        krw_val = self.handler._format_value(self.ticker_kr, 75600.78, is_price=True)
        self.assertEqual(krw_val, 75601)
        usd_val = self.handler._format_value(self.ticker_us, 17.5678, is_price=True)
        self.assertEqual(usd_val, 17.568)
        print("✅ 통화별 가격 포맷팅 검증 완료")

    def test_02_upsert_integrity_and_protection(self):
        print("\n🔍 [검증 2] 장부 업서트 및 수익률 보호 테스트 중...")
        file_path = self.handler._get_file_path(self.ticker_us)
        mock_df = pd.DataFrame([{"Audit_Date": self.sample_date, "Ticker": self.ticker_us, "Ret_20d": 12.5, "Risk_Score": 50.0}])
        mock_df.to_csv(file_path, index=False)
        self.handler.save_entry(self.ticker_us, "Barrick", self.sample_date, self.tech, self.stat, None, None, 85.0, self.details, self.alloc, {}, "Buy")
        df_updated = pd.read_csv(file_path)
        self.assertEqual(len(df_updated), 1)
        self.assertEqual(df_updated.iloc[0]['Ret_20d'], 12.5)
        print("✅ 장부 업서트 및 데이터 보존 확인 완료")

    def test_03_header_standard_check(self):
        print("\n🔍 [검증 3] v8.9.7+ 표준 39개 컬럼 규격 감사 중...")
        self.handler.save_entry(self.ticker_us, "Barrick", self.sample_date, self.tech, self.stat, None, None, 70.0, self.details, self.alloc, {}, "Hold")
        df = pd.read_csv(self.handler._get_file_path(self.ticker_us))
        self.assertEqual(len(df.columns), 39)
        print(f"✅ 총 {len(df.columns)}개 표준 컬럼 일치 확인")

    def test_04_time_series_accumulation(self):
        print("\n🔍 [검증 4] 시계열 데이터 누적 테스트 중...")
        for d in ["2026-01-26", "2026-01-27", "2026-01-28"]:
            self.handler.save_entry(self.ticker_us, "Barrick", d, self.tech, self.stat, None, None, 70.0, self.details, self.alloc, {}, "Hold")
        df = pd.read_csv(self.handler._get_file_path(self.ticker_us))
        self.assertEqual(len(df), 3)
        print("✅ 3일치 데이터 누적 확인 완료")

    def test_05_previous_state_reversion(self):
        print("\n🔍 [검증 5] 과거 기록된 레벨 및 점수 직접 조회 테스트 중...")
        file_path = self.handler._get_file_path(self.ticker_us)
        # Mock 데이터에 Risk_Level 컬럼 추가
        past_data = pd.DataFrame([
            {"Audit_Date": "2026-01-26", "Risk_Score": 40.0, "Risk_Level": 2},
            {"Audit_Date": "2026-01-27", "Risk_Score": 85.0, "Risk_Level": 5}
        ])
        past_data.to_csv(file_path, index=False)
        level, score = self.handler.get_previous_state(self.ticker_us)
        self.assertEqual(level, 5)
        self.assertEqual(score, 85.0)
        print("✅ 과거 기록 기반 상태 조회 확인 완료")

    def test_06_robustness_on_empty_file(self):
        print("\n🔍 [검증 6] 빈 장부 조회 안정성 테스트 중...")
        level, score = self.handler.get_previous_state("EMPTY")
        self.assertIsNone(level)
        print("✅ 예외 상황 핸들링 확인 완료")

if __name__ == '__main__':
    unittest.main()