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


def get_japan_stop_high():
    """
    株探の上昇率/ストップ高テーブルから、コード・社名・市場・株価・前日比を正確に抽出
    """
    url = "https://kabutan.jp/warning/?mode=2_1"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    stop_high_list = []
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.encoding = response.apparent_encoding
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")
            table = soup.find("table", class_="stock_table")
            
            if table:
                tbody = table.find("tbody")
                rows = tbody.find_all("tr") if tbody else table.find_all("tr")[1:]
                
                for row in rows:
                    # コード: 最初の td (class="tac")
                    first_td = row.find("td")
                    if not first_td:
                        continue
                    code = first_td.text.strip()
                    
                    # 社名: th タグ (scope="row" class="tal")
                    th_name = row.find("th")
                    name = th_name.text.strip() if th_name else ""
                    
                    # 全tdを取得して市場や株価を拾う
                    tds = row.find_all("td")
                    market = tds[1].text.strip() if len(tds) > 1 else ""
                    price = tds[4].text.strip() if len(tds) > 4 else ""
                    change = tds[5].text.strip() if len(tds) > 5 else ""
                    
                    stop_high_list.append({
                        "code": code,
                        "name": name,
                        "market": market,
                        "price": price,
                        "change": change
                    })
    except Exception as e:
        print(f"株探スクレイピングエラー: {e}")
        
    return stop_high_list


def main():
    require_settings("DIFY_API_KEY")
    print("データ収集中...")
    
    us_data = get_us_market_data()
    jp_data = get_japan_stop_high()
    
    payload = {
        "us_market": us_data,
        "japan_market": {
            "stop_high_count": len(jp_data),
            "stop_high_stocks": jp_data[:10]
        }
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
