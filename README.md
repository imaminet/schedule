# 市場ブリーフと夕方の答え合わせ

GitHub Actionsで平日（月〜金）の日本時間 **7:30** に朝のブリーフ、**17:00** に夕方の答え合わせを実行します。祝日も実行します。

配置先: https://github.com/imaminet/schedule

## GitHubへの設置

次のファイルをリポジトリのデフォルトブランチへアップロードしてください。`github_upload.zip` にも同じファイルをまとめています（展開して配置）。

- `fetch_market_data.py`
- `verify_and_learn.py`
- `settings.py`
- `requirements.txt`
- `.gitignore`
- `.github/workflows/market-schedule.yml`
- `.github/scripts/find_morning_artifact.py`
- `README.md`

**`local_settings.json` はAPIキーが入ったローカル専用ファイルです。アップロードしないでください。**

リポジトリの **Settings → Secrets and variables → Actions → New repository secret** に以下を登録してください。キーの値は手元の `local_settings.json` にあります。

| Secret名 | 値 |
| --- | --- |
| `DIFY_API_KEY` | 朝のDifyチャットフローの `app-...` キー |
| `DATASET_API_KEY` | ナレッジ用の `dataset-...` キー |
| `DATASET_ID` | ナレッジのID |

Actionsタブで **Market brief and review → Run workflow → mode: morning** を実行し、成功後に同じ日中に **mode: evening** を実行して確認できます。夕方の `notes` は任意です。

定期実行はデフォルトブランチに置かれたワークフローで動作します。設定時刻より遅れる場合があります。
公式仕様: https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule

## ファイルの引き継ぎ

朝のJSON・ブリーフ・生成日の情報をActionsのArtifactに14日間保存します。夕方は同日の成功した朝の実行から復元します。朝の失敗やファイル欠落、日付違いの場合は夕方も失敗として停止し、古いデータでナレッジを作成しません。

夕方のレポートもArtifactに30日間保存します。Dify処理やナレッジ追加が失敗した場合はActions上で失敗と表示します。再度夕方を実行するとナレッジに同名のドキュメントが追加される可能性があります。

Discordへの送信は設定済みのDifyフローが実施します。GitHub側ではDiscordへ直接送信しません。

## 手元で実行

現在のキーは `local_settings.json` に移してあります。環境変数を設定した場合はそちらを優先します。

```powershell
py -m pip install -r requirements.txt
py -X utf8 fetch_market_data.py
py -X utf8 verify_and_learn.py
```

夕方を入力なしで実行する場合は `--non-interactive` を付けます。この場合、同日に朝のスクリプトを実行しておく必要があります。
