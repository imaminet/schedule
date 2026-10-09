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

Actionsタブで **Market brief and review → Run workflow → mode: morning** を実行し、成功後、大引け以降に **mode: evening** を実行して確認できます。日付をまたいだ場合は `target_date` に朝の対象日（例: `2026-10-09`）を指定してください。夕方の `notes` は任意です。

定期実行はデフォルトブランチに置かれたワークフローで動作します。設定時刻より遅れる場合があります。
公式仕様: https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule

## ファイルの引き継ぎ

朝のJSON・ブリーフ・生成日の情報をActionsのArtifactに14日間保存します。夕方は同じ対象日の成功した朝の実行から復元します。朝の失敗やファイル欠落、日付違いの場合は夕方も失敗として停止し、古いデータでナレッジを作成しません。

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

## 遅延・再実行と対象日

定期実行の対象日は、GitHubの元のrunの `created_at`（再実行でも不変）を基準に、朝7:30／夕17:00の直近の平日予定日を計算して固定します。例えば夕方runが10/9 15:00 UTC（10/10 0:00 JST）に作られても、対象日は10/9となります。対象日は朝Artifact検索、メタデータ検証、夕方実績取得、レポート名、Dify文書名で共通です。

GitHubのscheduleイベントには本来の予定日時が含まれません。丸一日以上遅れてrun自体が作られる場合は元の予定日を一意に復元できないため、手動実行の `target_date` で指定してください。定期実行時刻そのものの遅延を、この修正で解消することはできません。

朝ブリーフには対象日、取得日時、国内データ掲載日時・区分を必ず付けます。寄り付き後に生成したブリーフは事前予測として扱いません。過去対象日の朝ブリーフを現在のライブデータから再作成する処理は停止します。株探の未来日・7日を超える古い掲載日・解析不一致・HTTPエラーは失敗として停止し、前日分の場合は日経平均の取引履歴を使って直前取引日との一致も検証し、確認できなければ停止します。掲載日の違いはレポートに明記します。

米国必須指標の欠落や不正値、夕方の日経平均・東証対象銘柄の対象日データ欠落は、Dify処理の前に停止します。夕方は対象日の実績と直前取引日の価格を取得し、別日の最新値を代用しません。休場日に対象日の実績がない場合も停止します。東証以外の銘柄は検証対象外と明記します。

夕方レポート生成後は対象日付きファイルの保存を必須とします。ナレッジ追加に失敗した場合も生成済みレポートは保存します。生成前に停止した場合は成功レポートを作らず、`failure-{run_id}-{attempt}` Artifactに失敗段階・対象日と処理ログを30日間保存します。

修正前の失敗runを「Re-run」しても古いコミットが使われます。修正を使うにはmainから新しい手動実行を開始してください。Difyナレッジの重複追加を避けるため、夕方の再実行は既存文書も確認してください。

回帰テスト: `python -m unittest discover -s tests -v`。定期／手動ワークフローでもデータ取得前に実行します。
