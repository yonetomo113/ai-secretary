# ツール設定

使用するツールを `有効` / `無効` で切り替える。
オンボーディング時に自動設定されるが、手動での変更も可能。

## メール

- **状態**: 無効
- **ツール**: （例: Gmail / Outlook）
- **操作方法**: （例: Gmail MCP, CLI, 手動コピペ）

## カレンダー

- **状態**: 無効
- **ツール**: （例: Google Calendar / Outlook Calendar）
- **操作方法**: （例: Google Calendar MCP, CLI）
- **タイムゾーン**: Asia/Tokyo

## チャット

- **状態**: 無効
- **ツール**: （例: Slack / Teams / Discord）
- **操作方法**: （例: Slack MCP, 手動コピペ）

## ドキュメント

- **状態**: 無効
- **ツール**: （例: Notion / Google Docs / Obsidian）
- **操作方法**: （例: Notion MCP, Google MCP）

## タスク管理

- **状態**: 無効
- **ツール**: （例: GitHub Issues / Linear / Todoist）
- **操作方法**: （例: gh CLI, Linear MCP）

## コード管理

- **状態**: 無効
- **ツール**: （例: GitHub / GitLab）
- **操作方法**: （例: gh CLI）

## 注意事項

- タイムゾーン付きAPI呼び出し時、dateTimeに"Z"（UTC）をつけない
- MCP系ツールは初回・トークン切れ時に再認証が必要な場合がある
