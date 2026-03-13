"""
OBS 文字源编辑脚本 - 修改文字内容和字体设置

用法:
    python obs_edit_text.py <源名称> <文字内容>              # 修改文字内容
    python obs_edit_text.py <源名称> <文字内容> --size 48   # 修改内容并设置字号
    python obs_edit_text.py <源名称> <文字内容> --font "微软雅黑" --size 36
    python obs_edit_text.py --list                          # 列出文字源
    python obs_edit_text.py --list --all                    # 列出所有输入源

参数:
    源名称      OBS 中文字源的名称
    文字内容    要显示的文字
    --font      字体名称（如 "微软雅黑"、"Arial"）
    --size      字号大小（如 36、48、72）
    --bold      加粗
    --italic    斜体
    --color     文字颜色（十六进制，如 FF0000 表示红色）

示例:
    python obs_edit_text.py "Text (GDI+)" "hello everyone"
    python obs_edit_text.py "Text (GDI+)" "Hello World" --font "Arial" --size 48 --bold
    python obs_edit_text.py "Text (GDI+)" "这是一条弹幕" --color 00FF00
"""
import sys

from loguru import logger


def parse_args(args: list[str]) -> dict:
    """解析命令行参数"""
    result = {
        "source_name": None,
        "text": None,
        "font": None,
        "size": None,
        "bold": False,
        "italic": False,
        "color": None,
        "list_sources": False,
    }
    
    i = 0
    positional = []
    
    while i < len(args):
        arg = args[i]
        
        if arg in ("--list", "-l"):
            result["list_sources"] = True
        elif arg == "--font" and i + 1 < len(args):
            result["font"] = args[i + 1]
            i += 1
        elif arg == "--size" and i + 1 < len(args):
            result["size"] = int(args[i + 1])
            i += 1
        elif arg == "--color" and i + 1 < len(args):
            result["color"] = args[i + 1]
            i += 1
        elif arg in ("--bold", "-b"):
            result["bold"] = True
        elif arg in ("--italic", "-i"):
            result["italic"] = True
        elif not arg.startswith("-"):
            positional.append(arg)
        
        i += 1
    
    if len(positional) >= 1:
        result["source_name"] = positional[0]
    if len(positional) >= 2:
        result["text"] = positional[1]
    
    return result


def list_text_sources(obs, show_all: bool = False):
    """列出所有文字源"""
    inputs = obs.get_input_list()
    
    # 文字源类型关键词
    text_keywords = ("text", "gdi", "ft2", "freetype")
    
    text_sources = [
        inp for inp in inputs
        if any(kw in inp.get("inputKind", "").lower() for kw in text_keywords)
    ]
    
    if text_sources:
        logger.info("===== 文字源列表 =====")
        for src in text_sources:
            name = src.get("inputName", "")
            kind = src.get("inputKind", "")
            # 显示 repr 以便发现隐藏字符
            logger.info(f"  - {name} (类型: {kind})")
            logger.info(f"    精确名称: {repr(name)}")
    else:
        logger.info("未找到文字源")
    
    # 显示所有源（用于调试）
    if show_all or not text_sources:
        logger.info("===== 所有输入源 =====")
        for inp in inputs:
            name = inp.get("inputName", "")
            kind = inp.get("inputKind", "")
            logger.info(f"  - {name} (类型: {kind})")


def get_current_settings(obs, source_name: str) -> dict:
    """获取文字源当前设置"""
    try:
        resp = obs._client.get_input_settings(source_name)
        return getattr(resp, "input_settings", {})
    except Exception:
        return {}


def main():
    from obs import OBSCtrl

    args = [a.strip() for a in sys.argv[1:] if a.strip()]
    params = parse_args(args)

    try:
        obs = OBSCtrl()
    except Exception as e:
        logger.error(f"无法连接 OBS: {e}")
        logger.info("请确认 OBS 已启动且 WebSocket 已开启")
        sys.exit(1)

    # 列出文字源
    if params["list_sources"]:
        # 检查是否有 --all 参数
        show_all = "--all" in sys.argv or "-a" in sys.argv
        list_text_sources(obs, show_all=show_all)
        sys.exit(0)

    # 检查必需参数
    if not params["source_name"]:
        logger.error("请指定源名称")
        logger.info("用法: python obs_edit_text.py <源名称> <文字内容>")
        logger.info("      python obs_edit_text.py --list  # 列出所有文字源")
        sys.exit(1)

    source_name = params["source_name"]

    # 仅查看当前内容
    if params["text"] is None and not any([params["font"], params["size"], params["color"]]):
        settings = get_current_settings(obs, source_name)
        current_text = settings.get("text", "(无)")
        logger.info(f"源: {source_name}")
        logger.info(f"当前内容: {current_text}")
        
        font = settings.get("font", {})
        if font:
            logger.info(f"字体: {font.get('face', '未知')} / {font.get('size', '?')}pt")
        sys.exit(0)

    # 构建设置
    settings: dict = {}
    
    if params["text"] is not None:
        settings["text"] = params["text"]
    
    # 字体设置（GDI+ 文字使用 font 对象）
    font_settings = {}
    if params["font"]:
        font_settings["face"] = params["font"]
    if params["size"]:
        font_settings["size"] = params["size"]
    if params["bold"]:
        font_settings["flags"] = font_settings.get("flags", 0) | 1  # OBS_FONT_BOLD
    if params["italic"]:
        font_settings["flags"] = font_settings.get("flags", 0) | 2  # OBS_FONT_ITALIC
    
    if font_settings:
        # 获取当前字体设置并合并
        current = get_current_settings(obs, source_name)
        current_font = current.get("font", {})
        current_font.update(font_settings)
        settings["font"] = current_font
    
    # 颜色设置（GDI+ 使用 color，格式为 ABGR 整数）
    if params["color"]:
        hex_color = params["color"].lstrip("#")
        # 用户输入 RGB，转换为 ABGR（OBS 格式）
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        abgr = 0xFF000000 | (b << 16) | (g << 8) | r
        settings["color"] = abgr

    if not settings:
        logger.warning("未指定任何修改内容")
        sys.exit(1)

    # 验证源是否存在，并尝试匹配正确的名称
    inputs = obs.get_input_list()
    input_names = [inp.get("inputName", "") for inp in inputs]
    
    # 精确匹配
    actual_name = None
    if source_name in input_names:
        actual_name = source_name
    else:
        # 大小写不敏感匹配
        for name in input_names:
            if name.lower() == source_name.lower():
                actual_name = name
                logger.info(f"名称大小写不匹配，使用: {actual_name}")
                break
    
    if not actual_name:
        logger.error(f"源不存在: {source_name}")
        logger.info("可用的输入源:")
        for name in input_names:
            logger.info(f"  - {repr(name)}")  # 用 repr 显示隐藏字符
        sys.exit(1)

    # 应用设置
    try:
        obs.set_input_settings(actual_name, settings, overlay=True)
        logger.info(f"已更新: {actual_name}")
        if params["text"] is not None:
            logger.info(f"  文字: {params['text']}")
        if params["font"]:
            logger.info(f"  字体: {params['font']}")
        if params["size"]:
            logger.info(f"  字号: {params['size']}")
        if params["bold"]:
            logger.info(f"  样式: 加粗")
        if params["italic"]:
            logger.info(f"  样式: 斜体")
        if params["color"]:
            logger.info(f"  颜色: #{params['color']}")
    except Exception as e:
        logger.error(f"更新失败: {e}")
        logger.info("请检查源名称是否正确")
        sys.exit(1)


if __name__ == "__main__":
    main()
