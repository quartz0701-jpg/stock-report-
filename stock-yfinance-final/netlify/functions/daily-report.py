"""
Netlify Scheduled Function: daily-report
매일 KST 07:00 (= UTC 22:00 전날) 자동 실행
get-stock-data 함수를 호출하여 이메일 발송
"""
import json
import urllib.request
import os

def handler(event, context):
    """Netlify scheduled function — cron: 0 22 * * *"""
    site_url = os.environ.get('URL', 'http://localhost:8888')
    func_url  = f"{site_url}/.netlify/functions/get-stock-data"

    print(f'[daily-report] 자동 실행 → {func_url}')
    try:
        req = urllib.request.Request(
            func_url,
            headers={'Content-Type': 'application/json'},
            method='GET'
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            body = json.loads(r.read())
            print(f"[daily-report] 완료 | 출처:{body.get('price_source')} | 이메일:{body.get('email_sent')}")
            return {'statusCode': 200, 'body': json.dumps({'ok': True})}
    except Exception as e:
        print(f'[daily-report] 오류: {e}')
        return {'statusCode': 500, 'body': json.dumps({'error': str(e)})}
