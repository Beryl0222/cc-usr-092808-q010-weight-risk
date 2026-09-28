# 健康项目运营协作平台

健康项目运营协作平台用于维护参与者授权、基础筛查、机构资质、从业人员、随访与证据审查之间的版本关系和业务状态。项目采用 Python 标准库与 SQLite，服务可在单个 Linux 应用容器内运行，不依赖外部数据库或远程接口。

## 目录

- `src/wellness_ops/`：领域模型、仓储、权限、审计、事务工作流和命令入口。
- `tests/`：核心流程、边界和恢复行为测试。
- `pyproject.toml`：Python 项目与命令入口配置。

## 测试命令

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

## 编译或构建命令

```bash
python -m compileall -q src
```

## 启动与使用

初始化本地数据库：

```bash
PYTHONPATH=src python -m wellness_ops.cli --database app.sqlite3 init
```

执行无需浏览器的最小验收：

```bash
PYTHONPATH=src python -m wellness_ops.cli --database /tmp/wellness_ops.sqlite3 smoke
```

所有时间字段使用带时区的 ISO 8601 字符串。业务记录采用租户与记录号联合标识，并通过版本号处理并发更新；敏感字段只向获准角色开放，状态变更和通知均保留审计依据。
