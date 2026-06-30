# FileSyncPlugin - QQ群文件同步NextCloud

QQ群文件自动同步到NextCloud私有云盘的AstrBot插件。

## 功能

- 定时扫描QQ群文件（支持间隔模式和时间点模式）
- **文件上传即时同步**：命名合规的文件在上传群后即刻自动同步到 NextCloud（无需等定时任务）
- 自动同步文件到NextCloud（按命名规范分析自动归类子目录）
- **五层过滤**：文件类型 → 时间戳 → file_id去重 → name+size去重 → 命名规范
- **细粒度失败诊断**：10+ 种失败阶段枚举，精确到下载/上传的具体原因
- **文件命名规范检查**：六大标准分类（封面/成片/素材/音频/字幕/数据组测试）
  - 新格式：`项目名称-分类v版本号-后缀.扩展名`
  - 兼容旧格式：`分类--名称.扩展名`（deprecated，温和提醒迁移）
- **预设路径与群绑定**：群 → 预设路径 → 自动定向云盘目录，通过WebDAV校验
  - **启动自动种子化**：配置 `startup_presets`，启动时自动校验路径存在并写入 SQLite
- **云盘目录分级**：`{预设路径}/{分类}[/工程]/{文件名}`
- 同步失败自动重试（最多3次），耗尽后群内通知
- **诊断日志**：记录跳过原因、失败阶段、命名分析，可通过命令查看

## 命令

| 命令 | 功能 |
|------|------|
| `/同步文件` | 手动触发全群同步 |
| `/同步状态` | 查看同步统计（总数/待重试） |
| `/同步统计 [群号]` | 分群统计或总览 |
| `/同步调试` | 检查后端 API 可用性 |
| `/诊断日志` | 查看最近诊断日志 |
| `/清空诊断日志` | 清空诊断日志 |
| `/预设路径 列表/添加/删除` | 预设路径管理（添加时WebDAV校验） |
| `/绑定路径 <群号> <名称>` | 绑定群到预设路径 |
| `/解绑路径 <群号>` | 解除群绑定 |
| `/绑定列表` | 列出所有绑定关系 |

## 配置

在AstrBot管理面板中配置以下选项：

| 配置项 | 说明 | 默认值 |
|-------|------|--------|
| `sync_enabled` | 同步功能总开关（false则定时循环不启动） | `true` |
| `nextcloud_url` | NextCloud WebDAV地址 | — |
| `nextcloud_username` | NextCloud用户名 | — |
| `nextcloud_password` | NextCloud应用密码 | — |
| `enabled_groups` | 启用的群号列表（安全开关，需同步配置群绑定） | — |
| `base_path` | 回退用云盘基础路径（群未绑定时使用） | `/QQ群文件` |
| `sync_interval_minutes` | 同步间隔（分钟） | `1440` |
| `sync_time_points` | 同步时间点，格式 `["08:00", "12:00"]`，配置后覆盖间隔模式 | `[]` |
| `file_type_whitelist` | 允许的文件类型，`["*"]` 表示全部 | `["*"]` |
| `retry_queue_enabled` | 启用失败重试队列 | `true` |
| `retry_max_attempts` | 最大重试次数 | `3` |
| `retry_delay_seconds` | 重试间隔（秒） | `300` |
| `filename_check_enabled` | 启用上传时文件名检查 | `false` |
| `filename_check_enabled` | 文件名模板 | `{project_name}-{category}v{version}-{suffix}.{ext}` |
| `naming_extra_categories` | 自定义扩展分类（JSON格式） | `{}` |
| `filename_notify_template` | @提醒自定义模板 | — |
| `startup_presets` | 预设路径映射 {名称: 路径}，启动时自动种子化到 SQLite | `{}` |

## 路径规则

**有群绑定时**: `{preset_path}/{分类}[/工程]/{文件名}`  
**无群绑定时**: `{base_path}/{群名_群号}/{分类}[/工程]/{文件名}`  

工程后缀（`工程/工程v2/工程-PR2022`）仅在成片、音频分类下产生二级`工程/`目录。

## 命名规范

```
新格式: {项目名称}-{分类}[v{版本号}][-{后缀}].{扩展名}
旧格式: {分类}--{名称}.{扩展名}  (deprecated，仍接受但温和提醒)
```

六大标准分类: 封面 / 成片 / 素材 / 音频 / 字幕 / 数据组测试

详情见 [同步上传逻辑文档](docs/superpowers/specs/2026-06-29-同步上传逻辑文档.md)

## 架构

```
file_sync_plugin2/
├── main.py            # 插件生命周期 + 命令注册 (~750行)
├── config.py          # Pydantic 配置模型(含 startup_presets)
├── handlers/          # 命令与事件处理器
│   ├── sync_commands.py      # 同步命令 + 预设路径/群绑定管理
│   ├── diagnostic_commands.py
│   └── file_events.py        # 文件上传事件: 命名检查 → 合规即时同步
├── services/          # 核心服务
│   ├── naming_validator.py   # 新命名规范验证器
│   ├── filename_checker.py   # [deprecated] 旧兼容层
│   ├── cloud_sync.py         # NextCloud WebDAV
│   ├── state_manager.py      # SQLite 状态管理(含预设路径+群绑定)
│   ├── file_scanner.py       # QQ群文件API
│   ├── file_downloader.py    # 流式下载(支持file_size=0跳过校验)
│   ├── sync_executor.py      # 下载→上传协调器
│   └── notify_service.py     # @提醒
├── models/            # 数据模型
│   ├── naming_result.py      # NamingResult
│   ├── sync_result.py        # SyncResult(失败阶段枚举)
│   ├── sync_record.py
│   └── validation_result.py  # [deprecated]
├── utils/             # 工具
│   ├── constants.py
│   ├── config_helpers.py
│   └── rename.py
├── tests/             # 测试
└── docs/              # 文档
```

## 安装

1. 将 `file_sync_plugin2` 目录复制到 AstrBot 插件目录
2. 在 AstrBot 管理面板中启用插件
3. 配置 NextCloud 连接信息、启用的群号，以及 `filename_check_enabled=true`
4. （可选）配置 `startup_presets`，启动时自动种子化预设路径
5. 绑定群到预设路径：`/绑定路径 <群号> <路径名称>`

> 预设路径也可以通过命令手动添加：`/预设路径 添加 <名称> <NextCloud路径>`（添加时 WebDAV 校验路径存在）

## 开发

```bash
pip install -r file_sync_plugin2/requirements.txt
pytest tests/ file_sync_plugin2/tests/ -v
```

## License

MIT
