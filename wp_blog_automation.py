import os
import requests
import base64
import json
from datetime import datetime

WP_BASE_URL = "https://yonetomo113.com/wp-json/wp/v2"
WP_USER = "yonetomo113"
WP_APP_PASSWORD = os.getenv("WP_APP_PASSWORD", "2MQn rl6o 5dDN hylm LTue nmmZ")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

def generate_blog_and_social_posts(topic):
    # 手短にテストするため、最小限の指示
    full_prompt = f"トピック「{topic}」についてブログ記事をJSON形式で。キーはblog_content, social_posts(facebook, instagram, threads)"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    try:
        response = requests.post(url, json={"contents": [{"parts": [{"text": full_prompt}]}], "generationConfig": {"responseMimeType": "application/json"}}, timeout=30)
        body = response.json()
        if "error" in body:
            print(f"Gemini API Error: {body['error']['code']} {body['error']['message'][:200]}")
            return None
        return json.loads(body['candidates'][0]['content']['parts'][0]['text'])
    except Exception as e:
        print(f"Gemini Error: {e}")
        return None

def post_to_wordpress(title, blog_data):
    auth_string = f"{WP_USER}:{WP_APP_PASSWORD}"
    base64_auth = base64.b64encode(auth_string.encode()).decode()
    headers = {"Authorization": f"Basic {base64_auth}", "Content-Type": "application/json"}
    
    # 下書き(draft)ではなく、一度「非公開(private)」で試してみます
    # これにより、通常の投稿一覧に「非公開：タイトル」として強制的に表示されるようになります
    payload = {
        "title": f"【緊急確認】{title}",
        "content": blog_data.get('blog_content', 'テスト本文'),
        "status": "draft"
    }

    print(f"📦 送信データ: {payload['title']}")
    try:
        # LiteSpeed環境では /wp-json/ ルーティングが機能しないため ?rest_route= 経由で投稿
        wp_site_url = WP_BASE_URL.replace("/wp-json/wp/v2", "")
        response = requests.post(f"{wp_site_url}/?rest_route=/wp/v2/posts", headers=headers, json=payload, timeout=30)
        
        print(f"📡 HTTP ステータス: {response.status_code}")
        
        if response.status_code in [200, 201]:
            print("✅ WordPress サーバーは「作成成功」と回答しました。")
            try:
                data = response.json()
                print(f"🆔 生成された投稿ID: {data.get('id')}")
                print(f"🔗 確認URL: https://yonetomo113.com/?p={data.get('id')}")
            except:
                print("⚠️ レスポンスが空です。サーバーのセキュリティ（WAF/SiteGuard）が応答を遮断した可能性があります。")
        else:
            print(f"❌ サーバーエラー: {response.status_code}")
            print(f"   詳細: {response.text}")
            
    except Exception as e:
        print(f"WP Connection Error: {e}")

if __name__ == "__main__":
    topic = "不動産投資の最新トレンド"
    print("🚀 最終デバッグ実行...")
    data = generate_blog_and_social_posts(topic)
    if data:
        post_to_wordpress(datetime.now().strftime('%H:%M:%S 最終テスト'), data)
