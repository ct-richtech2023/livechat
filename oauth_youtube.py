import os
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

# 直播创建/绑定等写操作建议用这个 scope；只读可换 youtube.readonly
SCOPES = ["https://www.googleapis.com/auth/youtube"]

CLIENT_SECRET_FILE = "client_secret.json"
TOKEN_FILE = "token.json"

def get_creds():
    creds = None

    # 1) 读取已有 token
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    # 2) token 过期则刷新；没有则走浏览器授权
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CLIENT_SECRET_FILE):
                raise FileNotFoundError(
                    f"找不到 {CLIENT_SECRET_FILE}，请把下载的 OAuth 客户端 JSON 放到同目录并改名为 client_secret.json"
                )
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
            # 会自动打开浏览器进行授权
            creds = flow.run_local_server(port=0)

        # 保存 token，后续运行不再弹浏览器
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(creds.to_json())

    return creds

def get_youtube_client():
    """获取 YouTube API 客户端，供 sender 等模块复用"""
    creds = get_creds()
    return build("youtube", "v3", credentials=creds)


def main():
    youtube = get_youtube_client()

    # 调用一个轻量接口验证：读取当前登录账号的频道信息
    resp = youtube.channels().list(part="snippet,contentDetails,statistics", mine=True).execute()

    items = resp.get("items", [])
    if not items:
        print("OAuth 成功，但没有取到频道信息。请确认你授权的账号确实有 YouTube 频道。")
        return

    ch = items[0]
    snippet = ch.get("snippet", {})
    stats = ch.get("statistics", {})

    print("✅ OAuth 配置验证成功！")
    print("token.json 已生成/更新。")
    print("Channel Title:", snippet.get("title"))
    print("Channel ID:", ch.get("id"))
    print("Subscribers:", stats.get("subscriberCount"))
    print("Views:", stats.get("viewCount"))

if __name__ == "__main__":
    main()
