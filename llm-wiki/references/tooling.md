# 本地工具

需要 Python 3.10+ 和 macOS/Linux（使用标准库 fcntl）。无第三方运行依赖、模型密钥、网络请求或动态技能代码加载。把下文 `SKILL_ROOT` 理解为本次加载的 skill 目录；不要依赖用户的固定绝对路径。

```bash
python3 "$SKILL_ROOT/scripts/wiki.py" --root ./knowledge init
python3 "$SKILL_ROOT/scripts/wiki.py" --root ./knowledge context --recent 10
python3 "$SKILL_ROOT/scripts/wiki.py" --root ./knowledge tags --add research database
python3 "$SKILL_ROOT/scripts/wiki.py" --root ./knowledge add-source /absolute/path/paper.html --title "论文标题" --url https://example.org/paper --published 2026-10-20
python3 "$SKILL_ROOT/scripts/wiki.py" --root ./knowledge search "概念或实体"
python3 "$SKILL_ROOT/scripts/wiki.py" --root ./knowledge evidence --claim atlas-production-db-17
python3 "$SKILL_ROOT/scripts/wiki.py" --root ./knowledge evidence --source <已登记来源ID> --limit 20
python3 "$SKILL_ROOT/scripts/wiki.py" --root ./knowledge lint
python3 "$SKILL_ROOT/scripts/wiki.py" --root ./knowledge index
```

可以设置任务专用/宿主配置中的 WIKI_PATH，省略 --root；显式 --root 始终优先。若两者都没有，CLI 拒绝执行，避免无意写入错误位置。此版不修改全局环境或搬迁现有库。

context 默认返回 schema.md、wiki/index.md 各最多 6000 字符的摘录，以及最近 10 条非 index 操作描述；--max-chars 作用于每份文档摘录，--recent 可为 0..100，每条 reason 最多 300 字符。JSON 结构本身还有额外开销。截断标记要求 agent 按需补读；命令不返回事务正文、不记查询日志，也不写文件。新事务在写锁内分配并持久化递增 sequence，复制/备份或时钟调整不改变顺序；无 sequence 的旧日志先按记录时间、再按 ID 稳定排序，无法恢复旧版同秒操作的真实先后。

tags 不带 --add 是只读查询；带 --add 时受写锁、版本检查与事务保护。新库只接受已登记的标签；旧库未配置标签表时保持兼容，详见 schema.md。index 现在按类型分组并展示 summary，无摘要的旧页不会因此失败。

`add-source` 的 file 必须已经由有权限的工具取得。`--url` 只是来源元数据，不触发抓取。所有字节原样复制到 raw；重复 hash 返回原来源，原始文件已有但损坏时报错。文件很大时要考虑内存，因为此版一次读取完整文件。正文抽取/OCR 由 agent 使用现有工具完成；工具不声称理解 PDF 或图片。

对会话/trace 使用 `--kind session` 或 `--kind trace`；派生摘要使用 `--kind derived --derived-from <已登记来源ID>`，多来源重复传 derived-from。`--scope` 默认为 private，标签不提供 OS 级访问控制。归档前先判断存储位置和派生内容是否适合用户授权的范围。

## 来源血缘审计

`evidence` 为只读操作，必须二选一：`--claim <断言ID>` 或 `--source <来源ID>`。前者返回断言、页面 hash、带 locator 的直接引用、去重的声明根与 unresolved_sources；后者返回派生后代和直接/间接引用它们的 affected_claims。`via` 是受影响的直接引用，`other_roots` 是避开目标来源的路径仍能到达的根。结果只覆盖已登记的 derived_from 和 claims.evidence，不遍历自由正文、supersedes 或 relations，也不进行反事实/语义失效推理。

每个集合使用 `{items,total,truncated}`；`--limit` 默认为 20，允许 1..100，作用于每个集合，total 在截断前计算。截断时提高 limit 或直接读登记表/页面；它不是分页接口，不可把当前 items 当作完整复核清单。命令会扫描全库并校验 raw hash，limit 限制返回项目数，不限制扫描时间、单项文本长度或 token 数。

`lineage_complete` 仅表示引用非空且声明图没有遇到无父项的 derived 来源。`semantic_support` 和 `independence` 始终是 `not_checked`。不同根不代表独立观测，多个共同父项也不表示任选一项即可支持结论。命令不读取 locator 对应的段落内容，不能证明引用蕴含断言。

快照丢失/损坏时仍返回复核清单，同时 `vault_integrity_ok=false`、integrity_errors 给出错误；退出 0 表示报告生成成功。其他结构错误（包括血缘成环、缺父项、坏页面、重复断言）拒绝审计，避免静默漏报。pending 批次沿用 recovery_required。先修复结构，再复查原文；不要用新 hash 掩盖损坏。

## 批次页面写入

manifest 是 JSON 文件，包含非空 reason 和 changes 数组。每个 change **只包含** path/expected_sha256/content。新文件 expected_sha256 为 null；更新必须填写读取时现有文件的完整 SHA-256（不是模型估算）。content 是包括 JSON frontmatter 的整页文本。

下面代码从两个真实文件生成一个更新 manifest：`current` 是已读取并审查的规范页面，`staged` 是 agent 在 staging 中编辑的候选。读取基线后到 apply 之间若规范页有变化，会冲突而不会覆盖。

```python
import hashlib
import json
from pathlib import Path

root = Path("knowledge")
relative = "wiki/entities/atlas.md"
current = root / relative
staged = Path("/tmp/atlas-staged.md")
baseline = current.read_bytes() if current.exists() else None
manifest = {
    "reason": "根据生产迁移公告更新 Atlas 数据库，保留旧版本断言",
    "changes": [{
        "path": relative,
        "expected_sha256": hashlib.sha256(baseline).hexdigest() if baseline is not None else None,
        "content": staged.read_text(encoding="utf-8"),
    }],
}
Path("/tmp/wiki-change.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
```

**基线 hash 必须来自决定如何修改时读取的版本。** 如果 staged 依据更早的文件生成，不可在提交前只刷新 hash 而不重新合并。为新页生成 manifest 时同样确认目标先前不存在。

```bash
python3 "$SKILL_ROOT/scripts/wiki.py" --root ./knowledge apply /tmp/wiki-change.json
python3 "$SKILL_ROOT/scripts/wiki.py" --root ./knowledge index
python3 "$SKILL_ROOT/scripts/wiki.py" --root ./knowledge lint
```

apply 先对整批候选做结构检查，再验证所有 hash，写入写前日志，逐个原子替换文件，最后标记 committed。进程内异常尝试回滚；进程强制退出可能留下 pending，后续 mutation 拒绝继续。批次不是多文件同时可见的 OS 事务；CLI 的协作读者受共享锁保护，外部编辑器仍可能看到中间态或绕过锁。

为支持大小写不敏感的 macOS 卷，所有平台都拒绝仅有大小写或 Unicode 规范化差异的页面路径。pending 存在时 search 同样拒绝读取不完整批次；lint 仍可用于诊断。

index 只重建目录和操作视图；不做语义摘要。log.md 排除 index 自身，避免目录重建递归产生新记录；state/transactions 保留包括 index 在内的操作依据。相同状态重复 index 不产生新写入。对 init、搜索或外部手工编辑没有全量审计保证。日志含页面前后正文，因此需与知识库同等保护。

## 恢复

```bash
python3 "$SKILL_ROOT/scripts/wiki.py" --root ./knowledge recover
```

recover 只处理 pending 批次：每个目标必须仍等于日志里的 before 或 after，全部匹配才恢复 before。若目标被后来手工编辑，返回 recovery_conflict，不抹掉新编辑。此时检查日志、保存双方文本、手动合并后再恢复/完成修复，不要改 hash 强制通过。日志不是外部可信输入；不要导入不认识的事务 JSON。

对已 committed 的语义错误，读取对应日志的 before，形成新的逆向 manifest，并使用**当前**已审查版本 hash；照常 apply/index/lint。不要把旧事务直接改成 pending。脚本不提供删除操作，归档通过 status 实现；真正删除在用户明确范围内另行处理。

## 输出与错误

操作响应是 JSON：protocol_version=1，status=ok/error，operation，data，error。错误包含稳定 code 和 message，不输出 traceback。CLI 参数语法错误与 --help 使用 argparse 的标准文本输出。进程退出 0 表示结构操作成功，1 表示业务/输入错误，2 表示命令参数错误。

version_conflict/busy/recovery_required 是停止当前写入并重读/恢复的条件；不要盲目重试。validation_failed 的 data.errors 可供逐项修复；warnings（例如孤页）不阻断写入。source_hash_mismatch 需要调查和恢复原始快照，不可用新 hash 掩盖篡改。

## 明确边界

- 路径/符号链接检查防误操作，不防同权限恶意进程的 TOCTOU 攻击。
- flock 是本机协作锁；没有分布式锁、ACL、多租户隔离或 NFS 一致性保证。
- 恢复针对进程中断；虽然关键文件 fsync，未对断电/文件系统损坏做全面认证。raw 在登记前复制，崩溃可能留下未登记的快照，可重新登记；不自动清除。
- search 直接扫描 wiki 页面，用 BM25 + 精确短语加分，汉字 bigram。没有向量、同义词扩展、自动图遍历或 PDF 全文搜索。它返回候选路径与 hash，agent 仍需读正文和原文。
- 没有自动语义冲突解决、秘密扫描、confidence 概率、后台调度、完整 skill optimizer；这些是 agent 工作流或按实测需要扩展的部分。
