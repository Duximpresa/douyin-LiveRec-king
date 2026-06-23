# douyin-LiveRec-king

面向 Windows 10/11 的抖音直播监控与自动录制桌面工具。使用 PySide6 构建界面，使用
[`streamget 4.0.10`](https://github.com/ihmily/streamget) 获取真实直播状态和 HLS/FLV 地址，
使用 FFmpeg 执行录制。

> 仅可录制您有权保存的内容。请遵守平台服务条款、版权规则和所在地法律法规。本项目不提供绕过登录、付费限制、DRM 或访问控制的能力。

## 功能

- 支持抖音直播间、作者主页、抖音号形式和 `v.douyin.com` 分享短链
- 支持 `live.bilibili.com/<room_id>`，平台 Cookie、Referer、User-Agent 和 headers 由各自 adapter 提供
- 主播昵称可留空自动获取，也可设置永久优先的自定义别名
- 多任务并发检测，单任务防重复录制
- HLS/FLV 来源选择，原画/超清/高清/标清/流畅画质
- TS、MP4、MKV、FLV 录制
- 分段录制、磁盘空间保护、TS 自动转 MP4
- 按平台或主播建立目录，自定义文件名模板
- 代理与用户手动 Cookie 配置
- 表格/卡片任务视图
- 录制历史、统计、设置、实时日志和关于独立页面
- ffprobe 媒体探测、中断 TS 转封装、临时文件恢复提示和损坏 JSON 备份恢复
- 完整历史、主播/平台汇总、每日趋势 CSV 导出（UTF-8 BOM）
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
python -m compileall src tests scripts main.py
python -m pytest
python scripts/check_utf8.py
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

## 录制核心设计

项目继续采用 PySide6 Windows 桌面架构，没有迁移到 Flet 或 Web 服务。当前录制核心按职责拆分：

- `TaskManager`：任务 CRUD、状态流转、持久化和状态通知
- `Monitor`：周期/手动检测以及统一的 task_id 防重复检测
- `RecordingService`：录制启动编排、输出路径和退出结果处理
- `StorageGuard`：输出目录与磁盘剩余空间检查
- `Recorder`：FFmpeg 进程生命周期、活动进程防重和优雅停止
- `platforms/`：把平台解析结果统一转换为 `LiveStatus`
- Qt Signal Bridge：把后台状态安全送回 UI 主线程

任务状态流为：

```text
IDLE / MONITORING
  -> CHECKING
  -> MONITORING                  未开播
  -> LIVE_DETECTED
  -> STARTING_RECORD
  -> RECORDING
  -> STOPPING
  -> MONITORING / IDLE           正常停止

任意检测、存储或录制错误 -> ERROR
禁用任务 -> DISABLED
```

FFmpeg 使用参数列表调用，不使用 `shell=True`。录制命令支持代理、断线重连、
User-Agent、Referer、Cookie、通用 HTTP headers 和分段录制；停止时依次尝试发送
`q`、`terminate`、`kill`，尽量保证容器尾部正常写入。

## 扩展新平台

1. 在 `PlatformType` 中增加平台类型。
2. 实现 `BasePlatformExtractor`，返回统一的 `LiveStatus`。
3. 使用 `platforms.registry.register_extractor()` 注册工厂。

录制服务和 UI 不应包含平台解析细节。测试时继续使用 `mock://offline`、
`mock://live?url=...` 和 `stream://...`。

## StreamCap 设计借鉴

本项目借鉴了 StreamCap 的后台服务边界、录制生命周期、active recorders、防重复启动、
后台状态广播和局部 UI 更新等工程思想，但保持独立的 PySide6/线程实现，不复制其源码，
也不迁移其技术栈。

v0.3.0 已完成 Bilibili、录制统计、可配置失败重试、媒体探测与文件恢复。新增平台仍通过 registry 扩展，不需要修改录制服务或 UI 核心。

## 应用生命周期与可靠性

- `ApplicationServices` 是轻量组合根，统一持有配置、任务管理、监控、录制和持久化服务。
- 启动时会把上次异常退出遗留的瞬时状态恢复为 `IDLE`；中断录制会保留明确错误提示，但不会自动重新录制。
- 录制服务使用 `RecordingEvent` 和 `RecordingEventType` 传递类型化生命周期事件。
- 状态变化采用 250ms 去抖保存，任务增删改立即原子保存；关闭前会强制刷新最新快照。
- 关闭窗口时 UI 保持可响应，并显示收尾进度。所有 FFmpeg 会并行执行优雅停止，总等待上限为 20 秒，超时后强制清理。

## 异常重试与录制历史

- 仅对超时、连接重置、临时 DNS 故障、HTTP 5xx、EOF 等瞬时网络错误自动重试。
- 默认最多重试 3 次，间隔为 5、15、45 秒；次数、退避秒数和全局同时重试数均可配置，每次重试都会重新解析直播地址。
- Cookie、风控、解析、磁盘、权限、格式和转换错误不会进入自动重试。
- 连续稳定录制超过 5 分钟后，下一次网络故障会重新从第 1 次重试开始计数。
- 录制历史保存在本地 `data/recording_history.json`，最多保留最近 1000 条。
- 历史包含主播、标题、时间、时长、大小、文件、退出原因、错误和转换结果。
- “删除历史”不会删除视频；删除视频文件是独立操作，并需要二次确认。
- 启动时会把未完成的历史标记为“中断”，并提示 `.part`、`.tmp` 等待人工检查的文件。
- 零字节或缺失文件判定为失败；小于 256 KiB 的文件只显示警告，不会自动删除。

## 媒体恢复与统计

- 历史详情保存 ffprobe 的时长、容器和音视频流信息；系统没有 ffprobe 时退回文件大小检查并显示警告。
- 中断的 TS 文件可在录制历史页后台转封装为 MP4，验证目标有效后更新历史，默认保留源文件。
- `.part`、`.tmp` 和中断历史文件只形成恢复提示；清理必须由用户逐项或批量二次确认。
- 任务或历史 JSON 损坏时会先生成 `.corrupt-时间戳.bak`，再依次尝试有效 `.tmp` 和最近备份，不会静默清空。
- 统计页显示全部、最近 7 天和最近 30 天指标，并按主播、平台、日期聚合。

## v0.3.0 本地发布

发布目录包含完整 PyInstaller 应用、配置示例和启动脚本。可用下面的无界面检查验证解压后的 EXE：

```powershell
.\douyin-LiveRec-king.exe --smoke-test
```

该命令会完成服务组装、Bilibili adapter 导入、配置/历史初始化和异步关闭，不启动监控或访问真实直播平台。

## 鸣谢与许可

功能思路参考了 [DouyinLiveRecorder](https://github.com/ihmily/DouyinLiveRecorder)，界面信息架构参考了
[StreamCap](https://github.com/ihmily/StreamCap)。直播解析依赖 MIT 许可的
[streamget](https://github.com/ihmily/streamget)。本项目为独立的 PySide6 实现，不复制上述项目源码。

项目自身采用 MIT License。
