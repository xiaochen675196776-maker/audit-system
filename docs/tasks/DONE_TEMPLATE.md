# 完成回报模板

每个 AI 完成任务后，把下面内容追加到自己任务文件底部，并将任务状态改为 `DONE`、`REVIEW_NEEDED` 或 `BLOCKED`。

````markdown
## 完成回报

状态：DONE / REVIEW_NEEDED / BLOCKED
执行者：
完成时间：YYYY-MM-DD HH:mm

### 修改文件

- `path/to/file`

### 完成内容

- 做了什么
- 修了什么问题

### 验证命令

```powershell
命令
```

结果：

- 通过 / 失败
- 关键输出摘要

### 风险和后续

- 无
- 或列出需要总指挥继续处理的问题
````
