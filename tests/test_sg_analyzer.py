import unittest
import sys
import os
# [Path Fix] 프로젝트 루트(SG)를 검색 경로에 추가하여 core 모듈을 불러올 수 있게 함
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.db_handler import DBHandler
from core.sigma_analyzer import SigmaAnalyzer

class TestSGAnalyzer(unittest.TestCase):
    def setUp(self):
        self.db = DBHandler(":memory:")
        self.analyzer = SigmaAnalyzer(self.db)

    def test_profit_factor_calculation(self):
        """손익비 및 승률 계산 검증"""
        # 1. 익절 매매: 10,000원 이익
        self.db.record_buy("WIN.KS", 10, 10000, 9000)
        self.db.record_sell("WIN.KS", 10, 11000) # 수수료 무시 시 10,000원 수익
        
        # 2. 손절 매매: 5,000원 손실
        self.db.record_buy("LOSS.KS", 10, 10000, 9000)
        self.db.record_sell("LOSS.KS", 10, 9500) # 수수료 무시 시 5,000원 손실
        
        stats = self.analyzer.get_trade_performance()
        # 손익비는 2.0 근처여야 함 (10,000 / 5,000)
        self.assertAlmostEqual(stats['profit_factor'], 2.0, delta=0.1)
        self.assertEqual(stats['win_rate'], 50.0)
        print(f"✅ 성과 분석 테스트 통과 (PF: {stats['profit_factor']:.2f})")

if __name__ == "__main__":
    unittest.main()