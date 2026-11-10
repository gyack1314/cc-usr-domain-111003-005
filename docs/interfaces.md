# 资料工作台接口

门户使用本地 HTTP 服务及 SQLite 草稿库。GET / 显示资料检索和每页五条的分页，GET /record/编号 显示完整业务字段、修订及 SHA-256，GET /attachment/编号 下载与摘要完全相同的 UTF-8 JSON 字节。引用采用 编号@SHA256。原始资料只读，栏目之间按业务编号关系解释，不能按显示顺序认定替代关系。

GET /drafts 展示草稿；GET /draft/new 新建；GET /draft/编号 回读与编辑。浏览器表单提交到 POST /draft/save，参数为 key、version、title、body、refs；refs 每行一项。首次 version=0，修订使用已读版本。相同正文和引用重送返回已有版本，不增历史；不同内容使用过时版本返回409，材料摘要变化也返回409，空内容或无效编号返回400。草稿总为待人工审批，不提供签章、发布、预约或对外通知接口。

workbench.evidence.Journal 提供 SQLite 进度账。append(key,note) 对相同键和内容幂等，对不同内容拒绝覆盖；read() 按序号返回。修订记录请使用新键并在内容中注明前序关系。note 可保存来源地址、原始材料摘要、观察事实和未决问题，不认定业务有效性。

python -m workbench.tools manifest 材料目录 清单.json 生成文件指纹。清单必须位于材料目录之外。verify 材料目录 清单.json 校验更改，摘要不符返回2。路径越界、符号链接拒绝处理。atomic_json 提供单文件原子替换，不代表多个文件已构成业务事务。

python -m workbench.browser URL 存档目录 使用 Chromium 对单个可见页面保存截图、标题和正文。它不遍历资料、不下载附件、不计算业务结论、不创建草稿。浏览器阅读与本地计算可以独立组合。领域工具见 domain-tools.md。

GET /document/编号 返回对应的文书副本；扫描资料返回SVG页面。下载文书的指纹可用材料工具另行保存。原始JSON摘要与文书摘要是不同对象，不可相互冒认。
