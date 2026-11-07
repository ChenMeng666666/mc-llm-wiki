# DSH 记忆插件：本机调查与最小验证

日期：2026-11-04，Asia/Shanghai。结论：**暂不开发新的记忆后端，也不直接启用本次筛选的插件。** 当前用户轨迹不足以证明跨会话记忆需求；已观察到的环境发现与安装问题应优先由当前状态读取和操作规程解决。如果后续真实会话证明需要长期记忆，先比较简单项目文件与现有实现的薄适配。

这次完成了本机取证、当前版本源码核对、一次插件兼容性复现、三种确定性上下文基线以及生命周期/故障探针。没有完成真实任务收益验证。未调用模型 API，未安装服务，未修改 skill 或主动写入 DSH 配置。下面明确区分实测结果和待验证设计。

## 1. 环境与证据身份

- 安装应用：`/Applications/DeepSeek Harness.app`，`Info.plist` 和包内两个 package.json 均为 **0.2.1-rc.5**。
- 当前 profile：`~/.dsh/profiles/desktop`。shell PATH 中没有 `dsh`。可用 CLI 包装器位于应用 `Contents/Resources/runtime/cli/bin/dsh`；本次没有调用它安装任何插件。
- `~/Documents/deepseek-harness` 仅含 `default-workspace`，不是 Git 源码 checkout。实际实现位于 **ASAR 包**。已按 ASAR 索引精确提取 176 份相关文件；这不是从 GitHub 最新版推断本机行为。
- ASAR SHA-256：`8dad52f295bdbe9fa71948fdf38ac2ce3c910213d3b89c37174b2af77db9fb31`。
- 最终执行探针使用应用随附 Node **v24.21.0**，Cordis **4.0.5**、DSH system-prompt/storage/tools **0.2.1-rc.5**。初步加载曾在宿主 Node v24.22.0 执行，最终结果以随附 Node 重跑产物为准。
- 原始 session：`~/.dsh/sessions/--Users-mengchen-Documents-deepseek-harness-default-workspace--/session-a9c225f4-d860-4dd0-8554-9b4b3bbd63de/session.v4.jsonl.zstd`。SHA、大小和逐项定位保存在本地 `observations.json`。定位的行号均为 **解压后的 JSONL 行号**。
- 所选现有插件：[guntur-d/dsh-memory](https://github.com/guntur-d/dsh-memory/tree/cc17aba9868122981e496380345e288d27bb8ac2)，版本 0.1.0，固定 commit `cc17aba9868122981e496380345e288d27bb8ac2`。
- Hindsight：固定 commit `047350acf96167534409e5d87a07b8b2ee1469f9`，coding-agents 包 0.8.5。检查范围是 **DSH 原生适配层**，没有执行记忆服务或验证其基准分数。

原始 trace 含本地认证材料，未复制到证据包。提取器只导出已知的两条用户安装请求、事件位置和布尔分类，不导出工具命令正文、Cookie、凭证文件、provider 请求体或 IM 群聊。历史轨迹内出现的命令没有被重放。

REA 对同一 ASAR 的两个选定模块进行了无执行静态分析，parent evidence ID 为 `ev_c84d15c0246940bdefae4092c645278057baf8416df87e83ab06703582ed6e8b`，摘要保存为 `rea-summary.json`。其图覆盖为 partial，不能据此声称分析了整个程序；后续结论来自指明位置的人工核读和下述真实模块执行。

## 2. 原始轨迹能证明什么

发现 **1 个持久根会话、2 条真实用户请求、127 个模型 step、158 次 tool/call、3 次 LLM retry**。22 个 user/message 事件中大部分是运行时上下文或系统通知，不能当作 22 次用户对话。请求是安装插件市场，以及安装一个模型供应商插件。

| 观察 | 原始位置 | 归因与边界 |
|---|---|---|
| shell 无法把 `app.asar/dsh/` 当普通目录遍历，两次出现 Not a directory | seq 31 / 行 33；seq 153 / 行 155 | 已证实的环境访问错误。应识别 Electron ASAR 或使用提取工具；保存一条路径本身不能解决 |
| shell 返回 dsh: command not found | seq 55 / 行 57 | 已证实的 CLI 发现问题。本轮同样发现 PATH 缺少入口，但应用内存在包装器；应用升级后应重新探测 |
| 第二轮的四次安装命令均使用 desktop，而非用户命令中的 web | seq 727、868、906、1084 | 反证：没有观察到“忘了正确 profile”。不能据请求里出现 web 就判定记忆失败 |
| 第二轮多次后台任务没有新输出、发出取消请求，之后选择性文件获取报告完成 | seq 735、741、776、816、948、978；850、896、934、1001；1077 | 说明安装/获取过程反复排查。具体网络吞吐和全部耗时归因没有被本次实验独立复现；不把 Agent 的速度描述当测量真值 |
| 本轮没有历史 compaction 事件，也未见子 Agent 执行事件 | event_types 完整计数 | 无法证明压缩导致遗忘，也没有真实子 Agent 记忆表现可评估 |

第一轮 69 step / 90 tool call，第二轮 58 step / 68 tool call。数量高不证明记忆插件能降低它们。没有“较早会话建立事实 → 后续新会话需要事实 → 错误结果”的证据链，因此**没有确认任何真实跨会话失败**。这是一项数据覆盖结论，不是对未来记忆价值的否定。

存档有 request/header、system/message、runtime-context 和工具事件，但没有逐次完整主模型 HTTP 请求快照。本次未重建全部请求投影，不能声称完整核验了每次实际发送给模型的字节。没有可用的后续真实会话作时间留出集；过去的 llm-wiki Atlas 合成样例不能替代用户后续任务。

## 3. 当前版本的实际执行路径

以下路径均相对于提取后的 `shipped/dsh/node_modules/@deepseek-ai/`，版本均为 0.2.1-rc.5；文件 hash 在 observations 中。

| 环节 | 本机源码位置 | 已核对行为 | 证据等级 |
|---|---|---|---|
| 提示注册/卸载 | `dsh-system-prompt/lib/index.js:253,279` | section/context 注册是可释放的 Cordis effect | 代码＋实际加载/卸载 |
| 每步组装 | `dsh-agent-loop/lib/index.js:907`；`dsh-agent/lib/index.js:291` | assemble 接收 agent 与 scope，再进入 agent/pre-step waterfall | 代码核读；未执行完整 loop |
| 请求/重试刷新 | `dsh-agent-loop/lib/index.js:1049,1053,1136`；`dsh-system-prompt/lib/index.js:324` | 同一步的 renderedPrompt 在重试循环外生成；重试内刷新 context，保留已接受 section/tool/variable | 代码＋真实 prompt registry 的探索性干预探针 |
| 存储域 | `dsh-storage-domain/lib/index.js:222,257,438` | 域内写链串行；后端成功后才更新可读状态；当前同时提供 storage.domain 和兼容别名 storageDomain | 代码＋真实 JSON/domain 执行 |
| 文件发布 | `dsh-storage-json/lib/index.js:24` | 同目录临时文件、fsync、rename、目录同步；不等于跨进程事务 | 代码＋重启读取；未测每个断电点 |
| 会话事件 | `dsh-session/lib/index.js:1579` | 接受事件进入 log 后通知 session/event；不能将“观察到事件”等同于后台模型任务完成 | 代码核读 |
| 压缩 | `dsh-compaction-basic/lib/index.js:628` | compaction/summary 与 replacement 事件保留来源范围；压缩摘要是派生资料 | 代码核读；真实历史未发生 |
| 子 Agent | `dsh-subagent-spawn-in-process/lib/index.js:27`；`dsh-subagent-fork-in-process/lib/index.js:41` | spawn 不继承父上下文；fork 继承完成轮次前缀。不能把父子复述算独立证据 | 代码核读；未执行子 Agent |

运行中 profile 在调查期间新增了 `@deepseek-ai/dsh-subagent-codex: 0.2.1-rc.5` 及其 bundle 行。**这不是本轮工具写入，来源未作归因**。因此不能宣称整个 profile 字节未变。初始/复核 hash 被保留，ASAR、两份 cordis 文件及原始 trace 的 hash 未变。新增外部子 Agent 插件不在本次继承行为核验范围内，尤其不能把包内 spawn/fork 结论外推给它。

## 4. 冻结方式、对照结果与限制

`protocol.json` 在探针实现前冻结，SHA-256 为 `3903543b7686192e578037591f68e822315b974c4d5bc341a18e8ffe65078a4c`。冻结的是场景、判据、资源预算和决策门；具体诊断样例由同一作者编制，**不是盲测、独立验证集或统计基准**。额外的无 cwd 与重试 context 探针标为 exploratory。模型调用预算为 0，因此答案引用质量、模型采用、最终任务成功、实际模型 token/费用收益均未测。

原插件的旧 peer 范围不覆盖当前 DSH。更关键的是：在当前真实 Cordis、Tools、SystemPrompt、StorageDomain、JSON backend 上直接加载，复现 `service "memory" has been registered`。保留固定上游原文；仅在隔离副本移除一次冗余 `ctx.provide('memory', memory)` 后继续。**适配后的对照不能称为原插件开箱可用，也未通过正常发布构建、依赖安装或桌面完整生命周期验收。**

三个基线使用同一组按时间保存的合成事实：一条较早的 build 命令，随后八条无关偏好。文件基线读取完整项目文件；插件基线采用默认 recent-eight 注入；两者都没有新增相关性排序。这里比较的是上下文供给行为，不是同 token 预算下的模型效果。

| 基线 | 所需证据进入自动上下文 | 无关事实条数 | 上下文字符数 |
|---|---:|---:|---:|
| 无记忆 | 否 | 0 | 0 |
| 简单工作区 Markdown 文件 | 是 | 8 | 350 |
| 现有插件＋单行兼容修正 | 否 | 8 | 510 |

插件显式 search 能找到那条旧事实。因此该例定位的是**自动注入选择**，不是数据没有保存，也不是关键词工具不能检索。没有测模型是否会主动调用 search，不能将“未自动进入上下文”直接计为任务失败。

12 组执行探针完成，无探针执行错误；**不代表 12 项产品契约全部通过**。主要结果如下：

| 探针 | 实际结果 |
|---|---|
| 持久化/工具/跨 fixture session/卸载 | 当前真实 Tools.execute 调用 memory_write 返回非错误并落盘；存储关闭再打开后可读；同项目 later fixture 可见；插件释放后 prompt/tool 注册移除 |
| 有明确 cwd 的项目隔离/删除 | A 的数据在 B 搜索与注入中不可见；B 删除 A 被拒绝；A 删除后重新 assemble 不再显示 |
| 无 cwd 边界（探索性） | 两个无 cwd 的 fixture session 共享 `<no-cwd>`；不满足拒绝模糊作用域的候选契约。不是用户实际泄漏事件 |
| 纠正 | 保存旧值及纠正后，两者都保留；未建立代码可识别的 supersession。模型仍可能读懂文字纠正 |
| 上下文上限 | 八条、每条 2000 字符的配置生效，渲染总长 16222 字符；没有总 token 上限。未预设总 token 阈值，因此不将该字符数记为超限失败 |
| 重复写入 | 重放同一事实产生两条 UUID 记录；无事件级幂等键 |
| 单进程并发 | 40 条独立并发保存全部可读，序号唯一；没有验证多进程共同写库 |
| 后端拒绝与重试 | 注入一次真实 unit.putRecord 拒绝；失败条目未进入可读状态，重试后出现一条。不是断电试验 |
| 提交后确认丢失 | 子进程真实写入后 exit(97)；重启可见一条，再次保存后两条。验证的是“已提交但未确认”，不是 fsync 途中中断 |
| 重试提示失效（探索性干预） | 删除后，已接受的静态 section 经 refreshContext 仍有旧内容；只把 section 改为 context，旧内容不再出现在刷新结果。两者完整重新组装均无旧内容 |

最后一项执行真实 prompt registry，fixture agent 只有 session 身份；没有发送模型请求。它不证明删除能撤回已发送历史、服务端缓存或其他副本。不能把 context 修正描述为完整隐私删除实现。

另有 scope/relevance/current-state 的离线开关控制，展示关掉过滤后出现的额外资料；这是机制示例。真正调用真实 registry 的 section/context 干预更有判别力，两者都不是任务成功率消融。没有对时延作统计比较，wall_ms 只保存为运行记录。

## 5. 只针对缺口比较方案

| 方案 | 文档约定 | 本次看到的代码 | 本次实际跑通 | 用户收益验证 |
|---|---|---|---|---|
| 简单项目文件 | 人工维护、直接读取 | 本次基线 | 文件读取/上下文供给 | 未做 |
| guntur 插件 | 工作区记忆、四个工具、有界注入 | 固定 commit 三份 TS＋manifest | 原版加载失败；单行修正后上述探针执行 | 未做 |
| llm-wiki | 来源/断言/时间/冲突/技能候选规约 | 当前本地 CLI、schema、workflow | 本轮 26 项工具回归通过；没有 DSH 接入验证 | 未做；既有记录也未证明量化基线增益 |
| Hindsight | 按会话仓库记忆、调用前召回、写回 | coding-agents 0.8.5 的 `src/dsh.ts` | 本轮未安装、未启动服务、未执行 adapter/core | 未做；公开产品基准不是本机证据 |

llm-wiki 可借鉴来源血缘、有效时间、supersedes 和小 patch/CAS 写入；这些数据规则不会自动提供 DSH lifecycle、检索相关性或模型采用保证。其完整 26 项通过仅是机械工具验证，不能当作语义回答质量验证。

Hindsight 已有[官方 DSH 原生入口](https://github.com/vectorize-io/hindsight/blob/047350acf96167534409e5d87a07b8b2ee1469f9/hindsight-integrations/coding-agents/src/dsh.ts)。定向核读看到：按会话 cwd 解析 workspace（162 行），排除 subagent（214 行），在新用户输入 pre-step 触发 core.onPrompt 并去重注入（290 行），turn-stopping 写回（321 行），通过当前事件快照和继承计数处理 fork（140、155 行），在 Cordis 注册原生 hook/tool（444 行）。这些是**适配源码存在**，不是本机兼容或收益通过；内部 core、超时、数据删除和记忆服务本轮未核验。

官方[接入文档](https://hindsight.vectorize.io/sdks/integrations/coding-agents)与[召回文档](https://hindsight.vectorize.io/developer/api/recall)可作为后续验证入口。既然原生适配已存在，目前没有证据支持为接入本身另写一个 Hindsight wrapper。服务成本、自动导入范围和本机版本兼容仍需独立验证，不能用插件条目存在替代。

## 6. 最小记忆契约（候选，未实现/启用）

| 内容 | 最小规则 | 应由代码执行 | 仍需语义判断 |
|---|---|---|---|
| 可写入内容 | 用户明确的长期偏好、可定位的项目决定、已验证的非显然经验 | 类型、必填字段、长度与授权范围校验 | 是否长期有效、是否过度泛化 |
| 当前状态 | profile、版本、工作目录、代码和配置优先现场读取；旧记忆只作探测线索 | 注入时附状态版本/核验标记；不将未复核记忆当当前状态 API | 证据冲突时的解释；文字优先级仍依赖模型采用 |
| 来源 | source_session、source_event_seq 或文件 hash＋locator、observed_at；推断保存为 draft | 缺少来源拒绝提升；类型不可省略 | 引用是否支持该陈述 |
| 作用域 | 显式项目边界和规范路径；缺少身份拒写，不能落入共享无 cwd 桶；用户全局偏好另分域 | 所有读写/注入由 host 解析 scope，而非信任模型参数 | 何时允许跨项目共享 |
| 纠正与时间 | 稳定 claim ID、valid_from/to、supersedes；保留历史，当前视图唯一 | 过滤已替代项、检测版本冲突、维护反向依赖 | 两条证据是否真的互相替代 |
| 重试与删除 | 来源事件幂等键；提交前不可见；删除/撤回使派生摘要和新注入失效 | 幂等提交、tombstone、缓存/摘要失效；恢复不重放已删除事实 | 历史导出/备份处置范围；已发送上下文无法撤回 |
| 预算与维护 | 按任务检索必要事实，总 token 预算可配置，保留可查原证据 | 限流/截断记录、显式跳过原因、日志去敏 | 反证重要性和必要覆盖 |

现有事实条目只保存了来源 session，缺少精确 event locator 和证据 hash；不能凭它证明语义正确。上表不是要求一次实现完整平台，而是决定何种内容可进入权威记忆的边界。

## 7. 决策与改变结论的证据

**当前选择：暂不开发新的记忆系统，不把本次诊断补丁部署到日用 profile。** 已有用户证据支持先改善“现场发现”，例如识别 ASAR、定位应用内 CLI、读取当前 profile；可以放入短操作规程，并在每次使用时复核，不需新增记忆后端。

若确有持续使用需求，下一步是一个小的、按时间划分的真实会话试验：

1. 用较早任务中的明确决定/纠正作为设计材料；后续新任务预先固定外部验收与必需证据。不得用本次已读会话或 Atlas 作为未见验证集。
2. 同模型、工具与上下文预算，先比无记忆＋现场读取、简单项目文件；按任务配对，保留失败与重复运行波动。检查模型是否真正读到、引用并采用了正确证据。
3. 只有简单文件仍失败且失败可定位到自动选择/作用域/维护时，才评估现有插件的薄适配。移除重复注册只是启动修正；还须正常构建、依赖版本、host lifecycle 和端到端验证。
4. 若本地简单路径在真实跨来源/时间/语义召回任务上持续不足，再试官方 Hindsight DSH adapter。只有它无法满足已实测需求时，才考虑新实现。

会改变建议的证据是：独立核验的跨会话错误或重复纠正，简单文件无法解决，候选在冻结的后续任务中改善成功/纠正成本，且没有作用域、删除或当前状态使用方面的重要退化。若只是在 fixture 中更容易命中字符串，建议不变。

## 8. 重跑与产物

从仓库根目录执行；Python 3.14 用于读取 Zstandard trace，Node 24.21 用于与该安装版本一致的探针。脚本只访问指定 ASAR、DSH 根下所列配置/会话，以及固定公开源码。可用 --home 指向匿名化 fixture 根，避免读取个人记录。

```bash
python3 docs/dsh-memory-investigation/collect.py --out .evaluation/dsh-memory-20261104
python3 docs/dsh-memory-investigation/prepare_runtime.py --out .evaluation/dsh-memory-20261104/runtime
python3 docs/dsh-memory-investigation/fetch_public.py --out .evaluation/dsh-memory-20261104/upstream
'/Applications/DeepSeek Harness.app/Contents/Resources/runtime/primary-runtime/dependencies/node/bin/node' docs/dsh-memory-investigation/run_probes.mjs .evaluation/dsh-memory-20261104
python3 -m unittest discover -s tests -v
```

`collect.py` 会覆写指定输出目录，重跑取证应使用新的 --out 保留首次快照；只有 probe-results 会被探针重跑更新。执行外部源码仅限上述固定 plugin，在临时存储与提取后的离线 host 上进行；没有执行上游 installer、prepare 或模型请求。

本地实验产物在 `.evaluation/dsh-memory-20261104/`，受仓库现有 gitignore 保护，不作为私有知识导出或安装包提交：

- `observations.json` / `recheck/observations.json`：初始/复核白名单取证与 hash。
- `shipped/`：精确提取的相关 JS/README/manifest；`runtime/runtime-manifest.json`：实际执行的 34 个包身份。
- `upstream/public-lock.json`：固定公开来源、内容 hash 与下载验证状态。
- `probe-results.json` / `probe-stdout.json`：12 组探针，包含预期失败、能力边界与实际 runtime 身份。
- `wiki-tests.log`：26 项回归输出。
- `rea-summary.json`：静态分析身份与覆盖局限。
- `integrity-check.json`：最终字节核验、外部配置变化与报告边界。

独立复核步骤与后续开放任务的盲评输入、事实/引用/纠正/资源指标见 [review.md](review.md)。本轮没有第三方实际盲评，不将提供复核材料称为独立复现。

未运行：真实模型对照、引用评分、独立盲评、Hindsight 服务、完整桌面启停/安装、全部子 Agent 提供商、多进程写入、fsync 中途断电。以上不计为通过。
