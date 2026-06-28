# TASK-094A / TASK-095A 敏感数据清理与历史风险说明

> 仓库: `xiaochen675196776-maker/audit-system`
> 适用范围: 当前 `master` 工作树
> 最近更新: TASK-095A

---

## 1. 当前工作树状态

当前工作树已按 TASK-095A 要求完成全仓库文本扫描治理。扫描范围覆盖 Git 实际提交和未忽略的文本文件，包括但不限于:

- `docs/tasks/**`
- `docs/security/**`
- `backend/test_reports/**`
- `backend/tests/fixtures/**`
- `backend/tests/**`
- `frontend/src/**`
- `scripts/**`
- `.github/workflows/**`
- `README.md` 及其他 Markdown

当前工作树中的完整账号、真实银行网点名称、真实客户名称、真实供应商名称、真实员工姓名、真实项目名称和产权证样例均已替换为占位符，例如:

- `<账户号样例001>`
- `银行A_支行01`
- `客户A`
- `供应商B`
- `员工001`
- `项目P001`

不得在完成报告、测试报告、任务报告或安全说明中再次写入真实敏感字符串。

---

## 2. 扫描器与规则

仓库级扫描命令:

```bash
python scripts/check_sensitive_fixture.py --strict --root .
```

扫描器默认扫描仓库文本文件，并只跳过以下技术目录:

- `.git`
- `node_modules`
- `dist`
- `build`
- `__pycache__`
- `.pytest_cache`

扫描扩展名包括:

```text
.py .ts .vue .js .json .md .yml .yaml .toml .ini .txt .csv
```

长数字规则已改为上下文白名单:只有字段上下文明示为 `account_code`、`source_account_code` 或 `科目代码` 时，合法会计科目代码才会被放行。Markdown 自然语言中的同样长数字不会被白名单绕过。

真实客户、供应商、员工、项目等本地敏感词可通过未提交文件维护:

```text
scripts/sensitive_terms.local.json
```

该文件已加入 `.gitignore`，不得提交。

---

## 3. Git 历史风险

当前工作树: 已清理，并已由仓库级扫描确认 0 命中。

Git 历史: 仍可能含有本次治理前提交过的敏感数据。历史提交、旧 clone、本地备份、CI 日志或外部分发副本均应按潜在敏感载体处理。

历史重写: 未授权，未执行。

在用户或管理层明确授权前，不得执行 `git filter-repo`、BFG Repo-Cleaner、`git push --force` 或其他强制重写历史的操作。

---

## 4. 后续处置建议

如确认仓库曾对外共享，建议在单独授权任务中评估:

- 是否重写 Git 历史;
- 是否废弃旧仓库并创建干净仓库;
- 是否轮换或审阅相关账号、合同、客户资料和员工资料;
- 是否清理旧 CI artifact、本地备份和共享压缩包。

以上事项不属于 TASK-095A 当前工作树清理范围。
