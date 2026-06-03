"""
Netlify Function: get-stock-data
- yfinance로 실시간 주가 수집
- 실패 시 Claude API web_search 폴백
- 국내/해외 뉴스 각 3개 수집 후 AI 분석
"""
import json
import os
import sys
from datetime import datetime, timezone, timedelta

# ── KST 시간 ──
KST = timezone(timedelta(hours=9))
def kst_now():
    return datetime.now(KST).strftime('%Y-%m-%d %H:%M')
def kst_date():
    return datetime.now(KST).strftime('%Y-%m-%d')

ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
EMAILJS_SERVICE   = os.environ.get('EMAILJS_SERVICE', '')
EMAILJS_TEMPLATE  = os.environ.get('EMAILJS_TEMPLATE', '')
EMAILJS_KEY       = os.environ.get('EMAILJS_PUBLIC_KEY', '')
NOTIFY_EMAIL      = os.environ.get('NOTIFY_EMAIL', '')

TICKERS = {
    'kospi'  : '^KS11',
    'dow'    : '^DJI',
    'samsung': '005930.KS',
    'hynix'  : '000660.KS',
    'nvda'   : 'NVDA',
    'tsla'   : 'TSLA',
    'usdkrw' : 'USDKRW=X',
}

# ── 1. yfinance로 주가 수집 ──
def fetch_prices_yfinance():
    import yfinance as yf
    results = {}
    symbols = list(TICKERS.values())
    try:
        data = yf.download(symbols, period='2d', auto_adjust=True, progress=False, timeout=15)
        close = data['Close']
        for name, sym in TICKERS.items():
            try:
                col = close[sym] if sym in close.columns else close
                prices = col.dropna()
                if len(prices) >= 2:
                    price = round(float(prices.iloc[-1]), 2)
                    prev  = round(float(prices.iloc[-2]), 2)
                    chg   = round((price - prev) / prev * 100, 2)
                    results[name] = {
                        'price': price,
                        'chg'  : f'+{chg}%' if chg >= 0 else f'{chg}%',
                        'date' : str(prices.index[-1].date()),
                        'src'  : 'yfinance',
                    }
                elif len(prices) == 1:
                    results[name] = {
                        'price': round(float(prices.iloc[-1]), 2),
                        'chg'  : '미확인',
                        'date' : str(prices.index[-1].date()),
                        'src'  : 'yfinance',
                    }
                else:
                    results[name] = None
            except Exception:
                results[name] = None
    except Exception as e:
        print(f'[yfinance] 전체 오류: {e}')
        for name in TICKERS:
            results[name] = None
    return results

# ── 2. Claude web_search 폴백 ──
def fetch_prices_claude(missing_names):
    import urllib.request
    today = kst_date()
    needed = ', '.join(missing_names)
    prompt = (
        f"날짜:{today}. 웹검색으로 최신가격 확인. JSON만 출력.\n"
        f"필요항목:{needed}\n"
        '{"kospi_price":"숫자","kospi_chg":"+x.xx%",'
        '"dow_price":"숫자","dow_chg":"+x.xx%",'
        '"samsung_price":"숫자","samsung_chg":"+x.xx%",'
        '"hynix_price":"숫자","hynix_chg":"+x.xx%",'
        '"nvda_price":"숫자","nvda_chg":"+x.xx%",'
        '"tsla_price":"숫자","tsla_chg":"+x.xx%",'
        '"usdkrw":"숫자"}\n'
        '규칙:실제값만.JSON외금지.'
    )
    body = json.dumps({
        'model': 'claude-haiku-4-5-20251001',
        'max_tokens': 600,
        'tools': [{'type': 'web_search_20250305', 'name': 'web_search'}],
        'messages': [{'role': 'user', 'content': prompt}]
    }).encode()
    req = urllib.request.Request(
        'https://api.anthropic.com/v1/messages',
        data=body,
        headers={
            'Content-Type': 'application/json',
            'x-api-key': ANTHROPIC_API_KEY,
            'anthropic-version': '2023-06-01',
        },
        method='POST'
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = json.loads(r.read())
        txt = ''.join(c['text'] for c in resp.get('content', []) if c['type'] == 'text')
        m = __import__('re').search(r'\{[\s\S]*\}', txt.replace('```json','').replace('```',''))
        return json.loads(m.group()) if m else {}
    except Exception as e:
        print(f'[claude_price] 오류: {e}')
        return {}

# ── 3. Claude web_search로 뉴스 수집 + AI 분석 ──
def fetch_news_and_insight(price_summary):
    import urllib.request
    today = kst_date()
    prompt = (
        f"날짜:{today}. 아래 종목의 오늘 뉴스를 검색. JSON만 출력.\n"
        "각 종목 국내뉴스3개+해외뉴스3개 제목+1줄요약. 마지막에 종합인사이트.\n"
        '{"samsung":{"domestic":[{"title":"제목","summary":"1줄요약"},...],"global":[...]},'
        '"hynix":{"domestic":[...],"global":[...]},'
        '"nvda":{"domestic":[...],"global":[...]},'
        '"tsla":{"domestic":[...],"global":[...]},'
        '"market_insight":"전체시황 종합인사이트 **핵심** 볼드 700자이내"}\n'
        '규칙:실제뉴스만.JSON외금지.'
    )
    body = json.dumps({
        'model': 'claude-haiku-4-5-20251001',
        'max_tokens': 2000,
        'tools': [{'type': 'web_search_20250305', 'name': 'web_search'}],
        'messages': [{'role': 'user', 'content': prompt}]
    }).encode()
    req = urllib.request.Request(
        'https://api.anthropic.com/v1/messages',
        data=body,
        headers={
            'Content-Type': 'application/json',
            'x-api-key': ANTHROPIC_API_KEY,
            'anthropic-version': '2023-06-01',
        },
        method='POST'
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            resp = json.loads(r.read())
        txt = ''.join(c['text'] for c in resp.get('content', []) if c['type'] == 'text')
        m = __import__('re').search(r'\{[\s\S]*\}', txt.replace('```json','').replace('```',''))
        return json.loads(m.group()) if m else {}
    except Exception as e:
        print(f'[claude_news] 오류: {e}')
        return {}

# ── 4. EmailJS로 이메일 발송 ──
def send_email(report):
    import urllib.request
    if not all([EMAILJS_SERVICE, EMAILJS_TEMPLATE, EMAILJS_KEY, NOTIFY_EMAIL]):
        print('[email] 설정 없음')
        return False
    
    def fmt(p, unit=''):
        if not p: return '미확인'
        try: return f'{float(p):,.0f}{unit}'
        except: return str(p)
    
    def news_block(data, key):
        d = data.get(key, {})
        lines = []
        for item in d.get('domestic', [])[:3]:
            lines.append(f"[국내] {item.get('title','')} — {item.get('summary','')}")
        for item in d.get('global', [])[:3]:
            lines.append(f"[해외] {item.get('title','')} — {item.get('summary','')}")
        return '\n'.join(lines) if lines else '뉴스 없음'

    news = report.get('news', {})
    body_txt = f"""📅 기준일: {report.get('data_date', kst_date())}  
조회: {report.get('fetched_at', kst_now())}

═══════════════════════════
📈 지수 현황
═══════════════════════════
🇰🇷 KOSPI   : {fmt(report.get('kospi_price'),'pt')}  {report.get('kospi_chg','')}
🇺🇸 DOW     : {fmt(report.get('dow_price'))}  {report.get('dow_chg','')}
💱 원/달러  : {fmt(report.get('usdkrw_price'),'원')}

═══════════════════════════
📊 종목별 주가 ({report.get('price_source','yfinance')})
═══════════════════════════
삼성전자  : {fmt(report.get('samsung_price'),'원')}  {report.get('samsung_chg','')}
SK하이닉스: {fmt(report.get('hynix_price'),'원')}  {report.get('hynix_chg','')}
NVIDIA    : ${report.get('nvda_price','')}  {report.get('nvda_chg','')}
Tesla     : ${report.get('tsla_price','')}  {report.get('tsla_chg','')}

═══════════════════════════
📰 뉴스 요약
═══════════════════════════
[삼성전자]
{news_block(news,'samsung')}

[SK하이닉스]
{news_block(news,'hynix')}

[NVIDIA]
{news_block(news,'nvda')}

[Tesla]
{news_block(news,'tsla')}

═══════════════════════════
🧠 종합 인사이트
═══════════════════════════
{news.get('market_insight','').replace('**','')}

━━━━━━━━━━━━━━━━━━━━━━━━━
본 리포트는 투자 권유가 아닙니다.
데이터 출처: {report.get('price_source','yfinance')}
"""
    payload = json.dumps({
        'service_id'  : EMAILJS_SERVICE,
        'template_id' : EMAILJS_TEMPLATE,
        'user_id'     : EMAILJS_KEY,
        'template_params': {
            'to_email'    : NOTIFY_EMAIL,
            'subject'     : f"[주식시황] {report.get('data_date',kst_date())} | 삼성 {fmt(report.get('samsung_price'),'원')} | NVDA ${report.get('nvda_price','')}",
            'message'     : body_txt,
            'date'        : report.get('data_date', kst_date()),
            'kospi'       : f"{fmt(report.get('kospi_price'),'pt')} {report.get('kospi_chg','')}",
            'dow'         : f"{fmt(report.get('dow_price'))} {report.get('dow_chg','')}",
            'samsung'     : f"{fmt(report.get('samsung_price'),'원')} {report.get('samsung_chg','')}",
            'hynix'       : f"{fmt(report.get('hynix_price'),'원')} {report.get('hynix_chg','')}",
            'nvda'        : f"${report.get('nvda_price','')} {report.get('nvda_chg','')}",
            'tsla'        : f"${report.get('tsla_price','')} {report.get('tsla_chg','')}",
            'usdkrw'      : f"{fmt(report.get('usdkrw_price'),'원')}",
            'insight'     : news.get('market_insight','').replace('**',''),
        }
    }).encode()
    req = urllib.request.Request(
        'https://api.emailjs.com/api/v1.0/email/send',
        data=payload,
        headers={'Content-Type': 'application/json'},
        method='POST'
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            print(f'[email] 발송 성공: {r.status}')
            return True
    except Exception as e:
        print(f'[email] 발송 실패: {e}')
        return False

# ── 메인 핸들러 ──
def handler(event, context):
    try:
        today = kst_date()
        print(f'[start] {kst_now()}')

        # ── 1단계: yfinance 주가 수집 ──
        prices = fetch_prices_yfinance()
        missing = [k for k, v in prices.items() if v is None]
        price_source = 'yfinance'

        # ── 2단계: 실패 항목 Claude 폴백 ──
        if missing:
            print(f'[fallback] Claude web_search for: {missing}')
            fallback = fetch_prices_claude(missing)
            price_source = 'yfinance+websearch' if len(missing) < len(TICKERS) else 'websearch'
            # 폴백 데이터 병합
            for name in missing:
                prices[name] = {
                    'price': fallback.get(f'{name}_price', '미확인'),
                    'chg'  : fallback.get(f'{name}_chg', ''),
                    'date' : today,
                    'src'  : 'websearch',
                }

        # 가격 추출
        def gp(name): return prices.get(name, {}).get('price', '미확인') if isinstance(prices.get(name), dict) else '미확인'
        def gc(name): return prices.get(name, {}).get('chg', '') if isinstance(prices.get(name), dict) else ''
        def gd(name): return prices.get(name, {}).get('date', today) if isinstance(prices.get(name), dict) else today

        # 실제 거래일 (가장 최근 데이터 날짜)
        data_date = gd('samsung') or gd('kospi') or today

        report = {
            'date'          : today,
            'data_date'     : data_date,
            'is_holiday'    : data_date != today,
            'fetched_at'    : kst_now(),
            'price_source'  : price_source,
            'kospi_price'   : gp('kospi'),
            'kospi_chg'     : gc('kospi'),
            'dow_price'     : gp('dow'),
            'dow_chg'       : gc('dow'),
            'samsung_price' : gp('samsung'),
            'samsung_chg'   : gc('samsung'),
            'hynix_price'   : gp('hynix'),
            'hynix_chg'     : gc('hynix'),
            'nvda_price'    : gp('nvda'),
            'nvda_chg'      : gc('nvda'),
            'tsla_price'    : gp('tsla'),
            'tsla_chg'      : gc('tsla'),
            'usdkrw_price'  : gp('usdkrw'),
        }

        # ── 3단계: 뉴스 + 인사이트 ──
        news = fetch_news_and_insight(report)
        report['news'] = news

        # ── 4단계: 이메일 발송 ──
        email_sent = send_email(report)
        report['email_sent'] = email_sent

        print(f'[done] {kst_now()} | source:{price_source}')
        return {
            'statusCode': 200,
            'headers'   : {'Content-Type': 'application/json; charset=utf-8'},
            'body'      : json.dumps(report, ensure_ascii=False),
        }

    except Exception as e:
        print(f'[error] {e}')
        import traceback; traceback.print_exc()
        return {
            'statusCode': 500,
            'headers'   : {'Content-Type': 'application/json'},
            'body'      : json.dumps({'error': str(e)}),
        }
