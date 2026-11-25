# Steam Collection Curator 中文指南

Curator 从你已保存的 SteamDB HTML 或 CSV 生成本地分类计划。AI 可协助理解少数疑难游戏，程序处理重复工作，个人价值由玩家决定。

## 安装与使用

需要 Python 3.11 或更新版本。把独立 ZIP 解压到项目或用户目录的 `.agents/skills`，目录名保持 `steam-collection-curator`，然后在 Codex 调用 `$steam-collection-curator`。CLI 可直接从解压目录运行。卸载时只移除已安装的 Skill 目录。玩家自行决定是否保留单独存放的计划、缓存与备份。

把导出和计划放在仓库外已创建的私人目录。以下是命令示例。

```sh
python scripts/curator.py /path/to/library.csv --output /path/to/private/plan.json
python scripts/curator.py /path/to/library.html --previous /path/to/private/plan.json --output /path/to/private/next.json
python scripts/curator.py --manual-only --language en --output /path/to/private/manual.json
```

CSV 至少需要 AppID、游戏名称两列。HTML 需要已经保存的应用表格，多表用 `--table-id` 指定。分类方案有精简 `compact`、均衡 `balanced` 和详细 `detailed`，默认均衡。使用 `--taxonomy` 指定私人模板副本，可更改八个 `00-` 收藏集的名称。保留原编号以稳定映射。新增归类优先遵循玩法，免费只作为元数据。系列、主题和体验收藏集可交叉归属。

低置信度或冲突条目进入待复核清单。支持本地元数据、已审核的旧基线，以及用户确认的决定。查看[字段与复核命令](../references/classification.md)。可选联网仅查询玩家选中的少量公开 AppID，使用同一份本地缓存以核对累计范围。

## Steam 写入与恢复

先运行独立写入器检查账户、差异和本机 Steam 状态。

```sh
python scripts/write_steam.py --target /path/to/Steam/userdata/42/config/cloudstorage/cloud-storage-namespace-1.json --account 42 --plan /path/to/private/plan.json
```

完全退出 Steam 后，由玩家在本机终端运行带 `--apply --expect <preview_digest>` 的同一命令，并按提示交互确认。已有人工收藏集保持玩家管理，未登记、自建、动态和系统收藏集受保护。移除或移动受管成员须另外列出并二次确认。

写入目标是 Windows、macOS、原生 Linux 和 Steam Deck 桌面模式的现代 CloudStorage JSON。使用真实物理路径。Linux 库的符号链接路径可先由玩家定位实际目录。真实客户端、云同步、空收藏集显示待验收。回滚恢复本地匹配的事务快照。详见[写入和恢复命令](../references/writer.md)。

## 常见问题

- **提示选表或格式错误**时，确认导出含静态数据行，或改用 UTF-8 CSV。
- **发现同名收藏集**时，它继续由玩家管理。旧版 ID 本身不代表登记所有权。
- **游戏仍待复核**时，补充类型或明确的玩法证据，或记录个人确认。
- **客户端同步结果异常**时，先退出 Steam 检查事务记录。若本地文件已变动，保留当前文件和备份，避免反复覆盖。

查看[隐私政策](privacy.md)、[英文说明](../README.md)和[测试报告](../TEST_REPORT.md)。
