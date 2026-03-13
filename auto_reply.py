"""
YouTube 直播自动回复机器人

监听直播聊天，检测特定问题并自动回复，同时更新 OBS 文字显示。

用法:
    python auto_reply.py                    # 自动获取当前直播
    python auto_reply.py <VIDEO_ID>         # 指定直播
    python auto_reply.py --test             # 测试模式（不发送消息）

配置:
    在 REPLY_RULES 中定义问答规则
"""
import os
import re
import sys
import time
import subprocess
from dataclasses import dataclass
from typing import Callable

from loguru import logger

from live_pytchat import YoutubeLivePytchat, PytchatMessage
from sender import get_youtube_client, get_my_live_video_id, get_live_chat_id, send_message


@dataclass
class ReplyRule:
    """自动回复规则"""
    name: str
    keywords: list[str]
    reply_template: str
    obs_source: str | None = None
    obs_template: str | None = None
    
    def match(self, message: str) -> bool:
        """检查消息是否匹配规则"""
        msg_lower = message.lower()
        return any(kw.lower() in msg_lower for kw in self.keywords)


# ===== 配置区域 =====

# OBS 文字源名称（需要与 OBS 中的源名称一致）
OBS_CAMERA_TEXT = "camera text"

# 自动回复规则
REPLY_RULES = [
    ReplyRule(
        name="adam功能",
        keywords=["adam可以做什么", "adam能做什么", "adam会做什么", "what can adam do"],
        reply_template="{name} adam可以做咖啡 ☕",
        obs_source=OBS_CAMERA_TEXT,
        obs_template="{name} adam可以做咖啡",
    ),
    ReplyRule(
        name="adam咖啡",
        keywords=["adam做咖啡", "adam咖啡", "adam coffee"],
        reply_template="{name} 好的，adam马上为您制作咖啡 ☕",
        obs_source=OBS_CAMERA_TEXT,
        obs_template="{name} 正在制作咖啡...",
    ),
]

# 回复冷却时间（秒），避免重复回复同一用户
REPLY_COOLDOWN = 60

# ===== 配置结束 =====


class AutoReplyBot:
    """自动回复机器人"""
    
    def __init__(self, video_id: str, test_mode: bool = False):
        self.video_id = video_id
        self.test_mode = test_mode
        self.youtube = None
        self.live_chat_id = None
        self.pytchat = None
        self.reply_cooldowns: dict[str, float] = {}
        
    def _init_sender(self) -> bool:
        """初始化发送端（OAuth）"""
        if self.test_mode:
            logger.info("[测试模式] 跳过 OAuth 初始化")
            return True
        try:
            self.youtube = get_youtube_client()
            self.live_chat_id = get_live_chat_id(self.youtube, self.video_id)
            if not self.live_chat_id:
                logger.error(f"无法获取直播聊天 ID: {self.video_id}")
                return False
            logger.info(f"已连接到直播聊天: {self.live_chat_id}")
            return True
        except Exception as e:
            logger.error(f"初始化发送端失败: {e}")
            return False
    
    def _init_pytchat(self) -> bool:
        """初始化 pytchat 监听"""
        try:
            self.pytchat = YoutubeLivePytchat(self.video_id)
            if not self.pytchat.is_alive():
                logger.error(f"直播不在线或无法连接: {self.video_id}")
                return False
            logger.info(f"已连接到直播监听: {self.video_id}")
            return True
        except Exception as e:
            logger.error(f"初始化 pytchat 失败: {e}")
            return False
    
    def _is_on_cooldown(self, user_name: str, rule_name: str) -> bool:
        """检查用户是否在冷却中"""
        key = f"{user_name}:{rule_name}"
        last_time = self.reply_cooldowns.get(key, 0)
        return (time.time() - last_time) < REPLY_COOLDOWN
    
    def _set_cooldown(self, user_name: str, rule_name: str):
        """设置用户冷却"""
        key = f"{user_name}:{rule_name}"
        self.reply_cooldowns[key] = time.time()
    
    def _send_reply(self, reply_text: str) -> bool:
        """发送回复消息"""
        if self.test_mode:
            logger.info(f"[测试模式] 将发送: {reply_text}")
            return True
        return send_message(self.youtube, self.live_chat_id, reply_text)
    
    def _update_obs_text(self, source_name: str, text: str) -> bool:
        """更新 OBS 文字"""
        try:
            cmd = ["python", "obs_edit_text.py", source_name, text]
            if self.test_mode:
                logger.info(f"[测试模式] 将执行: {' '.join(cmd)}")
                return True
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
                cwd=os.path.dirname(os.path.abspath(__file__))
            )
            if result.returncode == 0:
                logger.info(f"OBS 文字已更新: {source_name}")
                return True
            else:
                logger.error(f"OBS 更新失败: {result.stderr}")
                return False
        except Exception as e:
            logger.error(f"OBS 更新异常: {e}")
            return False
    
    def _process_message(self, msg: PytchatMessage):
        """处理单条消息"""
        if msg.type != "textMessage":
            return
        
        for rule in REPLY_RULES:
            if not rule.match(msg.message):
                continue
            
            if self._is_on_cooldown(msg.author_name, rule.name):
                logger.debug(f"用户 {msg.author_name} 在冷却中，跳过规则: {rule.name}")
                continue
            
            logger.info(f"匹配规则 [{rule.name}]: {msg.author_name} - {msg.message}")
            
            reply_text = rule.reply_template.format(name=msg.author_name)
            if self._send_reply(reply_text):
                logger.info(f"已回复: {reply_text}")
                self._set_cooldown(msg.author_name, rule.name)
            
            if rule.obs_source and rule.obs_template:
                obs_text = rule.obs_template.format(name=msg.author_name)
                self._update_obs_text(rule.obs_source, obs_text)
            
            break
    
    def run(self, poll_interval: float = 2.0):
        """运行机器人"""
        logger.info(f"启动自动回复机器人 - 视频: {self.video_id}")
        logger.info(f"已加载 {len(REPLY_RULES)} 条回复规则")
        for rule in REPLY_RULES:
            logger.info(f"  - {rule.name}: {rule.keywords}")
        
        if not self._init_sender():
            return
        if not self._init_pytchat():
            return
        
        logger.info("开始监听聊天消息... (Ctrl+C 退出)")
        
        try:
            while self.pytchat.is_alive():
                has_msg = False
                for msg in self.pytchat.get_chat_items():
                    has_msg = True
                    logger.debug(f"[{msg.author_name}] {msg.message}")
                    self._process_message(msg)
                
                if not has_msg:
                    time.sleep(poll_interval)
        except KeyboardInterrupt:
            logger.info("收到退出信号，停止监听")
        
        logger.info("机器人已停止")


def main():
    args = sys.argv[1:]
    
    test_mode = "--test" in args
    args = [a for a in args if a != "--test"]
    
    video_id = None
    if args and len(args[0]) == 11 and args[0].replace("-", "").replace("_", "").isalnum():
        video_id = args[0]
    
    if not video_id:
        video_id = os.environ.get("VIDEO_ID")
    
    if not video_id:
        logger.info("未指定 VIDEO_ID，尝试自动获取当前直播...")
        try:
            youtube = get_youtube_client()
            video_id = get_my_live_video_id(youtube)
        except Exception as e:
            logger.error(f"获取当前直播失败: {e}")
    
    if not video_id:
        logger.error("无法确定直播 VIDEO_ID")
        logger.info("用法: python auto_reply.py <VIDEO_ID>")
        logger.info("      python auto_reply.py --test  # 测试模式")
        return
    
    bot = AutoReplyBot(video_id, test_mode=test_mode)
    bot.run()


if __name__ == "__main__":
    main()
