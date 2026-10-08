import os
import argparse
import sys
import json
import requests
from datetime import datetime
import yfinance as yf
from settings import BASE_DIR, get_setting, require_settings, today_jst

# ==========================================
# API 設定
# ==========================================
# 1. ナレッジ更新用（Dataset API）
DATASET_API_KEY = get_setting("DATASET_API_KEY")
DATASET_ID = get_setting("DATASET_ID")
DIFY_DATASET_URL = f"https://api.dify.ai/v1/datasets/{DATASET_ID}/document/create_by_text"

# 2. 答え合わせ推論用（朝のチャットフローAPIキー）
DIFY_APP_API_KEY = get_setting("DIFY_APP_API_KEY", get_setting("DIFY_API_KEY"))
DIFY_CHAT_URL = "https://api.dify.ai/v1/chat-messages"


def load_morning_context():
    """
    朝生成したブリーフと市場データJSONを読み込む
    """
    brief_text = ""
    if (BASE_DIR / "morning_brief_latest.md").exists():
        with open(BASE_DIR / "morning_brief_latest.md", "r", encoding="utf-8") as f:
            brief_text = f.read()

    summary_data = {}
    if (BASE_DIR / "market_summary.json").exists():
        with open(BASE_DIR / "market_summary.json", "r", encoding="utf-8") as f:
            summary_data = json.load(f)

    return brief_text, summary_data


def fetch_evening_actual_results(summary_data):
    """
    夕方の日経平均および朝注目銘柄の引け値・騰落を自動取得
    """
    print("\n[1/3] 夕方の市場実績データを収集中...")
    results = {}

    # 日経平均（^N225）
    try:
        n225 = yf.Ticker("^N225")
        h = n225.history(period="2d")
        if len(h) >= 2:
            c = float(h["Close"].iloc[-1])
            prev = float(h["Close"].iloc[-2])
            pct = round(((c - prev) / prev) * 100, 2)
            results["nikkei225"] = {"close": round(c, 2), "change_pct": pct}
    except Exception as e:
        results["nikkei225"] = {"error": str(e)}

    # 朝の注目銘柄
    stocks = summary_data.get("japan_market", {}).get("stop_high_stocks", [])[:5]
    stock_results = []
    for s in stocks:
        code = str(s.get("code", "")).strip()
        name = s.get("name", "")
        if len(code) != 4 or not code.isascii() or not code.isalnum():
            stock_results.append({"code": code, "name": name, "error": "銘柄コードの形式を確認できません"})
            continue

        market = str(s.get("market", "")).strip()
        if not market.startswith("東"):
            reason = f"市場 '{market}' は東証用の .T で取得できないためスキップ"
            print(f"取得スキップ: {code} {name}（{reason}）")
            stock_results.append({"code": code, "name": name, "market": market, "error": reason})
            continue

        ticker_sym = f"{code}.T"
        try:
            t = yf.Ticker(ticker_sym)
            hist = t.history(period="2d")
            if len(hist) >= 2:
                close = float(hist["Close"].iloc[-1])
                prev = float(hist["Close"].iloc[-2])
                high = float(hist["High"].iloc[-1])
                low = float(hist["Low"].iloc[-1])
                pct = round(((close - prev) / prev) * 100, 2)
                stock_results.append({
                    "code": code,
                    "name": name,
                    "open": round(float(hist["Open"].iloc[-1]), 2),
                    "close": round(close, 2),
                    "high": round(high, 2),
                    "low": round(low, 2),
                    "change_pct": pct
                })
            else:
                stock_results.append({"code": code, "name": name, "error": "前日比の計算に必要な2日分のデータがありません"})
        except Exception as e:
            stock_results.append({"code": code, "name": name, "error": str(e)})

    results["monitored_stocks"] = stock_results
    return results


def generate_review_with_llm(brief_text, actual_data, manual_notes, summary_data):
    """
    Dify LLMに投げて「朝の予測」vs「夕方の実績」の自動答え合わせ＆教訓Markdownを生成
    """
    print("\n[2/3] AIによる答え合わせ・教訓レポートを生成中...")
    headers = {
        "Authorization": f"Bearer {DIFY_APP_API_KEY.strip()}",
        "Content-Type": "application/json"
    }

    verification_query = f"""
本日の大引け後の検証・教訓レポートを作成してください。

### 朝の投資戦略ブリーフ（前提）
{brief_text}

### 大引け後の市場実績データ
{json.dumps(actual_data, ensure_ascii=False, indent=2)}

### トレーダーの手動気づきメモ
{manual_notes if manual_notes else "（特になし）"}

---
### 指示
上記に基づき、朝の想定シナリオがどう機能したか、乖離はどうだったかを検証し、以下のMarkdown構成で出力してください。
取得エラーのある銘柄は検証対象外と明記し、価格や値動きを推測しないでください。
日足の始値・高値・安値・終値だけでは高値や安値を付けた順序は分かりません。寄り天や午後の値動きを断定しないでください。

# 相場答え合わせと教訓: {today_jst()}

## 1. 朝の想定シナリオと実際の結果（答え合わせ）
- 指数・マクロの動向と乖離
- 朝注目銘柄の推移（寄り天・続伸など）

## 2. 実戦メモ・気づき
（メモがあればその詳細、なければ当日の地合いの特徴）

## 3. 次回以降に活かす相場教訓・セオリー
- 具体的な教訓を箇条書きで整理
"""

    # market_data が必須入力のため、JSON文字列を渡す
    payload = {
        "inputs": {
            "market_data": json.dumps(summary_data, ensure_ascii=False)
        },
        "query": verification_query,
        "response_mode": "blocking",
        "user": "master_trader_verify"
    }

    try:
        res = requests.post(DIFY_CHAT_URL, headers=headers, json=payload, timeout=90)
        if res.status_code == 200:
            return res.json().get("answer", "")
        else:
            print(f"LLMエラー (HTTP {res.status_code}): {res.text}")
            return None
    except Exception as e:
        print(f"通信エラー: {e}")
        return None


def upload_learning_to_dify(today_str, content):
    """
    Dify Dataset APIを使ってナレッジにテキストドキュメントを追加
    """
    print(f"\n[3/3] Difyナレッジ（{DATASET_ID}）へ教訓を送信中...")
    headers = {
        "Authorization": f"Bearer {DATASET_API_KEY.strip()}",
        "Content-Type": "application/json"
    }

    payload = {
        "name": f"相場教訓_{today_str}.md",
        "text": content,
        "indexing_technique": "high_quality",
        "process_rule": {
            "mode": "automatic"
        }
    }

    response = requests.post(DIFY_DATASET_URL, headers=headers, json=payload, timeout=60)

    if response.status_code in [200, 201]:
        print("✅ Difyナレッジへの自動追加に成功しました！")
        res_json = response.json()
        print(f"ドキュメントID: {res_json.get('document', {}).get('id')}")
    else:
        print(f"❌ 追加エラー: HTTP {response.status_code}")
        print(response.text)
        raise RuntimeError(f"Dify Dataset upload failed: HTTP {response.status_code}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--notes", default="")
    args = parser.parse_args()
    require_settings("DATASET_API_KEY", "DATASET_ID")
    if not DIFY_APP_API_KEY:
        raise RuntimeError("DIFY_API_KEY or DIFY_APP_API_KEY is required")
    if args.non_interactive:
        metadata = json.loads((BASE_DIR / "morning_context.json").read_text(encoding="utf-8"))
        if metadata.get("date_jst") != today_jst():
            raise RuntimeError("Today's morning data is required")
    print("=== [夕方] 相場答え合わせ＆ナレッジ自動蓄積 ===")
    brief_text, summary_data = load_morning_context()

    if not brief_text:
        print("エラー: 'morning_brief_latest.md' が見つかりません。")
        raise RuntimeError("morning_brief_latest.md is missing or empty")
    if not summary_data:
        raise RuntimeError("market_summary.json is missing or empty")

    # 1. 夕方の実績を自動取得
    actual_data = fetch_evening_actual_results(summary_data)

    # 2. 手動メモ入力（Enterでスキップ可）
    notes = args.notes
    if not args.non_interactive and sys.stdin.isatty() and not notes:
        notes = input("\n手動メモ・気づきがあれば入力（Enterでスキップ）: ")

    # 3. LLMで自動答え合わせレポート生成
    reviewed_doc = generate_review_with_llm(brief_text, actual_data, notes, summary_data)

    today_str = today_jst()

    if not reviewed_doc:
        raise RuntimeError("AI review generation failed; knowledge upload stopped")

    print("\n" + "=" * 50)
    print("📝 生成された答え合わせ＆教訓レポート")
    print("=" * 50)
    print(reviewed_doc)
    (BASE_DIR / f"evening_review_{today_str}.md").write_text(reviewed_doc, encoding="utf-8")

    # 4. Difyナレッジへ自動POST
    upload_learning_to_dify(today_str, reviewed_doc)


if __name__ == "__main__":
    main()
