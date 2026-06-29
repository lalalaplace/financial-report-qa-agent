# 安全与数据边界

## 不提交内容

- `.env`
- API Key、Token、数据库密码
- 原始 PDF
- Excel 附件
- 数据库文件
- `input/`
- `output/`
- `logs/`
- `示例数据/`
- Python 缓存和测试缓存

## 配置策略

数据库连接通过环境变量读取。PDF 抽取流程不需要模型配置；只有运行 Agent 的真实 LLM 节点或集成测试时，才需要配置模型地址、模型名和 API Key。

示例：

```text
DATABASE_URL=postgresql+psycopg2://user:password@localhost:5432/financial_data

# 仅 Agent 真实 LLM 调用需要
AGENT_LLM_API_KEY=change_me
AGENT_LLM_MODEL=change_me
AGENT_LLM_BASE_URL=https://api.example.com/v1
```

`.env.example` 和 `configs/*.example.env` 只保留占位符。

## SQL 安全

Agent 查询链路不开放自由 Text-to-SQL：

- LLM 只生成 `QueryPlan`、route 或 slot patch。
- SQL 由固定 intent 节点生成。
- SQL Guard 拒绝多语句、写操作、危险关键字和未授权函数。
- `db/readonly_executor.py` 只允许 `SELECT` 或 `WITH` 查询。

## 上传前扫描

```bash
rg -n --hidden --glob '!/.git/**' "password|passwd|pwd|api[_-]?key|secret|token|Bearer|sk-|DATABASE_URL|C:\\Users|D:\\"
```

```bash
git ls-files | rg "(^input/|^output/|^logs/|^示例数据/|\.pdf$|\.xlsx$|\.db$|\.sqlite|\.parquet$|__pycache__|\.pyc$)"
```

第二条命令应没有输出。
