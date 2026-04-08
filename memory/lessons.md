# 失敗記録

## 2026-04-08
- 事象：git pushを別アカウント（nogataka）のリポジトリに試みた
- 原因：clone元のremoteを確認せずそのままpushしようとした
- 対策：push前に必ずgit remote -v でリモートURLとアカウント名を確認する

## 2026-04-08
- 事象：noise_monitor.htmlのntfy通知がXMLHttpRequestに変更後、送信中のまま止まった
- 原因：iPhoneのSafariからXHRがブロックされた
- 対策：iPhoneからの外部APIコールはfetchを使う。ヘッダーは最小限にする
