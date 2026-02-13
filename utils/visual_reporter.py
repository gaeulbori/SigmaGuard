import pandas as pd
import numpy as np
import unicodedata
from datetime import datetime
from utils.visual_utils import VisualUtils
from core.risk_engine import RiskEngine

class VisualReporter:
    def __init__(self, logger):
        self.logger = logger
        self.vu = VisualUtils()
        self.engine = RiskEngine()
        self.line = "-" * 100
        self.double_line = "=" * 100

    def print_audit_report(self, item, market_date, latest, bench_latest, score, prev_score, details, alloc, bt_res):
        """[v9.8.7] David's Master Layout: 벤치마크 Insight 및 데이터 무결성 보강"""
        ticker = item.get('ticker')
        name = item.get('name') 
        b_ticker = item.get('bench', 'N/A')
        b_name = item.get('bench_name', 'Standard Index')
        holdings = item.get('holdings', {'qty': 0, 'avg_price': 0})        
        
        # 1. HEADER & DASHBOARD
        self.logger.info(self.double_line)
        self.logger.info(f" 🔍 {name} ({ticker}) vs {b_name} ({b_ticker}) | 감사기준일: {market_date}")        
        self.logger.info(self.line)

        # 보유 자산 정보 출력 (David님 전용 수익률 계산기)
        if holdings and float(holdings.get('qty', 0)) > 0:
            qty = holdings['qty']
            avg_p = holdings['avg_price']
            curr_p = latest.get('Close', 0)
            profit_pct = ((curr_p - avg_p) / avg_p) * 100
            self.logger.info(f" 💰 [HOLDING INFO] Qty: {qty:,} | Avg: ${avg_p:.2f} | Return: {profit_pct:+.2f}%")

        delta_str = self._get_delta_str(score, prev_score)
        lvl = self._get_lvl(score)
        lvl_label = self._get_label_with_emoji(lvl)

        vix, dxy, us10y = details.get('vix', 'N/A'), details.get('dxy', 'N/A'), details.get('us10y', 'N/A')
        
        self.logger.info(f" 🚩 [REPORT VERDICT] RISK SCORE: {score} 점 {delta_str} | {lvl_label} (LEVEL {lvl})")        
        self.logger.info(f" 🌐 [MARKET WEATHER] VIX: {vix} | DXY: {dxy} | US10Y: {us10y}%")
        
        p_str = self._fmt_money(latest.get('Close', 0), ticker)
        disp = latest.get('disp120', 100.0)
        self.logger.info(f" 🎯 [TACTICAL DATA]  Price: {p_str:10} | 120MA Disp: {disp:.1f}%")
        self.logger.info(f" 🛡️ [TREND CONFIRM] LIVERMORE: {details.get('liv_status', 'N/A')}")
        self.logger.info(self.double_line)

        # 2. PART별 상세 분석
        self._print_p1_table_aligned(ticker, latest, bench_latest, b_ticker, b_name)
        self.logger.info(f" ▶ 진단: {details.get('v1_comment', 'N/A')}")
        self.logger.info(self.line)

        self._print_p2_energy_comparative(ticker, latest, bench_latest, details, b_ticker, b_name)
        self.logger.info(f" ▶ 진단: {details.get('v2_comment', 'N/A')}")
        self.logger.info(self.line)

        self._print_p3_trend_with_gap(latest, details, bench_latest, b_ticker, b_name)
        self.logger.info(f" ▶ 진단: {details.get('v4_comment', 'N/A')}")
        self.logger.info(self.line)

        # 3. FINAL VERDICT
        self._print_final_verdict_left_full(score, prev_score, details, alloc, bt_res, name, ticker)

    def _print_p1_table_aligned(self, ticker, latest, bench_latest, b_ticker, b_name):
        self.logger.info(f" [PART 1. 통계적 위치 분석]")
        self.logger.info(self.line)
        
        # 1. 컬럼 너비 정의 (기존 유지)
        W_PRD, W_TGT, W_BCH, W_ST, W_CMT = 10, 25, 25, 10, 18
        
        # 2. [수정] 벤치마크 이름 노출 로직 정밀화
        # 너비가 25이므로, 22자까지만 쓰고 ..을 붙여야 양옆 1칸씩 여백이 생깁니다.
        b_disp = b_name[:22] + ".." if len(b_name) > 25 else b_name
        
        h_period = f"{'PERIOD':^{W_PRD}}"
        h_target = f"{f'SIGMA ({ticker})':^{W_TGT}}"
        h_bench  = f"{f'SIGMA ({b_disp})':^{W_BCH}}"
        h_status = f"{'상태':^{W_ST}}"
        
        # 3. [수정] 구분선 구조 재설계 (세로선 좌우 공백 반영)
        # 각 구간 대시(-) 사이에 ' + ' (공백+플러스+공백)를 배치합니다.
        inner_sep = "-"*W_PRD + " + " + "-"*W_TGT + " + " + "-"*W_BCH + " + " + "-"*W_ST + " + " + "-"*W_CMT
        
        # 4. [수정] 헤더 출력 (세로선 좌우 공백 추가)
        self.logger.info(f" {h_period} | {h_target} | {h_bench} | {h_status} |  통계적 해설")
        self.logger.info(f" {inner_sep}")
        
        comments = ["1y 변동성 범위", "2y 변동성 범위", "3y 주기 분석", "4y 장기 추세", "5y 역사적 고점"]
        
        # 5. 데이터 행 출력
        for i, y in enumerate(range(1, 6)):
            s_t = latest.get(f'sig_{y}y', 0.0)
            s_b_raw = bench_latest.get(f'sig_{y}y') if bench_latest is not None else None
            
            # 수치 포맷팅 (부호 포함)
            val_t_str = f"{float(s_t):>+10.2f}σ"
            val_b_str = f"{float(s_b_raw):>+10.2f}σ" if s_b_raw is not None else "N/A"
            
            # 셀 데이터 중앙 정렬
            c_period = f"{y}y".center(W_PRD)
            c_target = val_t_str.center(W_TGT)
            c_bench  = val_b_str.center(W_BCH)
            
            label_text = "광기🚨" if s_t > 2.5 else "과열⚠️" if s_t > 1.5 else "정상"
            c_status = label_text.center(W_ST)
            
            # [수정] 데이터 로우도 헤더와 동일하게 ' | ' (공백 포함 세로선) 사용
            self.logger.info(f" {c_period} | {c_target} | {c_bench} | {c_status} |  {comments[i]}")

        self.logger.info(self.line)

    def _print_p2_energy_comparative(self, ticker, latest, bench_latest, details, b_ticker, b_name):
        self.logger.info(f" [PART 2. 수급 에너지 분석]")
        self.logger.info(self.line)
        bbw, thr = latest.get('bbw', 0), details.get('bbw_thr', 0.3)
        mfi, rsi = latest.get('MFI', 50), latest.get('RSI', 50)
        macd_h = details.get('macd_h', 0.0)
        mfi_l, rsi_l = ("과열🚨" if mfi > 70 else "심해📉" if mfi < 30 else "안정"), ("과열🚨" if rsi > 70 else "침체📉" if rsi < 30 else "적정")
        supply_conclusion, risk_hint = self.engine._get_supply_intelligence(mfi, rsi)

        self.logger.info(f" ▶ {ticker:^10} | 변동성[BBW]: {bbw:.4f} (임계: {thr:.2f}) -> {details.get('vol_label', 'STABLE')}")
        self.logger.info(f"              | 자금흐름[MFI]: {mfi:>4.1f} ({mfi_l}) | 탄력[RSI]: {rsi:>4.1f} ({rsi_l})")
        self.logger.info(f"              | 에너지 힌트: {risk_hint} | 추세엔진[MACD]: {macd_h:>8.4f}")
        self.logger.info(f"              | 수급 진단 : {supply_conclusion}")
        
        if bench_latest is not None:
            b_mfi, b_rsi = bench_latest.get('MFI', 50), bench_latest.get('RSI', 50)
            self.logger.info(f" ▷ {b_name[:20]} ({b_ticker}) | 에너지 대조: MFI({b_mfi:.1f}) RSI({b_rsi:.1f}) | MACD Hist: {details.get('bench_macd_h', 0.0):>8.4f}")

    def _print_p3_trend_with_gap(self, latest, details, bench_latest, b_ticker, b_name):
        self.logger.info(f" [PART 3. 추세 성격 및 구조적 저항]")
        self.logger.info(self.line)
        ma_status = details.get('ma_status', 'N/A')
        ma_desc = "120MA 우상향" if ma_status == "Rising" else "120MA 우하향"
        ma_emoji = "✅" if ma_status == "Rising" else "⚠️"
        r2, adx = latest.get('R2', 0), latest.get('ADX', 0)
        r2_l = "매우 직선적" if r2 >= 0.85 else "안정적 추세" if r2 >= 0.60 else "방향성 모호"
        adx_l = "추세 관성 강력" if adx >= 25 else "추세 약화/횡보"
        disp, limit = latest.get('disp120', 100.0), latest.get('disp120_limit', 115.0)
        trap_diag = "✅ SAFE" if disp <= limit else "🚨 ALERT (과이격)"
        
        self.logger.info(f" ▶ 추세신뢰 : {ma_emoji} {ma_status} [{ma_desc}]")
        self.logger.info(f" ▶ 신뢰/관성 : R2({r2:.2f}) [{r2_l}] | ADX({adx:.1f}) [{adx_l}]")
        self.logger.info(f" ▶ 구조저항 : 120MA 이격도 {disp:.1f}% (Limit: {limit:.1f}% 이하) | 상태: {trap_diag}")
        self.logger.info(f"             ({b_name} 대비 추세 괴리: {details.get('discrepancy', 0.0):>+4.1f})")

    def _print_final_verdict_left_full(self, score, prev_score, details, alloc, bt_res, name, ticker):
        delta = self._get_delta_str(score, prev_score)
        self.logger.info(f" 🚩 [FINAL INTEGRATED RISK SCORE] : {score} 점 {delta}")
        self.logger.info(self.line)
        p1, p2, p4 = details.get('p1_ema', 0), details.get('p2_ema', 0), details.get('p4_ema', 0)
        mult, liv_disc = details.get('multiplier', 1.0), (1 - details.get('liv_discount', 0)) * 100
        self.logger.info(f" 산출근거 : [위치 {p1:.1f} + 에너지 {p2:.1f} + 저항 {p4:.1f}] × 가중치 {mult:.2f} × 할인 {liv_disc:.0f}%")        
        self.logger.info(f" 백테스트 : {name} 기준 기대MDD {bt_res.get('avg_mdd', 0.0)}% | 평균회복 {bt_res.get('avg_days', 0)}일")
        stop_str = self._fmt_money(alloc.get('stop_loss', 0), ticker)
        self.logger.info(f" 전술지표 : Stop Loss: {stop_str:10} | Invest E.I: {alloc.get('ei', 0.0):<5.2f} | 권고비중: {alloc.get('weight', 0.0)}%")
        self.logger.info(f" 집행지침 : LEVEL {self._get_lvl(score)} - {details.get('action', 'N/A')}")
        self.logger.info(self.double_line + "\n")

    def print_audit_summary_table(self, audit_results):
        """[v9.8.8 Fix] 한글/영문 혼용 환경에서의 세로 칼럼 폭 완벽 정렬"""
        if not audit_results:
            self.logger.warning("📊 요약할 감사 결과가 없습니다."); return

        df = pd.DataFrame(audit_results).sort_values(by='score', ascending=False)
        
        # [CPA 정밀 규격] 각 칼럼의 고정 너비 설정 (합계 약 145자)
        W = {
            'rank': 4, 'name': 20, 'ticker': 12, 'price': 15,
            'score': 18, 'action': 32, 'ei': 8, 'stop': 15, 'weight': 10
        }

        # 전체 구분선 생성
        total_width = sum(W.values()) + (len(W) - 1) * 3 + 2
        line_sep = "-" * total_width
        double_sep = "=" * total_width

        self.logger.info(double_sep)
        self.logger.info(f" 📑 [TOTAL AUDIT SUMMARY] 총 {len(df)}개 종목 전수 감사 결과 요약")
        self.logger.info(line_sep)
        
        # 1. 헤더 출력 (시각적 폭 계산 적용)
        header = (
            f" {self._pad_visual('Rank', W['rank'], 'center')} | "
            f"{self._pad_visual('Name', W['name'], 'left')} | "
            f"{self._pad_visual('Ticker', W['ticker'], 'left')} | "
            f"{self._pad_visual('Current Price', W['price'], 'right')} | "
            f"{self._pad_visual('Score(Δ)', W['score'], 'right')} | "
            f"{self._pad_visual('Level (Action)', W['action'], 'left')} | "
            f"{self._pad_visual('EI', W['ei'], 'center')} | "
            f"{self._pad_visual('Stop Loss', W['stop'], 'right')} | "
            f"{self._pad_visual('Weight', W['weight'], 'right')}"
        )
        self.logger.info(header)
        self.logger.info(line_sep)

        # 2. 데이터 로우 출력
        for i, (_, row) in enumerate(df.iterrows(), 1):
            ticker = str(row['ticker'])
            p_str = self._fmt_money(row.get('price', 0), ticker)
            s_str = self._fmt_money(row.get('stop', 0), ticker)
            
            # 리스크 및 델타 계산
            score, p_score = float(row['score']), row.get('prev_score')
            if p_score is not None and not pd.isna(p_score):
                delta = score - float(p_score)
                delta_str = f"{delta:>+4.1f}"
            else:
                delta_str = " NEW"
            
            score_display = f"{score:.1f} ({delta_str})"
            
            # Action 메시지 최적화 (이모지 포함)
            lvl = self._get_lvl(score)
            emoji = self._get_label_with_emoji(lvl).split()[0]
            # 지침 텍스트가 너무 길면 잘라서 정렬 유지
            action_raw = str(row.get('action_text', 'N/A')).split(':')[0]
            action_display = f"{emoji} LV.{lvl} {action_raw}"

            # 최종 라인 조립
            line = (
                f" {self._pad_visual(i, W['rank'], 'center')} | "
                f"{self._truncate_and_pad_visual(row.get('name', ticker), W['name'])} | "
                f"{self._pad_visual(ticker, W['ticker'])} | "
                f"{self._pad_visual(p_str, W['price'], 'right')} | "
                f"{self._pad_visual(score_display, W['score'], 'right')} | "
                f"{self._truncate_and_pad_visual(action_display, W['action'])} | "
                f"{self._pad_visual(f'{float(row.get('ei', 0)):.2f}', W['ei'], 'center')} | "
                f"{self._pad_visual(s_str, W['stop'], 'right')} | "
                f"{self._pad_visual(f'{float(row.get('weight', 0)):.1f}%', W['weight'], 'right')}"
            )            
            self.logger.info(line)

        self.logger.info(double_sep + "\n")

    def assemble_delta_alerts(self, new, up, down):
        if not (new or up or down): return ""
        now = datetime.now().strftime("%Y-%m-%d")
        body = f"🛡️ <b>[Sigma Guard Alert] {now}</b>\n━━━━━━━━━━━━━\n\n"
        if new: body += "✨ <b>[신규 분석 종목]</b>\n" + "".join(new) + "---\n\n"
        if up: body += "🚨 <b>[SOP 레벨 상승]</b>\n" + "".join(up) + "---\n\n"
        if down: body += "✅ <b>[SOP 레벨 완화]</b>\n" + "".join(down) + "---\n\n"
        return body

    def build_delta_alert_msg(self, data):
        score, p_score, ticker = data['score'], data.get('prev_score'), data['ticker']
        name, p_val = data.get('name', ticker), data.get('price', 0)
        p_str = self._fmt_money(p_val, ticker)
        emoji = self._get_label_with_emoji(self._get_lvl(score)).split()[0]
        if p_score is None or pd.isna(p_score):
            return f"{emoji} <b>{name} ({ticker})</b> 🆕 [<b>{p_str}</b>]\n상태: <b>LEVEL {self._get_lvl(score)}</b> ({score:.1f}점)\n지침: <code>{data.get('action_text', '관망')}</code>\n\n"
        diff = score - p_score
        if abs(diff) >= 5.0:
            trend = "📈 리스크 급증" if diff > 0 else "📉 리스크 완화"
            return f"{emoji} <b>{name} ({ticker})</b> ⚠️ [<b>{p_str}</b>] {trend}\n변동: <code>{p_score:.1f}</code> → <b>{score:.1f}</b>\n지침: <i>{data.get('action_text', '지침 확인')}</i>\n\n"
        return ""

    def build_weekly_dashboard(self, results):
        if not results: return ""
        msg = f"📊 <b>[Weekly Audit Dashboard]</b>\n────────────\n"
        for res in sorted(results, key=lambda x: x['score'], reverse=True):
            lvl = self._get_lvl(res['score'])
            emoji = self._get_label_with_emoji(lvl).split()[0]
            d_name = self._truncate_and_pad_visual(res.get('name', res['ticker']), 16)
            p_str = self._fmt_money(res.get('price', 0), res['ticker'])
            p_display = self._pad_visual(p_str, 12, align='right')
            action = str(res.get('action_text', '관망')).split(':')[0].split('-')[-1].strip()
            msg += f"{emoji} <code>{d_name} | {p_display} | {action}</code>\n"
        msg += f"────────────\n💡 <i>David SOP 9단계 기준 보고입니다.</i>"
        return msg

    def _get_delta_str(self, score, prev):
        if prev is None or pd.isna(prev): return "(NEW)"
        diff = score - prev
        return f"({'▲' if diff > 0 else '▼' if diff < 0 else '-'}{abs(diff):.1f})"

    def _get_lvl(self, s):
        if s >= 91: return 9
        if s >= 81: return 8
        if s >= 71: return 7
        if s >= 61: return 6
        if s >= 41: return 5
        if s >= 31: return 4
        if s >= 21: return 3
        if s >= 11: return 2
        return 1

    def _get_label_with_emoji(self, lvl):
        emojis = {9: "🚫 EXIT", 8: "🚨 DANGER", 7: "🔴 WARNING", 6: "🟠 CAUTION", 5: "🟡 WATCH", 4: "🔵 ENTRY", 3: "🟢 ACCUMULATE", 2: "💎 CONCENTRATE", 1: "🔥 FULL"}
        return emojis.get(lvl, "N/A")

    def _fmt_money(self, val, ticker):
        if val is None or pd.isna(val): return "N/A"
        is_krw = any(s in str(ticker) for s in ['.KS', '.KQ'])
        return f"₩{int(val):,}" if is_krw else f"${val:,.2f}"

    def _get_visual_width(self, text):
        width = 0
        for char in str(text):
            width += 2 if unicodedata.east_asian_width(char) in ('W', 'F') else 1
        return width

    def _pad_visual(self, text, length, align='left'):
        padding = max(0, length - self._get_visual_width(text))
        if align == 'right': return (" " * padding) + str(text)
        if align == 'center': return (" " * (padding // 2)) + str(text) + (" " * (padding - padding // 2))
        return str(text) + (" " * padding)

    def _truncate_and_pad_visual(self, text, length):
        if self._get_visual_width(text) <= length: return self._pad_visual(text, length)
        res, width = "", 0
        for char in str(text):
            w = 2 if unicodedata.east_asian_width(char) in ('W', 'F') else 1
            if width + w > length - 2: return self._pad_visual(res + "..", length)
            res += char; width += w
        return self._pad_visual(res, length)