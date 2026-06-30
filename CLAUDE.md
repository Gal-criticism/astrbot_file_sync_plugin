# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

`file_sync_plugin2/` 是一个 AstrBot 插件，用于将 QQ 群文件自动同步到 NextCloud 私有云盘。支持命名规范校验、预设路径与群绑定、五层过滤、细化诊断日志。

## 开发命令

```bash
# 安装依赖
pip install -r file_sync_plugin2/requirements.txt

# 运行所有测试
pytest tests/ file_sync_plugin2/tests/ -v

# 运行单个测试文件
pytest tests/test_config.py -v
```

## 架构设计

```
main.py (FileSyncPlugin ~750行)                     ← 插件生命周期 + 命令注册
  └── handlers/                                       ← 命令与事件处理器
      ├── sync_commands.py      ← 同步命令 + 预设路径/群绑定管理
      ├── diagnostic_commands.py
      └── file_events.py        ← 文件上传事件: 命名检查 → 合规即时同步
  └── services/
      ├── naming_validator.py   ← 新命名规范验证器(六大分类 + 版本号 + 扩展名校验)
      ├── filename_checker.py   ← [deprecated] 旧 FilenameChecker(重定向到 NamingValidator)
      ├── cloud_sync.py         ← NextCloud WebDAV(PROPFIND/MKCOL/PUT)
      ├── state_manager.py      ← SQLite(sync_records/retry_queue/preset_paths/group_bindings)
      ├── file_scanner.py       ← QQ 群文件 API 封装
      ├── file_downloader.py    ← QQ 群文件流式下载(httpx AsyncClient; file_size=0 跳过大小校验)
      ├── sync_executor.py      ← 单文件同步协调器(下载→上传,返回 SyncResult)
      └── notify_service.py     ← @提醒消息链构建
  └── models/
      ├── naming_result.py      ← NamingResult(含 errors 列表 + suggested_fix)
      ├── sync_result.py        ← SyncResult(failed_stage 枚举 + naming_*)
      ├── sync_record.py
      └── validation_result.py  ← [deprecated]
  └── utils/ (constants.py / config_helpers.py / rename.py)
```

### 同步流程

**三种触发方式**:
1. **监听上传即时同步** — `handle_file_upload()` 命名合规 → `sync_uploaded_file()` 即时上传
2. **定时同步** — `_sync_loop()` → `sync_all_groups()` → `sync_group()`
3. **手动命令** — `/同步文件` → `sync_all_groups()`

**五层过滤** (见 [main.py:sync_group](file_sync_plugin2/main.py#L376)):
1. 文件类型: `is_file_type_allowed()` → 跳过
2. 时间戳: `upload_time <= last_sync_time` → 跳过
3. file_id 精确匹配: `is_synced(file_id)` → 跳过
4. 文件名+大小+群号: `is_synced_by_name_size()` → 跳过
5. 命名规范: `naming_validator.parse()` 不合规且非数据组测试 → 跳过

**路径优先级**: preset_path (SQLite group_bindings) > base_path 回退

**启动时自动种子化**: `config.startup_presets` → WebDAV 校验路径存在 → 写入 SQLite

**开关**: `sync_enabled=false` → 定时循环不启动; `enabled_groups` 作为安全开关

### 命名规范

新格式: `{项目名称}-{分类}[v{版本号}][-{后缀}].{扩展名}`  
兼容旧格式: `{分类}--{名称}.{扩展名}` (deprecated)  
六大标准分类: 封面/成片/素材/音频/字幕/数据组测试  

详情见 [docs/superpowers/specs/2026-06-29-同步上传逻辑文档.md](file_sync_plugin2/docs/superpowers/specs/2026-06-29-同步上传逻辑文档.md)

## 测试 Mock 配置

[conftest.py](conftest.py) 和 [tests/conftest.py](tests/conftest.py) 预先 mock 了 `astrbot` 相关模块。

## 深入文档

| 文档 | 内容 |
|------|------|
| [同步上传逻辑文档](file_sync_plugin2/docs/superpowers/specs/2026-06-29-同步上传逻辑文档.md) | 完整同步流程、五层过滤、命名规范、预设路径、命令列表、配置一览 |
| [命名规范](file_sync_plugin2/docs/superpowers/命名规范.md) | 六大标准分类规范详情 |

## 红线

- 禁止修改 SyncResult 的 boolean 判断语义 — `result.success` 是唯一正确用法
- 禁止删除旧兼容层 filename_checker.py — 仍被部分代码引用
- preset_paths 已从 JSON 配置迁移到 SQLite，不要在 config.py 中重新添加 JSON 版
