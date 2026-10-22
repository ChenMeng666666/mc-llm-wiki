# 数据契约

本文件是新建 wiki 的默认格式。已有知识库遵守其现有格式；不要为使用工具批量改写已有 frontmatter。CLI 的结构化检查只适用于这里定义的格式。

## 目录

```text
knowledge/
  schema.md                 领域约定；用户和 agent 共同维护
  raw/                      原始二进制快照，按 SHA-256 命名
  wiki/
    index.md                可重建目录
    log.md                  可重建操作视图
    sources/                来源摘要及阅读局限
    entities/               人物、项目、组织、工具等
    concepts/               跨来源的稳定概念
    syntheses/              有证据的分析与问题答案
    patterns/               从执行经验提炼的条件化模式
    questions/              未解问题与证据缺口
    sessions/               去敏后的会话摘要
  state/
    sources.json            来源登记表
    taxonomy.json           允许标签列表；新库初始化为空列表
    transactions/*.json     写前日志、前后文本、最终状态
    lock                    本地协作锁
  proposals/                待审议变更，不是默认检索知识
  skill-candidates/         尚未启用的技能包及评测证据
```

`raw/` 的不可变性是操作契约，hash 检查可发现篡改；普通文件权限并不能防住拥有写权限的进程。删除、法律保留和敏感信息处置遵守用户实际要求，不由遗忘曲线自动决定。需要彻底删除时也要考虑 Git、备份和包含前后正文的事务日志。

## 来源

脚本生成来源 ID `src-` + 完整内容 SHA-256。相同字节重复登记返回原 ID；新增 URL 作为别名登记。同 URL 内容发生变化会得到新 ID，是否语义取代旧版本由 agent 判断。

记录 `title, urls, path, sha256, retrieved_at, published_at, kind, scope, derived_from`。`published_at` 不清楚则 null；必要时在来源摘要补充作者、版本号、会议/期刊状态、访问限制、提取方法和抓取失败。`scope` 是保密/使用范围标签，不是访问控制。

`kind` 可为 `document/session/trace/derived`。`derived_from` 指向原始来源 ID，用于来源血缘。论文引用别人的数字不等于独立复现实验；镜像、转述、会话摘要和基于同一论文写出的综合页不能重复计数。网页提取文本可作为另一个快照，关联原始 HTML/PDF；OCR 必须记录页码及不确定性。

## 页面

正文是普通 Markdown，支持 `[[page-id]]` 和相对 Markdown 链接。优先使用稳定、唯一的页面 ID，避免重名简称。下面的 `src-demo` 仅用于展示字段，实际写入时替换成登记表已有的真实来源 ID。

Frontmatter 用 **JSON 对象包在 YAML 的 `---` 分隔符之间**。JSON 是 YAML 的子集，工具无需第三方 YAML 依赖；多行 YAML 写法不受本 CLI 支持。

```markdown
---
{
  "id": "atlas",
  "title": "Atlas 数据库",
  "type": "entity",
  "status": "active",
  "summary": "Atlas 生产数据库的当前版本、历史迁移与依据。",
  "tags": [],
  "sources": ["src-demo"],
  "claims": [
    {
      "id": "atlas-production-db-17",
      "text": "Atlas 生产库从 2026-10-20 起使用 PostgreSQL 17。",
      "status": "supported",
      "scope": "Atlas/production",
      "valid_from": "2026-10-20",
      "valid_to": null,
      "observed_at": "2026-10-21",
      "evidence": [{"source": "src-demo", "locator": "迁移公告，第 2 段"}],
      "supersedes": ["atlas-production-db-16"]
    }
  ]
}
---

# Atlas 数据库

当前状态与依据；为什么迁移仍需其他材料。
```

上例的旧断言也必须保留在某个受管页面中，否则 `supersedes` 检查失败。页面只保留一个断言的规范定义；其他页链接该页面或引用断言 ID，避免到处复制同一 claim ID。

必填页面字段：`id, title, type, status, sources, claims`。类型为 source/entity/concept/synthesis/pattern/question/session。状态为 draft/active/disputed/superseded/archived。source 页总结一份来源；concept 页围绕概念；synthesis 页回答明确问题。无需为了凑齐目录创建空页面。

断言必填 `id, text, status`；涉及环境差异时填写 `scope`。状态为：

| status | 含义 |
|---|---|
| supported | 给定证据直接支持这个范围内的陈述，非“绝对正确” |
| inferred | agent 的推断，说明推导与前提来源 |
| disputed | 相同范围/时间的证据不一致，保留双方 |
| superseded | 后续证据已建立替代关系，历史仍可查询 |
| unverified | 暂无可核验的支持，不能作为确定结论 |

supported/disputed/superseded 必须包含非空 `evidence`，每条有 `source` 和具体 `locator`，且来源列在页面 `sources` 中。推断也应列前提证据，正文明确“推断”。`claims: []` 可用于问题页或纯导航，不代表正文事实免于引用检查。

`valid_from/valid_to` 为事实生效区间，使用 ISO 日期，结束日期约定为不包含；只有日期粒度时不要假装知道精确时刻。`observed_at` 是记录/得知时间，两者不能互换。没有生效时间保持 null，不从文章发布日期臆造。日期字段校验不证明时间结论正确。旧决定发布日期不一定是旧版本首次上线日期。

导航字段 `summary` 和 `tags` 对已有页面保持可选。summary 如提供必须是非空字符串；新页面应写具体的一句话摘要。index 按页面类型分组、标题排序，展示作者填写的 summary 与状态；旧页面缺少摘要时明确显示尚未提供，不从正文自动猜测。

`tags` 是去重、非空、首尾无空白的字符串列表，未填写相当于 []。新库 `state/taxonomy.json` 是允许列表：先用 `tags --add database research` 登记，再给页面使用。标签定义、别名与适用边界写在 schema.md；允许值以 taxonomy.json 为准，不需要预先凑满固定数量。

旧库没有 taxonomy.json 时仍可读取已有标签，lint 给 taxonomy_unconfigured 提示。再次 init 不会强制启用空标签表；用 tags --add 显式启用时必须覆盖已有页面使用的标签，避免让旧页面失效。标签登记也有事务记录，重复登记同一标签不会产生新写入。受管标签未知时 apply/lint 报 unknown_tag。

其他可选字段：`aliases, updated_at, review_after, evidence_note, relations`。`relations` 用 subject/predicate/object/evidence 表示 uses/depends_on/contradicts 等；只是可阅读的图结构，不声称已有图数据库或自动遍历器。CLI 暂不校验这些其他扩展字段；agent 语义复核负责它们。

## 变更与读写边界

`apply` 仅接受 `wiki/` 内非派生 `.md` 页面。它不能修改 raw、schema、AGENTS、skill 包或执行任何来源代码。`expected_sha256` 为现有文件完整 UTF-8 字节的 hash，新页面用 null。所有前置条件检查通过才开始批次写入。完整历史记录在事务日志；index/log 是派生视图。

查询不需要写操作。用户要求把答案存回时，给新综合页标明原问题、时间、证据、推断与缺口；它依然派生于原材料。对同一问题反复生成回答不会增加独立证据。
