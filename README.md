# YouTube 直播聊天抓取与工具集

- **只读抓取**：用 [pytchat](https://github.com/taizan-hokuto/pytchat) 获取直播聊天消息，无需 API 密钥
- **发弹幕 / 直播管理**：通过 YouTube Data API v3（OAuth）发消息、管理直播与推流
- **OBS 控制**：通过 WebSocket 控制 OBS 推流、录制、场景等

## 安装

```bash
pip install -r requirements.txt
```

## 使用

### 只读抓取直播聊天（无需 OAuth）

- 使用 `live_pytchat.py` 中的 `YoutubeLivePytchat(video_id)`，或你的 `bot.py` 等脚本
- 直播地址形如 `https://www.youtube.com/watch?v=xxxxxx`，其中的 `xxxxxx` 即为 **VIDEO_ID**
- 需直播**正在进行中**，pytchat 仅能获取连接后的新消息

### 发弹幕 / 使用 YouTube API

1. **首次配置 OAuth**：将 Google Cloud Console 下载的 OAuth 客户端 JSON 保存为 `client_secret.json`（见下方「JSON 凭据管理」）。
2. **授权并验证**：运行 `python oauth_youtube.py`，在浏览器中完成登录后会在同目录生成 `token.json`，之后无需重复授权。
3. **发弹幕**：
   - 命令行：`python sender.py [消息]`（不传 VIDEO_ID 时自动使用当前账号正在直播）；或 `python sender.py <VIDEO_ID> [消息]`；也可设置环境变量 `VIDEO_ID`。
   - 代码中：`sender.send_message(youtube, live_chat_id, "消息内容")`。
4. **完整 API**：使用 `live_api.py` 的 `YoutubeLiveAPI`（视频信息、聊天、创建/绑定直播、推流、投票、封禁等）。

### OBS 控制

- 使用 `obs.py` 中的 `OBSCtrl`：推流地址/密钥、开始停止推流、录制、场景切换、文字源、音量等
- 前置：OBS Studio + obs-websocket（OBS 28+ 内置），在 OBS 中启用 WebSocket 并设置端口与密码
- 修改 `obs.py` 顶部 `HOST`、`PORT`、`PASSWORD` 与 OBS 一致

## JSON 凭据管理（OAuth）

- **client_secret.json**：从 [Google Cloud Console](https://console.cloud.google.com/) → 凭据 → 创建 OAuth 客户端 ID（桌面应用）→ 下载 JSON，放到项目根目录或自定义目录
- **token.json**：首次运行 `oauth_youtube.py` 授权后自动生成，用于免重复登录


## 注意事项

- 仅**正在直播**的视频可被 pytchat 抓取；直播结束后无法抓取
- 若直播未开始，程序会提示并退出
- 使用 API 或发弹幕需网络可访问 Google（可配置代理，见 `oauth_youtube.py` 中的 `PROXY_*`）


###本地代码调试
```shell
#开启直播
python start_live.py adame14
#obs切换画面
python switch_scene.py Video
#obs修改标题
python obs_edit_text.py "Text (GDI+)" "hello everyone"
#关闭直播
python end_live.py
```

###OBS设置”流延迟”
1.打开OBS
2.点击右下角设置
3.进入高级
找到流延迟(Stream Delay)
5.勾选「启用」
6.设置延迟时间(单位:秒)
7.点击确定
