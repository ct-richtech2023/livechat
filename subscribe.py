"""
YouTube 频道订阅管理脚本

用法:
    python subscribe.py --sub <CHANNEL_ID>       # 订阅频道
    python subscribe.py --unsub <CHANNEL_ID>     # 取消订阅（需要 subscription_id）
    python subscribe.py --list                   # 列出已订阅的频道
    python subscribe.py --list --max 50          # 列出更多订阅
    python subscribe.py --find <CHANNEL_ID>      # 查找订阅记录（获取 subscription_id）

示例:
    python subscribe.py --sub UCxxxxxxxxxxxx
    python subscribe.py --find UCxxxxxxxxxxxx
    python subscribe.py --unsub SUBSCRIPTION_ID
    python subscribe.py --list
"""
import sys
import json
from loguru import logger
from oauth_youtube import get_youtube_client
from sender import _retry_request


def subscribe_channel(youtube, channel_id: str) -> dict | None:
    """
    订阅指定频道。
    返回订阅记录（含 subscription_id），失败返回 None。
    """
    def _do():
        return youtube.subscriptions().insert(
            part="snippet",
            body={
                "snippet": {
                    "resourceId": {
                        "kind": "youtube#channel",
                        "channelId": channel_id
                    }
                }
            }
        ).execute()
    
    try:
        result = _retry_request(_do)
        return result
    except Exception as e:
        error_msg = str(e)
        if "subscriptionDuplicate" in error_msg:
            logger.warning(f"已经订阅过该频道: {channel_id}")
        elif "subscriberNotFound" in error_msg:
            logger.error(f"频道不存在: {channel_id}")
        else:
            logger.error(f"订阅失败: {e}")
        return None


def unsubscribe_channel(youtube, subscription_id: str) -> bool:
    """
    取消订阅。需要 subscription_id（可通过 --find 或 --list 获取）。
    """
    def _do():
        youtube.subscriptions().delete(id=subscription_id).execute()
        return True
    
    try:
        _retry_request(_do)
        return True
    except Exception as e:
        logger.error(f"取消订阅失败: {e}")
        return False


def list_subscriptions(youtube, max_results: int = 25, page_token: str | None = None) -> tuple[list[dict], str | None]:
    """
    列出已订阅的频道。
    返回 (订阅列表, 下一页 token)。
    """
    def _do():
        return youtube.subscriptions().list(
            part="snippet,contentDetails",
            mine=True,
            maxResults=min(max_results, 50),
            pageToken=page_token or "",
            order="relevance"
        ).execute()
    
    try:
        resp = _retry_request(_do)
        return resp.get("items", []), resp.get("nextPageToken")
    except Exception as e:
        logger.error(f"获取订阅列表失败: {e}")
        return [], None


def find_subscription(youtube, channel_id: str) -> dict | None:
    """
    查找指定频道的订阅记录。
    返回订阅记录（含 subscription_id），未找到返回 None。
    """
    def _do():
        return youtube.subscriptions().list(
            part="snippet",
            mine=True,
            forChannelId=channel_id,
            maxResults=1
        ).execute()
    
    try:
        resp = _retry_request(_do)
        items = resp.get("items", [])
        return items[0] if items else None
    except Exception as e:
        logger.error(f"查找订阅失败: {e}")
        return None


def get_channel_info(youtube, channel_id: str) -> dict | None:
    """获取频道信息"""
    def _do():
        return youtube.channels().list(
            part="snippet,statistics",
            id=channel_id
        ).execute()
    
    try:
        resp = _retry_request(_do)
        items = resp.get("items", [])
        return items[0] if items else None
    except Exception:
        return None


def main():
    args = sys.argv[1:]
    
    if not args or "--help" in args or "-h" in args:
        print(__doc__)
        return
    
    youtube = get_youtube_client()
    
    # 解析参数
    action = None
    target = None
    max_results = 25
    
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("--sub", "-s"):
            action = "subscribe"
            if i + 1 < len(args):
                target = args[i + 1]
                i += 1
        elif arg in ("--unsub", "-u"):
            action = "unsubscribe"
            if i + 1 < len(args):
                target = args[i + 1]
                i += 1
        elif arg in ("--list", "-l"):
            action = "list"
        elif arg in ("--find", "-f"):
            action = "find"
            if i + 1 < len(args):
                target = args[i + 1]
                i += 1
        elif arg == "--max" and i + 1 < len(args):
            max_results = int(args[i + 1])
            i += 1
        elif not arg.startswith("-") and target is None:
            target = arg
        i += 1
    
    if action == "subscribe":
        if not target:
            logger.error("请指定频道 ID: --sub <CHANNEL_ID>")
            return
        
        logger.info(f"正在订阅频道: {target}")
        
        # 先获取频道信息
        channel_info = get_channel_info(youtube, target)
        if channel_info:
            snippet = channel_info.get("snippet", {})
            logger.info(f"频道名称: {snippet.get('title')}")
            logger.info(f"订阅者数: {channel_info.get('statistics', {}).get('subscriberCount', '隐藏')}")
        
        result = subscribe_channel(youtube, target)
        if result:
            logger.info("订阅成功!")
            logger.info(f"Subscription ID: {result.get('id')}")
            snippet = result.get("snippet", {})
            logger.info(f"频道: {snippet.get('title')}")
    
    elif action == "unsubscribe":
        if not target:
            logger.error("请指定 Subscription ID: --unsub <SUBSCRIPTION_ID>")
            logger.info("提示: 使用 --find <CHANNEL_ID> 查找 Subscription ID")
            return
        
        logger.info(f"正在取消订阅: {target}")
        if unsubscribe_channel(youtube, target):
            logger.info("取消订阅成功!")
    
    elif action == "find":
        if not target:
            logger.error("请指定频道 ID: --find <CHANNEL_ID>")
            return
        
        logger.info(f"查找订阅记录: {target}")
        result = find_subscription(youtube, target)
        if result:
            logger.info("找到订阅记录:")
            logger.info(f"  Subscription ID: {result.get('id')}")
            snippet = result.get("snippet", {})
            logger.info(f"  频道名称: {snippet.get('title')}")
            logger.info(f"  订阅时间: {snippet.get('publishedAt')}")
            logger.info("")
            logger.info(f"取消订阅命令: python subscribe.py --unsub {result.get('id')}")
        else:
            logger.info("未找到该频道的订阅记录（可能未订阅）")
    
    elif action == "list":
        logger.info(f"获取订阅列表 (最多 {max_results} 个)...")
        
        all_subs = []
        token = None
        while len(all_subs) < max_results:
            subs, token = list_subscriptions(youtube, min(50, max_results - len(all_subs)), token)
            all_subs.extend(subs)
            if not token:
                break
        
        logger.info(f"共 {len(all_subs)} 个订阅:")
        logger.info("")
        
        for i, sub in enumerate(all_subs, 1):
            snippet = sub.get("snippet", {})
            resource_id = snippet.get("resourceId", {})
            channel_id = resource_id.get("channelId", "")
            title = snippet.get("title", "")
            desc = snippet.get("description", "")[:50]
            sub_id = sub.get("id", "")
            
            logger.info(f"{i}. {title}")
            logger.info(f"   Channel ID: {channel_id}")
            logger.info(f"   Subscription ID: {sub_id}")
            if desc:
                logger.info(f"   简介: {desc}...")
            logger.info("")
    
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
