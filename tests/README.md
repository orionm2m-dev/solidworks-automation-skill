# 离线回归与原生资格验证

默认 `pytest` 使用合成数据、模拟接口和真实解析器，不连接或修改 CAD 文档。
测试通过只能证明软件契约；真实刀路、刀具、机床和加工结果仍须单独验证。

## 本地运行

```powershell
python -m pytest -q --basetemp "$env:TEMP/solidworks-tests"
python scripts/validate_mcp.py
```

在 Windows 上把临时目录放在本地磁盘，避免每个临时文件都经过网络或 WSL 共享。
同一临时目录只供一个测试进程使用。

## 行与分支覆盖

```powershell
python -m pip install coverage
python -m coverage run --branch --source=scripts,mcp-server -m pytest -q --basetemp "$env:TEMP/solidworks-coverage-tests"
python -m coverage report
python -m coverage html
```

覆盖率记录执行的分支，不代表原生 API 或生产工艺已经合格。
输入模式测试从当前服务器源码提取 AST；不导入服务器，不启动 CAD。

## 可移植数据

提交的 fixtures 必须由合成数据构成，不包含客户 CAD 快照、个人路径或私有凭据。
需要本地观察记录或已安装类型库的检查必须显式启用；默认跳过此类检查。
跳过项须在报告中单列，不计为原生验证成功。
