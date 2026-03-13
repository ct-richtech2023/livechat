"""
结束直播脚本 - 停止 OBS 推流并将直播状态转为 complete

功能概述:
    检查状态 → 停止 OBS → 等待确认 → transition complete → 显示统计

执行流程:
    1. 获取直播当前状态（若已 complete 则直接返回）
    2. 停止 OBS 推流（若启用）
    3. 等待 YouTube 确认推流已停止
    4. transition → complete（结束直播）
    5. 获取并显示直播统计信息（观看人数、时长等）

状态说明:
    - testing/live → complete: 正常结束
    - ready/created: 直播还未开始，直接删除即可
    - complete: 已经结束，无需操作

stream 清理说明:
    本脚本不删除 stream 资源（YouTube 限制刚结束的 broadcast 绑定的 stream 不能立即删除）
    旧 stream 的清理在 start_live.py 创建新直播前进行

命令行用法:
    python end_live.py                     # 结束当前直播（自动检测）
    python end_live.py <broadcast_id>      # 结束指定直播
    python end_live.py --no-obs <id>       # 仅 API 结束，不停止 OBS
"""
import sys
import time

from loguru import logger

# 停止 OBS 后等待 YouTube 确认的时间（秒）
WAIT_AFTER_OBS_STOP_SEC = 3


def _get_broadcast_status(api, broadcast_id: str) -> str | None:
    """获取 broadcast 的 lifeCycleStatus"""
    try:
        broadcasts, _ = api.list_broadcasts(broadcast_status="all", max_results=50)
        for bc in broadcasts:
            if bc.get("id") == broadcast_id:
                return bc.get("status", {}).get("lifeCycleStatus")
    except Exception as e:
        logger.warning(f"获取直播状态失败: {e}")
    return None


def _display_statistics(api, broadcast_id: str):
    """显示直播统计信息"""
    try:
        details = api.get_live_streaming_details()
        if details:
            logger.info("===== 直播统计 =====")
            if details.concurrent_viewers is not None:
                logger.info(f"   最终观看人数: {details.concurrent_viewers}")
            if details.scheduled_start_time:
                logger.info(f"   计划开始时间: {details.scheduled_start_time}")
            if details.actual_start_time:
                logger.info(f"   实际开始时间: {details.actual_start_time}")
            if details.actual_end_time:
                logger.info(f"   实际结束时间: {details.actual_end_time}")
    except Exception as e:
        logger.debug(f"获取统计信息失败: {e}")


def end_live(
    broadcast_id: str | None = None,
    obs_stop: bool = True,
) -> bool:
    """
    结束直播：停止 OBS 推流，调用 API 将直播状态转为 complete。

    参数:
        broadcast_id: 直播 ID，不传则自动获取当前正在进行的直播
        obs_stop: 是否停止 OBS 推流（默认 True）
    
    注意：stream 资源不在此处删除（YouTube 限制刚结束的 broadcast 绑定的 stream 不能立即删除）
    清理工作在 start_live.py 创建新直播前进行

    返回:
        True 表示成功结束，False 表示失败
    """
    from live_api import YoutubeLiveAPI

    try:
        api = YoutubeLiveAPI()
    except Exception as e:
        logger.error(f"初始化 YouTube API 失败: {e}")
        return False

    # 获取 broadcast_id
    if not broadcast_id:
        broadcast_id = api.get_my_active_live_video_id()
        if not broadcast_id:
            logger.warning("未找到正在进行的直播（live 状态）")
            # 尝试获取 testing 状态的直播
            broadcasts, _ = api.list_broadcasts(broadcast_status="all", max_results=10)
            for bc in broadcasts:
                status = bc.get("status", {}).get("lifeCycleStatus")
                if status in ("testing", "liveStarting", "testStarting"):
                    broadcast_id = bc.get("id")
                    logger.info(f"找到 {status} 状态的直播: {broadcast_id}")
                    break
            if not broadcast_id:
                logger.error("未找到任何可结束的直播（testing/live 状态）")
                return False
    logger.info(f"目标直播 ID: {broadcast_id}")

    # 1. 检查当前状态
    logger.info("1. 检查直播状态...")
    status = _get_broadcast_status(api, broadcast_id)
    logger.info(f"   当前状态: {status}")

    if status == "complete":
        logger.info("   直播已经结束，无需操作")
        return True

    if status in ("created", "ready"):
        logger.warning(f"   直播处于 {status} 状态（未开播），建议直接删除而非结束")
        logger.info(f"   如需删除，请执行: api.delete_broadcast('{broadcast_id}')")
        return False

    if status not in ("testing", "testStarting", "live", "liveStarting"):
        logger.warning(f"   未知状态: {status}，尝试继续结束...")

    # 2. 停止 OBS 推流
    if obs_stop:
        logger.info("2. 停止 OBS 推流...")
        try:
            from obs import OBSCtrl
            obs = OBSCtrl()
            # get_stream_status() 返回 dataclass，属性是 output_active
            streaming = obs.get_stream_status()
            is_active = getattr(streaming, "output_active", False)
            if is_active:
                obs.stop_stream()
                logger.info("   OBS 已停止推流")
                logger.info(f"   等待 {WAIT_AFTER_OBS_STOP_SEC}s 让 YouTube 确认...")
                time.sleep(WAIT_AFTER_OBS_STOP_SEC)
            else:
                logger.info("   OBS 当前未在推流")
        except Exception as e:
            logger.warning(f"   OBS 操作失败: {e}")
            logger.info("   继续执行 API 结束...")
    else:
        logger.info("2. 跳过 OBS 停止（--no-obs）")

    # 3. transition to complete
    logger.info("3. transition → complete...")
    ok = api.transition_broadcast(broadcast_id, "complete")
    if ok:
        logger.info("   直播已结束")
    else:
        logger.error("   transition to complete 失败")
        logger.info("   可能原因: 直播状态不允许直接结束，或 API 权限问题")
        logger.info(f"   请到 YouTube Studio 手动结束，或重试")
        return False

    # 4. 显示统计信息
    logger.info("4. 获取直播统计...")
    _display_statistics(api, broadcast_id)

    return True


def main():
    argv = [a.strip() for a in sys.argv[1:] if a.strip()]
    obs_stop = True
    broadcast_id = None

    # 解析参数
    i = 0
    while i < len(argv):
        arg = argv[i].lower()
        if arg in ("--no-obs", "-n"):
            obs_stop = False
        elif not arg.startswith("-"):
            broadcast_id = argv[i]
        i += 1

    logger.info("===== 结束直播 =====")
    ok = end_live(broadcast_id=broadcast_id, obs_stop=obs_stop)
    if ok:
        logger.info("===== 完成 =====")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
