# 招标补遗对投标文件的有效条款归并资料工作台

面向内部资料人员的 Python 工作台，提供本地资料门户、草稿修订、进度账和领域计算工具。业务规程见 materials/policy.md；门户中的来文可能具有不同权限、时间与适用对象，下载可用不代表结论已获批准。

## 运行

```bash
python -m pip install -r requirements.txt
python -m playwright install chromium --with-deps
python -m workbench.portal --port 8765 --state state/portal
```

打开 http://127.0.0.1:8765。本地材料位于 materials，门户提供检索、分页、详情与附件下载。既有草稿保存在 state/portal，不会写回原始资料。

```bash
docker build -t local-business-workbench .
docker run --rm --shm-size=1g -p 127.0.0.1:8765:8765 local-business-workbench
```

容器包含所需浏览器与系统库，依赖准备后运行不访问外部业务系统；离线验证可加 --network none，在容器内访问本地服务。

## 测试与构建

```bash
python -m unittest discover -s tests -v
python -m tests.browser_checks
python -m compileall -q workbench tests
```

浏览器检查用临时状态验证目录、附件、草稿和冲突处理；不会改变日常资料。编译检查为 Python 字节码构建。

## 工具与材料

```bash
python -m workbench.tools list
python -m workbench.tools manifest materials state/materials-manifest.json
python -m workbench.tools verify materials state/materials-manifest.json
```

workbench/domain.py 提供与本业务相关的计算原语，examples/tool_calls.json 包含独立的小型调用例子。docs/domain-tools.md 和 docs/interfaces.md 说明输入与错误。资料采信、争议裁决与审批由业务人员负责，门户草稿始终保留人工审批状态。

目录职责：workbench 为应用与工具，portal_data 为门户服务数据，materials 为本地业务材料，tests 为原有能力检查，docs 为接口及运行说明。所有主体、编号和文书均为合成数据。
