# 有限会社クロスエッジ 自動化ステータス

最終更新: 2026年4月21日（火）

## 完了

### 1. 朝のブリーフィング
- スクリプト: `morning_briefing.py`
- スケジュール: 毎日 JST 7:20
- 概要: Gmail・Googleカレンダー・Airbnb予約メールを取得し、Claude AIで要約してメール送信

### 2. assift シフト自動割当
- スクリプト: `assift_automator.py`
- スケジュール: 毎月24日 JST 17:00
- 概要: Airbnb予約メールからチェックアウト日を抽出してassiftに自動登録

**運用ルール**:
- 毎月23日 JST 7:00 にリマインドメール送信（「明日は24日です。assift URLを更新してください」）
- 翌24日 JST 17:00 に `assift_automator.py` が自動実行

### 3. WordPress 自動投稿
- スクリプト: `wp_buffer_integration.py`
- スケジュール: 火・土 JST 7:00
- 概要: Gemini AIでブログ下書き（約1000字）とSNSコピーを生成し、WordPressに下書き保存

**運用ルール**: 火・土の朝7時に自動生成。人間が内容確認してBufferへ投稿。

---

## 次回予定

| 日付 | 内容 |
|------|------|
| 2026年4月24日（金） | assift シフト自動割当（毎月24日） |
| 2026年4月25日（土） | WordPress ブログ自動生成 |
| 2026年5月23日（土） | assift URLリマインドメール |

---

## 進行中

（なし）

---

## 備考

- GitHub Actions リポジトリ: `yonetomo113/ai-secretary`
- WordPress: https://yonetomo113.com/
- 各スクリプトの前提条件・注意事項は各ファイルのdocstringを参照
