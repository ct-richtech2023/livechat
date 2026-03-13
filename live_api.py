"""
通过 YouTube Data API v3 获取直播相关数据

可获取的数据：
--------------------
1. 视频信息 (get_video_info)：标题、描述、频道、缩略图、直播状态
2. 直播流详情 (get_live_streaming_details)：实时观看人数、开始/结束时间、liveChatId
3. 频道统计 (get_channel_stats)：订阅数、播放量、视频数
4. 直播聊天消息 (get_live_chat_messages)：文字/打赏/贴纸/新会员等各类型消息
5. Super Chat 事件 (get_super_chat_events)：过去 30 天打赏记录

已实现的写操作：
--------------------
1. 发送消息 (liveChatMessages.insert): send_message, create_poll
2. 删除消息 (liveChatMessages.delete): delete_message
3. 封禁/解除封禁 (liveChatBans): ban_user, unban_user
4. 管理管理员 (liveChatModerators): add_moderator, remove_moderator, list_moderators
管理员权限：删除消息、封禁用户、解除封禁、发送消息、关闭投票
5. 直播管理 (liveBroadcasts): create_broadcast, update_broadcast, delete_broadcast, bind_broadcast, transition_broadcast, insert_cuepoint, list_broadcasts
6. 推流管理 (liveStreams): create_stream, update_stream, delete_stream, list_streams
7. 投票状态 (liveChatMessages.transition): transition_poll (关闭投票)

注意：需 OAuth 授权，需网络可访问 Google API
"""
from dataclasses import dataclass, field
from typing import Any
import json
import os
import re
from oauth_youtube import get_youtube_client
from sender import get_live_chat_id, _retry_request
from loguru import logger

@dataclass
class VideoInfo:
    """视频/直播基本信息"""
    video_id: str
    title: str
    description: str
    channel_id: str
    channel_title: str
    published_at: str
    thumbnails: dict
    live_broadcast_content: str  # live, none, upcoming


@dataclass
class LiveStreamingDetails:
    """直播流详情"""
    actual_start_time: str | None
    actual_end_time: str | None
    scheduled_start_time: str | None
    scheduled_end_time: str | None
    concurrent_viewers: int | None
    active_live_chat_id: str | None


@dataclass
class ChannelStats:
    """频道统计"""
    channel_id: str
    title: str
    subscriber_count: int
    view_count: int
    video_count: int


@dataclass
class ChatMessage:
    """聊天消息统一结构"""
    message_id: str
    type: str  # textMessageEvent, superChatEvent, superStickerEvent, newSponsorEvent 等
    published_at: str
    author_channel_id: str
    display_name: str
    display_message: str
    raw: dict = field(default_factory=dict)


class YoutubeLiveAPI:
    """YouTube 直播 API 封装，获取官方 API 可用的所有数据"""

    def __init__(self, video_id: str | None = None, auto_fetch_video_id: bool = True):
        """
        初始化 YouTube Live API 客户端。
        
        参数:
            video_id: 直播视频 ID，若不传且 auto_fetch_video_id=True 则自动获取当前直播
            auto_fetch_video_id: 是否自动获取当前直播的 video_id（创建新直播时可设为 False）
        """
        self._youtube = get_youtube_client()
        self._live_chat_id = None
        if video_id:
            self.video_id = video_id
        elif auto_fetch_video_id:
            # 未传则在线获取：优先当前直播，否则即将开始的直播
            self.video_id = self._fetch_my_live_video_id() or ""
            if self.video_id:
                logger.info(f"获取到当前/即将直播的 video_id: {self.video_id}")
            else:
                logger.warning("未传入 video_id 且未获取到当前/即将直播，后续需 video_id 的接口可能失败")
        else:
            self.video_id = ""

    def _fetch_my_live_video_id(self) -> str | None:
        """内部：获取当前账号的直播 video_id（active 或 upcoming）"""
        items, _ = self._list_broadcasts_raw(mine=True, max_results=10)
        status_priority = ("live", "testing", "liveStarting", "testStarting", "ready", "created")
        for status in status_priority:
            for it in items:
                if (it.get("status") or {}).get("lifeCycleStatus") == status:
                    return it.get("id")
        return None

    def _req(self, func):
        return _retry_request(func)

    def get_video_info(self) -> VideoInfo | None:
        """获取视频基本信息"""
        def _do():
            return self._youtube.videos().list(
                part="snippet",
                id=self.video_id
            ).execute()

        resp = self._req(_do)
        items = resp.get("items", [])
        if not items:
            return None
        s = items[0]["snippet"]
        return VideoInfo(
            video_id=self.video_id,
            title=s.get("title", ""),
            description=s.get("description", ""),
            channel_id=s.get("channelId", ""),
            channel_title=s.get("channelTitle", ""),
            published_at=s.get("publishedAt", ""),
            thumbnails=s.get("thumbnails", {}),
            live_broadcast_content=s.get("liveBroadcastContent", "none"),
        )

    def get_live_streaming_details(self) -> LiveStreamingDetails | None:
        """获取直播流详情（含实时观看人数、liveChatId）"""
        def _do():
            return self._youtube.videos().list(part="liveStreamingDetails", id=self.video_id).execute()

        resp = self._req(_do)
        items = resp.get("items", [])
        if not items:
            return None
        d = items[0].get("liveStreamingDetails", {})
        cv = d.get("concurrentViewers")
        return LiveStreamingDetails(
            actual_start_time=d.get("actualStartTime"),
            actual_end_time=d.get("actualEndTime"),
            scheduled_start_time=d.get("scheduledStartTime"),
            scheduled_end_time=d.get("scheduledEndTime"),
            concurrent_viewers=int(cv) if cv else None,
            active_live_chat_id=d.get("activeLiveChatId"),
        )

    def get_channel_stats(self) -> ChannelStats | None:
        """获取频道统计（订阅数、播放量、视频数）"""
        info = self.get_video_info()
        if not info:
            return None

        def _do():
            return self._youtube.channels().list(
                part="snippet,statistics",
                id=info.channel_id
            ).execute()

        resp = self._req(_do)
        items = resp.get("items", [])
        if not items:
            return None
        s = items[0].get("statistics", {})
        sn = items[0].get("snippet", {})
        return ChannelStats(
            channel_id=info.channel_id,
            title=sn.get("title", ""),
            subscriber_count=int(s.get("subscriberCount", 0) or 0),
            view_count=int(s.get("viewCount", 0) or 0),
            video_count=int(s.get("videoCount", 0) or 0),
        )

    def get_live_chat_id(self) -> str | None:
        """获取直播聊天 ID，缓存结果"""
        if not self._live_chat_id:
            self._live_chat_id = get_live_chat_id(self._youtube, self.video_id)
        return self._live_chat_id

    def get_live_chat_messages(self, live_chat_id: str | None = None, max_results: int = 200, page_token: str | None = None) -> tuple[list[ChatMessage], str | None]:
        """
        获取直播聊天消息。
        返回 (消息列表, 下一页 token)
        """
        cid = live_chat_id or self.get_live_chat_id()
        if not cid:
            return [], None

        def _do():
            return self._youtube.liveChatMessages().list(
                liveChatId=cid,
                part="snippet,authorDetails",
                maxResults=min(max_results, 2000),
                pageToken=page_token or "",
            ).execute()

        resp = self._req(_do)
        items = resp.get("items", [])
        next_token = resp.get("nextPageToken")

        messages = []
        for it in items:
            sn = it.get("snippet", {})
            auth = it.get("authorDetails", {})
            msg = ChatMessage(
                message_id=it.get("id", ""),
                type=sn.get("type", ""),
                published_at=sn.get("publishedAt", ""),
                author_channel_id=auth.get("channelId", "") or sn.get("authorChannelId", ""),
                display_name=auth.get("displayName", ""),
                display_message=sn.get("displayMessage", ""),
                raw=it,
            )
            messages.append(msg)

        return messages, next_token

    def get_all_live_chat_messages(self, live_chat_id: str | None = None, max_pages: int = 10) -> list[ChatMessage]:
        """分页获取所有聊天消息"""
        cid = live_chat_id or self.get_live_chat_id()
        if not cid:
            return []

        all_msgs = []
        token = None
        for _ in range(max_pages):
            msgs, token = self.get_live_chat_messages(cid, page_token=token)
            all_msgs.extend(msgs)
            if not token:
                break
        return all_msgs

    def get_super_chat_events(self, max_results: int = 50) -> list[dict]:
        """
        获取 Super Chat 事件（过去 30 天内，需频道主授权）
        """
        try:
            def _do():
                return self._youtube.superChatEvents().list(
                    part="snippet",
                    maxResults=max_results,
                ).execute()

            resp = self._req(_do)
            return resp.get("items", [])
        except Exception:
            return []

    # ---------- liveChatMessages 写操作 ----------

    def send_message(self, message_text: str, live_chat_id: str | None = None) -> dict | None:
        """
        发送文字消息到直播聊天。需频道主或管理员。
        返回插入的消息，失败返回 None。
        """
        
        cid = live_chat_id or self.get_live_chat_id()
        if not cid:
            logger.warning("无 live_chat_id")
            return None
        logger.info(f"发送消息: {message_text}, live_chat_id: {cid}")

        def _do():
            return self._youtube.liveChatMessages().insert(
                part="snippet",
                body={
                    "snippet": {
                        "liveChatId": cid,
                        "type": "textMessageEvent",
                        "textMessageDetails": {"messageText": message_text},
                    }
                },
            ).execute()

        try:
            return self._req(_do)
        except Exception as e:
            logger.error(f"发送消息失败: {e}")
            return None

    def create_poll(self, question: str, options: list[str], live_chat_id: str | None = None) -> dict | None:
        """
        创建直播投票。需频道主或管理员。
        options: 选项列表，2-4 项。
        返回插入的消息（含 poll 信息），失败返回 None。
        """
        cid = live_chat_id or self.get_live_chat_id()
        if not cid:
            logger.warning("无 live_chat_id")
            return None
        logger.info(f"创建投票: {question}, options: {options}, live_chat_id: {cid}")
        # API schema: metadata.options 为对象数组，每项 {optionText}；questionText 与 options 同级
        # 选项需 2-4 个
        opts = [{"optionText": t} for t in options[:4]]
        if len(opts) < 2:
            logger.warning("投票选项需至少 2 个，最多 4 个")
            return None

        def _do():
            return self._youtube.liveChatMessages().insert(
                part="snippet",
                body={
                    "snippet": {
                        "liveChatId": cid,
                        "type": "pollEvent",
                        "pollDetails": {
                            "metadata": {
                                "questionText": question,
                                "options": opts,
                            },
                        },
                    }
                },
            ).execute()

        try:
            return self._req(_do)
        except Exception as e:
            logger.error(f"创建投票失败: {e}")
            return None

    def delete_message(self, message_id: str) -> dict | None:
        """删除指定聊天消息。需频道主或管理员。"""
        logger.info(f"删除消息: {message_id}")
        def _do():
            self._youtube.liveChatMessages().delete(id=message_id).execute()
            return True

        try:
            return self._req(_do)
        except Exception as e:
            logger.error(f"删除消息失败: {e}")
            return None

    def transition_poll(self, poll_message_id: str, status: str = "closed") -> dict | None:
        """
        转换投票状态，如关闭投票。status 一般为 "closed"。
        返回更新后的消息（含 poll 结果），失败返回 None。
        """
        def _do():
            return self._youtube.liveChatMessages().transition(
                id=poll_message_id,
                status=status,
            ).execute()

        try:
            return self._req(_do)
        except Exception as e:
            logger.error(f"转换投票状态失败: {e}")
            return None

    # ---------- liveChatBans ----------

    def ban_user(self, channel_id: str, ban_type: str = "permanent", ban_duration_seconds: int | None = None, live_chat_id: str | None = None) -> dict | None:
        """
        封禁用户。ban_type: "permanent" 或 "temporary"。
        临时封禁需提供 ban_duration_seconds。
        返回封禁记录，失败返回 None。
        """
        cid = live_chat_id or self.get_live_chat_id()
        if not cid:
            logger.warning("无 live_chat_id")
            return None
        
        snippet: dict = {
            "liveChatId": cid,
            "bannedUserDetails": {"channelId": channel_id},
            "type": ban_type,
        }
        if ban_type == "temporary" and ban_duration_seconds is not None:
            snippet["banDurationSeconds"] = str(ban_duration_seconds)

        logger.info(f"封禁用户: {channel_id}, ban_type: {ban_type}, ban_duration_seconds: {ban_duration_seconds}, live_chat_id: {cid}")
        def _do():
            return self._youtube.liveChatBans().insert(
                part="snippet",
                body={"snippet": snippet},
            ).execute()

        try:
            return self._req(_do)
        except Exception as e:
            logger.error(f"封禁用户失败: {e}")
            return None

    def unban_user(self, ban_id: str) -> bool:
        """解除封禁。ban_id 为封禁时返回的 id。"""
        def _do():
            self._youtube.liveChatBans().delete(id=ban_id).execute()
            return True

        try:
            self._req(_do)
            return True
        except Exception as e:
            logger.error(f"解除封禁失败: {e}")
            return False

    # ---------- liveChatModerators ----------

    def add_moderator(self, channel_id: str, live_chat_id: str | None = None) -> dict | None:
        """添加管理员。返回新管理员记录，失败返回 None。"""
        cid = live_chat_id or self.get_live_chat_id()
        if not cid:
            logger.warning("无 live_chat_id")
            return None
        logger.info(f"添加管理员: {channel_id}, live_chat_id: {cid}")
        def _do():
            return self._youtube.liveChatModerators().insert(
                part="snippet",
                body={
                    "snippet": {
                        "liveChatId": cid,
                        "moderatorDetails": {"channelId": channel_id},
                    }
                },
            ).execute()

        try:
            return self._req(_do)
        except Exception as e:
            logger.error(f"添加管理员失败: {e}")
            return None

    def remove_moderator(self, moderator_id: str) -> bool:
        """移除管理员。moderator_id 为管理员记录的 id。"""
        def _do():
            self._youtube.liveChatModerators().delete(id=moderator_id).execute()
            return True

        try:
            self._req(_do)
            return True
        except Exception as e:
            logger.error(f"移除管理员失败: {e}")
            return False

    def list_moderators(self, live_chat_id: str | None = None, max_results: int = 50, page_token: str | None = None) -> tuple[list[dict], str | None]:
        """
        列出管理员。
        返回 (管理员列表, 下一页 token)。
        """
        cid = live_chat_id or self.get_live_chat_id()
        if not cid:
            return [], None

        def _do():
            return self._youtube.liveChatModerators().list(
                liveChatId=cid,
                part="snippet",
                maxResults=min(max_results, 50),
                pageToken=page_token or "",
            ).execute()

        try:
            resp = self._req(_do)
            return resp.get("items", []), resp.get("nextPageToken")
        except Exception as e:
            logger.error(f"列出管理员失败: {e}")
            return [], None

    # ---------- liveBroadcasts ----------

    def create_broadcast(
        self,
        title: str,
        scheduled_start_time: str,
        scheduled_end_time: str | None = None,
        privacy_status: str = "private",
        description: str = "",
        enable_dvr: bool = True,
        record_from_start: bool = True,
        enable_embed: bool = False,
        made_for_kids: bool = False,
    ) -> dict | None:
        """
        创建直播。scheduled_start_time/scheduled_end_time 为 ISO 8601 格式。
        scheduled_start_time 须为将来时间且不能太远（否则 invalidScheduledStartTime）。
        privacy_status: "public" | "unlisted" | "private"。
        enable_embed: 默认 False。True 需账号在 YouTube 功能页开启「嵌入直播」，否则会报 invalidEmbedSetting。
        made_for_kids: 是否为儿童内容（COPPA），默认 False（非儿童内容）。
        返回创建的 broadcast，失败返回 None。
        """
        body: dict = {
            "snippet": {
                "title": title,
                "scheduledStartTime": scheduled_start_time,
                **({"scheduledEndTime": scheduled_end_time} if scheduled_end_time else {}),
                "description": description or "",
            },
            "status": {
                "privacyStatus": privacy_status,
                "selfDeclaredMadeForKids": made_for_kids,
            },
            "contentDetails": {
                "enableDvr": enable_dvr,
                "recordFromStart": record_from_start,
                "enableEmbed": enable_embed,
            },
        }

        def _do():
            return self._youtube.liveBroadcasts().insert(
                part="snippet,status,contentDetails",
                body=body,
            ).execute()

        try:
            return self._req(_do)
        except Exception as e:
            logger.error(f"创建直播失败: {e}")
            return None

    def update_broadcast(
        self,
        broadcast_id: str,
        title: str | None = None,
        description: str | None = None,
        scheduled_start_time: str | None = None,
        scheduled_end_time: str | None = None,
        privacy_status: str | None = None,
    ) -> dict | None:
        """
        更新直播。仅传入需要修改的字段。
        API 要求：若更新 snippet，请求体须包含 scheduledStartTime 等必填项，故会先拉取当前 broadcast 再合并。
        """
        body: dict = {"id": broadcast_id}
        need_snippet = any(x is not None for x in (title, description, scheduled_start_time, scheduled_end_time))
        need_status = privacy_status is not None

        if not need_snippet and not need_status:
            return self._get_broadcast(broadcast_id)

        if need_snippet or need_status:
            current = self._get_broadcast(broadcast_id)
            if not current:
                logger.error("更新直播失败: 未找到该 broadcast")
                return None
            if need_snippet:
                sn = current.get("snippet", {})
                body["snippet"] = {
                    "title": title if title is not None else sn.get("title", ""),
                    "description": description if description is not None else sn.get("description", ""),
                    "scheduledStartTime": scheduled_start_time if scheduled_start_time is not None else sn.get("scheduledStartTime", ""),
                    "scheduledEndTime": scheduled_end_time if scheduled_end_time is not None else sn.get("scheduledEndTime", ""),
                }
            if need_status:
                st = current.get("status", {})
                body["status"] = {
                    "privacyStatus": privacy_status if privacy_status is not None else st.get("privacyStatus", "private"),
                }

        part = ",".join(p for p in ("snippet", "status") if p in body)

        def _do():
            return self._youtube.liveBroadcasts().update(
                part=part,
                body=body,
            ).execute()

        try:
            return self._req(_do)
        except Exception as e:
            logger.error(f"更新直播失败: {e}")
            return None

    def _get_broadcast(self, broadcast_id: str) -> dict | None:
        """内部：获取单个 broadcast"""
        def _do():
            return self._youtube.liveBroadcasts().list(
                part="snippet,status,contentDetails",
                id=broadcast_id,
            ).execute()

        resp = self._req(_do)
        items = resp.get("items", [])
        return items[0] if items else None

    def delete_broadcast(self, broadcast_id: str) -> bool:
        """删除直播。"""
        def _do():
            self._youtube.liveBroadcasts().delete(id=broadcast_id).execute()
            return True

        try:
            self._req(_do)
            return True
        except Exception as e:
            logger.error(f"删除直播失败: {e}")
            return False

    def bind_broadcast(self, broadcast_id: str, stream_id: str | None = None) -> dict | None:
        """
        绑定直播与推流。stream_id 为空则解除绑定。
        返回更新后的 broadcast。
        """
        kwargs: dict = {"id": broadcast_id, "part": "snippet,contentDetails"}
        if stream_id is not None:
            kwargs["streamId"] = stream_id

        def _do():
            return self._youtube.liveBroadcasts().bind(**kwargs).execute()

        try:
            return self._req(_do)
        except Exception as e:
            logger.error(f"绑定直播失败: {e}")
            return None

    def transition_broadcast(self, broadcast_id: str, broadcast_status: str) -> dict | None:
        """
        转换直播状态。broadcast_status: "testing" | "live" | "complete"。
        返回更新后的 broadcast。
        """
        def _do():
            return self._youtube.liveBroadcasts().transition(
                id=broadcast_id,
                broadcastStatus=broadcast_status,
                part="snippet,status,contentDetails",
            ).execute()

        try:
            return self._req(_do)
        except Exception as e:
            logger.error(f"转换直播状态失败: {e}")
            return None

    def insert_cuepoint(self, broadcast_id: str, *, cue_type: str = "cueTypeAd", duration_secs: int | None = None, insertion_offset_time_ms: str | None = None, walltime_ms: str | None = None) -> dict | None:
        """
        插入广告断点 (cuepoint)。
        duration_secs: 广告时长（秒）。
        insertion_offset_time_ms 或 walltime_ms 二选一指定插入时间。
        返回创建的 cuepoint，失败返回 None。
        """
        body: dict = {"cueType": cue_type}
        if duration_secs is not None:
            body["durationSecs"] = duration_secs
        if insertion_offset_time_ms is not None:
            body["insertionOffsetTimeMs"] = str(insertion_offset_time_ms)
        elif walltime_ms is not None:
            body["walltimeMs"] = str(walltime_ms)

        def _do():
            return self._youtube.liveBroadcasts().insertCuepoint(
                id=broadcast_id,
                body=body,
            ).execute()

        try:
            return self._req(_do)
        except Exception as e:
            logger.error(f"插入 cuepoint 失败: {e}")
            return None

    def get_my_active_live_video_id(self) -> str | None:
        """
        获取当前账号正在进行中的直播视频 ID。
        需 OAuth 授权且为频道主。无直播时返回 None。
        """
        items, _ = self.list_broadcasts(broadcast_status="active", max_results=1)
        return items[0]["id"] if items else None

    def get_my_upcoming_live_video_id(self) -> str | None:
        """
        获取当前账号即将开始的直播视频 ID（取最近一场）。
        无即将开始的直播时返回 None。
        """
        items, _ = self.list_broadcasts(broadcast_status="upcoming", max_results=1)
        return items[0]["id"] if items else None

    def list_broadcasts(self, broadcast_status: str | None = None, broadcast_type: str = "event", mine: bool = True, max_results: int = 5, page_token: str | None = None) -> tuple[list[dict], str | None]:
        """
        列出直播。broadcast_status: "all"|"active"|"upcoming"|"completed"。
        broadcast_type: "all"|"event"|"persistent"。
        注：mine=True 时 API 不支持 broadcastStatus，会在客户端按 lifeCycleStatus 过滤。
        返回 (列表, 下一页 token)。
        """
        # mine 与 broadcastStatus 互斥，mine 时需客户端过滤
        if mine and broadcast_status and broadcast_status != "all":
            status_map = {
                "active": ["live"],
                "upcoming": ["ready", "created", "testing", "testStarting", "liveStarting"],
                "completed": ["complete"],
            }
            want_statuses = status_map.get(broadcast_status, [])
            all_items, next_token = [], page_token
            while len(all_items) < max_results:
                items, next_token = self._list_broadcasts_raw(
                    broadcast_type=broadcast_type,
                    mine=True,
                    max_results=min(50, max_results * 3),  # 多取以便过滤
                    page_token=next_token,
                )
                for it in items:
                    lc = (it.get("status") or {}).get("lifeCycleStatus", "")
                    if lc in want_statuses:
                        all_items.append(it)
                        if len(all_items) >= max_results:
                            break
                if not next_token:
                    break
            return all_items[:max_results], next_token

        kwargs: dict = {
            "part": "snippet,status,contentDetails",
            "broadcastType": broadcast_type,
            "mine": mine,
            "maxResults": min(max_results, 50),
        }
        # mine 与 broadcastStatus 互斥，mine=True 时不能传 broadcastStatus
        if broadcast_status and not mine:
            kwargs["broadcastStatus"] = broadcast_status
        if page_token:
            kwargs["pageToken"] = page_token

        def _do():
            return self._youtube.liveBroadcasts().list(**kwargs).execute()

        try:
            resp = self._req(_do)
            return resp.get("items", []), resp.get("nextPageToken")
        except Exception as e:
            logger.error(f"列出直播失败: {e}")
            return [], None

    def _list_broadcasts_raw(self, broadcast_type: str = "event", mine: bool = True, max_results: int = 50, page_token: str | None = None) -> tuple[list[dict], str | None]:
        """内部：不带 broadcastStatus 的 list 调用"""
        kwargs = {
            "part": "snippet,status,contentDetails",
            "broadcastType": broadcast_type,
            "mine": mine,
            "maxResults": max_results,
        }
        if page_token:
            kwargs["pageToken"] = page_token
        try:
            resp = self._req(lambda: self._youtube.liveBroadcasts().list(**kwargs).execute())
            return resp.get("items", []), resp.get("nextPageToken")
        except Exception as e:
            logger.error(f"列出直播失败: {e}")
            return [], None

    # ---------- liveStreams ----------

    def create_stream(
        self,
        title: str,
        description: str = "",
        ingestion_type: str = "rtmp",
        resolution: str = "1080p",
        frame_rate: str = "30fps",
    ) -> dict | None:
        """
        创建推流。ingestion_type: "rtmp"|"dash"|"webrtc"|"hls"。
        resolution: "240p"|"360p"|"480p"|"720p"|"1080p"|"1440p"|"2160p"|"variable"。
        frame_rate: "30fps"|"60fps"|"variable"。
        返回创建的 stream（含 ingestion 地址），失败返回 None。
        """
        body = {
            "snippet": {"title": title, "description": description or ""},
            "cdn": {
                "ingestionType": ingestion_type,
                "resolution": resolution,
                "frameRate": frame_rate,
            },
        }

        def _do():
            return self._youtube.liveStreams().insert(
                part="snippet,cdn,status",
                body=body,
            ).execute()

        try:
            return self._req(_do)
        except Exception as e:
            logger.error(f"创建推流失败: {e}")
            return None

    def update_stream(self, stream_id: str, title: str | None = None, description: str | None = None) -> dict | None:
        """更新推流。"""
        body: dict = {"id": stream_id}
        if title is not None:
            body.setdefault("snippet", {})["title"] = title
        if description is not None:
            body.setdefault("snippet", {})["description"] = description

        if "snippet" not in body:
            return self._get_stream(stream_id)

        def _do():
            return self._youtube.liveStreams().update(
                part="snippet",
                body=body,
            ).execute()

        try:
            return self._req(_do)
        except Exception as e:
            logger.error(f"更新推流失败: {e}")
            return None

    def _get_stream(self, stream_id: str) -> dict | None:
        """内部：获取单个 stream"""
        def _do():
            return self._youtube.liveStreams().list(
                part="snippet,cdn,status",
                id=stream_id,
            ).execute()

        resp = self._req(_do)
        items = resp.get("items", [])
        return items[0] if items else None

    def get_stream(self, stream_id: str) -> dict | None:
        """
        获取单个推流的完整信息。
        返回包含 snippet, cdn, status 的 dict，失败返回 None。
        """
        try:
            return self._get_stream(stream_id)
        except Exception as e:
            logger.error(f"获取推流信息失败: {e}")
            return None

    def get_stream_status(self, stream_id: str) -> str | None:
        """
        获取推流状态。
        返回 streamStatus: "active" | "inactive" | "created" | "error"，失败返回 None。
        """
        stream = self.get_stream(stream_id)
        if not stream:
            return None
        return stream.get("status", {}).get("streamStatus")

    def delete_stream(self, stream_id: str) -> bool:
        """删除推流。"""
        def _do():
            self._youtube.liveStreams().delete(id=stream_id).execute()
            return True

        try:
            self._req(_do)
            return True
        except Exception as e:
            logger.error(f"删除推流失败: {e}")
            return False

    def list_streams(self, *, mine: bool = True, max_results: int = 5, page_token: str | None = None) -> tuple[list[dict], str | None]:
        """列出推流。返回 (列表, 下一页 token)。"""
        kwargs: dict = {
            "part": "snippet,cdn,status",
            "mine": mine,
            "maxResults": min(max_results, 50),
        }
        if page_token:
            kwargs["pageToken"] = page_token

        def _do():
            return self._youtube.liveStreams().list(**kwargs).execute()

        try:
            resp = self._req(_do)
            return resp.get("items", []), resp.get("nextPageToken")
        except Exception as e:
            logger.error(f"列出推流失败: {e}")
            return [], None

    def fetch_all(self) -> dict[str, Any]:
        """一次性获取所有可获取的数据"""
        video_info = self.get_video_info()
        streaming = self.get_live_streaming_details()
        channel = self.get_channel_stats()
        live_chat_id = self.get_live_chat_id()

        chat_messages = []
        if live_chat_id:
            msgs, _ = self.get_live_chat_messages(live_chat_id, max_results=500)
            chat_messages = [
                {
                    "message_id": m.message_id,
                    "type": m.type,
                    "published_at": m.published_at,
                    "author_channel_id": m.author_channel_id,
                    "display_name": m.display_name,
                    "display_message": m.display_message,
                }
                for m in msgs
            ]

        broadcast_status = None
        if self.video_id:
            bc = self._get_broadcast(self.video_id)
            if bc and bc.get("status"):
                broadcast_status = bc["status"].get("lifeCycleStatus")

        return {
            "video_info": video_info.__dict__ if video_info else None,
            "live_streaming_details": streaming.__dict__ if streaming else None,
            "channel_stats": channel.__dict__ if channel else None,
            "live_chat_id": live_chat_id,
            "chat_messages": chat_messages,
            "super_chat_events": self.get_super_chat_events(),
            "broadcast_status": broadcast_status,
        }

    def print_summary(self, data: dict | None = None) -> None:
        """汇总并打印数据"""
        if data is None:
            data = self.fetch_all()

        logger.info("=" * 60)
        logger.info("YouTube 直播数据汇总")
        logger.info("=" * 60)

        # 视频信息
        vi = data.get("video_info")
        if vi:
            logger.info("【视频信息】")
            logger.info(f"  视频ID: {vi.get('video_id')}")
            logger.info(f"  标题: {vi.get('title')}")
            logger.info(f"  频道: {vi.get('channel_title')}")
            logger.info(f"  发布时间: {vi.get('published_at')}")
            # 与 list_broadcasts 一致：优先用 broadcast 的 lifeCycleStatus
            status = data.get("broadcast_status") or vi.get("live_broadcast_content")
            logger.info(f"  直播状态: {status}")
        else:
            logger.info("【视频信息】 无")

        # 直播流详情
        ls = data.get("live_streaming_details")
        if ls:
            logger.info("【直播流】")
            logger.info(f"  实时观看人数: {ls.get('concurrent_viewers', '-')}")
            logger.info(f"  开始时间: {ls.get('actual_start_time', '-')}")
            logger.info(f"  结束时间: {ls.get('actual_end_time', '-')}")
        else:
            logger.info("【直播流】 无（可能未在直播）")

        # 频道统计
        ch = data.get("channel_stats")
        if ch:
            logger.info("【频道统计】")
            logger.info(f"  订阅数: {ch.get('subscriber_count')}")
            logger.info(f"  总播放量: {ch.get('view_count')}")
            logger.info(f"  视频数: {ch.get('video_count')}")
        else:
            logger.info("【频道统计】 无")

        # 聊天消息
        msgs = data.get("chat_messages", [])
        logger.info(f"【聊天消息】 共 {len(msgs)} 条")
        for i, m in enumerate(msgs[:20], 1):
            logger.info(f"  {i}. [{m.get('type', '')}] {m.get('display_name')}: {m.get('display_message')}")
        if len(msgs) > 20:
            logger.info(f"  ... 还有 {len(msgs) - 20} 条")
        if msgs:
            last = msgs[-1]
            logger.info(f"  最后一条消息: {json.dumps(last, ensure_ascii=False, indent=4)}")
        

        # 发言者名称及留言数量
        name_count: dict[str, int] = {}
        for m in msgs:
            name = m.get("display_name") or "(未知)"
            name_count[name] = name_count.get(name, 0) + 1
        if name_count:
            logger.info(f"【发言者统计】 共 {len(name_count)} 人")
            for name, cnt in sorted(name_count.items(), key=lambda x: -x[1]):
                logger.info(f"  {name}: {cnt} 条")

        # Super Chat
        sc = data.get("super_chat_events", [])
        logger.info(f"【Super Chat】 共 {len(sc)} 条")
        for i, e in enumerate(sc[:5], 1):
            sn = e.get("snippet", {})
            logger.info(f"  {i}. {sn.get('supporterDetails', {}).get('displayName')} {sn.get('amountDisplayString')} {sn.get('commentText', '')}")
        if len(sc) > 5:
            logger.info(f"  ... 还有 {len(sc) - 5} 条")

        logger.info("=" * 60)


if __name__ == "__main__":
    # VIDEO_ID="ttlT7tBAd6I"
    api = YoutubeLiveAPI()

    data = api.fetch_all()
    api.print_summary(data)

    # 发送消息
    # api.send_message("Hello, world!", live_chat_id=api.get_live_chat_id())
    # # 创建投票
    # api.create_poll("What is your favorite color?", ["Red", "Green", "Blue"])
    # # 删除消息
    # api.delete_message("LCC.EhwKGkNPU041c2I0MEpJREZZM3p3Z1FkeXNzNUl3")
    # # 封禁用户 （注意：必须要保存band_id，后续解除封禁需要用到）
    # band_response = api.ban_user("UCoYq-X2rDDHRYwq0FHDueUg", ban_type="permanent")
    # logger.info(f"封禁用户响应: {json.dumps(band_response, ensure_ascii=False, indent=4)}")
    # 临时封禁 5 分钟
    # band_response = api.ban_user("UCoYq-X2rDDHRYwq0FHDueUg", ban_type="temporary", ban_duration_seconds=30)
    # logger.info(f"封禁用户响应: {json.dumps(band_response, ensure_ascii=False, indent=4)}")
    # # 解除封禁
    # api.unban_user("UCoYq-X2rDDHRYwq0FHDueUg")

    # 添加管理员
    # api.add_moderator("UCoYq-X2rDDHRYwq0FHDueUg")
    # # 删除管理员
    # api.remove_moderator(moderator_id="CjgKDQoLdHRsVDd0QkFkNkkqJwoYVUM0WmxQQ0dMVTZHSXdfVFhpTl9oMDl3Egt0dGxUN3RCQWQ2SRIYVUNwdDBtQ2VicDJYcGtPUnZOckQ1TWdB")
    # # 列出管理员
    # moderators = api.list_moderators()
    # logger.info(f"管理员列表: {moderators}")


    # -------------------------------------------------------------
    # 方式 1：创建直播时保存
    # res = api.create_broadcast("标题", "2026-02-15T20:00:00.000Z")
    # broadcast_id = res["id"]
    # logger.info(f"直播ID: {broadcast_id}")
    # # 方式 2：从当前/即将直播获取
    # broadcast_id = api.get_my_active_live_video_id()
    # logger.info(f"当前直播ID: {broadcast_id}")
    # # 或
    # broadcast_id = api.get_my_upcoming_live_video_id()
    # logger.info(f"即将直播ID: {broadcast_id}")
    # # 方式 3：从直播列表获取
    # items, _ = api.list_broadcasts(broadcast_status="all", max_results=10)
    # for b in items:
    #     broadcast_id = b["id"]
    #     logger.info(f"直播ID: {broadcast_id}")
    #     break
    # -------------------------------------------------------------
    # 创建直播（scheduledStartTime 须为将来且不能太远，否则 invalidScheduledStartTime）
    # 使用动态时间：当前 UTC +1h 开始、+3h 结束，避免固定时间已过期
    # from datetime import datetime, timezone, timedelta
    # _now = datetime.now(timezone.utc)
    # _start = (_now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    # _end = (_now + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    # res = api.create_broadcast("Broadcast 20260224 002", _start, _end)
    # if res:
    #     broadcast_id = res["id"]
        # api.bind_broadcast(broadcast_id, stream_id="xxx")
    # else:
    #     logger.error("创建直播失败，请检查 scheduledStartTime 是否为将来时间")
    # # 更新直播
    # api.update_broadcast("s0dNAE16YJo", title="Updated Broadcast")
    # # 删除直播
    # api.delete_broadcast("1234567890")
    # 绑定直播
    # api.bind_broadcast("JOxvQu7SS1k", stream_id="4ZlPCGLU6GIw_TXiN_h09w1771924347622456")
    # # # 转换直播状态
    # api.transition_broadcast("s0dNAE16YJo", "complete")
    # # 插入 cuepoint 广告类型 插入时间 10秒后 广告时长 10秒 【只能在 直播正在推流时 插入 cuepoint】
    # api.insert_cuepoint("s0dNAE16YJo", cue_type="cueTypeAd", duration_secs=10, insertion_offset_time_ms="10000", walltime_ms="10000")
    # # 列出直播
    logger.info("-" * 30 + "直播列表" + "-" * 30)
    items, _ = api.list_broadcasts()
    for b in items:
        logger.info(f"直播ID: {b['id']}")
        logger.info(f"直播标题: {b['snippet']['title']}")
        logger.info(f"直播描述: {b['snippet']['description']}")
        logger.info(f"直播状态: {b['status']['lifeCycleStatus']}")
        logger.info(f"直播创建时间: {b['snippet']['publishedAt']}")
        # logger.info(f"直播更新时间: {b['snippet']['updatedAt']}")
        logger.info("*" * 60)


    # -------------------------------------------------------------
    # 创建推流
    # res = api.create_stream("my_stream 20260224 002", resolution="1080p", frame_rate="30fps")
    # if res:
    #     stream_id = res["id"]
    #     # 推流地址
    #     ingestion = res.get("cdn", {}).get("ingestionInfo", {})
    #     url = ingestion.get("ingestionAddress")
    #     key = ingestion.get("streamName")
    #     logger.info(f"推流ID: {stream_id}")
    #     logger.info(f"推流地址: {url}")
    #     logger.info(f"推流密钥: {key}")
    # else:
    #     logger.error("创建推流失败")
    # # 更新推流
    # api.update_stream(stream_id="4ZlPCGLU6GIw_TXiN_h09w1770969320063637", title="my_stream_updated", description="my_stream_updated_description")
    # # # 删除推流
    # api.delete_stream("4ZlPCGLU6GIw_TXiN_h09w1770969107022081")
    # # # 列出推流
    logger.info("-" * 30 + "推流列表" + "-" * 30)
    items, _ = api.list_streams(mine=True, max_results=10)
    for s in items:
        logger.info(f"推流ID: {s['id']}")
        logger.info(f"推流标题: {s['snippet']['title']}")
        logger.info(f"推流描述: {s['snippet']['description']}")
        logger.info(f"推流状态: {s['status']['streamStatus']}")
        logger.info(f"推流创建时间: {s['snippet']['publishedAt']}")
        logger.info(f"推流地址: {s['cdn']['ingestionInfo']['ingestionAddress']}")
        logger.info(f"推流密钥: {s['cdn']['ingestionInfo']['streamName']}")
        logger.info("-" * 60)
