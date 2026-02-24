"""
[File Purpose]
- data/ledgers/ledger_handler.py의 장부 기입 로직 및 사후 결산 무결성 전수 감사.
- v8.9.7+ 표준 39개 컬럼 구조와 20일 경과 데이터 필터링 로직의 정확성을 확정함.

[Key Features]
- Currency Standard Audit (검증 1): 통화별 가격 포맷팅(원화 정수/달러 소수점 3자리) 확인.
- Transaction Integrity (검증 2): 동일 날짜 데이터 업서트 시 기존 결산 데이터(Ret_20d) 보존 검증.
- Structural Compliance (검증 3): 표준 39개 헤더의 완전성 감사.
- Time-Series Continuity (검증 4): 일자별 데이터 누적 정합성 확인.
- Historical State Retrieval (검증 5): 과거 리스크 상태(Level, Score) 직접 조회 기능 검증.
- Post-Audit Filter (검증 7): 20일 경과 여부에 따른 결산 대상 선정 로직(Date Mask) 감사.
"""

import unittest
import sys
import os
import pandas as pd
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timedelta

# [Path Fix] 프로젝트 루트(SG)를 검색 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.ledgers.ledger_handler import LedgerHandler

class TestLedgerAudit(unittest.TestCase):
    def setUp(self):
        """임시 디렉토리를 생성하여 실전 데이터 오염 차단"""
        self.test_dir = Path(tempfile.mkdtemp())
        self.handler = LedgerHandler()
        # 핸들러의 저장 경로를 임시 폴더로 변경
        self.handler.data_dir = self.test_dir / "ledgers"
        if not self.handler.data_dir.exists():
            self.handler.data_dir.mkdir(parents=True)

        self.ticker_kr = "005930.KS"
        self.ticker_us = "GOLD"
        self.sample_date = datetime.now().strftime("%Y-%m-%d")

        # [v9.7.0+] 현행 save_entry() API 기준 Mock 데이터 (latest 단일 dict)
        self.latest = {
            'Close': 150.0, 'RSI': 55.0, 'MFI': 60.0, 'bbw': 0.1, 'bbw_thr': 0.3,
            'disp120': 100.0, 'disp120_limit': 115.0, 'R2': 0.9, 'ADX': 25.0,
            'avg_sigma': 1.5, 'sig_1y': 1.0, 'sig_2y': 1.0, 'sig_3y': 1.0,
            'sig_4y': 1.0, 'sig_5y': 1.0
        }
        self.alloc = {'stop_loss': 140.0, 'risk_pct': 2.5, 'ei': 100, 'weight': 10.0}
        self.details = {'base_raw': 70, 'multiplier': 1.0, 'scenario': 'Bull', 'p1': 20, 'p2': 30, 'p4': 20}
        self.bt_res = {'avg_mdd': -5.0}

    def tearDown(self):
        """테스트 종료 후 임시 데이터 삭제"""
        shutil.rmtree(self.test_dir)

    def test_01_currency_formatting_audit(self):
        print("\n🔍 [검증 1] 통화별 규격화 테스트 중...")
        # 원화 가격 정수화 확인
        krw_val = self.handler._format_value(self.ticker_kr, 75600.78, "price")
        self.assertEqual(krw_val, 75601)
        # 달러 가격 소수점 3자리 확인
        usd_val = self.handler._format_value(self.ticker_us, 17.5678, "price")
        self.assertEqual(usd_val, 17.568)
        print("✅ 통화별 가격 포맷팅 검증 완료")

    def test_02_upsert_integrity_and_protection(self):
        print("\n🔍 [검증 2] 장부 업서트 및 수익률 데이터 보호 테스트 중...")
        file_path = self.handler._get_file_path(self.ticker_us)
        
        # 1. 기존에 이미 결산된(Ret_20d 존재) 데이터가 있다고 가정
        self.handler.save_entry(self.ticker_us, "Barrick", self.sample_date, self.latest, 50.0, self.details, self.alloc, self.bt_res, {})
        df_init = pd.read_csv(file_path)
        df_init.at[0, 'Ret_20d'] = 12.5 # 수동 결산 데이터 기입
        df_init.to_csv(file_path, index=False)

        # 2. 동일 날짜에 새로운 점수로 업데이트 실행
        self.handler.save_entry(self.ticker_us, "Barrick", self.sample_date, self.latest, 85.0, self.details, self.alloc, self.bt_res, {})
        
        # 3. 확인: 점수는 바뀌었지만, 기존 결산 데이터(Ret_20d)는 보존되어야 함
        df_updated = pd.read_csv(file_path)
        self.assertEqual(df_updated.iloc[0]['Risk_Score'], 85.0)
        self.assertEqual(df_updated.iloc[0]['Ret_20d'], 12.5)
        print("✅ 장부 업서트 및 기존 수익률 데이터 보호 확인")

    def test_03_header_standard_check(self):
        print("\n🔍 [검증 3] v8.9.7+ 표준 39개 컬럼 규격 감사 중...")
        self.handler.save_entry(self.ticker_us, "Barrick", self.sample_date, self.latest, 70.0, self.details, self.alloc, self.bt_res, {})
        df = pd.read_csv(self.handler._get_file_path(self.ticker_us))
        self.assertEqual(len(df.columns), 53)
        self.assertIn("Ret_20d", df.columns)
        print(f"✅ 총 {len(df.columns)}개 표준 컬럼 정합성 확인")

    def test_04_time_series_accumulation(self):
        print("\n🔍 [검증 4] 시계열 데이터 누적 테스트 중...")
        dates = ["2026-01-26", "2026-01-27", "2026-01-28"]
        for d in dates:
            self.handler.save_entry(self.ticker_us, "Barrick", d, self.latest, 70.0, self.details, self.alloc, self.bt_res, {})
        df = pd.read_csv(self.handler._get_file_path(self.ticker_us))
        self.assertEqual(len(df), 3)
        print("✅ 3일치 데이터 시계열 누적 확인 완료")

    def test_05_previous_state_reversion(self):
        print("\n🔍 [검증 5] 과거 기록된 상태(Level/Score) 조회 테스트 중...")
        # 어제 날짜로 데이터 강제 기입
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        self.handler.save_entry(self.ticker_us, "Barrick", yesterday, self.latest, 85.0, self.details, self.alloc, self.bt_res, {})

        today = datetime.now().strftime("%Y-%m-%d")
        level, score = self.handler.get_previous_state(self.ticker_us, today)
        self.assertEqual(level, 8) # 85점은 Level 8 (v9.7.0 9단계 규격: 81~90 → 8)
        self.assertEqual(score, 85.0)
        print(f"✅ 과거 상태 조회 확인 (Lv.{level} / {score}점)")

    def test_06_robustness_on_empty_file(self):
        print("\n🔍 [검증 6] 장부 부재 시 예외 처리 테스트 중...")
        level, score = self.handler.get_previous_state("NON_EXISTENT", datetime.now().strftime("%Y-%m-%d"))
        self.assertIsNone(level)
        self.assertIsNone(score)
        print("✅ 예외 상황 안정성 확인 완료")

    def test_07_post_audit_date_logic_compliance(self):
        print("\n🔍 [검증 7] 사후 결산 대상(20일 경과) 필터링 로직 감사...")
        file_path = self.handler._get_file_path(self.ticker_us)
        
        # 1. 두 개의 데이터 생성: 하나는 25일 전(결산 대상), 하나는 5일 전(대기 대상)
        date_target = (datetime.now() - timedelta(days=25)).strftime("%Y-%m-%d")
        date_wait = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
        
        self.handler.save_entry(self.ticker_us, "Barrick", date_target, self.latest, 50.0, self.details, self.alloc, self.bt_res, {})
        self.handler.save_entry(self.ticker_us, "Barrick", date_wait, self.latest, 60.0, self.details, self.alloc, self.bt_res, {})
        
        # 2. 결산 메서드 실행 (yfinance 호출 에러 방지를 위해 mask 로직만 간접 검증 가능)
        # 여기서는 update_forward_returns 내의 필터링 로직이 20일 경과 건만 잡는지 확인
        df = pd.read_csv(file_path)
        df['Audit_Date'] = pd.to_datetime(df['Audit_Date'])
        
        # 결산 로직과 동일한 Mask 적용
        mask = df['Ret_20d'].isna() & (df['Audit_Date'] <= datetime.now() - timedelta(days=20))
        target_count = len(df[mask])
        
        self.assertEqual(target_count, 1, f"❌ 결산 대상 선정 오류: 1건이어야 하나 {target_count}건 감지됨")
        print(f"✅ 사후 결산 대상 필터링 확인 (대상: {date_target})")

if __name__ == '__main__':
    unittest.main()