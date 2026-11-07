# LLM Wiki Skill

研究驱动的本地知识编译 skill：保留原始来源，把资料合成有证据的 Markdown 知识库，并将验证过的经验提炼为可复用技能候选。

- [技能入口](llm-wiki/SKILL.md)
- [研究与方案取舍](llm-wiki/references/research.md)：三份指定材料、12 篇相关论文、所给执行引擎方案的评估。
- [数据格式](llm-wiki/references/schema.md) · [操作工作流](llm-wiki/references/workflows.md) · [工具说明](llm-wiki/references/tooling.md)
- [技能演化](llm-wiki/references/evolution.md) · [评测规约](llm-wiki/references/evaluation.md) · [验证记录](docs/verification.md)
- [2026-11-05 前沿核读与优化](docs/frontier-review-2026-11-05.md)：从原文、固定源码和失败探针收敛到来源血缘审计。

## 使用

工具需 Python 3.10+，支持 macOS/Linux/Windows。克隆仓库，将技能链接到全局共享目录：

```bash
git clone git@github.com:ChenMeng666666/mc-llm-wiki.git
cd mc-llm-wiki
mkdir -p ~/.agents/skills
ln -s "$PWD/llm-wiki" ~/.agents/skills/llm-wiki
```

Windows 没有可用的 `ln -s` 时，用目录 junction 等价实现（无需管理员权限，在仓库目录内执行）：

```bat
mkdir "%USERPROFILE%\.agents\skills" 2>nul
mklink /J "%USERPROFILE%\.agents\skills\llm-wiki" "%cd%\llm-wiki"
```

支持 `~/.agents/skills` 的 Agent 可从全局目录发现它。其他宿主可以把自己的技能入口链接到同一份源码，例如：

```bash
mkdir -p ~/.codex/skills ~/.hermes/skills/research
ln -s ~/.agents/skills/llm-wiki ~/.codex/skills/llm-wiki
ln -s ~/.agents/skills/llm-wiki ~/.hermes/skills/research/llm-wiki
```

已有同名入口时先检查并复用，不要覆盖其他技能。各入口链接同一份源码后，更新同步生效。共享技能不会自动迁移或合并知识库；若还要共享数据，使用相同的 WIKI_PATH 或显式 --root。

自然语言调用：

```text
使用 $llm-wiki 把这几篇论文纳入 ./knowledge，更新相关概念并列出分歧。
使用 $llm-wiki 回答截至 2026-10-21 的结论，给出原文依据。
使用 $llm-wiki 检查知识库的断链、过期断言和互相冲突的证据。
使用 $llm-wiki 从这些成功和失败 trace 提炼技能候选，独立评测后决定是否启用。
```

脚本只处理机械操作，摄入理解和语义核验由 agent 完成。它不会抓取 URL、调用模型、自动启用候选技能或安装后台任务。

已吸收 Hermes 版的会话恢复、摘要目录和标签治理：context 只读加载有界近期上下文，index 按类型展示 summary，tags 登记允许标签后由 lint/apply 校验。CLI 支持 WIKI_PATH，显式 --root 优先。浏览建议见 [viewing.md](llm-wiki/references/viewing.md)。

```bash
python3 llm-wiki/scripts/wiki.py --root ./knowledge init
python3 llm-wiki/scripts/wiki.py --root ./knowledge context
python3 llm-wiki/scripts/wiki.py --root ./knowledge tags --add research
python3 llm-wiki/scripts/wiki.py --root ./knowledge add-source /absolute/path/source.txt --title "来源标题"
python3 llm-wiki/scripts/wiki.py --root ./knowledge search "问题关键词"
python3 llm-wiki/scripts/wiki.py --root ./knowledge evidence --claim <断言ID>
python3 llm-wiki/scripts/wiki.py --root ./knowledge evidence --source <来源ID>
python3 llm-wiki/scripts/wiki.py --root ./knowledge lint
python3 -m unittest discover -s tests -v
```

当前没有使用 Embedding：检索采用 BM25、精确短语加分和中文 bigram，无向量数据库或第三方 Python 运行依赖。受管页面使用 JSON frontmatter（YAML 子集），已有其他格式的 wiki 先按原有约定工作，不自动迁移。事务工具提供本地协作写入和进程中断恢复，不是沙箱、多租户权限系统或分布式数据库。

`evidence` 只读追溯声明的共同来源根和上游变化的复核范围；lint 拒绝循环血缘，重复登记不再静默忽略显式的血缘冲突。根数量不等于独立证据数，工具不判断引用语义或自动撤销事实。详细输出及截断约定见 [工具说明](llm-wiki/references/tooling.md)。
