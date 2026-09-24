# 用户指南

[中文 README](../../README.md) · [English](../en/user-guide.md) · [日本語](../jp/user-guide.md) · [安装指南（英语）](../en/installation.md)

双击 `start.bat` 可按步骤创建项目并处理音频；双击 `webui.bat` 可直接打开两个 WebUI。下面的命令适用于需要单独启动某一步或指定参数的用户。请在仓库根目录的 PowerShell 中运行。两个批处理文件分别通过 `run.ps1` 调用 `start` 和 `webui`。

## 命令与参数

| 命令 | 作用 |
| --- | --- |
| `start` | 打开项目中心，可选分段与转录，随后打开两个 WebUI。 |
| `project` | 只打开项目中心，用于创建项目和管理数据库。 |
| `process` | 对已有项目绑定的音频进行分段与转录；不创建项目，也不打开 WebUI。 |
| `webui` | 不选择或处理项目，直接打开两个 WebUI。 |
| `webui1` | 只打开单项目时间线校对界面。 |
| `webui2` | 只打开多项目组合界面。 |
| `language [zh-CN\|en-US\|ja-JP]` | 显示当前界面语言，或保存指定的界面语言。 |
| `doctor` | 检查运行环境。 |

例如：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 start
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 project
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 process
```

`run.ps1` 会根据自身位置找到项目目录，因此也可以从其他目录用绝对路径调用。运行 `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 --help` 可查看内置帮助；要查看某个命令的参数，将命令放在 `--help` 前面，例如 `start --help`。

全局参数 `--config PATH` 必须放在命令之前，用于指定主 YAML 配置文件。默认文件为 `config/default.yaml`：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 --config .\config\default.yaml doctor
```

| 适用命令 | 参数 | 作用 |
| --- | --- | --- |
| `start`、`process` | `AUDIO` | 直接处理一个音频文件，不打开处理选择窗口。 |
| `start`、`process` | `--project NAME` | 与 `AUDIO` 一起使用时指定项目；不提供 `AUDIO` 时，在 `start` 中预填项目名称，或在 `process` 中优先选中该项目。 |
| `start`、`process` | `--subtitle PATH` | 提供可选字幕文件；在选择窗口中使用字幕时，只能选中一个项目。 |
| `start`、`process` | `--start-padding SECONDS`、`--end-padding SECONDS` | 设置本次处理的非负分段补白秒数；未提供时使用配置默认值。 |
| `start`、`process`、`webui1`、`webui` | `--language CODE` | 指定本次运行的 ASR 语言，例如 `auto`、`zh`、`en`、`ja`；它与 `language` 命令保存的界面语言不同。 |
| `webui1`、`webui` | `AUDIO`、`--project NAME` | 在 WebUI1 打开已绑定的音频或项目；只提供 `AUDIO` 时从数据库推断项目。 |
| `webui1`、`webui2` | `--port NUMBER` | 修改监听端口；默认分别为 8765 和 8766。 |
| `webui` | `--webui1-port NUMBER`、`--webui2-port NUMBER` | 修改两个不同的监听端口；默认分别为 8765 和 8766。 |
| `webui1`、`webui2`、`webui` | `--no-open` | 启动本地服务，但不自动打开浏览器标签页。 |

例如：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 process --project "Example Project"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 webui1 --project "Example Project"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 webui --webui1-port 8875 --webui2-port 8876 --no-open
```

## 项目与处理流程

项目中心将单个创建、批量创建、待创建队列和数据库管理放在同一个窗口。创建项目时，名称及音频绑定立即写入数据库，即使项目还没有分段；下方数据库列表也会刷新。WebUI1 的项目菜单也可以打开这个窗口。

使用 `start` 时，点击 **下一步** 打开分段与转录窗口。新建项目会默认在数据库列表中勾选；当前勾选的项目（包括手动勾选的已有项目）会作为下一窗口的初始选择。取消勾选可将项目排除在初始选择之外。在处理窗口仍可调整选择、留空，或点击 **跳过**，然后直接进入两个 WebUI。只有绑定了可用音频文件的项目才能处理。

如果执行了处理，`start` 会让 WebUI1 打开最后一个处理过的项目。如果没有处理，WebUI1 会收到项目中心最后一个勾选的项目；一个也没选时，不指定初始项目。WebUI2 会收到项目中心所有勾选的项目名称，以及实际处理过的项目名称。关闭任一流程窗口，而不是点击 **下一步** 或 **跳过**，会取消 `start`。

使用 `start AUDIO [--project NAME]` 会跳过两个选择窗口：如有需要先创建项目并绑定音频，再处理音频，最后打开两个 WebUI。已有项目中的音频必须已经绑定到该项目。不提供 `--project` 时，新项目名称取音频文件名去掉扩展名后的部分。

`process` 只处理已有项目中已绑定的音频，不创建项目，也不打开 WebUI。不提供 `AUDIO` 时会打开处理选择窗口；提供 `AUDIO` 时，该音频必须已绑定到已有项目，可以根据绑定关系推断项目，也可以用 `--project` 指定。处理需要下载两个模型，参见[安装指南（英语）](../en/installation.md)。

## 校对与组合

WebUI1 是单项目时间线编辑器，可校对时间坐标、说话人、转录文本、标签和备注，也可预览音频、重新转录、导出字幕或切片。已有项目数据的修改会先保留在页面上，点击 **保存** 后才写入数据库。项目更新计数用于检测外部修改。

WebUI2 可组合多个项目的数据，支持音频版本与偏移、筛选、切片处理、列表导出和电子表格导出。生成的文件默认写入被 Git 忽略的 `output/`；列表导出位于 `output/asr_opt/slicer_opt.list`。

原始音频仍保留在原有位置。本地数据库默认为 `data/audio-registry.sqlite3`；更新或清理源码目录时不要删除它。

## 语言与配置

如果没有保存过语言选择，界面会优先使用浏览器或系统支持的语言，否则回退到英语。保存界面语言的命令如下：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 language zh-CN
```

将 `zh-CN` 换成 `en-US` 或 `ja-JP` 可选择英语或日语。应用默认配置在 `config/default.yaml`；本机专用设置应写入被 Git 忽略的 `config/default.local.yaml`。Python、FFmpeg 和模型配置参见[安装指南（英语）](../en/installation.md)。
