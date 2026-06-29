# QQ群文件名合规检查插件设计

## 概述

当 QQ 群有成员上传文件时，机器人实时检测文件名是否符合规范格式（`分类--项目名称`，如 `素材--项目1`）。如果不符合，@提醒上传者并说明原因。合规的文件进入同步流程，路径按分类组织；不合规的文件保留在群中不同步，等待用户重命名后再次触发。

## 功能范围（第一阶段）

本设计文档覆盖第一阶段：**文件名合规检查与提醒**

### 已确定功能

1. **实时监听** — 监听群文件上传消息
2. **格式检查** — 检测文件名是否包含 `--` 分隔符
3. **分类白名单** — 可选配置，分组管理允许的分类
4. **@提醒通知** — 自定义模板 + 错误原因占位符
5. **不合规文件处理** — 不同步，只@提醒

### 后续阶段（不在本设计范围）

- 云盘存储路径重构（按分类组织）
- 不合规文件同步到待处理文件夹

---

## 配置项

### 新增配置项

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `filename_check_enabled` | bool | `false` | 是否启用文件名检查 |
| `filename_template` | string | `{category}--{name}` | 文件名模板格式 |
| `filename_categories` | dict | `{}` | 分类白名单（分组），可选，留空则只检查格式 |
| `filename_notify_template` | string | 见下方 | @提醒模板 |
| `sync_non_compliant` | bool | `false` | 是否同步不合规文件（预留） |

### 默认通知模板

```text
@{sender} 你上传的文件「{filename}」格式不规范
原因：{error_reason}
正确格式：{template}
可用分类：{categories}
```

### 分类白名单示例

```json
{
  "设计类": ["素材", "成品", "草稿"],
  "文档类": ["报告", "合同", "方案"]
}
```

---

## 占位符说明

`filename_notify_template` 支持以下占位符：

| 占位符 | 说明 |
|--------|------|
| `{sender}` | 上传者昵称 |
| `{sender_id}` | 上传者 QQ 号 |
| `{filename}` | 上传的文件名 |
| `{error_reason}` | 错误原因（系统自动填充） |
| `{template}` | 正确格式模板 |
| `{categories}` | 可用分类列表（格式化后的字符串） |

---

## 错误类型与原因

| 错误类型 | 触发条件 | `{error_reason}` 值 |
|----------|----------|---------------------|
| 格式错误 | 文件名不包含 `--` 分隔符 | `缺少分隔符 "--"` |
| 分类不在白名单 | 配置了白名单且文件名分类不在其中 | `分类「{category}」不在允许列表中` |

---

## 文件名检查流程

```
1. 收到群文件上传消息
2. 提取文件名（从 File 组件或 raw_message）
3. 检查是否包含 "--"
   ├─ 否 → 格式错误，返回 {error_reason: "缺少分隔符 '--'"}
   └─ 是 → 提取分类，检查白名单
           ├─ 白名单为空 → 合规，检查通过
           └─ 白名单不为空 → 分类在白名单中？
                            ├─ 是 → 合规，检查通过
                            └─ 否 → 返回 {error_reason: "分类「xxx」不在允许列表中"}
4. 如果不合规，发送 @提醒
5. 如果合规，触发后续同步逻辑（本阶段不实现）
```

---

## 数据结构

### FileValidationResult

```python
@dataclass
class FileValidationResult:
    is_valid: bool           # 是否合规
    filename: str            # 文件名
    category: str            # 提取的分类（如果有）
    error_type: str          # 错误类型（格式错误/分类不在白名单）
    error_reason: str        # 错误原因描述
    sender_id: str           # 上传者 QQ
    sender_name: str         # 上传者昵称
    group_id: str            # 群号
```

---

## 组件设计

### 1. 文件名检查器 (FilenameChecker)

**职责**：核心检查逻辑

```python
class FilenameChecker:
    def __init__(self, template: str, categories: dict):
        """
        template: 文件名模板，如 "{category}--{name}"
        categories: 分类白名单，如 {"设计类": ["素材", "成品"]}
        """

    def validate(self, filename: str) -> FileValidationResult:
        """验证文件名是否合规"""

    def extract_category(self, filename: str) -> Optional[str]:
        """从文件名提取分类"""

    def format_categories(self) -> str:
        """格式化分类列表为字符串"""
```

### 2. 通知服务 (NotifyService)

**职责**：发送 @提醒消息

```python
class NotifyService:
    def __init__(self, template: str):
        self.template = template

    def format_message(self, result: FileValidationResult) -> list:
        """根据模板和检查结果生成消息链"""

    async def notify(self, event: AstrMessageEvent, result: FileValidationResult):
        """发送 @提醒"""
```

### 3. 事件监听器 (FileUploadListener)

**职责**：监听群文件上传事件，触发检查

```python
class FileUploadListener:
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def on_group_message(self, event: AstrMessageEvent):
        # 检查消息中是否有 File 组件
        # 调用 FilenameChecker.validate()
        # 调用 NotifyService.notify()
```

---

## 配置示例

```json
{
  "filename_check_enabled": true,
  "filename_template": "{category}--{name}",
  "filename_categories": {
    "设计类": ["素材", "成品", "草稿"],
    "文档类": ["报告", "合同", "方案"]
  },
  "filename_notify_template": "@{sender} 你上传的文件「{filename}」格式不规范\n原因：{error_reason}\n正确格式：{template}\n可用分类：{categories}",
  "sync_non_compliant": false
}
```

---

## 文件结构

```
file_sync_plugin2/
├── __init__.py
├── main.py
├── config.py
├── services/
│   ├── __init__.py
│   ├── file_scanner.py      # 现有：文件扫描
│   ├── filename_checker.py  # 新增：文件名检查器
│   ├── notify_service.py    # 新增：通知服务
│   └── cloud_sync.py        # 现有：云盘同步
├── models/
│   ├── __init__.py
│   └── sync_record.py       # 现有
└── _conf_schema.json        # 更新：新增配置项
```

---

## 依赖关系

```
FileUploadListener
    ├── FilenameChecker
    │   └── 正则表达式处理
    └── NotifyService
        └── 消息组件 (Comp.At, Comp.Plain)
```

---

## 测试场景

| 场景 | 输入 | 期望输出 |
|------|------|----------|
| 合规文件名 | `素材--项目1.pdf` | `is_valid: True` |
| 缺少分隔符 | `素材项目1.pdf` | `is_valid: False, error_reason: 缺少分隔符 '--'` |
| 分类不在白名单 | `其他--项目1.pdf`（白名单含素材、成品） | `is_valid: False, error_reason: 分类「其他」不在允许列表中` |
| 白名单为空 | `任意--名称.pdf`（白名单为空） | `is_valid: True` |
| 多级分类 | `素材--子分类--项目1.pdf` | `is_valid: True, category: 素材` |

---

## 后续扩展（本阶段不实现）

1. **云盘路径重构** — 根据分类组织存储路径
2. **不合规文件同步** — 可选同步到待处理文件夹
3. **违规统计** — 记录违规历史用于分析

---

## 设计时间

2024-06-08