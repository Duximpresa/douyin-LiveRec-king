# douyin-LiveRec-king v0.3.0

发布日期：2026-06-23

## 主要更新

- 新增 Bilibili 直播间支持，并由各平台 adapter 独立提供 Cookie、Referer、User-Agent 和 headers。
- 自动重试次数、退避间隔和全局并发数可配置；每次重试重新解析直播流地址。
- 录制历史支持 ffprobe 媒体信息、中断记录恢复、TS 安全转封装和临时文件人工清理。
- 新增全部/7 天/30 天录制统计，以及历史、主播/平台汇总、每日趋势 CSV 导出。
- 任务卡片原地更新，增加状态概览、历史详情、恢复文件和批量删除历史。
- UI 页面、运行时协调器和应用服务进一步拆分，保留旧公共 import 与调用兼容。
- JSON 损坏时保留带时间戳备份，并尝试 `.tmp` 或最近有效备份恢复。

## 安装与验证

1. 完整解压 ZIP。
2. 运行 `douyin-LiveRec-king.exe` 或 `run_windows.bat`。
3. 首次使用时在设置页填写输出目录和所需平台 Cookie。
4. 可执行 `douyin-LiveRec-king.exe --smoke-test` 做无界面启动/关闭检查。

发布包内包含 FFmpeg 与 ffprobe，仅用于本地录制、探测和转封装。包内不包含真实 Cookie、用户配置、任务、录制历史或媒体文件。

## 校验

使用同目录 `SHA256SUMS.txt` 校验 ZIP 的 SHA256。
