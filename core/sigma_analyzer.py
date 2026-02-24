"""
[File Purpose]
- 리스크 등급별 예측력 검증(CSV 기반) 및 실전 매매 성과 분석(DB 기반) 통합 모듈.
- 안티프래질 시스템의 피드백 루프를 완성하여 전략의 유효성을 통계로 입증.
"""

import pandas as pd
from pathlib import Path
from utils.logger import setup_custom_logger

logger = setup_custom_logger("SigmaAnalyzer")

class SigmaAnalyzer:
    def __init__(self, db_handler, data_dir="data"):
        # 실전 매매 기록용 DB 핸들러
        self.db = db_handler
        # 과거 감사 기록용 CSV 경로 (data/ledgers)
        self.data_dir = Path(data_dir) / "ledgers"

    def get_trade_performance(self):
        """[신규] DB에 기록된 실전 매매 성과를 분석하여 요약합니다."""
        trades = self.db.get_all_trades()
        if not trades:
            return None
        
        df = pd.DataFrame(trades)
        # 매도(SELL) 건만 필터링하여 성과 계산
        completed = df[df['type'] == 'SELL'].copy()
        
        if completed.empty:
            return None

        # 기본 통계 계산
        total_trades = len(completed)
        wins = completed[completed['profit'] > 0]
        losses = completed[completed['profit'] <= 0]
        
        win_count = len(wins)
        loss_count = len(losses)
        total_profit = completed['profit'].sum()
        avg_profit_pct = completed['profit_percent'].mean()
        
        # 손익비 (Profit Factor) 계산: $$PF = \frac{\sum Profits}{\sum |Losses|}$$
        total_win_amt = wins['profit'].sum()
        total_loss_amt = abs(losses['profit'].sum())
        profit_factor = total_win_amt / total_loss_amt if total_loss_amt != 0 else float('inf')

        summary = {
            'total_trades': total_trades,
            'win_rate': (win_count / total_trades) * 100,
            'win_count': win_count,
            'loss_count': loss_count,
            'total_profit': total_profit,
            'avg_profit_pct': avg_profit_pct,
            'profit_factor': profit_factor,
            'max_profit': completed['profit'].max(),
            'max_loss': completed['profit'].min()
        }
        return summary

    def run_performance_audit(self):
        """[기존 유지] 장부 데이터를 전수 조사하여 등급별 평균 낙폭 통계 산출"""
        all_files = list(self.data_dir.glob("sigma_guard_ledger_*.csv"))
        
        if not all_files:
            return "📊 <b>[성과 감사 요약]</b>\n데이터 부족: 분석할 장부 파일이 없습니다."

        try:
            combined_df = pd.concat([pd.read_csv(f) for f in all_files], ignore_index=True)
            audit_ready = combined_df.dropna(subset=['Ret_20d']).copy()
            
            if audit_ready.empty:
                return "📊 <b>[성과 감사 요약]</b>\n사후 수익률 결산 대기 중입니다 (T+20일 미경과)."

            summary = audit_ready.groupby('Risk_Level', observed=False).agg({
                'Ret_20d': 'mean',
                'Min_Ret_20d': 'mean',
                'Ticker': 'count'
            }).rename(columns={'Ticker': 'Case_Count'})

            msg = "📊 <b>[리스크 등급별 예측력 검증]</b>\n"
            msg += "━━━━━━━━━━━━━━\n"
            for level in [9, 8, 7, 6, 5, 4, 3, 2, 1]:
                if level in summary.index:
                    row = summary.loc[level]
                    icon = "🚨" if level >= 6 else "🔴" if level in (4, 5) else "🟡" if level == 3 else "✅"
                    msg += f"{icon} Lv.{level}: {int(row['Case_Count'])}건 (평균낙폭 {row['Min_Ret_20d']:>+.1f}%)\n"
                else:
                    msg += f"⚪ Lv.{level}: 데이터 없음\n"
            msg += "━━━━━━━━━━━━━━\n"
            return msg

        except Exception as e:
            logger.error(f"❌ 성과 분석 중 오류 발생: {e}")
            return "⚠️ 성과 분석 엔진 가동 중 오류가 발생했습니다."