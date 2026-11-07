// Execute the pinned upstream plugin against the installed DSH modules.
// All storage is temporary; no model/provider, live profile, or network is used.
import assert from 'node:assert/strict';
import {mkdtemp, mkdir, readFile, writeFile, rm, cp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {resolve, dirname, join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {performance} from 'node:perf_hooks';
import {spawnSync} from 'node:child_process';
import {createHash} from 'node:crypto';

const artifact = resolve(process.argv[2] ?? '.evaluation/dsh-memory-20261104');
const runtime = join(artifact, 'runtime');
const load = p => import(pathToFileURL(join(runtime, p)).href);
const {Context} = await load('node_modules/@deepseek-ai/cordis/lib/index.js');
const {default: SystemPrompt, renderPrompt, renderContextSnapshot} = await load('node_modules/@deepseek-ai/dsh-system-prompt/lib/index.js');
const {default: Storage} = await load('node_modules/@deepseek-ai/dsh-storage/lib/index.js');
const {default: Tools} = await load('node_modules/@deepseek-ai/dsh-tools/lib/index.js');
const jsonBackend = await load('node_modules/@deepseek-ai/dsh-storage-json/lib/index.js');
const domainFacility = await load('node_modules/@deepseek-ai/dsh-storage-domain/lib/index.js');
const source = join(artifact, 'upstream/guntur-d');
const variants = {};
for (const variant of ['original', 'compat', 'dynamic']) {
  const dest = join(runtime, `plugin-${variant}`);
  await mkdir(dest, {recursive: true});
  await cp(join(source, 'src'), join(dest, 'src'), {recursive: true});
  await cp(join(source, 'package.json'), join(dest, 'package.json'));
  let code = await readFile(join(dest, 'src/index.ts'), 'utf8');
  if (variant !== 'original') {
    const needle = "  ctx.provide('memory', memory)\n";
    assert.equal(code.split(needle).length - 1, 1, 'upstream changed: duplicate registration patch no longer matches');
    code = code.replace(needle, '');
  }
  if (variant === 'dynamic') {
    assert.equal(code.split('ctx.systemPrompt.section({').length - 1, 1);
    code = code.replace('ctx.systemPrompt.section({', 'ctx.systemPrompt.context({');
  }
  await writeFile(join(dest, 'src/index.ts'), code);
  variants[variant] = await import(pathToFileURL(join(dest, 'src/index.ts')).href);
}

const a = {session: {id: 'fixture-earlier', header: {cwd: '/fixture/project-A'}}};
const later = {session: {id: 'fixture-later', header: {cwd: '/fixture/project-A'}}};
const b = {session: {id: 'fixture-other-project', header: {cwd: '/fixture/project-B'}}};
const assembleContext = agent => ({agent, scope: agent});
const results = [];
async function record(id, fn) {
  const start = performance.now();
  try {results.push({id, ...(await fn()), wall_ms: +(performance.now() - start).toFixed(3)});}
  catch (error) {results.push({id, probe_error: String(error), stack: error.stack, wall_ms: +(performance.now() - start).toFixed(3)});}
}
async function host(variant = 'compat', root, config = {}) {
  const ctx = new Context();
  await ctx.plugin(SystemPrompt, {includeHarnessIdentity: false});
  await ctx.plugin(Tools);
  await ctx.plugin(Storage);
  await ctx.plugin(jsonBackend, {root});
  await ctx.plugin(domainFacility, {backend: 'json'});
  const fiber = ctx.plugin(variants[variant], config);
  try {await fiber;} catch (error) {await ctx.fiber.dispose(); throw error;}
  return {ctx, fiber, close: () => ctx.fiber.dispose()};
}
const memoryText = (ctx, agent) => ctx.systemPrompt.assemble(assembleContext(agent)).then(renderPrompt);

// Child simulates a lost acknowledgement after a real durable save.
if (process.env.DSH_MEMORY_PROBE_CHILD === 'commit-then-exit') {
  const h = await host('compat', process.env.DSH_MEMORY_PROBE_STORE);
  await h.ctx.memory.save(a, {text: 'fixture committed before acknowledgement'});
  process.exit(97);
}

const work = await mkdtemp(join(tmpdir(), 'dsh-memory-evaluation-'));
const withHost = async fn => {
  const root = await mkdtemp(join(work, 'store-'));
  const h = await host('compat', root);
  try {return await fn(h, root);} finally {await h.close();}
};

try {
  await record('unmodified_plugin_load', async () => {
    const root = join(work, 'original');
    try {const h = await host('original', root); await h.close(); return {compatible: true};}
    catch (error) {return {compatible: false, error: String(error), patch_tested: "Remove the redundant ctx.provide('memory', memory); Service already registers it."};}
  });
  await record('lifecycle_and_durable_fact', async () => {
    const root = join(work, 'restart');
    let h = await host('compat', root);
    await h.ctx.memory.save(a, {text: 'fixture release requires owner approval', tags: ['release']});
    const toolResult = await h.ctx.tools.execute({name: 'memory_write', callId: 'fixture-tool-call', arguments: {text: 'fixture written through actual tool pipeline'}, agent: a, signal: AbortSignal.timeout(5000)});
    const toolSaved = h.ctx.memory.search(a, 'actual tool pipeline').length === 1;
    await h.close();
    h = await host('compat', root);
    try {
      const prompt = await memoryText(h.ctx, later);
      const scopePrompt = await memoryText(h.ctx, b);
      const tools = (await h.ctx.systemPrompt.assemble(assembleContext(later))).tools.map(t => t.name);
      await h.fiber.dispose();
      const disposed = await memoryText(h.ctx, later);
      return {contract_met: prompt.includes('owner approval') && !scopePrompt.includes('owner approval') && !disposed.includes('owner approval') && toolSaved, later_session_evidence_present: prompt.includes('owner approval'), cross_scope_evidence_present: scopePrompt.includes('owner approval'), disposed_prompt_evidence_present: disposed.includes('owner approval'), actual_tool_pipeline_write_present: toolSaved, actual_tool_result: toolResult, registered_tools: tools};
    } finally {await h.close();}
  });
  await record('baseline_context_comparison', async () => withHost(async ({ctx}, root) => {
    const target = 'fixture build command is make verify';
    const facts = [target, ...Array.from({length: 8}, (_, i) => `fixture unrelated lunch preference ${i}`)];
    for (const text of facts) await ctx.memory.save(a, {text});
    const file = join(root, 'project-A-MEMORY.md');
    await writeFile(file, facts.map(t => `- ${t}`).join('\n'));
    const fileContext = await readFile(file, 'utf8');
    const pluginContext = await memoryText(ctx, later);
    const contexts = {no_memory: '', plain_workspace_file: fileContext, existing_plugin_compat: pluginContext};
    return {fixture_kind: 'synthetic; same earlier facts; no model adoption measured', contexts: Object.fromEntries(Object.entries(contexts).map(([name, text]) => [name, {required_evidence_present: text.includes(target), unrelated_fact_count: facts.slice(1).filter(f => text.includes(f)).length, context_characters: text.length}])), explicit_plugin_search_finds_older_evidence: ctx.memory.search(later, 'make verify').some(x => x.text === target), contract_met: false, reason: 'Default recent-eight injection excludes older relevant evidence and includes unrelated facts; explicit search still finds it.'};
  }));
  await record('scope_and_delete', async () => withHost(async ({ctx}) => {
    const entry = await ctx.memory.save(a, {text: 'fixture private project-A convention'});
    const otherSearch = ctx.memory.search(b, 'convention');
    let refused = false;
    try {await ctx.memory.forget(b, entry.id);} catch {refused = true;}
    await ctx.memory.forget(a, entry.id);
    const prompt = await memoryText(ctx, later);
    return {contract_met: otherSearch.length === 0 && refused && ctx.memory.search(later, 'convention').length === 0 && !prompt.includes(entry.text), other_workspace_matches: otherSearch.length, cross_workspace_delete_refused: refused, deleted_present_after_rebuild: prompt.includes(entry.text)};
  }));
  await record('missing_cwd_scope', async () => withHost(async ({ctx}) => {
    const one = {session: {id: 'no-cwd-one', header: {}}};
    const two = {session: {id: 'no-cwd-two', header: {}}};
    await ctx.memory.save(one, {text: 'fixture no-cwd secret'});
    const exposed = ctx.memory.search(two, 'no-cwd secret').length;
    return {phase: 'exploratory boundary probe', contract_met: exposed === 0, other_no_cwd_session_matches: exposed, limitation: 'Anonymous-workspace sessions share <no-cwd>; observed fixture risk, not an observed live-user leak.'};
  }));
  await record('correction', async () => withHost(async ({ctx}) => {
    await ctx.memory.save(a, {text: 'fixture deploy target is staging'});
    await ctx.memory.save(a, {text: 'fixture correction: deploy target is production'});
    const prompt = await memoryText(ctx, later);
    return {contract_met: false, old_value_present: prompt.includes('target is staging'), new_value_present: prompt.includes('target is production'), explicit_supersession_available: false, limitation: 'Both writes remain; a model may interpret correction text, but code does not establish a current claim.'};
  }));
  await record('prompt_budget', async () => withHost(async ({ctx}) => {
    for (let i = 0; i < 8; i++) await ctx.memory.save(a, {text: `${i}:` + 'x'.repeat(1998)});
    const prompt = await memoryText(ctx, later);
    return {entry_count: ctx.memory.list(later).length, context_characters: prompt.length, configured_entry_bound_met: ctx.memory.list(later).length <= 8, aggregate_token_bound: 'not implemented or measured', contract_met: null, limitation: 'The configured eight-entry and 2000-character-per-entry limits hold. No aggregate token threshold was frozen; the observed character count is not a failure against an invented threshold or a tokenizer measurement.'};
  }));
  await record('duplicate_and_concurrency', async () => withHost(async ({ctx}) => {
    const input = {text: 'fixture same replayed save event'};
    await ctx.memory.save(a, input); await ctx.memory.save(a, input);
    const duplicateCount = ctx.memory.search(a, input.text).length;
    await Promise.all(Array.from({length: 40}, (_, i) => ctx.memory.save(a, {text: `fixture concurrent-${i}`})));
    const concurrent = ctx.memory.search(a, 'fixture concurrent-');
    return {duplicate_contract_met: duplicateCount === 1, replayed_event_records: duplicateCount, concurrency_contract_met: concurrent.length === 40 && new Set(concurrent.map(e => e.seq)).size === 40, accepted_concurrent_facts: concurrent.length, concurrency_scope: 'one process, one domain handle; no multi-process locking claim'};
  }));
  await record('backend_rejection_retry', async () => withHost(async ({ctx}) => {
    const unit = ctx.storageDomain.get('memory').unit;
    const original = unit.putRecord.bind(unit);
    let rejected = false;
    unit.putRecord = async (table, ...args) => {
      if (table === 'entries' && !rejected) {rejected = true; throw new Error('fixture injected backend rejection');}
      return original(table, ...args);
    };
    let failed = false;
    try {await ctx.memory.save(a, {text: 'fixture retry after failed persistence'});} catch {failed = true;}
    const beforeRetry = ctx.memory.search(a, 'failed persistence').length;
    await ctx.memory.save(a, {text: 'fixture retry after failed persistence'});
    const afterRetry = ctx.memory.search(a, 'failed persistence').length;
    return {contract_met: failed && beforeRetry === 0 && afterRetry === 1, first_write_rejected: failed, visible_before_retry: beforeRetry, visible_after_retry: afterRetry, limitation: 'Injected rejection, not a power-loss or filesystem-corruption test.'};
  }));
  await record('lost_acknowledgement_retry', async () => {
    const root = join(work, 'lost-ack');
    const child = spawnSync(process.execPath, [new URL(import.meta.url).pathname, artifact], {env: {...process.env, DSH_MEMORY_PROBE_CHILD: 'commit-then-exit', DSH_MEMORY_PROBE_STORE: root}, encoding: 'utf8', timeout: 15000});
    assert.equal(child.status, 97, child.stderr);
    const h = await host('compat', root);
    try {
      const before = h.ctx.memory.search(a, 'committed before acknowledgement').length;
      await h.ctx.memory.save(a, {text: 'fixture committed before acknowledgement'});
      const after = h.ctx.memory.search(a, 'committed before acknowledgement').length;
      return {contract_met: before === 1 && after === 1, child_exit: child.status, records_after_restart: before, records_after_retry: after, limitation: 'Process exits after durable commit before acknowledgement; does not simulate an interrupted fsync.'};
    } finally {await h.close();}
  });
  await record('retry_prompt_invalidation', async () => {
    const values = {};
    for (const variant of ['compat', 'dynamic']) {
      const h = await host(variant, join(work, `retry-${variant}`));
      try {
        const entry = await h.ctx.memory.save(a, {text: 'fixture revoked memory must disappear'});
        const accepted = await h.ctx.systemPrompt.assemble(assembleContext(a));
        await h.ctx.memory.forget(a, entry.id);
        const refreshed = h.ctx.systemPrompt.refreshContext(accepted, assembleContext(a));
        const prompt = renderPrompt(refreshed) + renderContextSnapshot(refreshed);
        const fresh = await memoryText(h.ctx, a);
        values[variant] = {deleted_present_in_accepted_retry_assembly: prompt.includes(entry.text), deleted_present_after_full_rebuild: fresh.includes(entry.text)};
      } finally {await h.close();}
    }
    return {phase: 'exploratory mechanism probe with intervention', variants: values, observed: 'Static section survives refreshContext; dynamic context is refreshed.', limitation: 'Executes the real prompt registry with a fixture agent. Actual model-request replay, already-sent conversation history and server-side caches are not tested; deletion cannot retract prior messages.'};
  });
  await record('ablation_controls', async () => {
    const entries = [{workspace: 'A', text: 'build make verify'}, {workspace: 'A', text: 'lunch tea'}, {workspace: 'B', text: 'build other-secret'}];
    const selected = (scope, relevance) => entries.filter(e => (!scope || e.workspace === 'A') && (!relevance || e.text.includes('build')));
    return {kind: 'offline fixture controls; not a deployed candidate or model benchmark', scoped_relevant: selected(true, true).map(e => e.text), scope_filter_off: selected(false, true).map(e => e.text), relevance_filter_off: selected(true, false).map(e => e.text), current_state_read_on: 'desktop (fixture current config)', current_state_read_off: 'web (fixture stale memory)', limitation: 'Demonstrates filter mechanisms only; no measured task-success improvement.'};
  });
} finally {await rm(work, {recursive: true, force: true});}

const protocolPath = resolve(dirname(new URL(import.meta.url).pathname), 'protocol.json');
const protocol = await readFile(protocolPath);
const output = {protocol_sha256: createHash('sha256').update(protocol).digest('hex'), fixture_type: 'synthetic deterministic execution probes, not held-out user tasks', model_calls: 0, api_spend: 0, host_node: process.version, results, remaining_gaps: ['No later user session exists for a temporal held-out evaluation.', 'No model adoption, final task success, answer citation quality, actual token usage, or model/API efficiency measured.', 'No live desktop plugin installation, full agent-loop replay, or mid-fsync power-loss test.']};
await writeFile(join(artifact, 'probe-results.json'), JSON.stringify(output, null, 2) + '\n');
console.log(JSON.stringify(output, null, 2));
if (results.some(r => r.probe_error)) process.exitCode = 1;
