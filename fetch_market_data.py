import json
import requests
from bs4 import BeautifulSoup
import yfinance as yf
from settings import BASE_DIR, get_setting, require_settings, today_jst

DIFY_API_KEY = get_setting("DIFY_API_KEY")
DIFY_API_URL = "https://api.dify.ai/v1/chat-messages"


def run_dify_morning_brief(market_data_dict):
    """
    収集した市場データJSONをDifyのチャットフローAPIに送信し、
    生成された投資ブリーフをコンソールに表示・ファイル保存する
    """
    if not DIFY_API_KEY or not DIFY_API_KEY.startswith("app-"):
        print("DIFY_API_KEY を設定すると、投資ブリーフを生成できます。")
        raise RuntimeError("DIFY_API_KEY is not configured")

    headers = {
        "Authorization": f"Bearer {DIFY_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "inputs": {
            "market_data": json.dumps(market_data_dict, ensure_ascii=False, indent=2)
        },
        "query": "ブリーフを作成して",
        "response_mode": "blocking",
        "user": "master_trader"
    }

    print("Dify APIへデータを送信中...")
    try:
        response = requests.post(DIFY_API_URL, headers=headers, json=payload, timeout=60)
    except requests.RequestException as e:
        print(f"Dify API通信エラー: {e}")
        raise RuntimeError("Dify API request failed") from e

    if response.status_code == 200:
        try:
            result = response.json()
        except ValueError:
            print("Dify APIの応答をJSONとして読み取れませんでした。")
            raise RuntimeError("Dify returned invalid JSON")
        brief_text = result.get("answer", "")
        if not isinstance(brief_text, str) or not brief_text.strip():
            raise RuntimeError("Dify returned an empty answer")
        print("\n=== 朝の投資戦略ブリーフ（自動生成完了）===\n")
        print(brief_text)

        with open(BASE_DIR / "morning_brief_latest.md", "w", encoding="utf-8") as f:
            f.write(brief_text)
        print("\n--> morning_brief_latest.md に保存しました。")
    else:
        print(f"エラー発生: {response.status_code}")
        print(response.text)
        raise RuntimeError(f"Dify API failed: HTTP {response.status_code}")


def get_us_market_data():
    """
    yfinanceを使って米国主要指標を取得し、前日比（%）等を計算
    """
    tickers = {
        "^GSPC": "sp500",      # S&P 500
        "^SOX": "sox",          # フィラデルフィア半導体株指数
        "^VIX": "vix",          # 恐怖指数
        "^TNX": "us10y",        # 米10年債利回り
        "JPY=X": "usdjpy"       # ドル円為替
    }
    
    result = {}
    
    for symbol, name in tickers.items():
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="5d")
            
            if len(hist) >= 2:
                latest_close = float(hist["Close"].iloc[-1])
                prev_close = float(hist["Close"].iloc[-2])
                change_pct = round(((latest_close - prev_close) / prev_close) * 100, 2)
                
                result[name] = {
                    "latest": round(latest_close, 2),
                    "change_pct": change_pct
                }
            elif len(hist) == 1:
                result[name] = {
                    "latest": round(float(hist["Close"].iloc[-1]), 2),
                    "change_pct": 0.0
                }
        except Exception as e:
            result[name] = {"error": str(e)}
            
    return result


STOP_HIGH_URL = "https://s.kabutan.jp/warnings/price_limit_up/"


def parse_japan_stop_high(html):
    """Parse only the public price-limit-up table; never disguise errors as zero."""
    import re
    from datetime import datetime

    soup = BeautifulSoup(html, "html.parser")
    heading = soup.find("h1")
    if not heading or "ストップ高銘柄" not in heading.get_text():
        raise RuntimeError("Kabutan stop-high page title is missing")
    stamp = re.search(
        r"株価[：:]\s*(\d{4})年(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})現在",
        soup.get_text(" ", strip=True),
    )
    if not stamp:
        raise RuntimeError("Kabutan quote date is missing")
    quote_date = datetime(*map(int, stamp.groups()[:3])).date()
    today = datetime.strptime(today_jst(), "%Y-%m-%d").date()
    if quote_date > today or (today - quote_date).days > 7:
        raise RuntimeError(f"Kabutan quote date is invalid or stale: {quote_date}")
    table = next(
        (t for t in soup.find_all("table")
         if t.select_one('thead a[href*="order=stock_code"]')),
        None,
    )
    if table is None:
        raise RuntimeError("Kabutan stop-high table is missing")
    stocks = []
    for row in table.select("tbody tr"):
        link = row.select_one('a[href^="/stocks/"]')
        cells = row.find_all("td", recursive=False)
        if not link:
            # Only an explicit no-results row can represent a legitimate empty list.
            if re.search(r"該当.*(?:ありません|ございません)|対象.*ありません", row.get_text()):
                continue
            raise RuntimeError("Unrecognized Kabutan stock row")
        code_match = re.fullmatch(r"/stocks/([0-9A-Z]{4})/", link.get("href", ""))
        name = link.find("p")
        labels = [s.get_text(strip=True) for s in link.find_all("span")]
        if not code_match or name is None or len(cells) < 2 or not labels:
            raise RuntimeError("Kabutan stock row format changed")
        marker = labels[1] if len(labels) > 1 else ""
        stocks.append({
            "code": code_match.group(1),
            "name": name.get_text(" ", strip=True),
            "market": labels[0],
            "price": cells[0].get_text(" ", strip=True),
            "change": cells[1].get_text(" ", strip=True),
            "limit_status": "current_limit_up" if marker == "Ｓ"
                            else "limit_up_quote" if marker in ("Sｹ", "Ｓケ")
                            else "special_buy_quote" if marker == "ケ"
                            else "intraday_limit_up_or_quote",
            "source_marker": marker,
        })
    # Do not trust the page's display-count widget (it can say 0 despite rows).
    if not stocks and not re.search(
        r"該当.*(?:ありません|ございません)|対象.*ありません", table.get_text()
    ):
        raise RuntimeError("Kabutan table is empty without an explicit no-results message")
    if soup.select_one('a[rel="next"]'):
        raise RuntimeError("Kabutan has additional pages; refusing an incomplete count")
    return {
        "stop_high_count": len(stocks),
        "stop_high_stocks": stocks,
        "source_url": STOP_HIGH_URL,
        "source_date_jst": quote_date.isoformat(),
        "source_time_jst": ":".join(stamp.groups()[3:]),
        "data_period": "prior_session" if quote_date < today else "current_session",
        "scope": "ストップ高銘柄（気配・一時ストップ高を含む）。掲載日のデータであり、全銘柄が終値ストップ高とは限りません。",
        "fetch_status": "success",
    }


def get_japan_stop_high():
    response = requests.get(
        STOP_HIGH_URL,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=30,
    )
    response.raise_for_status()
    response.encoding = "utf-8"
    return parse_japan_stop_high(response.text)


def main():
    require_settings("DIFY_API_KEY")
    print("データ収集中...")
    
    us_data = get_us_market_data()
    jp_data = get_japan_stop_high()
    
    payload = {
        "us_market": us_data,
        "japan_market": jp_data
    }
    
    json_output = json.dumps(payload, ensure_ascii=False, indent=2)
    print("\n=== 取得結果 JSON ===")
    print(json_output)
    
    with open(BASE_DIR / "market_summary.json", "w", encoding="utf-8") as f:
        f.write(json_output)
    print("\n-> 'market_summary.json' として保存しました。")
    run_dify_morning_brief(payload)
    (BASE_DIR / "morning_context.json").write_text(
        json.dumps({"date_jst": today_jst()}, indent=2), encoding="utf-8"
    )

if __name__ == "__main__":
    main()
