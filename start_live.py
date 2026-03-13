"""
一键开播脚本 - 自动完成 YouTube 直播的全部创建和启动流程

功能概述:
    清理旧 stream → 创建直播 → 创建推流 → 绑定 → OBS 推流 → 等待 active → testing → live

执行流程:
    0. 检查 OBS 连接（若启用自动推流）
    0.5 清理旧 stream 资源（上次直播遗留的，YouTube 限制刚结束时不能删）
    1. 创建直播（liveBroadcast），设置标题、描述、隐私状态
    2. 创建推流（liveStream），获取推流地址和密钥
    3. 绑定直播与推流
    4. 配置 OBS 推流地址并启动推流
    5. 轮询等待 YouTube 确认推流（streamStatus=active）
    6. transition → testing（预览状态）
    7. transition → live（正式开播，观众可见）

关键说明:
    - OBS 推流后不会自动开播，必须调用 transition to live 观众才能看到
    - YouTube 状态机: created → ready → testing → live → complete
    - 不能直接从 ready 跳到 live，必须经过 testing
    - stream 必须先变为 active 才能 transition

异常处理:
    - OBS 连接失败：不创建任何资源，直接返回
    - 创建/绑定失败：自动清理已创建的直播和推流（可配置）
    - OBS 推流失败：自动清理资源
    - 用户 Ctrl+C：自动清理资源
    - transition 失败：保留资源并提示手动命令

配置参数:
    WAIT_STREAM_ACTIVE_TIMEOUT_SEC = 180  # 等待 stream active 超时（秒）
    WAIT_STREAM_ACTIVE_POLL_SEC = 3       # 轮询间隔（秒）
    GO_LIVE_RETRY_COUNT = 3               # transition to live 重试次数
    GO_LIVE_RETRY_INTERVAL_SEC = 5        # 重试间隔（秒）

前置条件:
    - client_secret.json 和 token.json 已配置（OAuth 授权）
    - OBS 已启动并开启 WebSocket（工具 → obs-websocket 设置）
    - obs.py 中 HOST/PORT/PASSWORD 与 OBS WebSocket 配置一致

用法:
    python start_live.py "直播标题"
    python start_live.py "直播标题" "直播描述"

返回值:
    成功时返回 dict，包含:
        - broadcast_id: 直播 ID
        - stream_id: 推流 ID
        - video_id: 视频 ID
        - ingestion_url: 推流地址 (rtmp://...)
        - stream_key: 推流密钥
        - live_url: 直播观看地址
    失败时返回 None
"""
import sys
import time
from datetime import datetime, timezone, timedelta

from loguru import logger

# 最长等待推流被 YouTube 识别为 active 的时间（秒）
WAIT_STREAM_ACTIVE_TIMEOUT_SEC = 180
# 轮询间隔（秒）
WAIT_STREAM_ACTIVE_POLL_SEC = 3
# OBS 开始推流后，给一点点缓冲（秒）
OBS_START_GRACE_SEC = 2
# Go Live（transition to live）失败时的重试次数与间隔（秒）
GO_LIVE_RETRY_COUNT = 3
GO_LIVE_RETRY_INTERVAL_SEC = 5


def _cleanup_old_streams(api, keep_recent: int = 1) -> int:
    """
    清理旧的 stream 资源（保留最近 N 个）。
    返回删除的数量。
    
    注意：只能删除未绑定或绑定到已完成 broadcast 且已过一段时间的 stream。
    """
    deleted_count = 0
    try:
        streams, _ = api.list_streams(max_results=50)
        if len(streams) <= keep_recent:
            return 0
        
        # 按创建时间排序（保留最近的）
        streams_sorted = sorted(
            streams,
            key=lambda s: s.get("snippet", {}).get("publishedAt", ""),
            reverse=True
        )
        
        # 跳过最近的 N 个
        to_delete = streams_sorted[keep_recent:]
        
        for stream in to_delete:
            stream_id = stream.get("id")
            stream_status = stream.get("status", {}).get("streamStatus", "")
            
            # 只删除非 active 状态的 stream
            if stream_status == "active":
                logger.debug(f"   跳过 active stream: {stream_id}")
                continue
            
            try:
                if api.delete_stream(stream_id):
                    deleted_count += 1
                    logger.info(f"   已删除旧 stream: {stream_id}")
            except Exception:
                pass  # 静默失败，可能是 YouTube 限制
                
    except Exception as e:
        logger.debug(f"清理旧 stream 失败: {e}")
    
    return deleted_count


def _check_obs_connected() -> bool:
    """检测 OBS 是否可连接（WebSocket 可达且认证成功）。"""
    try:
        from obs import OBSCtrl
        obs = OBSCtrl()
        obs.get_stream_status()
        return True
    except Exception:
        return False


def _wait_until_stream_active(api, stream_id: str, timeout_sec: int) -> bool:
    """
    轮询等待 streamStatus == active。
    返回 True 表示已 active，False 表示超时或查询失败。
    """
    start_time = time.time()
    last_status = None

    while time.time() - start_time < timeout_sec:
        elapsed = int(time.time() - start_time)
        try:
            status = api.get_stream_status(stream_id)
        except Exception as e:
            logger.warning(f"   [{elapsed}s] 查询失败: {e}")
            time.sleep(WAIT_STREAM_ACTIVE_POLL_SEC)
            continue

        if status is None:
            logger.warning(f"   [{elapsed}s] 未获取到状态，继续等待...")
            time.sleep(WAIT_STREAM_ACTIVE_POLL_SEC)
            continue

        if status != last_status:
            logger.info(f"   [{elapsed}s] streamStatus = {status}")
            last_status = status

        if status == "active":
            return True

        time.sleep(WAIT_STREAM_ACTIVE_POLL_SEC)

    return False


def _cleanup_resources(api, broadcast_id: str | None, stream_id: str | None):
    """清理已创建的直播和推流资源"""
    if broadcast_id:
        logger.info(f"   清理: 删除直播 {broadcast_id}...")
        try:
            if api.delete_broadcast(broadcast_id):
                logger.info("   清理: 直播已删除")
            else:
                logger.warning(f"   清理: 直播删除失败，请手动删除: {broadcast_id}")
        except Exception as e:
            logger.warning(f"   清理: 删除直播异常: {e}")

    if stream_id:
        logger.info(f"   清理: 删除推流 {stream_id}...")
        try:
            if api.delete_stream(stream_id):
                logger.info("   清理: 推流已删除")
            else:
                logger.warning(f"   清理: 推流删除失败，请手动删除: {stream_id}")
        except Exception as e:
            logger.warning(f"   清理: 删除推流异常: {e}")


def start_live(
    title: str,
    description: str = "",
    privacy: str = "public",
    obs_auto_start: bool = True,
    cleanup_on_failure: bool = True,
) -> dict | None:
    """
    一键开播流程：
    1. 创建直播（public）、创建推流（每次新建，避免复用固定 key）、绑定
    2. 若 obs_auto_start 且 OBS 可用：设置推流地址并开始推流
    3. 等待 stream active 后依次 transition: testing -> live（更稳）
    4. 若 OBS 不可用：只完成 1，并打印推流地址与密钥供手动在 OBS 中设置

    参数:
        cleanup_on_failure: 若为 True，在关键步骤失败时自动删除已创建的直播和推流
    """
    from live_api import YoutubeLiveAPI

    # 用于追踪已创建的资源，以便失败时清理
    broadcast_id: str | None = None
    stream_id: str | None = None
    api: YoutubeLiveAPI | None = None

    # 若需自动推流，必须先确认 OBS 可连接，否则不创建直播/推流
    if obs_auto_start:
        logger.info("0. 检查 OBS 连接...")
        if not _check_obs_connected():
            logger.error("   无法连接 OBS（请确认 OBS 已启动且已开启 obs-websocket，并检查 obs.py 中 HOST/PORT/PASSWORD）")
            return None
        logger.info("   OBS 已连接")

    try:
        # 创建新直播，不需要获取现有直播的 video_id
        api = YoutubeLiveAPI(auto_fetch_video_id=False)
    except Exception as e:
        logger.error(f"初始化 YouTube API 失败: {e}")
        return None

    # 清理旧的 stream 资源（保留最近 1 个）
    logger.info("0.5 清理旧 stream 资源...")
    deleted = _cleanup_old_streams(api, keep_recent=1)
    if deleted > 0:
        logger.info(f"   已清理 {deleted} 个旧 stream")
    else:
        logger.info("   无需清理")

    try:
        # 创建直播：开始时间设为 2 分钟后，结束时间 4 小时后
        now = datetime.now(timezone.utc)
        start = (now + timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        end = (now + timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

        logger.info(f"1. 创建直播（{privacy}）...")
        bc = api.create_broadcast(
            title,
            scheduled_start_time=start,
            scheduled_end_time=end,
            privacy_status=privacy,
            description=description,
        )
        if not bc:
            logger.error("创建直播失败")
            return None
        broadcast_id = bc["id"]
        logger.info(f"   直播ID: {broadcast_id}")

        logger.info("2. 创建推流...")
        stream = api.create_stream(title, description=description)
        if not stream:
            logger.error("创建推流失败")
            if cleanup_on_failure:
                _cleanup_resources(api, broadcast_id, None)
            return None
        stream_id = stream["id"]
        cdn = stream.get("cdn", {}).get("ingestionInfo", {})
        server = cdn.get("ingestionAddress", "rtmp://a.rtmp.youtube.com/live2")
        stream_key = cdn.get("streamName", "")
        logger.info(f"   推流ID: {stream_id}")
        logger.info(f"   推流地址: {server}")
        logger.info(f"   推流密钥: {stream_key}")

        logger.info("3. 绑定直播与推流...")
        if not api.bind_broadcast(broadcast_id, stream_id):
            logger.error("绑定失败")
            if cleanup_on_failure:
                _cleanup_resources(api, broadcast_id, stream_id)
            return None

        video_id = bc.get("id", broadcast_id)
        result = {
            "broadcast_id": broadcast_id,
            "stream_id": stream_id,
            "video_id": video_id,
            "ingestion_url": server,
            "stream_key": stream_key,
            "live_url": f"https://www.youtube.com/watch?v={video_id}",
        }

        # 如果不自动推流，就直接返回（用户自己把 server/key 填到 OBS）
        if not obs_auto_start:
            logger.info("未启用 OBS 自动推流：请手动在 OBS 中设置推流地址并开始推流，然后再 transition 到 live")
            return result

        logger.info("4. 配置 OBS 并开始推流...")
        try:
            from obs import OBSCtrl

            obs = OBSCtrl()
            obs.set_stream_service(server, stream_key)
            obs.start_stream()
            logger.info("   OBS 已开始推流")
            time.sleep(OBS_START_GRACE_SEC)
        except Exception as e:
            logger.error(f"OBS 推流失败: {e}")
            if cleanup_on_failure:
                logger.info("由于 OBS 推流失败，清理已创建的资源...")
                _cleanup_resources(api, broadcast_id, stream_id)
            else:
                logger.info("请手动在 OBS 中设置推流地址并开始推流")
                logger.info(f"推流地址: {server}")
                logger.info(f"推流密钥: {stream_key}")
            return None

        # 关键：等 YouTube 端识别推流为 active，再执行 Go Live
        logger.info(f"5. 等待 YouTube 识别推流（最长 {WAIT_STREAM_ACTIVE_TIMEOUT_SEC}s）...")
        ok_active = _wait_until_stream_active(api, stream_id, WAIT_STREAM_ACTIVE_TIMEOUT_SEC)
        if not ok_active:
            logger.warning("   等待超时，stream 未变为 active")
            logger.info("   降级处理：额外等待 12s 后尝试 Go Live...")
            time.sleep(12)

        # 必须调用 Go Live：transition to live 后观众才能看到直播（OBS 推流不会自动开播）
        logger.info("6. transition → testing...")
        if not hasattr(api, "transition_broadcast"):
            logger.warning("YoutubeLiveAPI 未实现 transition_broadcast，请在 Studio 手动点「开始直播」")
            return result

        # 第一步：必须先 transition 到 testing
        testing_ok = api.transition_broadcast(broadcast_id, "testing")
        if not testing_ok:
            logger.error("   transition to testing 失败，可能 stream 尚未 active")
            logger.info("   请确认 OBS 正在推流，然后手动执行:")
            logger.info(f"     api.transition_broadcast('{broadcast_id}', 'testing')")
            logger.info(f"     api.transition_broadcast('{broadcast_id}', 'live')")
            return result
        logger.info("   已进入 testing 状态")

        # 等待 YouTube 完成状态切换（testing 需要几秒稳定）
        logger.info("   等待 5s 让状态稳定...")
        time.sleep(5)

        # 第二步：transition 到 live
        logger.info("7. transition → live...")
        live_ok = False
        for attempt in range(1, GO_LIVE_RETRY_COUNT + 1):
            live_ok = api.transition_broadcast(broadcast_id, "live")
            if live_ok:
                logger.info(f"   开播成功: {result['live_url']}")
                break
            if attempt < GO_LIVE_RETRY_COUNT:
                logger.warning(f"   第 {attempt} 次失败，{GO_LIVE_RETRY_INTERVAL_SEC}s 后重试...")
                time.sleep(GO_LIVE_RETRY_INTERVAL_SEC)

        if not live_ok:
            logger.warning("   transition to live 失败")
            logger.info("   broadcast 当前处于 testing 状态，请手动执行:")
            logger.info(f"     api.transition_broadcast('{broadcast_id}', 'live')")

        return result

    except KeyboardInterrupt:
        logger.warning("用户中断操作")
        if cleanup_on_failure and api:
            logger.info("清理已创建的资源...")
            _cleanup_resources(api, broadcast_id, stream_id)
        raise
    except Exception as e:
        logger.error(f"开播过程异常: {e}")
        if cleanup_on_failure and api:
            logger.info("清理已创建的资源...")
            _cleanup_resources(api, broadcast_id, stream_id)
        return None


def main():
    title = (sys.argv[1] if len(sys.argv) > 1 else "").strip() or "直播"
    description = (sys.argv[2] if len(sys.argv) > 2 else "").strip()
    logger.info(f"一键开播: 标题={title}")
    res = start_live(title, description=description)
    if res:
        logger.info(f"直播页: {res.get('live_url')}")
        logger.info(f"推流地址: {res.get('ingestion_url')}")
        logger.info(f"推流密钥: {res.get('stream_key')}")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()