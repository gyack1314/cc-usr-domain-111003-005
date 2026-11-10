# 领域工具

可用函数：patch, differences, referenced_targets。实现位于 workbench/domain.py，参数与返回类型见函数签名；examples/tool_calls.json 包含独立示例输入和结果。工具只处理显式传入的记录，不自行选择门户材料、认定有效性或进行审批。

调用方式：`python -m workbench.tools call <函数名> <参数JSON文件>`。输入文件为对象，键名对应函数参数。错误返回非零退出码，不产生成功记录。
