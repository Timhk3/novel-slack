# NovelSlack

[中文](#中文) · [English](#english)

[![CI](https://github.com/Timhk3/novel-slack/actions/workflows/ci.yml/badge.svg)](https://github.com/Timhk3/novel-slack/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Platforms](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)
![License](https://img.shields.io/badge/license-MIT-green)

> A terminal novel reader hidden inside a real, low-load system maintenance dashboard.  
> 一个藏在真实、低负载系统维护面板里的终端小说阅读器。

---

# 中文

## 简介

**NovelSlack** 是一个跨平台终端 TXT 小说阅读器，同时提供真实、低负载的本地系统维护面板。

它不是单纯伪装成“工作界面”的阅读器：Dashboard 会真实读取 CPU、内存、磁盘、进程等系统状态，并对明确安全的本地缓存和临时文件提供检查与清理能力。

支持：

- Windows 10 / 11
- macOS
- Linux（以 Ubuntu / Debian 类环境作为主要验证目标）

当前版本：**v0.7.0**

## 主要功能

### 📖 小说阅读

- 本地 TXT 阅读
- UTF-8 / UTF-8 BOM / GB18030 编码支持
- 自动保存和恢复阅读进度
- 页码跳转
- 全文搜索
- 搜索结果前后跳转
- 章节识别
- 卷 → 章节两级目录
- 章节跳转
- 章节索引缓存
- 窗口大小动态适配


### 🖥 系统维护面板

Dashboard 会真实读取和展示：

- CPU 使用情况
- 内存使用情况
- 磁盘剩余空间
- 运行进程数量
- 高内存占用进程
- 用户 TEMP
- pip / npm cache
- Trash / Recycle Bin
- 部分诊断 / 崩溃报告

后台扫描采用增量、低 I/O 方式运行，并会在系统负载升高时自动降低扫描速度。

### 🧹 Cleanup Review

按 `C` 进入 Cleanup Review。

默认勾选：

```text
[x] 30 天以上的用户 TEMP 文件
[x] 当前 workspace 中可重新生成的缓存
```

需要手动选择：

```text
[ ] pip cache
[ ] npm cache
[ ] Trash / Recycle Bin
```

仅查看，不自动删除：

```text
[-] System TEMP
[-] Diagnostics / crash reports
```

对于自动清理候选，NovelSlack 会在删除前再次检查文件路径、大小和修改时间，避免误删扫描后已发生变化的文件。

## 安装

### Windows

在项目目录中：

```powershell
python -m pip install --upgrade .
```

验证：

```powershell
novelslack --version
```

开始阅读：

```powershell
novelslack --text "D:\Books\book.txt"（你的txt文件路径）
```

### macOS / Linux

在项目目录中：

```bash
python3 -m pip install --upgrade .
```

验证：

```bash
novelslack --version
```

开始阅读：

```bash
novelslack --text ~/Downloads/book.txt （你的txt文件路径）
```

如果系统 Python 不允许直接安装用户包，建议先创建虚拟环境。

## 常用快捷键

### Reader

| 按键 | 功能 |
|---|---|
| `A` | 上一页 |
| `D` / `Space` | 下一页 |
| `G` | 跳转页码 |
| `/` / `F` | 搜索 |
| `N` / `P` | 下一个 / 上一个搜索结果 |
| `X` / `Esc` | 清除搜索 |
| `[` | 上一章 |
| `]` | 下一章 |
| `T` | 跳转章节 |
| `O` | 打开章节目录 |
| `W` | Dashboard |
| `Q` | 退出 |

### Cleanup Review

| 按键 | 功能 |
|---|---|
| `[` / `]` | 移动选择 |
| `Space` | 勾选 / 取消 |
| `Enter` | 执行清理 |
| `W` | 返回 Dashboard |

## 跨平台实现

NovelSlack v0.7.0 将系统相关能力拆成三套独立 Platform Adapter：

```text
novelslack/platforms/
├── base.py
├── factory.py
├── windows.py
├── macos.py
└── linux.py
```

### Windows

- CPU：`GetSystemTimes`
- 内存：`GlobalMemoryStatusEx`
- 进程：Toolhelp + `tasklist`
- Recycle Bin：Windows Shell API
- TEMP / CrashDumps / WER

### macOS

- CPU：低负载 load average
- 内存：`vm_stat` + `sysctl hw.memsize`
- 进程：`ps`
- Trash：`~/.Trash`
- DiagnosticReports

### Linux

- CPU：`/proc/stat`
- 内存：`/proc/meminfo`
- 进程：`/proc`
- Trash：XDG Trash
- state / cache：XDG 路径

在 macOS / Linux 的共享临时目录中，自动 TEMP 清理只会处理**当前用户拥有的文件**。

## 低负载设计

NovelSlack 尽量避免“为了监控系统而增加系统负担”：

- 单后台维护线程
- 增量式目录扫描
- Dirty Render，仅在数据变化时刷新
- 高 CPU / 高内存时自动降低扫描速度
- Reader / Catalog 模式暂停后台目录扫描
- macOS 较重系统命令降低执行频率
- 不杀进程
- 不修改注册表
- 不清理 Prefetch
- 不清空系统 standby list
- 不上传遥测数据

## 隐私

NovelSlack 完全在本地运行。

不会上传：

- 小说内容
- 阅读历史
- 系统状态
- 进程列表
- 清理结果
- 用户文件

运行时不需要网络连接。

## 小说内容说明

NovelSlack 本身**不包含、不下载、也不分发任何小说或其他书籍内容**。

Reader 只读取用户自己提供的本地 TXT 文件。请仅使用你有权访问和阅读的内容。

## Release

最新版本：

**[NovelSlack v0.7.0](https://github.com/Timhk3/novel-slack/releases/tag/v0.7.0)**

Windows / macOS / Ubuntu CI 均已通过。

---

# English

## Overview

**NovelSlack** is a cross-platform terminal TXT novel reader paired with a real, low-load local system maintenance dashboard.

It is not merely a fake “work screen.” The dashboard reads actual CPU, memory, disk, process, cache, TEMP, and Trash / Recycle Bin information, while keeping cleanup conservative and explicit.

Supported platforms:

- Windows 10 / 11
- macOS
- Linux, with Ubuntu / Debian-style environments as the primary validation target

Current version: **v0.7.0**

## Features

### 📖 Reader

- local TXT reading
- UTF-8 / UTF-8 BOM / GB18030 support
- persistent reading position
- page navigation
- full-text search
- next / previous match navigation
- chapter detection
- volume → chapter catalog
- direct chapter navigation
- cached chapter index
- responsive terminal layout
- **chapter-bounded pagination**

Every detected chapter starts at the top of a new Reader page. The last page of the previous chapter never previews the next chapter heading.

### 🖥 Maintenance Dashboard

The dashboard displays real local system information, including:

- CPU usage
- memory usage
- free disk space
- process count
- high-memory processes
- user TEMP
- pip / npm cache
- Trash / Recycle Bin
- selected diagnostics / crash-report locations

Storage scanning is incremental and intentionally low-I/O. Scan throughput is reduced automatically when system pressure rises.

### 🧹 Cleanup Review

Press `C` to open Cleanup Review.

Selected by default:

```text
[x] User TEMP files older than 30 days
[x] Regenerable cache inside the current workspace
```

Explicit opt-in:

```text
[ ] pip cache
[ ] npm cache
[ ] Trash / Recycle Bin
```

Review only:

```text
[-] System TEMP
[-] Diagnostics / crash reports
```

Before deleting indexed safe candidates, NovelSlack revalidates path, size, and modification time.

## Installation

### Windows

From the project directory:

```powershell
python -m pip install --upgrade .
```

Verify:

```powershell
novelslack --version
```

Start reading:

```powershell
novelslack --text "D:\Books\book.txt" 
```

### macOS / Linux

From the project directory:

```bash
python3 -m pip install --upgrade .
```

Verify:

```bash
novelslack --version
```

Start reading:

```bash
novelslack --text ~/Downloads/book.txt
```

If the system Python does not allow direct user-package installation, use a virtual environment.

## Keyboard shortcuts

### Reader

| Key | Action |
|---|---|
| `A` | Previous page |
| `D` / `Space` | Next page |
| `G` | Go to page |
| `/` / `F` | Search |
| `N` / `P` | Next / previous match |
| `X` / `Esc` | Clear search |
| `[` | Previous chapter |
| `]` | Next chapter |
| `T` | Go to chapter |
| `O` | Open catalog |
| `W` | Dashboard |
| `Q` | Quit |

### Cleanup Review

| Key | Action |
|---|---|
| `[` / `]` | Move selection |
| `Space` | Toggle |
| `Enter` | Execute selected cleanup |
| `W` | Return to Dashboard |

## Cross-platform backend

NovelSlack v0.7.0 isolates system-specific behavior behind three Platform Adapters:

```text
novelslack/platforms/
├── base.py
├── factory.py
├── windows.py
├── macos.py
└── linux.py
```

### Windows

- CPU: `GetSystemTimes`
- memory: `GlobalMemoryStatusEx`
- processes: Toolhelp + `tasklist`
- Recycle Bin: Windows Shell API
- TEMP / CrashDumps / WER

### macOS

- CPU: low-overhead load average
- memory: `vm_stat` + `sysctl hw.memsize`
- processes: `ps`
- Trash: `~/.Trash`
- DiagnosticReports

### Linux

- CPU: `/proc/stat`
- memory: `/proc/meminfo`
- processes: `/proc`
- Trash: XDG Trash
- state / cache: XDG locations

On shared macOS / Linux temp locations, automatic TEMP cleanup only accepts files owned by the current user.

## Low-load design

NovelSlack is designed to avoid becoming system load itself:

- one background maintenance worker
- incremental directory scans
- dirty rendering
- automatic scan throttling under CPU / memory pressure
- Reader / Catalog modes pause background directory scanning
- slower polling for heavier macOS probes
- no process killing
- no registry “optimization”
- no Prefetch clearing
- no standby-list purge
- no telemetry upload

## Privacy

NovelSlack runs locally.

It does not upload:

- book contents
- reading history
- system status
- process lists
- cleanup results
- user files

Runtime network access is not required.

## Book content

NovelSlack does **not** bundle, download, or distribute novels or other book content.

The Reader opens local TXT files supplied by the user. Use content you are authorized to access.

## Release

Latest release:

**[NovelSlack v0.7.0](https://github.com/Timhk3/novel-slack/releases/tag/v0.7.0)**

Windows, macOS, and Ubuntu CI are passing.
