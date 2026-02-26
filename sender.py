"""
YouTube 直播聊天消息发送模块

# 自动用当前账号的正在直播，发送默认消息
python sender.py

# 自动用当前账号的正在直播，发送指定消息
python sender.py 大家好

# 指定某场直播发送
python sender.py ttlT7tBAd6I 你好

# 用环境变量指定 VIDEO_ID
set VIDEO_ID=ttlT7tBAd6I
python sender.py 你好
"""
import os
import sys
import ssl
import time
from oauth_youtube import get_youtube_client

# 代理/网络不稳定时重试
MAX_RETRIES = 3
RETRY_DELAY = 2


def _retry_request(func):
    """对 SSL/连接错误自动重试"""
    for attempt in range(MAX_RETRIES):
        try:
            return func()
        except (ssl.SSLEOFError, ssl.SSLError, OSError, ConnectionError) as e:
            if attempt < MAX_RETRIES - 1:
                print(f"请求失败 ({e.__class__.__name__})，{RETRY_DELAY} 秒后重试 ({attempt + 1}/{MAX_RETRIES})...")
                time.sleep(RETRY_DELAY)
            else:
                raise


def get_my_live_video_id(youtube) -> str | None:
    """获取当前 OAuth 账号正在直播或即将开播的视频 ID（优先正在直播）。"""
    def _do():
        return (
            youtube.liveBroadcasts()
            .list(
                part="snippet,status",
                broadcastType="event",
                mine=True,
                maxResults=10,
            )
            .execute()
        )
    try:
        resp = _retry_request(_do)
    except Exception:
        return None
    items = resp.get("items", [])
    # 优先正在直播，其次测试/即将开始等
    for status in ("live", "testing", "liveStarting", "testStarting", "ready", "created"):
        for it in items:
            if (it.get("status") or {}).get("lifeCycleStatus") == status:
                return it.get("id")
    return None


def get_live_chat_id(youtube, video_id: str) -> str | None:
    """通过视频 ID 获取直播聊天 ID"""
    def _do():
        return (
            youtube.videos()
            .list(part="liveStreamingDetails", id=video_id)
            .execute()
        )
    response = _retry_request(_do)
    items = response.get("items", [])
    if not items:
        return None
    details = items[0].get("liveStreamingDetails", {})
    return details.get("activeLiveChatId")


def send_message(youtube, live_chat_id: str, message_text: str) -> bool:
    """发送消息到直播聊天"""
    def _do():
        return (
            youtube.liveChatMessages()
            .insert(
                part="snippet",
                body={
                    "snippet": {
                        "liveChatId": live_chat_id,
                        "type": "textMessageEvent",
                        "textMessageDetails": {
                            "messageText": message_text
                        }
                    }
                }
            )
            .execute()
        )
    try:
        _retry_request(_do)
        return True
    except Exception as e:
        print(f"发送失败: {e}")
        return False


def main():
    """命令行入口：python sender.py [VIDEO_ID] [消息内容]
    不传 VIDEO_ID 时自动使用当前账号正在直播/即将开播的视频；也可设置环境变量 VIDEO_ID。
    """
    args = sys.argv[1:]
    # 第一个参数若为 11 位且似视频 ID，则当作 VIDEO_ID，其余为消息
    video_id_arg = None
    if args and len(args[0]) == 11 and args[0].replace("-", "").replace("_", "").isalnum():
        video_id_arg = args[0]
        message = " ".join(args[1:]) if len(args) > 1 else "Hello from bot!"
    else:
        message = " ".join(args) if args else "Hello from bot!"

    print(f"准备发送: {message}")

    youtube = get_youtube_client()
    video_id = video_id_arg or os.environ.get("VIDEO_ID") or get_my_live_video_id(youtube)

    if not video_id:
        print("未指定 VIDEO_ID 且无法自动获取当前直播。请：")
        print("  1) 确保 OAuth 账号有正在直播或即将开播的节目，或")
        print("  2) 运行: python sender.py <VIDEO_ID> [消息]，或设置环境变量 VIDEO_ID")
        return

    live_chat_id = get_live_chat_id(youtube, video_id)
    if not live_chat_id:
        print(f"无法获取直播聊天 ID，请确认视频 {video_id} 正在直播")
        return

    if send_message(youtube, live_chat_id, message):
        print("发送成功!")
    else:
        print("发送失败")


if __name__ == "__main__":
    main()
