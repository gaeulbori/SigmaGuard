from utils.visual_utils import VisualUtils

class VisualReporter:
    def __init__(self, logger):
        self.logger = logger
        self.vu = VisualUtils()
        self.line = "-" * 100
        self.double_line = "=" * 100

    def print_audit_report(self, ticker, name, market_date, latest, bench_latest, score, prev_score, details, alloc, bt_res):
        """[v9.0.9] David 전용 Executive Summary 기반 감사 보고서"""
        
        # [STAGE 1] Executive Summary (최상단 배치: 3초 안에 판단)
        self._print_header(ticker, name, market_date, details)
        self._print_opinion(score, prev_score)
        self._print_decision(ticker, score, alloc)
        
        # [STAGE 2] Supporting Details (하단 배치: 결론에 대한 증거)
        self.logger.info(f" [ PART 1. 통계적 위치 (Z-Score Audit) ]")
        self._print_p1_table(ticker, latest, bench_latest)
        
        self.logger.info(f" [ PART 2. 추세 및 구조적 저항 (Context & Trap) ]")
        self._print_p2_context(latest, details)
        
        self.logger.info(f" [ PART 3. 수급 에너지 (Fuel & Momentum) ]")
        self._print_p3_energy(latest, details)
        
        self.logger.info(self.double_line + "\n")

    # -------------------------------------------------------------------------
    # [STAGE 1] Executive Block Methods
    # -------------------------------------------------------------------------
    def _print_header(self, ticker, name, date, details):
        self.logger.info(self.double_line)
        self.logger.info(f" 🔍 {name} ({ticker}) | {date} | LIV Status: {details.get('liv_status', 'N/A')}")
        self.logger.info(self.line)

    def _print_opinion(self, score, prev_score):
        label = self._get_label(score)
        emoji = "🚨" if score >= 81 else "⚠️" if score >= 46 else "✅"
        delta = self._get_delta_str(score, prev_score)
        
        self.logger.info(f" 🛡️ [AUDITOR'S OPINION]: {emoji} {label} | Risk Score: {score} {delta}")
        self.logger.info(self.line)

    def _print_decision(self, ticker, score, alloc):
        lvl = self._get_lvl(score)
        action = self._get_sop_action(lvl)
        stop = self._fmt_money(alloc.get('stop_loss', 0), ticker)
        
        self.logger.info(f" 🚩 [ FINAL DECISION ] : LEVEL {lvl} - {action}")
        self.logger.info(f" 📍 [EXECUTION]: STOP {stop} | WEIGHT {alloc.get('weight', 0)}% | E.I {alloc.get('ei', 0)}")
        self.logger.info(self.double_line)

    # -------------------------------------------------------------------------
    # [STAGE 2] Supporting Detail Methods
    # -------------------------------------------------------------------------
    def _print_p1_table(self, ticker, latest, bench_latest):
        self.logger.info(self.line)
        self.logger.info(f"   PERIOD  |     SIGMA ({ticker:^8})     |     SIGMA (BENCH)      |   상태   ")
        self.logger.info(self.line)
        
        for y in range(1, 6):
            s_t = latest.get(f'sig_{y}y', 0.0)
            # 벤치마크 미동기 대응: None인 경우 N/A 처리
            s_b_val = f"{bench_latest.get(f'sig_{y}y', 0.0):>+10.2f}σ" if bench_latest is not None else "    N/A     "
            label = "광기🚨" if s_t > 2.5 else "과열⚠️" if s_t > 1.5 else "정상"
            
            p_y = self.vu.pad_visual(f"{y}y", 10)
            p_st = self.vu.pad_visual(f"{s_t:>+10.2f}σ", 22)
            p_sb = self.vu.pad_visual(s_b_val, 22)
            p_lab = self.vu.pad_visual(label, 10)
            self.logger.info(f" {p_y}|{p_st}|{p_sb}|{p_lab}")
        self.logger.info(self.line)

    def _print_p2_context(self, latest, details):
        slope = details.get('multiplier', 1.0) # 기울기 대용
        r2 = latest.get('R2', 0)
        disp = latest.get('disp120', 0)
        trap_status = "🚨 ALERT (과이격)" if disp > 170 else "✅ SAFE"
        
        self.logger.info(f"  ▶ 추세 특성: Slope Coeff({slope:.4f}) | R2 신뢰도: {r2:.2f}")
        self.logger.info(f"  ▶ 구조적 저항: 120MA 이격도 {disp:.1f}% | 진단: {trap_status}")
        self.logger.info(self.line)

    def _print_p3_energy(self, latest, details):
        mfi = latest.get('MFI', latest.get('mfi', 0))
        rsi = latest.get('RSI', latest.get('rsi', 0))
        bbw = latest.get('bbw', 0)
        
        energy_label = "상승가속" if mfi > 60 and rsi > 60 else "에너지분산" if mfi < 40 else "안정"
        self.logger.info(f"  ▶ 수급 에너지: MFI({mfi:.1f}) | RSI({rsi:.1f}) | 변동성(BBW): {bbw:.4f}")
        self.logger.info(f"  ▶ 에너지 진단: [{energy_label}]")

    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------
    def _get_label(self, s):
        if s >= 81: return "DANGER"
        if s >= 66: return "WARNING"
        if s >= 46: return "WATCH"
        return "NORMAL"

    def _get_lvl(self, s):
        if s >= 81: return 5
        if s >= 66: return 4
        if s >= 46: return 3
        if s >= 26: return 2
        return 1

    def _get_sop_action(self, lvl):
        actions = {
            5: "비중 축소 및 강력 방어: 적극적 수익 실현 검토",
            4: "과열 주의: 신규 진입 금지 및 손절선 상향",
            3: "추세 관찰: 변동성 확대 대비 및 관망",
            2: "안정 보유: 리스크 관리 범위 내 정상 추세",
            1: "저평가/바닥권: 전략적 분할 매수 고려"
        }
        return actions.get(lvl, "데이터 분석 중")

    def _get_delta_str(self, score, prev):
        if not prev: return ""
        diff = score - prev
        sign = "▲" if diff > 0 else "▼" if diff < 0 else "-"
        return f"({sign}{abs(diff):.1f})"

    def _fmt_money(self, val, ticker):
        if not val: return "N/A"
        if any(s in ticker for s in ['.KS', '.KQ']):
            return f"₩{int(val):,}"
        return f"${val:,.2f}"