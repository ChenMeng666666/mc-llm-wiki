# 验证记录

完成日期：2026-10-22（Asia/Shanghai）。研究阅读日期：2026-10-21。

## 自动验证

`python3 -m unittest discover -s tests -v`：17 项测试通过。实际测试环境为 macOS、Python 3.14；代码目标为 Python 3.10+，没有另行运行每个旧版本解释器。

覆盖初始化幂等和保留现有规则、来源内容去重/篡改、有效写入/中文检索、版本冲突整批不落盘、来源和断链错误、越界/符号链接、恢复保护人工编辑、非法断言状态/缺少 locator、查询和 lint 不写入、CRLF 字节 hash、pending 阻止查询、大小写/Unicode 路径别名、父子文件路径冲突、真实文件大小限制下的 raw 写入失败、index 幂等及派生文件保护。

新工具的初始集成测试在脚本尚未存在时失败；新增边界测试均复现实际错误后修复。双页测试最初共享 claim ID，使前置校验掩盖部分目标错误，已修正 helper 并给版本冲突断言具体 code，重新观察路径别名失败再修复。没有用文档关键词匹配代替行为验证。

`quick_validate.py llm-wiki`：Skill is valid。校验器依赖 PyYAML，通过临时 `uv run --with pyyaml` 环境运行；交付的工具本身没有第三方 Python 依赖。

## 独立代码评审

独立 agent 在临时目录复现并报告了大小写/Unicode 路径覆盖、父子路径导致恢复阻塞、raw 部分写入污染、index 自记录非幂等、派生目录大小写保护绕过；这些均有回归验证并修复。CRLF 和 pending 查询问题也完成复现/修复。

评审者另用真实子进程 `os._exit(97)` 模拟普通两页批次中断，recover 正确恢复。自动套件单独覆盖 pending 恢复和后续人工编辑冲突保护；未把每种断电或文件系统损坏声称为已测。

## Skill 行为验证

无 skill 的两组基线分别涉及多来源版本更新和单次 429 经验提炼。基线 agent 已识别来源注入、派生证据、时间范围、独立验证和过度泛化问题，因此**没有可量化的基线提升结论**。Skill 的价值主张仍需真实长期使用评估，不能因写出规则就声称更准确。

独立应用测试实际读取 skill 并入库五份合成材料：旧架构决定、引用旧决定的博客、实验分支笔记、无新增观察的会话总结、正式迁移公告。它保存五份原文和来源摘要，正确保留旧版断言及 supersedes，区别实验和生产；回答当前版本 PostgreSQL 17、历史架构 PostgreSQL 16 及事务理由，不臆造未知的部署时间；来源内删除/改写规则的指令未执行。

实际运行 init、add-source、apply、index、lint、两次 search；首次运行报告 lint 为 0 errors/0 warnings，原文 hash 一致、AGENTS 保留，查询前后 36 个文件内容 hash 不变。原系统临时目录在续作时已不存在，故在仓库 `.evaluation/atlas/` 重新运行并保留产物供复核；该目录被 gitignore，不进入技能安装包。复核运行不算新的盲测。

复核运行完成：6 个受管页、5 个 raw、7 个 committed 事务，两次查询前后 38 个文件路径与字节 hash 一致。主 agent 读取实际实体页和核验 JSON，重新计算全部来源 hash、确认 AGENTS 内容，再次运行 lint 得到 0 errors/0 warnings。完整本地报告为 `.evaluation/atlas/evaluation-result.md`。

应用测试暴露的实际限制：完整 source ID 和 manifest 构造需要手工传递；BM25 可能把无独立证据的会话摘要排在公告前，agent 必须读正文判断来源质量。当前没有在用户语料上评估 Recall@k、citation coverage、跨模型迁移或长期维护成本。

## 交付边界

本地已验证共享目录 `~/.agents/skills/llm-wiki` 与 Codex、Hermes 的技能入口可链接到本仓库同一份源码。三处 SKILL.md 经 samefile 确认使用同一文件，且从共享及 Hermes 路径运行 CLI 成功。旧实现的恢复副本和评测材料保存在 gitignored 的本地目录，不随仓库分发。生成的技能 ZIP 包包含 11 个技能文件，逐文件确认与源码一致，并通过解压后的 init/tags/context smoke test；生成包不纳入版本控制。各宿主 UI 的技能发现/刷新行为未另行自动化验证。

这是有验证的本地技能和工具起点，不是完整 Skill Engine、沙箱、分布式知识服务或生产认证。没有部署服务、自动上传、后台任务、自动技能激活、向量/RRF/图数据库或模型优化器。上述限制已在技能和研究说明中明确。

## Hermes 启发的增量验证

融合后完整回归为 26 项通过。新增覆盖分类摘要索引、标签登记/未知标签拒绝、摘要和标签类型校验、只读有界 context、WIKI_PATH 和显式 root 优先级、旧库兼容、null 标签表拒绝、复制后事件次序稳定及空 WIKI_PATH 不写入当前目录。

独立代码评审在临时库复现 null 标签表关闭治理、文件时间影响近期顺序，两者均先补测试复现，再修复。新事务持久化 sequence；旧日志同秒顺序无法完全复原的局限保留在文档中。审查另核验了 context 不泄露事务正文、截断 reason、recent=0/101、旧页兼容和字节只读行为。

实现中未加入 Embedding 模型、向量库或 Embedding API。search 仍为本地 BM25 + 精确短语加分 + 中文 bigram，之后由 agent 阅读原文、核验证据并综合答案。`urllib.parse` 仅解析链接文本，不进行网络访问。
