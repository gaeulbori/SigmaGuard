"""
[Program Description]
- Sigma Guard v10.3.0 금융 로직 및 DB 무결성 단위 테스트.
- 주요 검증: 
    1. DB 디렉토리 자동 생성 여부.
    2. 분할 매수 시 이동평균법 평단가 계산.
    3. 국가별 수수료 산출.
    4. 매수-매도 전체 사이클의 실현 손익 및 수익률 검증 (AssertionError 해결).
"""

import unittest
import os
import shutil
import sys

# [Path Fix] 프로젝트 루트(SG)를 검색 경로에 추가하여 core 모듈을 불러올 수 있게 함
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.db_handler import DBHandler

class TestSGFinance(unittest.TestCase):
    def setUp(self):
        """테스트 환경 설정: 메모리 DB를 기본으로 사용하며, 디렉토리 테스트용 경로 정의"""
        self.test_db_dir = "data/db_test"
        self.test_db_path = os.path.join(self.test_db_dir, "test_sg.db")
        
        # 테스트 전 깨끗한 상태 유지
        if os.path.exists(self.test_db_dir):
            shutil.rmtree(self.test_db_dir)
            
        # 개별 테스트에서 사용할 핸들러 (메모리 DB)
        # :memory: DB는 연결이 유지되어야 테이블이 증발하지 않음
        self.handler = DBHandler(":memory:")

    def tearDown(self):
        """테스트 종료 후 임시 디렉토리 삭제"""
        if os.path.exists(self.test_db_dir):
            shutil.rmtree(self.test_db_dir)

    def test_db_directory_creation(self):
        """[Phase 1] data/db/ 디렉토리가 자동으로 생성되는지 검증"""
        # 파일 DB용 핸들러를 별도로 생성하여 디렉토리 생성 로직 확인
        _ = DBHandler(self.test_db_path)
        self.assertTrue(os.path.exists(self.test_db_dir))
        print(f"✅ DB 디렉토리 생성 확인: {self.test_db_dir}")

    def test_moving_average_logic(self):
        """[금융수학] 분할 매수 시 이동평균법 평단가 계산 검증"""
        # 사례: 100주 @ 10,000원 보유 중, 100주 @ 12,000원 추가 매수
        # 결과는 200주 @ 11,000원이어야 함
        res = self.handler.calculate_new_avg(old_qty=100, old_avg=10000, new_qty=100, new_price=12000)
        self.assertEqual(res, 11000)
        
        # 사례: 0주 보유 중 신규 매수 (100주 @ 50,000원)
        res_new = self.handler.calculate_new_avg(old_qty=0, old_avg=0, new_qty=100, new_price=50000)
        self.assertEqual(res_new, 50000)
        print("✅ 이동평균 평단가 계산 로직 검증 완료")

    def test_fee_calculation(self):
        """[금융수학] 국가별(티커 접미사별) 수수료 산출 검증"""
        amount = 1000000  # 100만 원 기준
        
        # 1. 한국 (.KS): 0.015% -> 150원
        kr_fee = self.handler._calculate_fee("005930.KS", amount)
        self.assertAlmostEqual(kr_fee, 150.0)
        
        # 2. 중국 (.SS): 0.2% -> 2,000원
        cn_fee = self.handler._calculate_fee("600519.SS", amount)
        self.assertAlmostEqual(cn_fee, 2000.0)
        
        # 3. 미국 (기타): 0.1% -> 1,000원
        us_fee = self.handler._calculate_fee("NVDA", amount)
        self.assertAlmostEqual(us_fee, 1000.0)
        print("✅ 국가별 수수료 산출 로직 검증 완료")

    def test_record_buy_integration(self):
        """[통합] record_buy 실행 시 holdings 및 trades 테이블 연동 검증"""
        ticker = "HMM.KS"
        # 연결이 유지되는 self.handler를 사용하여 데이터 휘발 방지
        success, _ = self.handler.record_buy(ticker, qty=10, price=20000, stop_loss=18000)
        
        self.assertTrue(success)
        print(f"✅ {ticker} 통합 매수 기록 테스트 통과")

    def test_full_trade_cycle(self):
        """[통합] 매수 후 매도 시 실현 손익 및 잔고 삭제 검증"""
        ticker = "SAMSUNG.KS"
        
        # 1. 매수: 100,000원에 10주 (수수료 150원 포함 총 비용 1,000,150원)
        self.handler.record_buy(ticker, 10, 100000, 90000)
        
        # 2. 매도: 110,000원에 10주 전량 매도
        # 매출: 1,100,000원 / 매도수수료: 165원 / 순매출: 1,099,835원
        # 예상 실현 손익: 1,099,835 - 1,000,150 = 99,685원
        success, profit = self.handler.record_sell(ticker, 10, 110000)
        
        self.assertTrue(success)
        self.assertAlmostEqual(profit, 99685.0)
        print(f"✅ 전체 매매 사이클 및 실현 손익({profit:,.0f}원) 검증 완료")

if __name__ == "__main__":
    unittest.main()