# pjgdcli - 本地票据归档 CLI

基于 Python + Click + SQLite + Rich 的本地票据归档管理工具。

## 功能特性

- ✅ 新增票据（发票号、金额、日期、项目、备注、标签、报销状态）
- ✅ 按项目、月份查询，支持金额区间和标签组合过滤
- ✅ 标签管理（绑定/移除/列表）
- ✅ 标记已报销 / 回退未报销
- ✅ 撤销最近一次状态变更（保留历史）
- ✅ CSV 批量导入，内置严格校验（金额、日期、发票号去重、必填字段）
- ✅ 导入失败行生成错误报告 CSV
- ✅ 月度汇总报表（按项目展示已报销/未报销金额）
- ✅ 导入批次报表，异常批次高亮显示

## 项目结构

```
pjgdcli/
├── pyproject.toml
├── requirements.txt
├── src/
│   └── pjgdcli/
│       ├── __init__.py
│       ├── database.py      # SQLite 连接与表结构
│       ├── services.py      # 业务逻辑层
│       └── cli.py           # Click CLI 入口
├── examples/
│   ├── receipts_sample.csv         # 正常示例 CSV
│   └── receipts_with_errors.csv    # 含错误的示例 CSV
└── README.md
```

数据存储位置：`~/.pjgdcli/receipts.db`
导入失败报告：`~/.pjgdcli/reports/`

## 安装

```bash
# 方式 1：直接安装依赖运行
pip install -r requirements.txt
export PYTHONPATH=src
python -m pjgdcli.cli --help

# 方式 2：以包形式安装（推荐）
pip install -e .
pjgdcli --help
```

## 命令总览

```
pjgdcli init          # 初始化数据库
pjgdcli add           # 新增票据
pjgdcli list          # 查询票据（多条件过滤）
pjgdcli reimburse     # 标记已报销
pjgdcli unreimburse   # 回退未报销
pjgdcli undo          # 撤销最近一次状态变更
pjgdcli tag list      # 列出所有标签
pjgdcli tag add       # 为票据绑定标签
pjgdcli tag remove    # 从票据移除标签
pjgdcli import        # 从 CSV 批量导入
pjgdcli summary       # 月度汇总报表
pjgdcli batches       # 查看导入批次（含异常）
```

## 详细使用说明

### 1. 初始化

```bash
pjgdcli init
```

### 2. 新增票据

```bash
# 基本用法
pjgdcli add -i FP20260001 -a 299.50 -d 2026-06-01 -p 项目A -m "客户招待晚餐"

# 带标签 + 直接标记已报销
pjgdcli add -i FP20260002 -a 1280.00 -d 2026-06-05 -p 项目B -t 差旅 -t 交通 -r
```

参数说明：
- `-i, --invoice` 发票号（**唯一**，必填）
- `-a, --amount` 金额（正数，必填）
- `-d, --date` 日期，格式 `YYYY-MM-DD`（必填）
- `-p, --project` 项目名称（必填）
- `-m, --desc` 备注说明
- `-t, --tag` 标签，可多次指定
- `-r, --reimbursed` 新增时即标记已报销

### 3. 查询票据

```bash
# 全部
pjgdcli list

# 按项目
pjgdcli list -p 项目A

# 按月份 (YYYY-MM)
pjgdcli list -m 2026-06

# 金额区间
pjgdcli list --min-amount 100 --max-amount 1000

# 组合标签（AND 关系，需同时匹配所有）
pjgdcli list -t 差旅 -t 餐饮

# 多条件组合
pjgdcli list -p 项目A -m 2026-06 --min-amount 200 -t 差旅

# 按状态
pjgdcli list -s reimbursed
```

### 4. 报销状态管理

```bash
# 标记为已报销
pjgdcli reimburse 1

# 回退为未报销
pjgdcli unreimburse 1

# 撤销最近一次状态变更（恢复到上一次状态）
pjgdcli undo 1
```

### 5. 标签管理

```bash
# 列出所有标签及其关联票据数
pjgdcli tag list

# 为票据 ID=1 绑定多个标签
pjgdcli tag add 1 餐饮 招待 VIP

# 从票据 ID=1 移除标签
pjgdcli tag remove 1 VIP
```

### 6. CSV 批量导入

CSV 必填字段：`invoice_number`, `amount`, `date`, `project`
可选字段：`description`, `tags`（多个标签用分号 `;` 分隔）

**示例 CSV** (`examples/receipts_sample.csv`)：
```csv
invoice_number,amount,date,project,description,tags
FP20260101001,299.50,2026-01-15,项目A,北京出差-餐饮,餐饮;差旅
FP20260101002,1200.00,2026-01-18,项目A,高铁票北京-上海,交通;差旅
FP20260101003,458.00,2026-01-20,项目B,办公用品采购,办公
```

导入命令：

```bash
pjgdcli import examples/receipts_sample.csv
```

导入校验规则：
- 必填字段缺失 → 失败
- 金额非正数或格式错误 → 失败
- 日期非 `YYYY-MM-DD` → 失败
- 发票号在 CSV 内重复 → 失败
- 发票号已存在于数据库 → 失败

失败行会被记录并生成独立报告 CSV，路径显示在导入结果中。

### 7. 月度汇总报表

```bash
pjgdcli summary -m 2026-06
```

输出按项目分组，显示：
- 票据数量
- 已报销金额合计
- 未报销金额合计
- 总计金额

### 8. 导入批次报表

```bash
# 全部批次
pjgdcli batches

# 仅显示有失败记录的异常批次
pjgdcli batches -f
```

异常批次会高亮显示，并列出前 10 条失败明细，完整报告可查看对应路径。

## 快速验证（必跑示例）

```bash
# 1. 初始化
pjgdcli init

# 2. 新增成功
pjgdcli add -i FPTEST001 -a 300.00 -d 2026-06-10 -p 项目A -m "测试票据1" -t 测试

# 3. 重复发票号应失败
pjgdcli add -i FPTEST001 -a 500.00 -d 2026-06-11 -p 项目B
# → 应提示：发票号已存在: FPTEST001

# 4. 标记报销再撤销
pjgdcli reimburse 1
pjgdcli list -s reimbursed    # 应能看到已报销
pjgdcli undo 1
pjgdcli list -s unreimbursed  # 应恢复为未报销

# 5. 批量导入
pjgdcli import examples/receipts_sample.csv
pjgdcli import examples/receipts_with_errors.csv

# 6. 查看月度汇总
pjgdcli summary -m 2026-01

# 7. 查询验证（与汇总金额一致）
pjgdcli list -m 2026-01

# 8. 查看异常批次
pjgdcli batches -f
```

## 设计说明

### 数据库表

| 表名 | 用途 |
|---|---|
| `receipts` | 票据主表（发票号唯一） |
| `tags` | 标签字典（名称唯一） |
| `receipt_tags` | 票据-标签多对多关联 |
| `status_history` | 状态变更历史（用于 undo） |
| `import_batches` | CSV 导入批次记录 |
| `import_failures` | 导入失败明细 |

### 状态流转

```
unreimbursed (默认) <-> reimbursed
         ↑              ↑
         └── undo 基于 status_history 回退
```

每次 `reimburse`/`unreimburse`/`undo` 都会在 `status_history` 写入一条记录，保证可追溯。
