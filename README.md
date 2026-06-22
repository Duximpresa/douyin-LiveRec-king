# douyin-LiveRec-king

面向 Windows 10/11 的抖音直播监控与自动录制桌面工具。使用 PySide6 构建界面，使用
[`streamget 4.0.10`](https://github.com/ihmily/streamget) 获取真实直播状态和 HLS/FLV 地址，
使用 FFmpeg 执行录制。

> 仅可录制您有权保存的内容。请遵守平台服务条款、版权规则和所在地法律法规。本项目不提供绕过登录、付费限制、DRM 或访问控制的能力。

## 功能

- 支持抖音直播间、作者主页、抖音号形式和 `v.douyin.com` 分享短链
- 主播昵称可留空自动获取，也可设置永久优先的自定义别名
- 多任务并发检测，单任务防重复录制
- HLS/FLV 来源选择，原画/超清/高清/标清/流畅画质
- TS、MP4、MKV、FLV 录制
- 分段录制、磁盘空间保护、TS 自动转 MP4
- 按平台或主播建立目录，自定义文件名模板
- 代理与用户手动 Cookie 配置
- 表格/卡片任务视图
- 录制文件、设置、实时日志和关于独立页面
- 本地 FFmpeg、系统 PATH、自定义路径三级查找

## 安装与运行

需要 Python 3.11+。真实抖音解析的部分备用路径可能需要 Node.js。

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python main.py
```

也可以双击 `run_windows.bat`。

## FFmpeg

查找顺序固定为：

1. `runtime/ffmpeg/bin/ffmpeg.exe`
2. 系统 `PATH`
3. 设置页指定的自定义路径

本地 FFmpeg 二进制被 `.gitignore` 排除，不会提交到 Git。测试 ZIP 构建时会将它复制到程序目录。

## 配置

- `data/tasks.json`：结构化任务列表
- `config/config.ini`：本机全局设置和 Cookie
- `config/config.example.ini`：可提交的无敏感信息示例

首次启动若只存在旧版 `data/config.json`，程序会自动迁移，旧文件不会删除。

设置页包括：

- 录制与命名：目录、格式、画质、直播源、分段、磁盘阈值、MP4 转换和命名规则
- 网络与解析：检测间隔、并发数和代理
- Cookie：遮盖显示、清空和解析测试
- FFmpeg 与环境：路径、实际使用版本、Node.js 检测
- 日志与界面：日志级别和默认任务视图

Cookie 只应由用户手动提供。`config/config.ini` 已被 Git 忽略。

## 测试模式

- `mock://offline`：始终未开播
- `mock://live?url=<URL编码后的测试流>`：使用指定测试流
- `stream://<直接流地址>`：直接交给 FFmpeg

## 测试

```powershell
python -m compileall src tests main.py
python -m pytest
python -c "from douyin_live_rec_king.app import main; print('import ok')"
```

## Windows 打包

```powershell
.\build_windows.bat
```

产物：

```text
dist\douyin-LiveRec-king\douyin-LiveRec-king.exe
```

请先完整解压 ZIP，再双击 `启动程序.bat` 或 `douyin-LiveRec-king.exe`。不要直接在压缩包预览窗口中运行，也不要只复制 EXE。构建脚本会收集 streamget 数据文件，并在本地 FFmpeg 存在时一起复制。

## 项目结构

```text
src/douyin_live_rec_king/
├─ app.py                 # 应用启动与配置迁移
├─ config.py              # INI 设置与 JSON 任务存储
├─ models.py              # 任务、设置和直播状态模型
├─ gui/                   # PySide6 导航、页面和对话框
├─ platforms/             # streamget 平台适配层
├─ recording/             # FFmpeg 定位、命令和进程生命周期
├─ services/              # 并发监控与任务协调
└─ utils/                 # 路径和文件名工具
```

## 鸣谢与许可

功能思路参考了 [DouyinLiveRecorder](https://github.com/ihmily/DouyinLiveRecorder)，界面信息架构参考了
[StreamCap](https://github.com/ihmily/StreamCap)。直播解析依赖 MIT 许可的
[streamget](https://github.com/ihmily/streamget)。本项目为独立的 PySide6 实现，不复制上述项目源码。

项目自身采用 MIT License。
