"""
[File Purpose]
- 리스크 등급(Normal, Warning, Danger)별 실제 성과를 통계적으로 분석.
- 시스템의 '예측력'을 객관적 데이터로 입증하기 위한 성과 감사 모듈.
"""

import pandas as pd
from pathlib import Path
from utils.logger import setup_custom_logger

logger = setup_custom_logger("SigmaAnalyzer")

class SigmaAnalyzer:
    def __init__(self, data_dir):
        # data/ledgers 폴더 경로 설정
        self.data_dir = Path(data_dir) / "ledgers"

    def run_performance_audit(self):
        """장부 데이터를 전수 조사하여 등급별 평균 낙폭 통계 산출"""
        all_files = list(self.data_dir.glob("sigma_guard_ledger_*.csv"))
        
        if not all_files:
            return "📊 <b>[성과 감사 요약]</b>\n데이터 부족: 분석할 장부 파일이 없습니다."

        try:
            # 1. 모든 종목의 장부를 하나로 통합
            combined_df = pd.concat([pd.read_csv(f) for f in all_files], ignore_index=True)
            
            # 2. 사후 결산(Ret_20d)이 완료된 데이터만 필터링
            audit_ready = combined_df.dropna(subset=['Ret_20d']).copy()
            
            if audit_ready.empty:
                return "📊 <b>[성과 감사 요약]</b>\n사후 수익률 결산 대기 중입니다 (T+20일 미경과)."

            # 3. 리스크 등급(Risk_Level)별 집계
            # Risk_Level은 1~5 정수이므로 이를 기준으로 그룹화
            summary = audit_ready.groupby('Risk_Level', observed=False).agg({
                'Ret_20d': 'mean',
                'Min_Ret_20d': 'mean',
                'Ticker': 'count'
            }).rename(columns={'Ticker': 'Case_Count'})

            # 4. 결과 메시지 구성
            msg = "📊 <b>[리스크 등급별 성과 감사 요약]</b>\n"
            msg += "━━━━━━━━━━━━━━\n"
            
            for level in [5, 4, 3, 2, 1]:
                if level in summary.index:
                    row = summary.loc[level]
                    icon = "🚨" if level >= 5 else "🔴" if level == 4 else "🟡" if level == 3 else "✅"
                    msg += f"{icon} Lv.{level}: {int(row['Case_Count'])}건 (평균낙폭 {row['Min_Ret_20d']:>+.1f}%)\n"
                else:
                    msg += f"⚪ Lv.{level}: 데이터 없음\n"
            
            msg += "━━━━━━━━━━━━━━\n"
            return msg

        except Exception as e:
            logger.error(f"❌ 성과 분석 중 오류 발생: {e}")
            return "⚠️ 성과 분석 엔진 가동 중 오류가 발생했습니다."