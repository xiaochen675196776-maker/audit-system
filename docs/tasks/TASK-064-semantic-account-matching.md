# TASK-064：科目语义匹配增强（客户代码与标准代码可不一致）

状态：OPEN
负责人：worker
优先级：P0
提出时间：2026-06-23

## 背景

真实验收文件：

```text
D:\NAS\xiaochen\李辉辉项目组\SynologyDrive\汇达228股改审计\1.账套\aglq710-科目余额表 20251231.xlsx
```

在标准化导入第 3 步“层级与科目匹配”中，当前流程可以完成上传、字段自动映射、层级识别和部分自动匹配，但仍有大量末级客户科目未匹配：

```text
全部 289
已匹配 112
未匹配 89
已忽略 0
有警告 139
```

这不是 UI 问题，也不是简单的标准科目库缺项问题。核心问题是当前匹配机制仍然过度依赖客户科目代码、代码前缀、名称字面包含关系。

真实业务中，客户账套科目代码体系和系统标准科目代码体系可能不同：

- 客户科目代码可能是 `112301`，标准科目代码可能是 `112401`。
- 客户科目名称可能是 `预付账款_预付材料款`，标准科目名称可能是 `预付款项`。
- 两者代码不同、名称字面也不完全一样，但经济含义一致，应该能自动匹配。
- 反过来，代码相同但经济含义冲突时，必须拒绝自动匹配，例如客户 `112301 预付账款_预付材料款` 不得匹配标准 `112301 应收款项融资`。

## 目标

把科目匹配从“代码/字面名称匹配”升级为“科目语义匹配”：

```text
客户科目代码 + 客户科目名称
→ 识别客户科目经济含义锚点
→ 映射到标准科目语义锚点
→ 在标准科目库中找启用科目
→ 生成安全候选
→ 安全时自动确认；不安全时只给 warning 候选
```

验收目标：

- 真实文件仍能上传并进入第 3 步。
- 字段映射和 UI 横向滚动不要回退。
- 未匹配数量必须明显下降，至少要解决本任务列出的语义等价类。
- 代码相同但语义冲突的候选不得自动确认。

## 产品口径

### 1. 客户代码不是标准科目匹配主键

不要把客户科目代码当成标准科目代码。

允许以下情况自动匹配：

```text
客户：112301 预付账款_预付材料款
标准：112401 预付款项
```

禁止以下情况自动匹配：

```text
客户：112301 预付账款_预付材料款
标准：112301 应收款项融资
```

### 2. 匹配应优先看经济含义

需要建立可维护的语义锚点/别名表，而不是针对单个例子写死。

示例别名关系：

```text
预付账款 / 预付款 / 预付款项      -> 预付款项
累计折旧 / 固定资产累计折旧      -> 减：固定资产-累计折旧
在建工程 / 在安装设备 / 工程项目  -> 在建工程-原值
其他应收款 / 备用金 / 押金保证金  -> 其他应收款
其他应付款                       -> 其他应付款
应交税费 / 应交税金              -> 应交税费
预收账款 / 预收款项              -> 合同负债（如果标准库只有合同负债）
长期待摊费用                     -> 长期待摊费用
无形资产累计摊销                 -> 减：无形资产-累计摊销
```

这些只是第一批验收锚点，不代表只能支持这些。实现要能继续扩展。

### 3. 安全自动确认条件

只有满足全部条件，候选才允许 `warning=None` 且 `score >= 0.9`：

- 标准科目启用。
- 客户科目名称能识别出明确语义锚点。
- 标准科目名称能归一到同一个语义锚点。
- 不存在方向/类别冲突，例如：
  - `预付` 不得自动匹配 `应收款项融资`。
  - `库存商品` 不得自动匹配 `产品成本差异`。
  - `应收`、`应付`、`预收`、`预付` 不能仅因代码相近互相匹配。
- 参与入库的末级客户科目才需要自动确认；父级行不入库，不要求匹配。

### 4. 危险候选仍要保留为 warning

如果代码相同但语义冲突，仍可作为候选展示给用户确认，但不得自动选中：

```text
source = code_match_conflict
score < 0.9
warning != None
```

## 必改文件

```text
backend/app/services/client_account_mapping_service.py
backend/tests/test_client_account_mapping_service.py
```

如需要补前端来源标签，可改：

```text
frontend/src/views/DataImportView.vue
frontend/src/types/index.ts
```

不要改：

```text
层级识别算法
金额拆分逻辑
第三步表格布局、列宽、横向滚动样式
旧导入流程或模板相关代码
```

## 实现建议

### A. 增加语义锚点配置

在 `backend/app/services/client_account_mapping_service.py` 中新增结构，建议形态如下：

```python
_SEMANTIC_ACCOUNT_GROUPS: dict[str, dict[str, object]] = {
    "prepayments": {
        "canonical": "预付款项",
        "client_aliases": ["预付账款", "预付款", "预付款项"],
        "standard_aliases": ["预付款项", "预付账款"],
        "negative_aliases": ["应收款项融资", "应收账款", "其他应收款"],
    },
    "accumulated_depreciation": {
        "canonical": "累计折旧",
        "client_aliases": ["累计折旧", "固定资产累计折旧"],
        "standard_aliases": ["固定资产累计折旧", "减固定资产累计折旧", "减：固定资产-累计折旧"],
        "negative_aliases": ["固定资产原值", "固定资产"],
    },
    "construction_in_progress": {
        "canonical": "在建工程",
        "client_aliases": ["在建工程", "在安装设备", "工程项目", "装修费用"],
        "standard_aliases": ["在建工程", "在建工程原值", "在建工程-原值"],
        "negative_aliases": ["在建工程减值准备"],
    },
}
```

注意：

- 这是示例结构，可以调整命名。
- 不要只写 `if client_name contains 预付账款 then 112401` 这种硬编码。
- 标准科目代码不能写死，必须从 `standard_accounts` 表查启用标准科目。

### B. 增加语义识别函数

建议新增函数：

```python
def _detect_semantic_group(client_name: str | None) -> str | None:
    ...

def _standard_account_matches_semantic_group(sa: StandardAccount, group_key: str) -> bool:
    ...

def _standard_account_conflicts_semantic_group(sa: StandardAccount, group_key: str) -> bool:
    ...

async def _query_semantic_alias_match(
    db: AsyncSession,
    client_name: str,
) -> list[StandardAccount]:
    ...
```

要求：

- 复用现有 `_normalize_name()` 和 `_canonical_name()`。
- 标准名称要能识别 `减：`、`加：`、`其中：` 等显示前缀。
- 语义匹配只返回启用标准科目优先；停用科目只能 warning。
- 如果多个标准科目都命中同一个语义组，优先名称完全等价，再按更安全的主科目排序。

### C. 插入推荐优先级

在 `recommend_mappings()` 中，把语义别名匹配放在危险代码匹配之后、弱相似度之前或替换弱相似度：

建议顺序：

```text
1. 同客户历史确认
2. 全局历史确认
3. 代码精确匹配，但必须做名称/语义冲突检测
4. 名称规范化精确匹配
5. 语义别名匹配
6. 代码类别锚点 / 名称锚点 / 前缀归集
7. 弱相似度兜底
```

如果语义别名候选和危险代码候选同时存在，安全语义候选应排在前面。

### D. 新增候选来源标签

后端候选可新增：

```text
source = semantic_alias
reason = 语义别名匹配：客户「预付账款」≈ 标准「预付款项」
score = 0.93
warning = None
```

如果前端需要展示来源，补充：

```text
semantic_alias: 语义匹配
```

## 必须新增的测试

在 `backend/tests/test_client_account_mapping_service.py` 新增测试类：

```python
class TestSemanticAccountMatching:
    """客户科目代码与标准科目代码不一致时，按经济含义匹配。"""
```

### 1. 预付账款匹配预付款项

测试数据：

```python
standards = [
    _make_standard_account("112301", "应收款项融资"),
    _make_standard_account("112302", "加：应收款项融资-公允价值变动"),
    _make_standard_account("112401", "预付款项"),
    _make_standard_account("112402", "减：预付款项-坏账准备"),
]
```

输入：

```python
[
    {"client_account_code": "112301", "client_account_name": "预付账款_预付材料款"},
    {"client_account_code": "112302", "client_account_name": "预付账款_预付机物料款"},
]
```

断言：

```python
safe = [
    c for c in candidates
    if c["standard_account_code"] == "112401"
    and c["warning"] is None
    and c["score"] >= 0.9
]
assert safe

bad = [
    c for c in candidates
    if c["standard_account_code"] in ("112301", "112302")
    and c["warning"] is None
    and c["score"] >= 0.9
]
assert not bad
```

### 2. 累计折旧明细匹配累计折旧标准科目

测试数据：

```python
standards = [
    _make_standard_account("1601", "固定资产-原值"),
    _make_standard_account("1602", "减：固定资产-累计折旧"),
]
```

输入：

```python
[
    {"client_account_code": "160202", "client_account_name": "累计折旧_机器设备"},
    {"client_account_code": "160203", "client_account_name": "累计折旧_运输设备"},
    {"client_account_code": "160204", "client_account_name": "累计折旧_其他设备"},
]
```

断言都应安全匹配 `1602 减：固定资产-累计折旧`。

### 3. 在建工程明细匹配在建工程原值

测试数据：

```python
standards = [
    _make_standard_account("160401", "在建工程-原值"),
    _make_standard_account("160402", "减：在建工程-减值准备"),
]
```

输入：

```python
[
    {"client_account_code": "160403", "client_account_name": "在建工程_在安装设备"},
    {"client_account_code": "160404", "client_account_name": "在建工程_其他费用"},
    {"client_account_code": "160405", "client_account_name": "在建工程_装修费用"},
    {"client_account_code": "160406", "client_account_name": "在建工程_工程项目"},
]
```

断言都应安全匹配 `160401 在建工程-原值`，不得匹配 `160402 减：在建工程-减值准备`。

### 4. 代码相同但语义冲突仍不能自动确认

输入：

```python
{"client_account_code": "112301", "client_account_name": "预付账款_预付材料款"}
```

标准：

```python
_make_standard_account("112301", "应收款项融资")
```

断言：

```python
conflict = next(c for c in candidates if c["source"] == "code_match_conflict")
assert conflict["warning"] is not None
assert conflict["score"] < 0.9
```

### 5. 库存商品仍不能错配产品成本差异

保留或补强现有测试：

```python
standards = [
    _make_standard_account("1405", "库存商品"),
    _make_standard_account("140501", "产品成本差异"),
]
input = {"client_account_code": "140501", "client_account_name": "库存商品"}
```

断言：

- 安全候选是 `1405 库存商品`。
- `140501 产品成本差异` 只能 warning，不能自动确认。

## 真实文件验收

启动后端和前端：

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 18000

cd D:\APP\Codex-项目\13、审计系统\frontend
$env:VITE_API_TARGET='http://127.0.0.1:18000'
npm run dev -- --host 127.0.0.1 --port 5177
```

浏览器验收：

1. 打开 `http://127.0.0.1:5177/data/import`。
2. 上传：

```text
D:\NAS\xiaochen\李辉辉项目组\SynologyDrive\汇达228股改审计\1.账套\aglq710-科目余额表 20251231.xlsx
```

3. 客户标识填 `Huida 228 QA`，年度 `2025`，期间 `12`。
4. 进入字段映射页，确认前 8 列自动映射：
   - 科目编号 -> 客户科目代码
   - 说明 -> 客户科目名称
   - 本币期初(借) -> 期初借方
   - 本币期初(贷) -> 期初贷方
   - 本币期间异动(借) -> 本期借方
   - 本币期间异动(贷) -> 本期贷方
   - 本币期末(借) -> 期末借方
   - 本币期末(贷) -> 期末贷方
5. 进入“层级与科目匹配”。
6. 验证：
   - `112301 预付账款_预付材料款` 已匹配 `112401 预付款项`。
   - `112302 预付账款_预付机物料款` 已匹配 `112401 预付款项`。
   - `160202/160203/160204 累计折旧_*` 已匹配 `1602 减：固定资产-累计折旧`。
   - `160403/160404/160405/160406 在建工程_*` 已匹配 `160401 在建工程-原值`。
   - `140501 库存商品` 仍匹配 `1405 库存商品`，不得匹配 `140501 产品成本差异`。
   - `10020108/10020141` 银行明细仍匹配 `1002 银行存款`，不能回退。
   - `660401 研发费用` 仍匹配 `660201 减：研发费用`，不能回退。
7. 未匹配数量必须明显低于修复前的 `89`。

不要为了通过验收自动忽略未匹配行。忽略是用户操作，不是匹配算法的替代品。

## 自动化验证

必须执行：

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m pytest tests/test_client_account_mapping_service.py -q
D:\python\python.exe -m pytest tests/test_standard_trial_balance_import.py -q
D:\python\python.exe -m pytest tests/ -q

cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
```

期望：

- 后端测试全部通过。
- 前端构建通过。
- 真实文件浏览器验收通过。

## 给弱模型的领取提示词

```text
你负责实现 docs/tasks/TASK-064-semantic-account-matching.md。

工作目录：
D:\APP\Codex-项目\13、审计系统

先阅读：
- docs/tasks/TASK-064-semantic-account-matching.md
- backend/app/services/client_account_mapping_service.py
- backend/tests/test_client_account_mapping_service.py

任务目标：
把客户科目到标准科目的匹配从“代码/字面名称匹配”增强为“语义匹配”。客户科目代码和标准科目代码可能不一致，不能把代码当主键。例如客户 112301 预付账款_预付材料款 应匹配标准 112401 预付款项，而不是匹配同代码的 112301 应收款项融资。

要求：
1. 不要硬编码单个例子，不要写 if code == 112301 then 112401。
2. 建立可维护的语义锚点/别名表。
3. 保留代码冲突保护：代码相同但语义冲突时，只能 warning，不能自动确认。
4. 新增测试覆盖预付账款/累计折旧/在建工程/库存商品等场景。
5. 不要修改第三步 UI 布局、金额列、横向滚动。

验收命令：
D:\python\python.exe -m pytest tests/test_client_account_mapping_service.py -q
D:\python\python.exe -m pytest tests/test_standard_trial_balance_import.py -q
D:\python\python.exe -m pytest tests/ -q
npm run build

真实文件验收：
D:\NAS\xiaochen\李辉辉项目组\SynologyDrive\汇达228股改审计\1.账套\aglq710-科目余额表 20251231.xlsx

交付时汇报：
- 改了哪些文件
- 新增了哪些语义组
- 真实文件未匹配数量从 89 降到多少
- 是否仍存在需要人工处理的科目及原因
```

## 完成标准

- `TASK-064` 状态可改为 `DONE` 的条件：
  - 自动化测试通过。
  - 真实文件验收通过。
  - 未匹配数量较 `89` 明显下降。
  - 不出现危险错配。
  - 没有 UI 回退。
