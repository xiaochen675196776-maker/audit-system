# TASK-080：跑通 6 张新增真实科目余额表模板

**Status:** TODO  
**Priority:** P0  
**Created:** 2026-06-25  
**Owner:** 待领取  

## 背景

用户新增 6 张真实科目余额表样本，希望当前“标准化科目余额表导入”功能能够直接跑通。验收要求是：用原始文件路径直接跑 `preview -> analyze -> execute -> get_tree`，使用临时 SQLite DB，不污染正式数据库。

本次验收结论：**6 张当前都不能直接跑通**。其中 4 张 `.xls` 在文件解析层直接失败；2 张 `.xlsx` 能解析，但在方向金额拆分、汇总行过滤、标准科目/父级上下文匹配上失败。

## 新增真实文件

```text
D:/APP/谷歌/文件下载/会展中心余额表.xlsx
D:/APP/谷歌/文件下载/1-12科目余额表.xls
D:/APP/谷歌/文件下载/205201-2023.xls
D:/APP/谷歌/文件下载/科目余额表2023年导入.xls
D:/APP/谷歌/文件下载/医疗3月31日序时账及余额表.xlsx
D:/APP/谷歌/文件下载/科目余额表-成都迪康-240930.xls
```

## 本次验收方式

1. 直接用当前系统 `parse_trial_balance_import` 解析 6 张原始文件。
2. 对能解析的 `.xlsx` 用临时 SQLite DB 跑完整链路。
3. 对不能直接解析的 `.xls`，额外用隐藏 Excel COM 临时转换为 `.xlsx` 做深层诊断。注意：这只是定位问题，最终产品不能依赖人工转换或 Excel COM。

## 结果汇总表

| 文件 | 当前直接结果 | 深层诊断结果 | 核心失败原因 |
|---|---:|---:|---|
| 会展中心余额表.xlsx | 未通过 | `preview_total_rows=266`, `active=195`, `unmatched=1`, `unsafe=0`, `non_parent_warning=346`, `error=5` | 方向+单金额列依赖标准方向，未使用源表方向列；空金额被当作解析警告；`123102 坏账准备\其它应收款` 未匹配 |
| 1-12科目余额表.xls | 未通过 | 原始 `.xls` 直接 `InvalidFileException`；临时转换后 `rows=1011`, `active=932`, `unmatched=688`, `unsafe=33` | 当前专用解析不支持旧 `.xls`；转换后暴露老科目编码、点分层级、父级继承/辅助明细识别不足 |
| 205201-2023.xls | 未通过 | 原始 `.xls` 直接 `InvalidFileException`；Excel COM 转换被信任中心阻止 | 文件是老 BIFF 流，当前 openpyxl 不支持；需要真正的 `.xls` 解析库，不能依赖 Excel COM |
| 科目余额表2023年导入.xls | 未通过 | 原始 `.xls` 直接 `InvalidFileException`；临时转换后 `rows=181`, `active=161`, `unmatched=101`, `unsafe=16` | 当前不支持 `.xls`；旧会计科目编码如 `101/102/137/209/211/502/521` 未建立映射；银行明细未继承父科目 |
| 医疗3月31日序时账及余额表.xlsx | 未通过 | `preview_total_rows=154`, `active=93`, `unmatched=2`, `unsafe=0`, `non_parent_warning=164`, `error=8` | `总计` 行未跳过；`165101 使用权资产\房屋及建筑物` 未匹配；方向+单金额列、空金额处理有问题 |
| 科目余额表-成都迪康-240930.xls | 未通过 | 原始 `.xls` 直接 `InvalidFileException`；临时转换后 `rows=404`, `active=294`, `unmatched=21`, `unsafe=4` | 当前不支持 `.xls`；方向+单金额列；研发费用/研发支出明细只看叶子名导致误配；`1412/123102/5301` 等上下文规则不足 |

## 关键失败样本

### 会展中心余额表.xlsx

解析结构：

```json
{
  "data_start_row": 1,
  "headers": ["科目编码", "科目名称", "方向", "期初余额", "借方累计", "贷方累计", "方向", "期末余额"],
  "preview_total_rows": 266
}
```

当前失败：

```json
{
  "unmatched_count": 1,
  "unmatched_sample": {"row_index": 14, "code": "123102", "name": "123102\\坏账准备\\其它应收款"},
  "non_parent_warning_count": 346,
  "error_samples": [
    "行 12: 标准科目余额方向缺失，无法按标准方向拆分，请手动指定借/贷方",
    "行 14: 标准科目余额方向缺失，无法按标准方向拆分，请手动指定借/贷方"
  ],
  "warning_sample": "行 49: 期间 ending 金额字段 'col_7' 无法解析为数字"
}
```

原因：

1. 表里有明确的源方向列：`col_2` 是期初方向，`col_6` 是期末方向。
2. 当前 `single_by_direction` 实际按“标准科目方向”拆，不按源表方向拆。
3. 如果某行暂时未匹配标准科目，就没有标准方向，于是金额拆分报 `no_direction`。
4. 空字符串金额应该按 0 处理，不应产生大量 `无法解析为数字` warning。
5. `123102 坏账准备\其它应收款` 应能匹配到“坏账准备-其他应收款/其他应收款坏账准备”类标准科目，当前标准库或语义规则缺失。

### 1-12科目余额表.xls

原始文件字节头：

```text
D0 CF 11 E0 A1 B1 1A E1 ...
```

说明是 OLE 旧版 Excel `.xls`。当前报错：

```text
InvalidFileException: openpyxl does not support the old .xls file format
```

临时转换后结构：

```json
{
  "data_start_row": 1,
  "headers": ["科目代码", "科目名称", "币别", "期初借方余额", "期初贷方余额", "本期借方发生额", "本期贷方发生额", "本年借方累计", "本年贷方累计", "期末借方余额", "期末贷方余额"],
  "preview_total_rows": 1011
}
```

临时转换后失败样本：

```json
{
  "unmatched_count": 688,
  "unsafe_count": 33,
  "unmatched_samples": [
    {"code": "1009.010.003", "name": "其他货币基金--工商银行宁国支行"},
    {"code": "1111.01", "name": "香农芯创(安徽聚隆传动科技股份有限公司)"},
    {"code": "1111.02", "name": "宁波吉德电器有限公司"},
    {"code": "1111.03", "name": "海信冰箱有限公司（原海信（山东）冰箱有限公司）"}
  ],
  "unsafe_samples": [
    {"code": "1009.010.002", "name": "其他货币基金--浦发银行", "picked": "1012 其他货币资金"},
    {"code": "1151.01", "name": "--流动资产", "picked": "1901 其他流动资产"},
    {"code": "2171.003.001", "name": "所得税-应交", "picked": "6801 所得税费用"}
  ]
}
```

原因：

1. 点分层级代码如 `1009.010.003` 没有稳定继承父级 `1009.010/1009` 的映射。
2. `1111.xx` 这类客户/往来对象名称没有继承父级科目，导致被当作独立标准科目匹配。
3. 老准则/老账套科目编码与当前标准库编码不一致，需要 code crosswalk，不应只靠名称相似度。
4. 低分名称相似度出现危险误配，例如税费明细被指向所得税费用。

### 205201-2023.xls

原始文件字节头：

```text
09 08 08 00 00 00 10 00 ...
```

当前报错：

```text
InvalidFileException: openpyxl does not support the old .xls file format
```

用 Excel COM 隐藏转换时也失败：

```text
您试图打开的文件类型被信任中心中的文件阻止设置阻止。
```

原因：

1. 这不是 `.xlsx`，也不是普通 openpyxl 可读格式。
2. 不能依赖 Excel COM，因为真实用户机器可能没有 Excel，且信任中心策略会阻止。
3. 必须引入可靠的旧 `.xls` 解析路径，例如 `xlrd` 或 `python-calamine`。

### 科目余额表2023年导入.xls

原始 `.xls` 直接失败；临时转换后结构：

```json
{
  "data_start_row": 1,
  "headers": ["科目代码", "科目名称", "币别", "期初借方余额", "期初贷方余额", "本期借方发生额", "本期贷方发生额", "本年借方累计", "本年贷方累计", "期末借方余额", "期末贷方余额"],
  "preview_total_rows": 181
}
```

临时转换后失败样本：

```json
{
  "unmatched_count": 101,
  "unsafe_count": 16,
  "unmatched_samples": [
    {"code": "102.001", "name": "中行丁办"},
    {"code": "102.006", "name": "无锡农村商业银行宜兴丁山分理处"},
    {"code": "102.015", "name": "招商银行宜兴丁蜀支行"}
  ],
  "unsafe_samples": [
    {"code": "101", "name": "现金", "picked": "1001 库存现金"},
    {"code": "137", "name": "产成品", "picked": "140601 半成品"},
    {"code": "502", "name": "产品销售成本", "picked": "140501 产品成本差异"},
    {"code": "521.013.062.002", "name": "工资", "picked": "1605 工程物资"}
  ]
}
```

原因：

1. 旧科目编码体系：`101=现金`、`102=银行存款`、`137=产成品`、`209=其他应付款`、`211=应付工资`、`502=产品销售成本` 等需要映射到新标准科目。
2. 银行明细 `102.xxx` 应继承 `102 银行存款 -> 1002 银行存款`，不能单独 no candidate。
3. `521... 工资/材料费/其他费用` 只看叶子名会误配到工程物资/原材料，必须使用父级路径判断是制造费用、生产成本、研发支出或销售/管理费用。

### 医疗3月31日序时账及余额表.xlsx

解析结构：

```json
{
  "data_start_row": 9,
  "headers": ["科目编码", "科目名称", "方向", "期初余额_本币", "本期借方_本币", "本期贷方_本币", "借方累计_本币", "贷方累计_本币", "方向", "期末余额_本币"],
  "preview_total_rows": 154
}
```

当前失败：

```json
{
  "unmatched_count": 2,
  "unmatched_samples": [
    {"row_index": 38, "code": "165101", "name": "使用权资产\\房屋及建筑物"},
    {"row_index": 150, "code": "总计", "name": null}
  ],
  "non_parent_warning_count": 164,
  "error_count": 8
}
```

原因：

1. `总计` 行没有被当前 `_collect_summary_total_skip_rows` 跳过。
2. `165101 使用权资产\房屋及建筑物` 缺标准科目或映射规则。
3. 方向+单金额列同会展中心，必须支持源方向列拆借贷。
4. 空金额不应产生 warning。

### 科目余额表-成都迪康-240930.xls

原始 `.xls` 直接失败；临时转换后结构：

```json
{
  "data_start_row": 5,
  "headers": ["科目编号", "科目名称", "期初_方向", "期初_金额", "本期发生_借方", "本期发生_贷方", "余额_方向", "余额_金额", "一级科目_金额", "一级科目_金额"],
  "preview_total_rows": 404
}
```

临时转换后失败样本：

```json
{
  "unmatched_count": 21,
  "unsafe_count": 4,
  "unmatched_samples": [
    {"code": "141201", "name": "行政管理类"},
    {"code": "141202", "name": "生产经营类"},
    {"code": "5301010102", "name": "职工福利"},
    {"code": "5301010201", "name": "检测费"},
    {"code": "53010106", "name": "委托外部研究开发费用"}
  ],
  "unsafe_samples": [
    {"code": "123102", "name": "其它应收款", "picked": "122101 其他应收款"},
    {"code": "5301010101", "name": "工资", "picked": "1605 工程物资"},
    {"code": "5301010202", "name": "材料费", "picked": "1403 原材料"}
  ]
}
```

原因：

1. `.xls` 解析不支持。
2. 方向+单金额列需要源方向字段。
3. `5301...` 明显是研发费用/研发支出相关明细，不能只看叶子名“工资/材料费”去匹配工程物资或原材料。
4. `1412` 下 `行政管理类/生产经营类` 应按父级科目上下文归入，不能单独 no candidate。
5. `123102 其它应收款` 可能是坏账准备/其他应收款相关，不能直接按名称误配为其他应收款本金。

---

## 必须修复任务

### Task A：补旧 `.xls` 解析能力

**目标：** `parse_file`、`parse_trial_balance_import`、`parse_file_with_config` 都能直接读取 `.xls`，不要求用户手工转 `.xlsx`。

**涉及文件：**

```text
backend/app/services/file_parser.py
backend/requirements.txt 或 pyproject/依赖文件
backend/tests/test_file_parser.py
backend/scripts/acceptance_task080_six_trial_balance_templates.py
```

**实现要求：**

1. 在 `.xls` 路径上不要调用 openpyxl。openpyxl 明确不支持旧 `.xls`。
2. 增加 `xlrd` 或 `python-calamine` 作为旧 Excel 读取后端。
3. `_parse_excel_all_rows(file_path)` 必须按扩展名或文件头分流：
   - `.xlsx/.xlsm`：openpyxl
   - OLE `.xls`，文件头 `D0 CF 11 E0 A1 B1 1A E1`：旧 Excel 解析后端
   - BIFF stream `.xls`，文件头类似 `09 08 08 00`：旧 Excel 解析后端
4. 返回结构必须与 openpyxl 路径一致：`headers, all_rows`，保留数值为数字、空单元格为 `None` 或 `""` 均可，但后续清洗要一致。
5. 不能依赖 Excel COM、LibreOffice 或用户本机 Office。

**测试要求：**

1. 新增单元测试覆盖 `_parse_excel_all_rows` 对 `.xls` 的调用路径。
2. 新增真实验收脚本 `backend/scripts/acceptance_task080_six_trial_balance_templates.py`，用 6 个原始文件路径直接跑，不允许先转格式。

### Task B：支持“方向列 + 单金额列”按源方向拆借贷

**目标：** 会展中心、医疗、成都迪康这三种表的期初/期末余额结构能正确拆成借贷两列。

**涉及文件：**

```text
backend/app/services/trial_balance_transform.py
backend/app/services/standard_trial_balance_import_service.py
backend/app/schemas/standard_trial_balance.py
frontend/src/views/DataImportView.vue
backend/tests/test_standard_trial_balance_import.py
backend/tests/test_standard_trial_balance_view.py
```

**当前问题：**

`single_by_direction` 当前依赖标准科目的 `standard_direction`。当行还未匹配标准科目，或标准科目方向缺失时，会报：

```text
标准科目余额方向缺失，无法按标准方向拆分
```

但真实表已经提供了方向列，例如：

```text
会展中心：col_2 期初方向，col_6 期末方向
医疗：col_2 期初方向，col_8 期末方向
成都迪康：col_2 期初_方向，col_6 余额_方向
```

**实现要求：**

1. 在金额映射配置中支持 `direction_column_id`：

```json
{
  "column_id": "col_3",
  "field_name": "opening_balance",
  "period_type": "opening",
  "split_mode": "single_by_source_direction",
  "direction_column_id": "col_2"
}
```

2. 新增或扩展 split mode：
   - 推荐新增 `single_by_source_direction`
   - 保留现有 `single_by_direction` 语义，避免破坏旧功能
3. 方向值映射：
   - `借`、`借方`、`debit`、`dr` -> 借方金额
   - `贷`、`贷方`、`credit`、`cr` -> 贷方金额
   - `平`、空方向，且金额为空/0 -> 借贷均为 0，不报 warning
   - `平` 但金额非 0 -> 产生明确 warning，提示方向为平但金额非零
4. 空金额、空字符串、`None` 在单金额模式下必须按 0 处理，不得产生 `无法解析为数字` warning。
5. 前端字段映射 UI 要能让用户给单金额余额列选择对应方向列；自动映射时应自动识别同组方向列。

**这 3 张表的目标映射：**

会展中心：

```text
account_code col_0
account_name col_1
opening_balance col_3 + direction col_2
current_debit col_4
current_credit col_5
ending_balance col_7 + direction col_6
```

医疗：

```text
account_code col_0
account_name col_1
opening_balance col_3 + direction col_2
current_debit col_4
current_credit col_5
ending_balance col_9 + direction col_8
```

成都迪康：

```text
account_code col_0
account_name col_1
opening_balance col_3 + direction col_2
current_debit col_4
current_credit col_5
ending_balance col_7 + direction col_6
```

### Task C：增强汇总行/总计行跳过规则

**目标：** `总计`、`合计`、`小计`、分类小计行都不参与科目匹配和入账。

**涉及文件：**

```text
backend/app/services/standard_trial_balance_import_service.py
backend/tests/test_standard_trial_balance_import.py
```

**当前漏掉：**

```text
医疗3月31日序时账及余额表.xlsx: code = 总计, name = null
```

**实现要求：**

1. `_collect_summary_total_skip_rows` 覆盖以下模式：

```text
合计
总计
小计
本页合计
本月合计
累计
(资产)小计：
(负债)小计：
(权益)小计：
(损益)小计：
```

2. 如果科目编码列或科目名称列命中上述模式，且不是合法科目编码，应跳过。
3. 跳过行必须：
   - 不产生 mapping recommendation
   - 不产生 unmapped_account
   - 不进入 execute
   - 在验收脚本中计入 `ignored_summary_total_rows`

### Task D：用父级路径增强科目匹配，不要只看叶子名称

**目标：** 点分层级、银行账户、客户/供应商往来、研发明细、周转/低值易耗品明细都要利用祖先路径判断。

**涉及文件：**

```text
backend/app/services/client_account_mapping_service.py
backend/app/services/standard_trial_balance_import_service.py
backend/app/services/trial_balance_transform.py
backend/tests/test_client_account_mapping_service.py
backend/tests/test_standard_trial_balance_import.py
```

**必须处理的样本：**

1. 点分层级继承：

```text
1002.001 中行丁办 -> 继承 102/1002 银行存款
1009.010.003 其他货币基金--工商银行宁国支行 -> 其他货币资金
1111.01 香农芯创... -> 继承父级 1111 的标准科目
```

2. 研发费用/研发支出上下文：

```text
5301010101 工资
5301010102 职工福利
5301010201 检测费
5301010202 材料费
53010106 委托外部研究开发费用
```

这些不能因为叶子名是“工资/材料费”就匹配到 `1605 工程物资` 或 `1403 原材料`。必须把完整路径或父级 `5301/研发费用/研发支出` 纳入推荐。

3. 旧账套明细：

```text
521.013.062.002 工资
521.013.063.006 其他费用
```

必须结合 `521` 及祖先路径判断，不允许仅按叶子名称误配。

4. 坏账准备/其他应收款：

```text
123102 坏账准备\其它应收款
```

应匹配到坏账准备类标准科目，而不是其他应收款本金。

**实现要求：**

1. 在 `analyze_standard_import` 生成 client account mapping 输入时，附带：
   - `client_account_full_path`
   - `parent_client_account_code`
   - `parent_client_account_name`
   - `ancestor_codes`
   - `ancestor_names`
2. `recommend_mappings` 先尝试父级已匹配继承，再做名称/语义匹配。
3. 对“银行账号/客户名称/供应商名称/项目名称”这类明显辅助明细，如果父级已有安全标准映射，应继承父级标准科目，不要单独 no candidate。
4. 如果叶子名很泛化，例如 `工资`、`材料费`、`其他费用`，必须降低单独名称相似度权重，除非父级路径支持。

### Task E：补旧科目编码 crosswalk 和标准科目

**目标：** 支持老会计科目编码体系和缺失标准科目。

**涉及文件：**

```text
backend/app/data/standard_accounts_seed.py
backend/app/services/client_account_mapping_service.py
backend/tests/test_client_account_mapping_service.py
```

**必须加入或修正的规则：**

```text
101 现金 -> 1001 库存现金
102 银行存款 -> 1002 银行存款
137 产成品 -> 1406 库存商品/产成品，不得匹配半成品
209/209.01 其他应付 -> 2241 其他应付款
211 应付工资 -> 2211 应付职工薪酬
502 产品销售成本 -> 6401 主营业务成本
503 其他费用 -> 结合父级判断费用类，不得默认匹配利息费用
521... 工资/材料费/其他费用 -> 结合父级路径，不得匹配工程物资/原材料
123102 坏账准备\\其它应收款 -> 坏账准备-其他应收款类标准科目
165101 使用权资产\\房屋及建筑物 -> 1651 使用权资产类标准科目
```

如果标准库缺少以下科目，应补齐启用：

```text
1651 使用权资产
165101 使用权资产-房屋及建筑物
1231 坏账准备
123102 坏账准备-其他应收款
1477 合同取得成本（如尚未补）
```

注意：不要为了跑通把性质不同的科目强行归类。例如：

```text
产品销售成本 不能匹配 产品成本差异
工资 不能匹配 工程物资
材料费 在研发路径下不能匹配 原材料库存
坏账准备\\其它应收款 不能匹配 其他应收款本金
```

### Task F：新增 6 文件验收脚本

**目标：** 用 6 个原始文件直接验收，不使用临时转换文件。

**创建文件：**

```text
backend/scripts/acceptance_task080_six_trial_balance_templates.py
```

**脚本要求：**

1. 使用临时 SQLite DB。
2. `seed_standard_accounts -> preview_standard_import -> analyze_standard_import -> execute_standard_import -> get_tree`。
3. 直接读取这 6 个原始文件路径。
4. 不允许 Excel COM 转换，不允许手工改文件。
5. 每张表输出：

```json
{
  "file": "...",
  "preview_total_rows": 0,
  "data_start_row": 0,
  "headers": [],
  "active_recommendations": 0,
  "ignored_zero_amount_rows": 0,
  "ignored_summary_total_rows": 0,
  "inherited_auxiliary_rows": 0,
  "unmatched_count": 0,
  "unsafe_count": 0,
  "warning_count": 0,
  "non_parent_warning_count": 0,
  "error_count": 0,
  "execute_status": "executed",
  "entry_count": 0,
  "tree_total_nodes": 0,
  "dup_node_id_count": 0
}
```

6. 最后必须输出：

```text
TASK080_SIX_TRIAL_BALANCE_TEMPLATES_PASSED
```

**字段映射要求：**

1-12 科目余额表、科目余额表2023年导入：

```text
account_code col_0
account_name col_1
opening_debit col_3
opening_credit col_4
current_debit col_5
current_credit col_6
ending_debit col_9
ending_credit col_10
```

会展中心：

```text
account_code col_0
account_name col_1
opening_balance col_3 direction col_2
current_debit col_4
current_credit col_5
ending_balance col_7 direction col_6
```

医疗：

```text
account_code col_0
account_name col_1
opening_balance col_3 direction col_2
current_debit col_4
current_credit col_5
ending_balance col_9 direction col_8
```

成都迪康：

```text
account_code col_0
account_name col_1
opening_balance col_3 direction col_2
current_debit col_4
current_credit col_5
ending_balance col_7 direction col_6
```

`205201-2023.xls` 当前无法解析。修复 `.xls` 后脚本必须先打印该文件 headers，再为它补字段映射。最终验收标准仍是 direct execute 通过。

## 必跑命令

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m pytest tests/test_file_parser.py tests/test_standard_trial_balance_import.py tests/test_client_account_mapping_service.py tests/test_standard_trial_balance_view.py -q
D:\python\python.exe -m pytest -q
$env:PYTHONIOENCODING='utf-8'
D:\python\python.exe scripts\acceptance_task080_six_trial_balance_templates.py
```

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
```

## 通过标准

全部满足才算完成：

1. 6 个原始文件都能直接读取，不手工转换。
2. 6 个文件都 `execute_status == executed`。
3. 6 个文件都 `entry_count > 0`。
4. 6 个文件都 `unmatched_count == 0`。
5. 6 个文件都 `unsafe_count == 0`。
6. 6 个文件都 `non_parent_warning_count == 0`。
7. `dup_node_id_count == 0`。
8. 脚本最后输出 `TASK080_SIX_TRIAL_BALANCE_TEMPLATES_PASSED`。
9. 后端定向测试、后端全量测试、前端 build 全部通过。

## 给执行 AI 的提示词

你要修复 TASK-080。先读：

```text
docs/tasks/TASK-080-six-new-trial-balance-template-acceptance.md
docs/tasks/TASK-078-three-real-trial-balance-imports.md
docs/tasks/TASK-079-fix-task078-real-trial-balance-acceptance.md
```

这次不是简单补几个科目。当前 6 张新增样本都没直接跑通，问题分四类：

1. `.xls` 文件当前不支持。`parse_trial_balance_import` 直接走 openpyxl，旧 `.xls` 报 `InvalidFileException`。必须补 `xlrd` 或 `python-calamine`，不能依赖 Excel COM。
2. 会展中心、医疗、成都迪康是“方向列 + 单金额列”的余额格式。当前 `single_by_direction` 按标准科目方向拆，不按源表方向列拆，导致 `no_direction` 和大量空金额 warning。要新增 `single_by_source_direction`，支持 `direction_column_id`。
3. `总计` 行没有跳过；空金额不应产生 warning。
4. 匹配算法需要使用父级路径和旧科目编码 crosswalk。不要只看叶子名。`工资/材料费` 在研发路径下不能匹配工程物资/原材料；`产品销售成本` 不能匹配产品成本差异；银行账户、往来客户明细要继承父级科目。

请按任务里的 Task A-F 做。完成后必须新增并运行：

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
$env:PYTHONIOENCODING='utf-8'
D:\python\python.exe scripts\acceptance_task080_six_trial_balance_templates.py
```

必须看到：

```text
TASK080_SIX_TRIAL_BALANCE_TEMPLATES_PASSED
```

同时跑：

```powershell
D:\python\python.exe -m pytest tests/test_file_parser.py tests/test_standard_trial_balance_import.py tests/test_client_account_mapping_service.py tests/test_standard_trial_balance_view.py -q
D:\python\python.exe -m pytest -q
```

前端跑：

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
```

交付时贴出 6 张表各自的摘要：

```text
preview_total_rows / data_start_row / active_recommendations /
ignored_zero_amount_rows / ignored_summary_total_rows /
inherited_auxiliary_rows / unmatched_count / unsafe_count /
warning_count / non_parent_warning_count / error_count /
execute_status / entry_count / tree_total_nodes / dup_node_id_count
```

如果 `205201-2023.xls` 修复 `.xls` 解析后仍出现新表头结构，必须把该结构纳入同一个验收脚本并继续修到通过，不能跳过该文件。
