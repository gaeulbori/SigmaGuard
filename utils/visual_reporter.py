import pandas as pd
import unicodedata

from utils.visual_utils import VisualUtils
from core.risk_engine import RiskEngine
from datetime import datetime

class VisualReporter:
    def __init__(self, logger):
        self.logger = logger
        self.vu = VisualUtils()
        self.engine = RiskEngine()
        self.line = "-" * 100
        self.double_line = "=" * 100

    def print_audit_report(self, item, market_date, latest, bench_latest, score, prev_score, details, alloc, bt_res):
        """[v9.6.0] David's Master Layout: 상단 현황판 및 하단 집행 지침 최적화"""
        # 1. 기존 필드 그대로 사용 (수정 최소화)
        ticker = item.get('ticker')
        name = item.get('name') 
        b_ticker = item.get('bench', 'N/A')
        # 2. 추가된 필드만 매핑
        b_name = item.get('bench_name', 'Standard Index')
        holdings = item.get('holdings', {'qty': 0, 'avg_price': 0})        
        
        # 1. HEADER & DASHBOARD
        self.logger.info(self.double_line)
        self.logger.info(f" 🔍 {name} ({ticker}) vs {b_name} ({b_ticker}) | 감사기준일: {market_date}")        
        self.logger.info(self.line)

        # [홀딩 정보] 수익률 계산: ((현재가 - 평단가) / 평단가) * 100
        if holdings.get('qty', 0) > 0:
            qty = holdings['qty']
            avg_p = holdings['avg_price']
            curr_p = latest.get('Close', 0)
            profit_pct = ((curr_p - avg_p) / avg_p) * 100
            self.logger.info(f" 💰 [HOLDING INFO] Qty: {qty:,} | Avg: ${avg_p:.2f} | Return: {profit_pct:+.2f}%")

        delta_str = self._get_delta_str(score, prev_score)
        lvl = self._get_lvl(score)
        # 2. [신규 호출] 레벨에 따른 이모지 라벨 획득
        lvl_label = self._get_label_with_emoji(lvl)

        # 매크로 수치 매핑 (details에서 추출)
        vix = details.get('vix', 'N/A')
        dxy = details.get('dxy', 'N/A')
        us10y = details.get('us10y', 'N/A')
        
        # [REPORT VERDICT] 결론 라인
        self.logger.info(f" 🚩 [REPORT VERDICT] RISK SCORE: {score} 점 {delta_str} | {lvl_label} (LEVEL {lvl})")        
        
        # [MARKET WEATHER] 매크로 기상도
        self.logger.info(f" 🌐 [MARKET WEATHER] VIX: {vix} | DXY: {dxy} | US10Y: {us10y}%")
        # [TACTICAL DATA] 현황 (가격 및 이격도)
        p_str = self._fmt_money(latest.get('Close', 0), ticker)
        disp = latest.get('disp120', 100.0)
        self.logger.info(f" 🎯 [TACTICAL DATA]  Price: {p_str:10} | 120MA Disp: {disp:.1f}%")
        # [TREND CONFIRM] 리버모어 상태
        self.logger.info(f" 🛡️ [TREND CONFIRM] LIVERMORE: {details.get('liv_status', 'N/A')}")
        self.logger.info(self.double_line)

        # 2. PART 1/2/3 상세 분석 (생략...)
        self._print_p1_table_aligned(ticker, latest, bench_latest, b_ticker)
        self.logger.info(f" ▶ 진단: {details.get('v1_comment', 'N/A')}")
        self.logger.info(self.line)

        self._print_p2_energy_comparative(ticker, latest, bench_latest, details, b_ticker)
        self.logger.info(f" ▶ 진단: {details.get('v2_comment', 'N/A')}")
        self.logger.info(self.line)

        self._print_p3_trend_with_gap(latest, details, bench_latest, b_ticker)
        self.logger.info(f" ▶ 진단: {details.get('v4_comment', 'N/A')}")
        self.logger.info(self.line)

        # 3. FINAL VERDICT (전술지표와 집행지침 출력)
        self._print_final_verdict_left_full(score, prev_score, details, alloc, bt_res, name, ticker)

    def _print_final_verdict_left_full(self, score, prev_score, details, alloc, bt_res, name, ticker):
        """[v9.6.0] 하단 결론부: 전술지표(Stop/EI/Weight)와 집행지침 분리"""
        delta = self._get_delta_str(score, prev_score)
        self.logger.info(f" 🚩 [FINAL INTEGRATED RISK SCORE] : {score} 점 {delta}")
        self.logger.info(self.line)
        
        p1, p2, p4 = details.get('p1_ema', 0), details.get('p2_ema', 0), details.get('p4_ema', 0)
        p1r, p2r, p4r = details.get('p1', 0), details.get('p2', 0), details.get('p4', 0)
        
        mult = details.get('multiplier', 1.0)
        liv_disc = (1 - details.get('liv_discount', 0)) * 100
        
        self.logger.info(f" 산출근거 : [위치 {p1}(Raw:{p1r}) + 에너지 {p2}(Raw:{p2r}) + 저항 {p4}(Raw:{p4r})] × 가중치 {mult:.2f} × 할인 {liv_disc:.0f}%")        
        self.logger.info(f" 백테스트 : {name} 기준 기대MDD {bt_res.get('avg_mdd', 0.0)}% | 평균회복 {bt_res.get('avg_days', 0)}일")
        
        # [핵심 수정] 전술지표 라인으로 데이터 통합
        stop_str = self._fmt_money(alloc.get('stop_loss', 0), ticker)
        weight = alloc.get('weight', 0.0)
        ei = alloc.get('ei', 0.0)
        self.logger.info(f" 전술지표 : Stop Loss: {stop_str:10} | Invest E.I: {ei:<5} | 권고비중: {weight}%")
        
        # 집행지침은 순수하게 SOP 액션만 출력
        self.logger.info(f" 집행지침 : LEVEL {self._get_lvl(score)} - {details.get('action', 'N/A')}")
        self.logger.info(self.double_line + "\n")

    def _print_p2_energy_comparative(self, ticker, latest, bench_latest, details, b_ticker):
        """[개선] 종목과 지수의 RSI를 나란히 배치하여 에너지 강도 대조"""
        self.logger.info(f" [PART 2. 수급 에너지 분석]")
        self.logger.info(self.line) # <--- 추가

        bbw = latest.get('bbw', 0)
        thr = details.get('bbw_thr', 0.3)
        mfi, rsi = latest.get('MFI', 50), latest.get('RSI', 50)
        macd_h = details.get('macd_h', 0.0)

        # [개선 포인트] 수치 옆에 바로 해석을 병기하여 직관성 극대화
        mfi_label = "과열🚨" if mfi > 70 else "심해📉" if mfi < 30 else "안정"
        rsi_label = "과열🚨" if rsi > 70 else "침체📉" if rsi < 30 else "적정"
        macd_label = "상승가속" if macd_h > 0 else "하락가속"
        
        # RiskEngine에서 계산된 통합 진단 결과 가져오기 (없을 시 즉석 계산)
        supply_conclusion, risk_hint = self.engine._get_supply_intelligence(mfi, rsi)

        self.logger.info(f" ▶ {ticker:^10} | 변동성[BBW]: {bbw:.4f} (임계: {thr:.2f}) -> {details.get('vol_label', 'STABLE')}")
        self.logger.info(f"              | 자금흐름[MFI]: {mfi:>4.1f} ({mfi_label}) | 탄력[RSI]: {rsi:>4.1f} ({rsi_label})")
        self.logger.info(f"              | 에너지 힌트: {risk_hint} | 추세엔진[MACD]: {macd_h:>8.4f} ({macd_label})")
        self.logger.info(f"              | 수급 진단 : {supply_conclusion}")
        
        if bench_latest is not None:
            b_mfi = bench_latest.get('MFI', 50); b_rsi = bench_latest.get('RSI', 50)
            self.logger.info(f" ▷ {b_ticker:^10} | 에너지 대조: MFI({b_mfi:.1f}) RSI({b_rsi:.1f}) | MACD Hist: {details.get('bench_macd_h', 0.0):>8.4f}")

    def _print_p3_trend_with_gap(self, latest, details, bench_latest, b_ticker):
        """[v9.6.9] David's Signature Layout: 직관적 지표 해설 도입"""
        self.logger.info(f" [PART 3. 추세 성격 및 구조적 저항]")
        self.logger.info(self.line)
        
        # 1. 120일선 추세 상태 (Rising/Falling)
        ma_status = details.get('ma_status', 'N/A')
        ma_desc = "120MA 우상향" if ma_status == "Rising" else "120MA 우하향"
        ma_emoji = "✅" if ma_status == "Rising" else "⚠️"
        
        # 2. R2 (방향성/신뢰도) 해설
        r2 = latest.get('R2', 0)
        if r2 >= 0.85: r2_label = "매우 직선적"
        elif r2 >= 0.60: r2_label = "안정적 추세"
        else: r2_label = "방향성 모호"
        
        # 3. ADX (관성/에너지) 해설
        adx = latest.get('ADX', 0)
        adx_label = "추세 관성 강력" if adx >= 25 else "추세 약화/횡보"
        
        # 4. 이격도 및 임계치
        disp = latest.get('disp120', 100.0)
        limit = latest.get('disp120_limit', 115.0)
        trap_diag = "✅ SAFE" if disp <= limit else "🚨 ALERT (과이격)"
        
        # [최종 출력] David님의 익숙한 포맷으로 구성
        disc = details.get('discrepancy', 0.0)
        self.logger.info(f" ▶ 추세신뢰 : {ma_emoji} {ma_status} [{ma_desc}]")
        self.logger.info(f" ▶ 신뢰/관성 : R2({r2:.2f}) [{r2_label}] | ADX({adx:.1f}) [{adx_label}]")
        self.logger.info(f" ▶ 구조저항 : 120MA 이격도 {disp:.1f}% (Limit: {limit:.1f}% 이하) | 상태: {trap_diag}")
        self.logger.info(f"             (지수 대비 추세 괴리: {disc:>+4.1f})")

    def _print_p1_table_aligned(self, ticker, latest, bench_latest, b_ticker):
        """
        [v9.5.4 Precision Alignment]
        - 모든 컬럼 너비를 고정하여 세로선(|)과 구분선(+)을 수직으로 일치시킴
        - 이모지 포함 시 정렬 흐트러짐 최소화 로직 적용
        """
        self.logger.info(f" [PART 1. 통계적 위치 분석]")
        self.logger.info(self.line)
        
        # 1. 컬럼 너비 정의 (Dash 개수와 정확히 일치시켜야 함)
        W_PRD, W_TGT, W_BCH, W_ST, W_CMT = 10, 25, 25, 10, 18
        
        # 2. 헤더 생성 (양끝 공백 없이 너비에 맞게 배치)
        h_period  = f"{'PERIOD':^{W_PRD}}"
        h_target  = f"{f'SIGMA ({ticker})':^{W_TGT}}"
        h_bench   = f"{f'SIGMA ({b_ticker})':^{W_BCH}}"
        h_status  = f"{'상태':^{W_ST}}"
        
        # 3. 구분선 생성 (Dash와 + 기호의 조합)
        # 각 구간의 대시(-) 개수를 컬럼 너비와 1:1로 매칭
        inner_sep = "-"*W_PRD + "+" + "-"*W_TGT + "+" + "-"*W_BCH + "+" + "-"*W_ST + "+" + "-"*W_CMT
        
        # 헤더 출력
        self.logger.info(f" {h_period}|{h_target}|{h_bench}|{h_status}|  통계적 해설")
        self.logger.info(f" {inner_sep}")
        
        comments = ["1y 변동성 범위", "2y 변동성 범위", "3y 주기 분석", "4y 장기 추세", "5y 역사적 고점"]
        
        # 4. 데이터 행 출력
        for i, y in enumerate(range(1, 6)):
            s_t = latest.get(f'sig_{y}y', 0.0)
            s_b_raw = bench_latest.get(f'sig_{y}y') if bench_latest is not None else None
            
            # 수치 포맷팅 (부호 포함 우측 정렬 후 중앙 배치)
            val_t_str = f"{float(s_t):>+10.2f}σ"
            val_b_str = f"{float(s_b_raw):>+10.2f}σ" if s_b_raw is not None else "N/A"
            
            # 셀 데이터 중앙 정렬
            c_period = f"{y}y".center(W_PRD)
            c_target = val_t_str.center(W_TGT)
            c_bench  = val_b_str.center(W_BCH)
            
            # 상태 라벨 및 이모지 보정 (광기/과열 등 텍스트 길이에 따른 미세 조정)
            label_text = "광기🚨" if s_t > 2.5 else "과열⚠️" if s_t > 1.5 else "정상"
            c_status = label_text.center(W_ST)
            
            # 행 조합 및 출력 (각 세로선 앞에 추가 공백 없이 규격 준수)
            self.logger.info(f" {c_period}|{c_target}|{c_bench}|{c_status}|  {comments[i]}")

        self.logger.info(self.line)

    """
    [Program 설명]
    1. 수치 우측 정렬(Right Alignment): 가격, 점수, 손절가, 비중 등 숫자는 모두 우측으로 정렬하여 자릿수를 맞췄습니다.
    2. 통화/단위 통일: ₩와 $ 기호를 숫자 앞에 붙이되, 전체 폭 내에서 우측 정렬되어 자릿수가 흐트러지지 않게 합니다.
    3. 헤더-본문 1:1 매칭: 헤더 역시 본문과 동일한 폭 계산 함수를 통과시켜 구분선(|)의 위치를 완벽히 일치시켰습니다.
    """

    def print_audit_summary_table(self, audit_results):
        if not audit_results:
            self.logger.warning("📊 요약할 감사 결과가 없습니다.")
            return

        df = pd.DataFrame(audit_results)
        df = df.sort_values(by='score', ascending=False)

        # [CPA 정밀 규격] 각 칼럼의 고정 너비 설정
        W = {
            'rank': 4, 'name': 20, 'ticker': 12, 'price': 15,
            'score': 16, 'action': 28, 'ei': 8, 'stop': 15, 'weight': 10
        }

        self.logger.info("="*165)
        self.logger.info(f" 📑 [TOTAL AUDIT SUMMARY] 총 {len(df)}개 종목 전수 감사 결과 요약")
        self.logger.info("-" * 165)
        
        # 1. 헤더 출력 (본문과 100% 동일한 패딩 로직 적용)
        header = (
            f"{self._pad_visual('Rank', W['rank'], 'center')} | "
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
        self.logger.info("-" * 165)

        # 2. 데이터 로우 출력
        for i, (_, row) in enumerate(df.iterrows(), 1):
            ticker = str(row['ticker'])
            is_krw = ticker.endswith(".KS")
            unit = "₩" if is_krw else "$"
            
            # 수치 포맷팅 (지수 표기 방지 및 자릿수 고정)
            p_val = float(row.get('price', 0))
            s_val = float(row.get('stop', 0))
            curr_p = f"{unit}{p_val:,.0f}" if is_krw else f"{unit}{p_val:,.2f}"
            stop_p = f"{unit}{s_val:,.0f}" if is_krw else f"{unit}{s_val:,.1f}"
            
            delta = float(row.get('delta', 0.0))
            score_str = f"{float(row['score']):.1f} ({delta:>+4.1f})"
            
            # Action 메시지 (이모지 포함 폭 계산)
            lvl = self._get_lvl(row['score'])
            emoji = self._get_label_with_emoji(lvl).split()[0]
            action_brief = str(row.get('action_text', '관망')).split(':')[0]
            action_display = f"{emoji} LEVEL {lvl} - {action_brief}"

            # 최종 라인 조립
            line = (
                f"{self._pad_visual(i, W['rank'], 'center')} | "
                f"{self._truncate_and_pad_visual(row.get('name', ticker), W['name'])} | "
                f"{self._pad_visual(ticker, W['ticker'])} | "
                f"{self._pad_visual(curr_p, W['price'], 'right')} | "
                f"{self._pad_visual(score_str, W['score'], 'right')} | "
                f"{self._truncate_and_pad_visual(action_display, W['action'])} | "
                f"{self._pad_visual(f"{float(row.get('ei', 0)):.2f}", W['ei'], 'center')} | "
                f"{self._pad_visual(stop_p, W['stop'], 'right')} | "
                f"{self._pad_visual(f"{float(row['weight']):.1f}%", W['weight'], 'right')}"
            )
            self.logger.info(line)

        self.logger.info("=" * 165 + "\n")

    def _get_visual_width(self, text):
        """[v9.9.9] David's Unicode Width Logic: 한글(W,F)은 2칸, 나머지는 1칸"""
        if not text: return 0
        text = str(text)
        width = 0
        for char in text:
            if unicodedata.east_asian_width(char) in ('W', 'F'):
                width += 2
            else:
                width += 1
        return width

    def _pad_visual(self, text, length, align='left'):
        """시각적 폭 기준 정렬 패딩 (좌/우/중앙 지원)"""
        text = str(text)
        padding = max(0, length - self._get_visual_width(text))
        if align == 'right':
            return (" " * padding) + text
        elif align == 'center':
            left = padding // 2
            right = padding - left
            return (" " * left) + text + (" " * right)
        return text + (" " * padding)

    def _truncate_and_pad_visual(self, text, length):
        """시각적 폭 기준 자르기 및 패딩"""
        if self._get_visual_width(text) <= length:
            return self._pad_visual(text, length)
        res, width = "", 0
        for char in text:
            w = 2 if ord('가') <= ord(char) <= ord('힣') or ord(char) > 0x2000 else 1
            if width + w > length - 2:
                return self._pad_visual(res + "..", length)
            res += char
            width += w
        return self._pad_visual(res, length)
    
    """
    [Program 설명]
    1. 통화 감지: 티커의 접미사(.KS)를 확인하여 원화(₩)와 달러($) 기호를 자동으로 부착합니다.
    2. 가격 삽입: 신규 등록 및 리스크 변동 메시지의 종목명 바로 옆에 현재가를 괄호 형식으로 추가합니다.
    3. 가독성 유지: 텔레그램의 <b> 태그를 활용하여 가격 정보가 묻히지 않도록 강조합니다.
    """

    def build_delta_alert_msg(self, data):
        """[v9.9.9] 통화 기호와 현재가가 포함된 델타 알림"""
        score = data['score']
        prev_score = data.get('prev_score')
        name = data.get('name', data['ticker'])
        ticker = data['ticker']
        
        # 통화 설정
        is_krw = ticker.endswith(".KS")
        unit = "₩" if is_krw else "$"
        p_val = data.get('price', 0)
        curr_p_str = f"{unit}{p_val:,.0f}" if is_krw else f"{unit}{p_val:,.2f}"
        
        lvl = self._get_lvl(score)
        emoji = self._get_label_with_emoji(lvl).split()[0]
        
        # 신규 종목 등록 케이스
        if prev_score is None:
            return f"{emoji} <b>{name} ({ticker})</b> 🆕 [<b>{curr_p_str}</b>]\n" \
                   f"상태: <b>LEVEL {lvl}</b> ({score:.1f}점)\n" \
                   f"지침: <code>{data.get('action_text', '분석 중')}</code>\n\n"

        # 리스크 변동 케이스
        diff = score - prev_score
        if abs(diff) >= 5.0:
            trend_icon = "📈 리스크 급증" if diff > 0 else "📉 리스크 완화"
            return f"{emoji} <b>{name} ({ticker})</b> ⚠️ [<b>{curr_p_str}</b>] {trend_icon}\n" \
                   f"변동: <code>{prev_score:.1f}</code> → <b>{score:.1f}</b>\n" \
                   f"지침: <i>{data.get('action_text', '지침 확인 필요')}</i>\n\n"
        return ""

    def assemble_delta_alerts(self, new_stocks, risk_up, risk_down):
        """카테고리별 알림 메시지를 통합"""
        if not (new_stocks or risk_up or risk_down): return ""
        
        now_date = datetime.now().strftime("%Y-%m-%d")
        body = f"🛡️ <b>[Sigma Guard Alert] {now_date}</b>\n"
        body += "━━━━━━━━━━━━━\n\n"
        
        if new_stocks: body += "✨ <b>[신규 분석 종목]</b>\n" + "".join(new_stocks) + "---\n\n"
        if risk_up:    body += "🚨 <b>[SOP 레벨 상승]</b>\n" + "".join(risk_up) + "---\n\n"
        if risk_down:  body += "✅ <b>[SOP 레벨 완화]</b>\n" + "".join(risk_down) + "---\n\n"
        return body
    
    def build_weekly_dashboard(self, audit_results):
        """[v9.9.9] Mobile-Slim: 헤더를 제거하고 가시성을 극대화한 대시보드"""
        if not audit_results: return ""

        sorted_res = sorted(audit_results, key=lambda x: x['score'], reverse=True)
        # 모바일 화면 폭을 고려하여 구분선 길이를 최적화
        SHORT_LINE = "────────────"
        
        msg = f"📊 <b>[Weekly Audit Dashboard]</b>\n"
        msg += f"{SHORT_LINE}\n"
        # [CPA 보정] 모바일 시독성을 위해 복잡한 헤더 행은 과감히 생략합니다.
        
        for res in sorted_res:
            lvl = self._get_lvl(res['score'])
            emoji = self._get_label_with_emoji(lvl).split()[0]
            ticker = res['ticker']
            
            # 1. 종목명 8자(폭 16) 정렬 유지
            d_name = self._truncate_and_pad_visual(res.get('name', ticker), 16)
            
            # 2. 통화 기호 포함 가격 포맷팅 [cite: 2026-01-23]
            is_krw = ticker.endswith(".KS")
            unit = "₩" if is_krw else "$"
            p_val = float(res.get('price', 0))
            
            if is_krw:
                # 한국 종목: ₩159k 형태
                p_str = f"{unit}{p_val:,.0f}"
            else:
                # 미국 종목: $45.2 형태
                p_str = f"{unit}{p_val:,.1f}"
            
            # 가격 컬럼을 우측 정렬 (폭 8자)
            p_display = self._pad_visual(p_str, 12, align='right')
            
            # 3. 핵심 실행 지침 (SOP 9단계)
            raw_action = str(res.get('action_text', '관망'))
            action_brief = raw_action.split(':')[0].split('-')[-1].strip()
            
            # 본문 구성 (가독성을 위해 파이프 기호 '|' 위치 유지)
            msg += f"{emoji} <code>{d_name} | {p_display} | {action_brief}</code>\n"

        msg += f"{SHORT_LINE}\n"
        msg += "💡 <i>David SOP 9단계 기준 보고입니다.</i>"
        return msg

    # ... (_get_lvl, _fmt_money 등 헬퍼 메서드는 기존 유지)
    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------
    def _get_label(self, s):
        if s >= 81: return "DANGER"
        if s >= 66: return "WARNING"
        if s >= 46: return "WATCH"
        return "NORMAL"

    def _get_lvl(self, s):
        """[v9.7.0 Sync] 9단계 시각화 대응"""
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
        """레벨별 직관적 이모지 적용"""
        emojis = {
            9: "🚫 EXIT", 8: "🚨 DANGER", 7: "🔴 WARNING", 6: "🟠 CAUTION",
            5: "🟡 WATCH", 4: "🔵 ENTRY", 3: "🟢 ACCUMULATE", 2: "💎 CONCENTRATE", 1: "🔥 FULL"
        }
        return emojis.get(lvl, "N/A")

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