"""
OBS 控制类：通过 WebSocket 控制 OBS Studio

通过 OBS WebSocket 协议远程控制 OBS，支持：
- 直播：设置推流地址/密钥（YouTube 等）、开始/停止推流，查询推流状态
- 录制：开始/停止/暂停录制，获取录制目录
- 场景：切换节目场景，获取场景列表
- 虚拟摄像头：开启/关闭虚拟摄像头
- 回放缓冲：开始/停止缓冲，保存回放片段
- 输入源：修改文字源内容、图片源路径、浏览器源 URL 等（SetInputSettings）
- 音量/静音：设置/切换任意输入源静音（含桌面音频、麦克风等），设置音量
- 场景项：显示/隐藏场景中的源，获取输入列表
- 滤镜：启用/禁用源上的滤镜

前置条件：
1. 已安装 OBS Studio
2. 已安装 obs-websocket 插件（OBS 28+ 内置）
3. 在 OBS：工具 → obs-websocket 设置 中启用服务器，设置端口和密码
4. 修改本模块 HOST、PORT、PASSWORD 与 OBS 配置一致

用法示例：
    from obs import OBSCtrl
    obs = OBSCtrl()
    obs.set_scene("Camera")
    obs.start_stream()
    obs.set_text_input("文字源名称", "直播间显示的内容")
    obs.set_stream_key_youtube("8016-esqd-1qgw-58y0-4r9t")  # 设置 YouTube 推流密钥
"""

from obsws_python import ReqClient
import time

HOST = "127.0.0.1"
PORT = 4455
PASSWORD = "l30QZOVZtaQGtvmY"  # 改这里


class OBSCtrl:
    """OBS 控制类：直播、录制、场景、虚拟摄像头、回放缓冲等"""

    def __init__(self, host: str = HOST, port: int = PORT, password: str = PASSWORD, timeout: int = 10):
        self._client = ReqClient(host=host, port=port, password=password, timeout=timeout)

    # ---------- 直播 ----------
    def get_stream_service_settings(self):
        """获取当前推流服务设置（含 server、key 等）"""
        return self._client.get_stream_service_settings()

    def set_stream_key_youtube(self, stream_key: str) -> None:
        """
        设置 YouTube 推流密钥（rtmp_custom 模式）。
        server 固定为 rtmp://a.rtmp.youtube.com/live2。
        """
        self._client.set_stream_service_settings(
            "rtmp_custom",
            {"server": "rtmp://a.rtmp.youtube.com/live2", "key": stream_key},
        )

    def set_stream_service(self, server: str, key: str, service_type: str = "rtmp_custom") -> None:
        """
        设置推流服务地址和密钥。service_type 默认 rtmp_custom。
        例：set_stream_service("rtmp://a.rtmp.youtube.com/live2", "8016-esqd-1qgw-58y0-4r9t")
        """
        self._client.set_stream_service_settings(
            service_type,
            {"server": server, "key": key},
        )

    def start_stream(self) -> None:
        """开始推流"""
        self._client.start_stream()

    def stop_stream(self) -> None:
        """停止推流"""
        self._client.stop_stream()

    def toggle_stream(self):
        """切换推流状态（开/关）"""
        return self._client.toggle_stream()

    def get_stream_status(self):
        """获取推流状态（output_active, output_reconnecting 等）"""
        return self._client.get_stream_status()

    def is_streaming(self) -> bool:
        """是否正在推流"""
        return self.get_stream_status().output_active

    # ---------- 录制 ----------
    def start_record(self) -> None:
        """开始录制"""
        self._client.start_record()

    def stop_record(self):
        """停止录制，返回录制结果信息"""
        return self._client.stop_record()

    def toggle_record(self):
        """切换录制状态（开/关）"""
        return self._client.toggle_record()

    def get_record_status(self):
        """获取录制状态（output_active 等）"""
        return self._client.get_record_status()

    def is_recording(self) -> bool:
        """是否正在录制"""
        return self.get_record_status().output_active

    def pause_record(self) -> None:
        """暂停录制"""
        self._client.pause_record()

    def resume_record(self) -> None:
        """继续录制"""
        self._client.resume_record()

    def toggle_record_pause(self):
        """切换录制暂停状态"""
        return self._client.toggle_record_pause()

    def get_record_directory(self):
        """获取当前录制输出目录"""
        return self._client.get_record_directory()

    # ---------- 场景 ----------
    def get_current_scene(self) -> str:
        """获取当前节目场景名称"""
        r = self._client.get_current_program_scene()
        return r.current_program_scene_name

    def set_scene(self, scene_name: str) -> None:
        """切换到指定场景"""
        self._client.set_current_program_scene(scene_name)

    def get_scene_list(self):
        """获取场景列表"""
        return self._client.get_scene_list()

    # ---------- 虚拟摄像头 ----------
    def start_virtual_cam(self) -> None:
        """开启虚拟摄像头"""
        self._client.start_virtual_cam()

    def stop_virtual_cam(self) -> None:
        """关闭虚拟摄像头"""
        self._client.stop_virtual_cam()

    def toggle_virtual_cam(self):
        """切换虚拟摄像头状态"""
        return self._client.toggle_virtual_cam()

    # ---------- 回放缓冲 ----------
    def start_replay_buffer(self) -> None:
        """开始回放缓冲"""
        self._client.start_replay_buffer()

    def stop_replay_buffer(self) -> None:
        """停止回放缓冲"""
        self._client.stop_replay_buffer()

    def save_replay_buffer(self):
        """保存回放缓冲为文件"""
        return self._client.save_replay_buffer()

    # ---------- 输入源设置 ----------
    def set_text_input(self, input_name: str, text: str, overlay: bool = True) -> None:
        """
        修改文字源内容。适用于 GDI+ 文字、FreeType2 文字 等文字类输入源。
        overlay=True：在现有设置上合并；overlay=False：先重置再应用。
        """
        self._client.set_input_settings(input_name, {"text": text}, overlay)

    def set_input_settings(self, input_name: str, settings: dict, overlay: bool = True) -> None:
        """
        修改任意输入源的设置。
        settings 示例：
          - 文字源：{"text": "新内容"}
          - 图片源：{"file": "C:/path/to/image.png"}
          - 浏览器源：{"url": "https://..."}
        overlay=True：合并到现有设置；overlay=False：重置后应用。
        """
        self._client.set_input_settings(input_name, settings, overlay)

    def set_input_mute(self, input_name: str, muted: bool) -> None:
        """
        设置输入源静音状态。适用于桌面音频、麦克风等任意音频输入。
        输入名需与 OBS 中一致，如 "桌面音频"、"麦克风" 等，可用 get_input_list() 查看。
        """
        self._client.set_input_mute(input_name, muted)

    def toggle_input_mute(self, input_name: str):
        """切换输入源静音状态，返回切换后的静音状态"""
        return self._client.toggle_input_mute(input_name)

    def get_input_mute(self, input_name: str) -> bool:
        """获取输入源是否静音"""
        return self._client.get_input_mute(input_name).input_muted

    def set_input_volume(self, input_name: str, volume: float) -> None:
        """设置输入源音量。volume 为乘数，1.0=100%"""
        self._client.set_input_volume(input_name, vol_mul=volume)

    def get_input_volume(self, input_name: str):
        """获取输入源音量"""
        return self._client.get_input_volume(input_name)

    def get_input_list(self, kind: str | None = None) -> list:
        """
        获取输入源列表。kind 可过滤类型，如 "wasapi_output_capture"（桌面音频）、
        "wasapi_input_capture"（麦克风）。不传则返回全部。返回项含 inputName、inputKind 等。
        """
        r = self._client.get_input_list(kind)
        return getattr(r, "inputs", [])

    def set_scene_item_enabled(self, scene_name: str, item_id: int, enabled: bool) -> None:
        """显示或隐藏场景中的某个源。item_id 来自 get_scene_item_list"""
        self._client.set_scene_item_enabled(scene_name, item_id, enabled)

    def get_scene_item_list(self, scene_name: str) -> list:
        """获取场景中所有源列表，含 scene_item_id、source_name 等"""
        r = self._client.get_scene_item_list(scene_name)
        return getattr(r, "scene_items", getattr(r, "sceneItems", []))

    def set_source_filter_enabled(self, source_name: str, filter_name: str, enabled: bool) -> None:
        """启用或禁用源上的滤镜"""
        self._client.set_source_filter_enabled(source_name, filter_name, enabled)


def main():
    obs = OBSCtrl()

    # 读取当前场景（验证已连通）
    print("Current program scene:", obs.get_current_scene())

    # 场景切换示例
    # obs.set_scene("Camera")
    # print("Switched to: Camera")
    # time.sleep(2)
    obs.set_scene("Video")
    print("Switched to: Video")

    time.sleep(2)
    # 直播/录制控制示例（按需取消注释）
    # print("Stream active:", obs.is_streaming())
    obs.set_stream_key_youtube("kmth-wj4b-5k3j-p2xp-9vr2")
    time.sleep(1)
    obs.start_stream()   # 开始推流
    # obs.stop_stream()    # 停止推流
    # obs.start_record()   # 开始录制
    # obs.stop_record()    # 停止录制


if __name__ == "__main__":
    main()
