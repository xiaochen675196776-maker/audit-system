# TASK-078：跑通三张真实科目余额表，补多行表头/辅助明细/零金额模板行/行业科目匹配

**Status:** TODO  
**Priority:** P0  
**Owner:** 待领取  
**Created:** 2026-06-25  

## 背景

用户要求尝试跑通三张新的真实科目余额表：

```text
D:/NAS/xiaochen/李辉辉项目组/SynologyDrive/道恩钛业2025年年审-2025.12.31/1、中普账套/科目汇总表查询结果-道恩钛业20251231.xlsx
D:/NAS/xiaochen/项目汇总文件夹/SynologyDrive/海钦股份2025年报审计/1、企业提供的资料/1、财务账套、账表资料/2025年序时账及科目余额表/广西海钦发生额及余额表.xlsx
D:/NAS/xiaochen/项目汇总文件夹/SynologyDrive/海钦股份2025年报审计/1、企业提供的资料/1、财务账套、账表资料/2025年序时账及科目余额表/金碟软件公司科目余额表.xlsx
```

我用临时 SQLite DB 跑了当前系统的 `preview -> analyze -> execute`。为了排除手工路径编码问题，路径由 PowerShell 传入，数据库用临时文件，不污染现有库。

结论：三张表当前都没有安全跑通。

---

## 当前验收结果

### 1. 道恩钛业：只剩 2 个 unsafe 候选，不能安全自动确认

字段结构：

```json
{
  "headers": ["年", "科目代码", "科目全称", "级次", "上级科目代码", "年初借方余额", "年初贷方余额", "年借方发生额", "年贷方发生额", "期末借方余额", "期末贷方余额", "..."],
  "rows": 345
}
```

我使用的字段映射：

```text
科目代码 col_1
科目名称 col_2
期初借方 col_5
期初贷方 col_6
本期借方 col_7
本期贷方 col_8
期末借方 col_9
期末贷方 col_10
```

当前结果：

```json
{
  "preview_total_rows": 345,
  "active_recommendations": 295,
  "analyze_warning_count": 1,
  "analyze_error_count": 0,
  "no_candidate_count": 0,
  "unsafe_count": 2,
  "confirmed_count": 293
}
```

失败样例：

```json
[
  {
    "row_index": 109,
    "client_account_code": "150401",
    "client_account_name": "其他权益工具投资\\成本",
    "picked": {
      "standard_account_code": "1504",
      "standard_account_name": "长期套期工具资产",
      "score": 0.85,
      "source": "code_prefix_parent",
      "warning": "按客户明细科目代码「150401」前缀推荐至上级标准科目「1504 长期套期工具资产」，请确认是否汇总到该标准科目"
    }
  },
  {
    "row_index": 116,
    "client_account_code": "160502",
    "client_account_name": "工程物资\\设备",
    "picked": {
      "standard_account_code": "1605",
      "standard_account_name": "工程物资",
      "score": 0.85,
      "source": "code_prefix_parent",
      "warning": "按客户明细科目代码「160502」前缀推荐至上级标准科目「1605 工程物资」，请确认是否汇总到该标准科目"
    }
  }
]
```

根因：

1. 标准科目库里 `1504` 当前是 `长期套期工具资产`，但客户 `150401 其他权益工具投资\成本` 的经济含义是 `其他权益工具投资`。这不是安全匹配。
2. `160502 工程物资\设备` 明确是 `1605 工程物资` 的明细，应该可安全归入 `1605`，但当前 `code_prefix_parent` 一律 warning。

---

### 2. 广西海钦：多行表头 + 辅助核算明细空代码，当前无法跑通

`parse_file()` 当前把第一行报表元数据当成表头：

```json
{
  "headers": ["", "期间:", "2025.01 - 2025.12", "", "币种:", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""],
  "rows": 317
}
```

实际表头是多行：

```text
row 0: 科目类别 | 科目编码 | 科目名称 | 币种 | 期初余额 | 本期发生 | 本年累计 | 期末余额
row 1:                                  借方/贷方
row 2:                                  数量/金额
row 3+: 数据
```

关键样本：

```json
[
  ["", "资产", "1122", "应收账款", "人民币", "", "", "", 7767578.7, "", 1185112630.29, "", 1183545016.39, "..."],
  ["", "资产", "　1122001", "　业务款项", "人民币", "", "", "", 7767578.7, "", 1185112630.29, "", 1183545016.39, "..."],
  ["", "资产", "", "　 [0010004] 茂名市润源丰化工有限公司", "人民币", "", "", "", 1456, "", 2457000, "", 2457831.6, "..."],
  ["", "资产", "", "　 [0010005] 南宁三燃液化气有限公司", "人民币", "", 675100.8, "", "", "", 37573099.4, "", 39133362.2, "..."]
]
```

我使用的字段映射：

```text
科目代码 col_2
科目名称 col_3
期初借方金额 col_6
期初贷方金额 col_8
本期借方金额 col_10
本期贷方金额 col_12
期末借方金额 col_18
期末贷方金额 col_20
忽略表头说明行 row 0/1/2
```

当前结果：

```json
{
  "preview_total_rows": 317,
  "active_recommendations": 276,
  "initial_ignored_rows": [0, 1, 2],
  "analyze_warning_count": 103,
  "analyze_error_count": 156,
  "no_candidate_count": 155,
  "unsafe_count": 101,
  "confirmed_count": 19
}
```

失败样例：

```json
[
  {
    "row_index": 13,
    "client_account_code": null,
    "client_account_name": "[0010004] 茂名市润源丰化工有限公司",
    "participates_in_entry": true
  },
  {
    "row_index": 14,
    "client_account_code": null,
    "client_account_name": "[0010005] 南宁三燃液化气有限公司",
    "participates_in_entry": true
  }
]
```

这些不是标准科目，而是 `1122001 业务款项` 下面的辅助核算客户明细。当前系统把它们当成独立客户科目去匹配标准科目，所以必然失败。

另有大量 warning 候选，例如：

```json
{
  "client_account_code": "1002001",
  "client_account_name": "中国建设银行股份有限公司钦州港区支行",
  "picked": {
    "standard_account_code": "1002",
    "standard_account_name": "银行存款",
    "score": 0.86,
    "source": "code_category_anchor",
    "warning": "按客户科目代码「1002001」类别/名称锚点推荐至标准科目「1002 银行存款」，请确认是否归入该标准科目"
  }
}
```

这类明细应该结合父级/代码前缀安全归入，不应让用户逐条确认。

---

### 3. 金碟软件公司：多行表头 + 零金额模板科目 + 金融/保险类标准科目缺口

字段结构：

```json
{
  "headers": ["科目代码", "科目名称", "公司", "核算项目", "", "", "年初余额", "", "期初余额", "", "本期发生额", "", "本年累计", "", "期末余额", ""],
  "rows": 12289
}
```

实际第二行是借贷方向子表头：

```json
["", "", "", "", "", "", "借方", "贷方", "借方", "贷方", "借方", "贷方", "借方", "贷方", "借方", "贷方"]
```

我使用的字段映射：

```text
科目代码 col_0
科目名称 col_1
期初借方 col_8
期初贷方 col_9
本期借方 col_10
本期贷方 col_11
期末借方 col_14
期末贷方 col_15
忽略表头方向行 row 0
```

当前结果：

```json
{
  "preview_total_rows": 12289,
  "recommendations": 588,
  "active_recommendations": 513,
  "initial_ignored_rows": [0],
  "analyze_warning_count": 381,
  "analyze_error_count": 65,
  "no_candidate_count": 65,
  "unsafe_count": 369,
  "confirmed_count": 79
}
```

未匹配样例：

```json
[
  {"row_index": 87, "client_account_code": "1003", "client_account_name": "存放中央银行款项"},
  {"row_index": 111, "client_account_code": "1011", "client_account_name": "存放同业"},
  {"row_index": 230, "client_account_code": "1021", "client_account_name": "结算备付金"},
  {"row_index": 367, "client_account_code": "1111", "client_account_name": "买入返售金融资产"},
  {"row_index": 616, "client_account_code": "1123.001", "client_account_name": "业务款项"},
  {"row_index": 712, "client_account_code": "1201", "client_account_name": "应收代位追偿款"},
  {"row_index": 1318, "client_account_code": "1301", "client_account_name": "贴现资产"},
  {"row_index": 1390, "client_account_code": "1304", "client_account_name": "贷款损失准备"},
  {"row_index": 2178, "client_account_code": "1471", "client_account_name": "存货跌价准备"},
  {"row_index": 2232, "client_account_code": "1475", "client_account_name": "合同履约成本"}
]
```

进一步检查发现一部分未匹配是零金额模板科目，例如：

```json
["1003", "存放中央银行款项", "海钦能源", "", "", "", "", "", "", "", "", "", "", "", "", ""]
```

这类全金额为空/零、且没有有效子金额的模板科目，不应参与入库，也不应产生未匹配错误。

但也存在有金额的未匹配，例如：

```json
["1123.001", "业务款项", "海钦能源", "", "", "", "830000", "", "830000", "", "", "", "", "", "830000", ""]
["1222.001", "内部关联方", "海钦能源", "", "", "", "", "", "", "", "", "", "6652.86", "6652.86", "", ""]
```

这类小数点明细代码应按前缀归入其上级标准/语义标准，例如 `1123.*` 应归入预付款项/预付账款类，`1222.*` 应归入其他应收款类或对应标准口径，不能直接无候选。

---

## 必修任务

### 1. 支持多行表头和自动数据起始行识别

涉及文件：

```text
backend/app/services/file_parser.py
backend/app/services/standard_trial_balance_import_service.py
frontend/src/views/DataImportView.vue
backend/tests/test_file_parser.py
backend/tests/test_standard_trial_balance_import.py
```

要求：

1. `preview_standard_import` 不能只把第一行当表头。需要能识别：
   - 顶部报表元数据行：如 `期间: 2025.01 - 2025.12`、`币种:`。
   - 多行复合表头：如 `期初余额 / 借方 / 金额`，`本期发生 / 贷方 / 金额`。
   - 借贷方向子表头：如金蝶的第一数据行 `借方/贷方`。
2. 输出给前端的 columns 应该是合并后的可读表头，例如：

```text
科目编码
科目名称
期初余额_借方_金额
期初余额_贷方_金额
本期发生_借方_金额
本期发生_贷方_金额
期末余额_借方_金额
期末余额_贷方_金额
```

3. 后端批次应保存 `data_start_row` 或等价配置，`analyze/execute` 必须跳过表头说明行，不能把 `科目编码/科目名称/借方/贷方` 当客户科目入库。
4. 前端字段自动映射要支持合并表头，不能要求用户手工选 8 个金额列。

### 2. 补字段自动映射别名

涉及文件：

```text
frontend/src/views/DataImportView.vue
backend/app/services/column_matcher.py
```

至少补充：

```text
科目全称 -> account_name
年初借方余额 -> opening_debit
年初贷方余额 -> opening_credit
年借方发生额 -> current_debit
年贷方发生额 -> current_credit
期初余额_借方_金额 -> opening_debit
期初余额_贷方_金额 -> opening_credit
本期发生_借方_金额 -> current_debit
本期发生_贷方_金额 -> current_credit
期末余额_借方_金额 -> ending_debit
期末余额_贷方_金额 -> ending_credit
年初余额_借方 -> opening_debit 或 opening_amount 场景下正确拆分
```

### 3. 支持辅助核算明细行继承父科目

涉及文件：

```text
backend/app/services/trial_balance_transform.py
backend/app/services/standard_trial_balance_import_service.py
backend/app/services/standard_trial_balance_service.py
```

广西海钦的典型结构：

```text
1122 应收账款
  1122001 业务款项
    [0010004] 茂名市润源丰化工有限公司
    [0010005] 南宁三燃液化气有限公司
```

要求：

1. 当行的 `account_code` 为空，但 `account_name` 是 `[辅助编码] 辅助名称` 或明显的辅助核算对象，并且它位于最近一个有科目代码的客户科目之后，应继承最近有效父科目的标准映射。
2. 这类行应作为客户明细 entry 或 client_group 展示在父科目下，而不是单独拿辅助对象名称去匹配标准科目。
3. 入库时应保存：
   - `client_account_code` 可以使用父科目代码 + 辅助编码的合成键，或新增辅助字段；
   - `client_account_name` 应保留辅助对象名称；
   - 标准科目快照使用继承的父科目标准科目。
4. 查询树里应展示：

```text
112201 应收账款
  客户层级 1122001 业务款项
    客户/辅助：[0010004] 茂名市润源丰化工有限公司
```

5. 不允许这些辅助对象产生 `unmapped_account`。

### 4. 自动跳过零金额模板科目

金蝶文件中大量标准科目模板行没有任何金额，例如：

```json
["1003", "存放中央银行款项", "海钦能源", "", "", "", "", "", "", "", "", "", "", "", "", ""]
```

要求：

1. 若某行所有映射金额字段均为空/0，且没有子孙行形成有效金额汇总，则不参与入库，不进入 mapping_recommendations 的 active entry，不产生未匹配错误。
2. 如果零金额父行下面有非零子行，则父行仍可作为层级节点，但不要求单独标准映射。
3. 这条规则不能误删真实零余额但有本期发生额的科目；判断必须覆盖期初、本期、期末所有映射金额字段。

### 5. 增强明细代码安全匹配

涉及文件：

```text
backend/app/services/client_account_mapping_service.py
backend/tests/test_client_account_mapping_service.py
```

要求：

1. `160502 工程物资\设备` 应安全匹配 `1605 工程物资`：

```python
assert candidates[0]["standard_account_code"] == "1605"
assert candidates[0]["warning"] is None
assert candidates[0]["score"] >= 0.9
```

2. 银行存款、其他货币资金、库存商品、固定资产原值、累计折旧、应收/应付等明细代码，如果同时满足：
   - 客户代码以前缀落在标准科目代码或明确类别锚点下；
   - 客户名称或父级层级能证明经济含义一致；
   - 标准科目不是冲突科目；
   
   则应给安全候选，不要全部 `score=0.85/0.86 + warning`。
3. 小数点明细代码要规范化：

```text
1012.001 -> 1012001
1123.001 -> 1123001
1222.001 -> 1222001
```

并能按 `1012/1123/1222` 前缀或语义组推荐。

### 6. 补标准科目库/语义组

涉及文件：

```text
backend/app/data/standard_accounts_seed.py
backend/app/services/client_account_mapping_service.py
backend/tests/test_standard_account_import.py
```

至少处理：

```text
1504 其他权益工具投资（或按系统标准库口径补正确代码/名称，不能把 1504 写成长久套期工具资产后又把其他权益工具投资映射过去）
1471 存货跌价准备
1475 合同履约成本
1123.* 预付款项/预付账款类明细
1222.* 其他应收款类明细或系统标准口径对应科目
```

对金蝶里的金融/保险行业科目，需要二选一：

1. 若标准库要覆盖金融/保险行业，则补标准科目并匹配：

```text
1003 存放中央银行款项
1011 存放同业
1021 结算备付金
1111 买入返售金融资产
1201 应收代位追偿款
1211 应收分保账款
1212 应收分保合同准备金
1301 贴现资产
1302 拆出资金
1303 贷款
1304 贷款损失准备
1311 代理兑付证券
1321 代理业务资产
1441 抵债资产
1451 损余物资
```

2. 若当前系统只服务一般工商企业标准库，则这些零金额模板行必须被自动跳过；有金额的行业特殊科目必须给出明确可确认的映射或提示，不得阻断整表导入。

---

## 验收脚本要求

新增脚本：

```text
backend/scripts/acceptance_task078_three_real_trial_balances.py
```

脚本必须：

1. 使用临时 SQLite DB，不污染现有库。
2. 逐个跑三张真实文件：

```text
seed_standard_accounts
preview_standard_import
analyze_standard_import
execute_standard_import
get_tree
```

3. 不允许手工改 Excel。
4. 不允许把大量真实数据行简单加入 ignored_rows 来绕过问题。允许忽略的只能是自动识别出的表头/说明行、零金额模板行。
5. 验收通过条件：

```text
每张表 execute.status == executed
每张表 entry_count > 0
每张表 unmapped_account == 0
每张表 unsafe candidate == 0
每张表 warning_count == 0，或仅保留经证明真实存在的 parent_amount_mismatch
查询树 node_id 不重复
```

6. 脚本输出每张表摘要：

```json
{
  "file": "...xlsx",
  "preview_total_rows": 0,
  "data_start_row": 0,
  "active_recommendations": 0,
  "ignored_header_rows": [],
  "ignored_zero_amount_rows": 0,
  "inherited_auxiliary_rows": 0,
  "unmatched_count": 0,
  "unsafe_count": 0,
  "warning_count": 0,
  "entry_count": 0,
  "tree_total_nodes": 0
}
```

脚本最后必须输出：

```text
TASK078_THREE_REAL_TRIAL_BALANCES_PASSED
```

---

## 必跑测试

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m pytest tests/test_file_parser.py tests/test_standard_trial_balance_import.py tests/test_client_account_mapping_service.py tests/test_standard_trial_balance_view.py -q
D:\python\python.exe -m pytest -q
$env:PYTHONIOENCODING='utf-8'
D:\python\python.exe scripts\acceptance_task078_three_real_trial_balances.py
```

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
```

---

## 给执行 AI 的提示词

你要修 TASK-078。先阅读 `docs/tasks/TASK-078-three-real-trial-balance-imports.md`，不要只补一个小点。目标是让三张真实科目余额表都能通过标准化导入链路。

三张真实文件路径已经写在任务文件顶部。当前失败情况：

1. `科目汇总表查询结果-道恩钛业20251231.xlsx`：345 行，295 个有效入库科目，目前只剩 2 个 unsafe：`150401 其他权益工具投资\成本` 错指向/不安全指向 `1504 长期套期工具资产`，以及 `160502 工程物资\设备` 没能安全归入 `1605 工程物资`。
2. `广西海钦发生额及余额表.xlsx`：多行表头，`parse_file` 把 `期间:` 当表头；同时大量 `[0010004] 客户名称` 这种空科目编码的辅助核算明细被当成独立科目去匹配，导致 155 个 no candidate。必须让辅助明细继承父科目映射。
3. `金碟软件公司科目余额表.xlsx`：多行表头，含大量零金额模板科目和小数点明细代码；当前 65 个 no candidate、369 个 unsafe。零金额模板科目应自动跳过，有金额的小数点明细代码应按前缀/语义匹配。

请按任务文件里的 6 个必修任务改：

- 支持多行表头和 data_start_row。
- 补字段自动映射别名。
- 支持辅助核算明细继承父科目。
- 自动跳过零金额模板科目。
- 增强明细代码安全匹配，包括 `160502 -> 1605` 和 `1123.001/1222.001` 这类小数点代码。
- 补或修标准科目库/语义组，尤其 `1504 其他权益工具投资`、`1471 存货跌价准备`、`1475 合同履约成本` 等。

必须新增 `backend/scripts/acceptance_task078_three_real_trial_balances.py`，用临时 SQLite DB 真实跑三张文件，不污染数据库。不能靠手工忽略大量数据行绕过，只能自动忽略表头说明行和零金额模板行。最终必须输出 `TASK078_THREE_REAL_TRIAL_BALANCES_PASSED`。

完成后跑：

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m pytest tests/test_file_parser.py tests/test_standard_trial_balance_import.py tests/test_client_account_mapping_service.py tests/test_standard_trial_balance_view.py -q
D:\python\python.exe -m pytest -q
$env:PYTHONIOENCODING='utf-8'
D:\python\python.exe scripts\acceptance_task078_three_real_trial_balances.py
```

再跑：

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
```

交付时必须贴出三张表各自的 `preview_total_rows / active_recommendations / ignored_zero_amount_rows / inherited_auxiliary_rows / unmatched_count / unsafe_count / warning_count / entry_count` 摘要。
