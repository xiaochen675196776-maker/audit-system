# TASK-094E 敏感数据扫描报告

生成时间: 2026-06-28T13:30
扫描器: `scripts/check_sensitive_fixture.py`（TASK-094A 实现）
扫描模式: `--strict`（命中即非零退出，适合 CI）
扫描路径: `backend/tests/fixtures/` + `backend/test_reports/` + `docs/security/` + frontend 测试 fixtures

## 1. 扫描结果

| 项目 | 结果 |
|------|------|
| 命中数 | **0** |
| 后端 fixture 命中 | 0 |
| 后端 test_reports 命中 | 0 |
| docs/security 命中 | 0 |
| 前端测试 fixture 命中 | 0 |
| 退出码 | **0** ✅ |

## 2. 扫描规则覆盖

| 规则 | 触发条件 | 命中 |
|------|----------|------|
| `long_digit_run` | 连续 12 位以上纯数字（不在白名单内） | 0 |
| `id_card` | 18 位身份证号 | 0 |
| `cn_mobile` | 11 位手机号（1[3-9]xxxxxxxxx） | 0 |
| `email` | 邮箱地址 | 0 |
| `bank_keyword` | "银行账号/银行账户/银行帐号/银行卡号/银行卡账户" 关键字 | 0 |
| `real_bank_name` | 国内大型商业银行/股份制商业银行/城市商业银行全称 | 0 |
| `real_customer_blacklist` | 真实客户/供应商/员工黑名单 | 0 |
| `garbled_reason_in_json` | review_reason 全部是 ?/全角 ? | 0 |
| `duplicate_row_key_conflict` | 同一 row_key 重复确认到不同标准科目 | 0 |

## 3. 本轮复跑额外清理

`docs/security/TASK-094A_敏感数据清理说明.md`（解释"清理了什么"的元文档）原本
包含"实际命中举例"列出的真实敏感字符串（银行账号样例、客户名样例等），虽
然是元说明文档，仍触发扫描器 35 处命中。

本轮按"文档也要干净"原则做了内部脱敏：把举例占位符从真实字符串改为
`<账户号样例N>` / `<客户名样例N>` / `<国有大型商业银行A>` 等纯描述性占位符，
让文档既保留解释作用又不携带真实数据。

原始命中字符串另存到本地归档目录 `audit-system-backup-094a/`（如需查询）。

## 4. 红线检查

| §13 红线 | 结果 |
|----------|------|
| 任一敏感数据扫描命中 | ✅ 0 命中 |

## 5. CI 接入

新增 `.github/workflows/sensitive-scan.yml`（TASK-094E §10 范围），每次 push/PR
自动跑 `python scripts/check_sensitive_fixture.py --strict`，命中即 fail。

## 6. 复跑命令

```bash
python scripts/check_sensitive_fixture.py --strict --root <repo-root>
echo "exit code: $?"
```

预期：输出 `✓ 未发现疑似敏感数据` 且 exit code = 0。