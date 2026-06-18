# 会话 B · 导入引擎

## 前置依赖（会话 A 已完成）

以下文件已就绪，你可直接 import 使用：

### ORM 模型（`backend/app/models/`）
| 文件 | 模型 | 核心字段 |
|------|------|---------|
| `company.py` | `Company` | id(UUID), name, code(唯一), tax_id, industry, firm_id(预留), is_active |
| `account.py` | `Account` | id, company_id(FK), code, name, level, parent_code, direction(debit/credit), category |
| `trial_balance.py` | `TrialBalance` | company_id, fiscal_year, period(1-12), account_code/name, opening_debit/credit, current_debit/credit, ending_debit/credit, extra_fields(JSON) |
| `journal_entry.py` | `JournalEntry` | company_id, fiscal_year, period, voucher_no, voucher_date(date), summary, account_code/name, debit_amount, credit_amount, attachment_count |
| `subsidiary_ledger.py` | `SubsidiaryLedger` | 同上 + auxiliary_type, auxiliary_code, auxiliary_name |

### 枚举（`backend/app/models/enums.py`）
- `AuxiliaryType`: customer / supplier / department / project / person / inventory / other

### 数据库会话
```python
from app.core.database import async_session_factory, get_db
# get_db 是 FastAPI 依赖注入，返回 AsyncSession
```

---

## 你的任务：构建导入引擎

### 1. 文件解析器 `backend/app/services/file_parser.py`

**输入**：上传的文件路径（`.xlsx` / `.xls` / `.csv`）  
**输出**：`(headers: list[str], rows: list[list])`

要求：
- 用 `pandas` + `openpyxl` 读取
- 自动识别 sheet（csv 就一个，xlsx 默认第一个 sheet）
- 前 5 行识别表头行（遇到第一个全非空行即为表头）
- 返回清洗后的表头列表和所有数据行

```python
def parse_file(file_path: str) -> tuple[list[str], list[list]]:
    """返回 (表头列表, 数据行列表)"""
    ...
```

### 2. 列名匹配器 `backend/app/services/column_matcher.py`

**输入**：解析出的表头列表 + 目标数据类型（trial_balance / journal / subsidiary）  
**输出**：匹配结果 `{"column_name": "mapped_field", ...}`，以及未匹配的列

关键词库示例：
```python
KEYWORD_MAP = {
    "account_code": ["科目编码", "科目代码", "account code", "account_code", "科目号"],
    "account_name": ["科目名称", "科目", "account name", "account_name"],
    "debit_amount": ["借方金额", "借方发生额", "debit", "借方", "借"],
    "credit_amount": ["贷方金额", "贷方发生额", "credit", "贷方", "贷"],
    "voucher_no": ["凭证号", "凭证编号", "voucher", "voucher_no", "传票号"],
    "voucher_date": ["凭证日期", "日期", "date", "voucher_date"],
    "summary": ["摘要", "说明", "description", "summary"],
    ...
}
```

要求：
- 模糊匹配：用 `difflib.SequenceMatcher` 或直接 `in` 包含匹配
- 返回 `{"matched": {...}, "unmatched": [...], "data_type": "journal"}`

```python
def auto_match(headers: list[str], data_type: str) -> dict:
    """自动匹配列名，返回匹配结果"""
    ...

def get_required_fields(data_type: str) -> list[str]:
    """返回该数据类型必填字段列表"""
    ...
```

### 3. 数据校验器 `backend/app/services/validator.py`

**输入**：数据行列表 + 列映射 + 数据类型  
**输出**：`(valid_rows, error_rows)`

校验规则：
- 科目余额表：同一公司+年度+期间内，期末借方合计 = 期末贷方合计
- 序时账：同一凭证号内，借方合计 = 贷方合计
- 通用：必填字段不能为空、金额不能为负、日期格式正确
- 科目编码在 accounts 表中存在（或记录为新增科目）

```python
async def validate_rows(
    db: AsyncSession,
    company_id: UUID,
    rows: list[dict],
    data_type: str,
) -> tuple[list[dict], list[dict]]:
    """校验数据行，返回 (有效行, 错误行含错误信息)"""
    ...
```

### 4. 导入服务 `backend/app/services/import_service.py`

整合上面三步，提供统一入口：

```python
async def import_data(
    db: AsyncSession,
    company_id: UUID,
    file_path: str,
    data_type: str,
    column_mapping: dict | None = None,  # None 时自动匹配
) -> dict:
    """
    完整导入流程：
    1. 解析文件 → 表头 + 数据行
    2. 列匹配（自动 or 使用用户映射）
    3. 数据校验
    4. 批量写入对应表
    5. 返回结果：{"total": 100, "success": 95, "errors": [...]}
    """
    ...

async def preview_import(
    file_path: str,
    data_type: str,
) -> dict:
    """
    预览导入（不实际写入）：
    返回 {"headers": [...], "matched": {...}, "unmatched": [...], "preview_rows": [...]}
    """
    ...
```

---

## 接口契约（与前端对接）

### 预览接口（你建）
```
POST /api/v1/imports/preview
Body: { "file": <上传文件>, "data_type": "journal" }
Response: {
  "headers": ["科目编码", "科目名称", ...],
  "matched": {"科目编码": "account_code", ...},
  "unmatched": ["备注"],
  "preview_rows": [[...], ...]  // 前10行
}
```

### 执行导入接口（你建）
```
POST /api/v1/imports/execute
Body: {
  "company_id": "uuid",
  "data_type": "journal",
  "column_mapping": {"科目编码": "account_code", ...},  // 用户确认后的映射
  "file_path": "/uploads/xxx.xlsx"
}
Response: {
  "total": 5000,
  "success": 4980,
  "errors": [{"row": 23, "message": "借贷不平衡"}]
}
```

---

## 关键路径

```
backend/app/services/
├── file_parser.py        # 新建
├── column_matcher.py     # 新建
├── validator.py          # 新建
└── import_service.py     # 新建

backend/app/api/
└── imports.py            # 新建：两个路由
```

## 自测验证

```bash
cd backend
python -c "
from app.services.file_parser import parse_file
headers, rows = parse_file('test.xlsx')
print('Headers:', headers)
print('Rows:', len(rows))
"
```
