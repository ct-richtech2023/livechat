"""
通过 pytchat 获取 YouTube 直播聊天数据

可获取的数据类型：
--------------------
1. 文字消息 (textMessage)
   - 用户发送的普通聊天文字
   - 含时间戳、作者名、作者频道ID、消息内容
   - 表情以 :shortcut-name: 格式显示（如 :face-blue-smiling:）

2. 打赏 (superChat)
   - Super Chat 付费高亮消息
   - 含金额 (amount_string, amount_value)、留言内容

3. 贴纸 (superSticker)
   - Super Sticker 付费贴纸消息
   - 含金额、贴纸信息

4. 新会员 (newSponsor)
   - 用户加入频道会员时的系统通知

5. 捐赠 (donation)
   - 旧版打赏（已较少使用）

每条消息包含：type, timestamp, author_name, author_channel_id, message, amount_string, amount_value

注意：
- pytchat 仅能获取连接后新产生的消息，无历史消息
- 不依赖 OAuth，直接抓取公开页面
- 需网络可访问 YouTube（代理环境下可能不稳定）
"""
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterator

import pytchat
from pytchat.exceptions import InvalidVideoIdException

from loguru import logger

@dataclass
class PytchatMessage:
    """pytchat 聊天消息统一结构"""
    type: str  # textMessage, superChat, superSticker, newSponsor, donation
    timestamp: str
    author_name: str
    author_channel_id: str
    message: str
    amount_string: str
    amount_value: float
    raw: object = field(default=None)


class YoutubeLivePytchat:
    """YouTube 直播 pytchat 封装，获取 pytchat 可用的所有数据"""

    def __init__(self, video_id: str):
        self.video_id = video_id
        self._live_chat = None
        self._connect()

    def _connect(self) -> None:
        try:
            self._live_chat = pytchat.create(video_id=self.video_id)
        except InvalidVideoIdException:
            self._live_chat = None

    def is_alive(self) -> bool:
        """直播是否在进行中"""
        return self._live_chat is not None and self._live_chat.is_alive()

    def _parse_chat(self, chat) -> PytchatMessage:
        msg_type = getattr(chat, "type", "textMessage") or "textMessage"
        return PytchatMessage(
            type=msg_type,
            timestamp=getattr(chat, "timestamp", ""),
            author_name=getattr(chat.author, "name", ""),
            author_channel_id=getattr(chat.author, "channelId", ""),
            message=getattr(chat, "message", ""),
            amount_string=getattr(chat, "amountString", ""),
            amount_value=getattr(chat, "amountValue", 0.0) or 0.0,
            raw=chat,
        )

    def get_chat_items(self) -> Iterator[PytchatMessage]:
        """同步迭代聊天消息（阻塞式）"""
        if not self.is_alive():
            return
        for chat in self._live_chat.get().sync_items():
            yield self._parse_chat(chat)

    def collect_chat(
        self,
        duration_sec: int | None = None,
        max_count: int | None = None,
    ) -> list[PytchatMessage]:
        """
        收集一段时间或一定数量的聊天消息。
        :param duration_sec: 收集时长（秒），None 表示不按时间限制
        :param max_count: 最大消息数，None 表示不限制
        """
        import time

        messages = []
        start = time.time()

        for msg in self.get_chat_items():
            messages.append(msg)
            if max_count and len(messages) >= max_count:
                break
            if duration_sec and (time.time() - start) >= duration_sec:
                break
        return messages

    # 常见 YouTube 表情快捷键 -> 中文含义
    EMOJI_MEANINGS = {
        "face-blue-smiling": "蓝色微笑",
        "face-purple-crying": "紫色哭泣",
        "face-red-droopy-eyes": "红色下垂眼",
        "face-green-smiling": "绿色微笑",
        "hand-pink-waving": "粉色挥手",
        "text-green-game-over": "游戏结束",
        "face-blue-wide-eyes": "蓝色大眼",
        "face-red-heart-shape": "红色爱心",
        "grinning_squinting_face": "眯眼笑",
        "face-with-tears-of-joy": "笑哭",
        "thumbs-up": "点赞",
        "red-heart": "红心",
        "smiling-face-with-hearts": "爱心笑",
    }

    def _parse_message_parts(self, message: str) -> dict:
        """解析消息，区分文字和表情。表情格式 :shortcut-name:"""
        text_parts = []
        emojis = []
        # 匹配 :word-with-hyphens: 格式
        pattern = re.compile(r":([a-zA-Z0-9_-]+):")
        last_end = 0
        for m in pattern.finditer(message):
            # 文字部分
            if m.start() > last_end:
                text_parts.append({"type": "text", "content": message[last_end : m.start()]})
            # 表情部分
            shortcut = m.group(1)
            meaning = self.EMOJI_MEANINGS.get(shortcut, shortcut.replace("-", " "))
            emojis.append({"shortcut": shortcut, "meaning": meaning})
            last_end = m.end()
        if last_end < len(message):
            text_parts.append({"type": "text", "content": message[last_end:]})
        return {"text_parts": text_parts, "emojis": emojis}

    def _ts_to_datetime(self, ts) -> str:
        """时间戳转年月日时分秒"""
        try:
            if isinstance(ts, (int, float)):
                if ts > 1e12:
                    ts = ts / 1000
                return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
            return str(ts)
        except (ValueError, OSError):
            return str(ts)

    def _format_msg_as_kv(self, msg: PytchatMessage) -> dict:
        """单条消息转为 key-value 格式，区分文字和表情"""
        dt_str = self._ts_to_datetime(msg.timestamp)
        parsed = self._parse_message_parts(msg.message)
        kv = {
            "time": dt_str,
            "name": msg.author_name,
            "message": msg.message,
            "text_parts": [p["content"] for p in parsed["text_parts"] if p["content"].strip()],
            "emojis": parsed["emojis"],
        }
        if msg.amount_string:
            kv["amount"] = msg.amount_string
        return kv

    def _format_content(self, parsed: dict) -> str:
        """将解析结果拼接为内容字符串，表情只显示 shortcut"""
        parts = []
        for p in parsed["text_parts"]:
            if p["content"].strip():
                parts.append(p["content"].strip())
        for e in parsed["emojis"]:
            parts.append(f":{e['shortcut']}:")
        return " ".join(parts) if parts else "(空)"

    def _log_realtime_msg(self, msg: PytchatMessage) -> None:
        """用 logger 实时输出，格式 [时间][text/emojis] name: 内容"""
        parsed = self._parse_message_parts(msg.message)
        dt_str = self._ts_to_datetime(msg.timestamp)
        content = self._format_content(parsed)
        if msg.amount_string:
            content = f"{content} {msg.amount_string}"
        has_text = any(p["content"].strip() for p in parsed["text_parts"])
        label = "emojis" if parsed["emojis"] and not has_text else "text"
        logger.info(f"[{dt_str}][{label}] {msg.author_name}: {content}")

    def _log_summary(self, result: dict) -> None:
        """用 logger 打印汇总统计"""
        logger.info("=" * 50)
        logger.info("汇总统计")
        logger.info(
            f"总消息数: {len(result['messages'])} | 文字: {len(result['text_messages'])} | 打赏: {len(result['super_chats'])} | 贴纸: {len(result['super_stickers'])} | 新会员: {len(result['new_sponsors'])} | 捐赠: {len(result['donations'])} | 发言用户: {len(result['unique_chatters'])}",
        )
        if result["text_messages"]:
            text_list = [
                {
                    "name": m["author_name"],
                    "text": m.get("text_parts", []),
                    "emojis": m.get("emojis", []),
                }
                for m in result["text_messages"]
            ]
            logger.info(f"文字消息列表: {text_list}")
        logger.info("=" * 50)

    def fetch_all(
        self,
        duration_sec: int = 30,
        realtime_print: bool = True,
        poll_interval: float = 2.0,
    ) -> dict:
        """
        获取所有可获取的数据。
        会拉取 duration_sec 秒内的聊天并分类统计。
        pytchat 每次 get() 只拉取一批消息，无新消息时立即返回，因此外层循环持续轮询直到时长结束。
        :param duration_sec: 收集时长（秒）
        :param realtime_print: 是否实时打印每条消息，结束后打印汇总
        :param poll_interval: 无新消息时等待间隔（秒），避免频繁请求
        """
        import time

        result = {
            "video_id": self.video_id,
            "is_alive": self.is_alive(),
            "messages": [],
            "text_messages": [],
            "super_chats": [],
            "super_stickers": [],
            "new_sponsors": [],
            "donations": [],
            "unique_chatters": [],
        }

        if not self.is_alive():
            return result

        chatters_set = set()
        start = time.time()
        end_time = start + duration_sec

        if realtime_print:
            logger.info(f"开始监听 {duration_sec} 秒，实时打印中...")

        while time.time() < end_time and self.is_alive():
            has_new = False
            for msg in self.get_chat_items():
                has_new = True
                parsed = self._parse_message_parts(msg.message)
                d = {
                    "type": msg.type,
                    "timestamp": msg.timestamp,
                    "author_name": msg.author_name,
                    "author_channel_id": msg.author_channel_id,
                    "message": msg.message,
                    "text_parts": [p["content"] for p in parsed["text_parts"] if p["content"].strip()],
                    "emojis": parsed["emojis"],
                    "amount_string": msg.amount_string,
                    "amount_value": msg.amount_value,
                }
                result["messages"].append(d)

                if msg.author_name and msg.author_name not in chatters_set:
                    chatters_set.add(msg.author_name)
                    result["unique_chatters"].append(msg.author_name)

                if msg.type == "textMessage":
                    result["text_messages"].append(d)
                elif msg.type == "superChat":
                    result["super_chats"].append(d)
                elif msg.type == "superSticker":
                    result["super_stickers"].append(d)
                elif msg.type == "newSponsor":
                    result["new_sponsors"].append(d)
                elif msg.type == "donation":
                    result["donations"].append(d)

                if realtime_print:
                    self._log_realtime_msg(msg)

                if time.time() >= end_time:
                    break

            if not has_new and time.time() < end_time:
                time.sleep(min(poll_interval, end_time - time.time()))

        if realtime_print:
            self._log_summary(result)

        return result


if __name__ == "__main__":
    VIDEO_ID = "nqYWoAWJ2Mg"
    pt = YoutubeLivePytchat(VIDEO_ID)
    pt.fetch_all(duration_sec=300, realtime_print=True)
