# 有限会社クロスエッジ 自動化ステータス

## 完了

### 1. 朝のブリーフィング
- スクリプト: `morning_briefing.py`
- スケジュール: 毎日 JST 7:20
- 概要: Gmail・Googleカレンダー・Airbnb予約メールを取得し、Claude AIで要約してメール送信

### 2. assift シフト自動割当
- スクリプト: `assift_automator.py`
- スケジュール: 毎月24日 JST 17:00
- 概要: Airbnb予約メールからチェックアウト日を抽出してassiftに自動登録

### 3. WordPress 自動投稿
- スクリプト: `wp_buffer_integration.py`
- スケジュール: 火・土 JST 7:00
- 概要: Gemini AIでブログ下書き（約1000字）とSNSコピーを生成し、WordPressに下書き保存

**運用ルール**: 火・土の朝7時に自動生成。人間が内容確認してBufferへ投稿。

---

## 進行中

（なし）

---

## 予定

（なし）

---

## 備考

- GitHub Actions リポジトリ: `yonetomo113/ai-secretary`
- WordPress: https://yonetomo113.com/
- 各スクリプトの前提条件・注意事項は各ファイルのdocstringを参照
