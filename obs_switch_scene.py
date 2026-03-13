"""
OBS 场景切换脚本

用法:
    python obs_switch_scene.py <场景名称>     # 切换到指定场景
    python obs_switch_scene.py --list        # 列出所有场景
    python obs_switch_scene.py               # 显示当前场景

示例:
    python obs_switch_scene.py "Video"  # 切换到 Video 场景
    python obs_switch_scene.py "Camera" # 切换到 Camera 场景
    python obs_switch_scene.py -l # 列出所有场景
"""
import sys

from loguru import logger


def main():
    from obs import OBSCtrl

    args = [a.strip() for a in sys.argv[1:] if a.strip()]

    try:
        obs = OBSCtrl()
    except Exception as e:
        logger.error(f"无法连接 OBS: {e}")
        logger.info("请确认 OBS 已启动且 WebSocket 已开启")
        sys.exit(1)

    # 无参数：显示当前场景
    if not args:
        current = obs.get_current_scene()
        logger.info(f"当前场景: {current}")
        sys.exit(0)

    # --list / -l：列出所有场景
    if args[0].lower() in ("--list", "-l"):
        scene_list = obs.get_scene_list()
        scenes = getattr(scene_list, "scenes", [])
        current = getattr(scene_list, "current_program_scene_name", "")
        
        logger.info("===== 场景列表 =====")
        for s in scenes:
            name = s.get("sceneName", s.get("name", ""))
            marker = " ← 当前" if name == current else ""
            logger.info(f"  - {name}{marker}")
        sys.exit(0)

    # 切换场景
    scene_name = args[0]
    
    # 检查场景是否存在
    scene_list = obs.get_scene_list()
    scenes = getattr(scene_list, "scenes", [])
    scene_names = [s.get("sceneName", s.get("name", "")) for s in scenes]
    
    if scene_name not in scene_names:
        logger.error(f"场景不存在: {scene_name}")
        logger.info("可用场景:")
        for name in scene_names:
            logger.info(f"  - {name}")
        sys.exit(1)

    # 执行切换
    current = obs.get_current_scene()
    if current == scene_name:
        logger.info(f"已经在场景: {scene_name}")
        sys.exit(0)

    obs.set_scene(scene_name)
    logger.info(f"场景切换: {current} → {scene_name}")


if __name__ == "__main__":
    main()
