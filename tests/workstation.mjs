// Run: node tests/workstation.mjs. No browser or model keys required.
import assert from 'node:assert/strict';
import { readEvents, applyEvent, safeUrl } from '../web/chat.mjs';

const turn = () => ({ blocks: [], tokens: 0, finished: false });
const a = turn(), b = turn();
const frames = [
  ['tool_use_start', { name: 'search_kb' }],
  ['tool_use_start', { name: 'search_kb' }],
  ['tool_result', { name: 'search_kb', is_error: false, source_items: [{ label: 'Hours' }] }],
  ['tool_result', { name: 'search_kb', is_error: true }],
  ['delta', { text: 'Café ☕' }],
  ['usage', { input_tokens: 10, output_tokens: 3, reasoning_tokens: 2 }],
  ['done', {}],
].map(([event,data])=>`event: ${event}\r\ndata: ${JSON.stringify(data)}\r\n\r\n`).join('');
// Split at every byte, including CRLF and multibyte Unicode boundaries.
const bytes = new TextEncoder().encode(frames);
await readEvents(new ReadableStream({ start(c) {
  for (const byte of bytes) c.enqueue(Uint8Array.of(byte));
  c.close();
}}), (event,data) => applyEvent(a,event,data));
assert.equal(a.blocks[0].status, 'done');
assert.equal(a.blocks[1].status, 'error');
assert.equal(a.blocks[2].text, 'Café ☕');
assert.equal(a.tokens, 13);
assert.equal(a.finished, true);
assert.deepEqual(b, turn(), 'Updates must stay on their originating conversation');
applyEvent(b, 'tool_use_start', { name: 'web_search' });
applyEvent(b, 'error', { message: 'Connection lost' });
assert.equal(b.blocks[0].status, 'interrupted');
assert.equal(b.error, 'Connection lost');
assert.equal(b.finished, true);
for (const url of ['javascript:alert(1)', 'data:text/html,test', 'file:///etc/passwd', '/relative', undefined]) assert.equal(safeUrl(url), null);
assert.equal(safeUrl('https://example.com/page'), 'https://example.com/page');
await assert.rejects(readEvents(new ReadableStream({start(c){c.enqueue(new TextEncoder().encode('event: delta\ndata: {'));c.close();}}),()=>{}), /before the response was complete/);
console.log('Workstation checks passed: fragmented SSE, Unicode, tools, errors, session isolation, safe URLs.');

const { createThread, threadShelf, organizeThread, wakeThreads } = await import('../web/threads.mjs');
const thread = createThread('research-analyst', 'model-a', 1000);
assert.equal(threadShelf(thread), 'active');
assert.equal(organizeThread(thread, 'pin'), true);
assert.equal(threadShelf(thread), 'pinned');
assert.equal(organizeThread(thread, 'snooze', 2000, 1000), true);
assert.equal(threadShelf(thread), 'snoozed', 'Snoozed pinned threads must not also appear in the active list');
assert.equal(wakeThreads([thread], 1999), false);
assert.equal(wakeThreads([thread], 2000), true);
assert.equal(threadShelf(thread), 'pinned', 'Waking preserves the original pin');
thread.busy = true;
assert.equal(organizeThread(thread, 'settle'), false, 'Working threads cannot be settled');
thread.busy = false;
assert.equal(organizeThread(thread, 'settle'), true);
assert.equal(threadShelf(thread), 'settled');
assert.equal(thread.pinned, false);
assert.equal(organizeThread(thread, 'restore'), true);
assert.equal(threadShelf(thread), 'active');
assert.equal(organizeThread(thread, 'snooze', NaN, 1000), false);
assert.equal(organizeThread(thread, 'snooze', 1000, 1000), false);
assert.equal(organizeThread(thread, 'snooze', 2000, 1000), true);
assert.equal(organizeThread(thread, 'settle'), true);
assert.equal(thread.snoozedUntil, null, 'Settling cancels a pending wake');
assert.equal(wakeThreads([thread], 3000), false);
const other = createThread('customer-service', 'model-b');
other.draft = 'Keep this draft';
assert.notEqual(other.id, thread.id);
assert.deepEqual(thread.turns, []);
assert.equal(other.draft, 'Keep this draft');
console.log('Thread checks passed: exclusive shelves, snooze expiry, busy guard, restore, independent drafts.');

const { turnUsage, threadUsage, usagePanel } = await import('../web/usage.mjs');
const usageTurn = turn();
applyEvent(usageTurn, 'usage', { input_tokens: 100, output_tokens: 30, reasoning_tokens: 20,
  cache_read_input_tokens: 60, cache_creation_input_tokens: 10 });
applyEvent(usageTurn, 'usage', { input_tokens: 150, output_tokens: 50, reasoning_tokens: 10 });
assert.equal(usageTurn.tokens, 330, 'Cached input and reasoning must not be counted twice');
assert.equal(usageTurn.usage.input, 250);
assert.equal(usageTurn.usage.reasoning, 30);
const metrics = { tokens: usageTurn.usage, tokens_total: 330, usage_status: 'partial',
  cost_usd: null, context_tokens: 150, context_window: 1000, ttft_ms: 0, duration_ms: 1000 };
applyEvent(usageTurn, 'metrics', metrics);
assert.equal(usageTurn.tokens, 330, 'A terminal snapshot replaces rather than adds usage');
assert.match(turnUsage(usageTurn, 0, true), /330 tokens · partial/);
assert.match(turnUsage(usageTurn, 0, true), / open/);
assert.match(turnUsage(usageTurn, 0), /15.0% of context/);
assert.match(turnUsage(usageTurn, 0), /0.00 s/);
assert.match(threadUsage([usageTurn]), /1 turns without pricing/);
assert.match(turnUsage(turn(), 1), /Usage unavailable/);
const panel = usagePanel({ days: 30, error: '<script>bad</script>', data: null }, [], []);
assert.ok(!panel.includes('<script>'));
assert.match(panel, /&lt;script&gt;/);
console.log('Usage checks passed: inclusive output, multi-hop totals, snapshot replacement, context, missing prices, escaping.');

const { identityBadge } = await import('../web/identity.mjs');
const identities = Array.from({length: 30}, (_, i) => ({id: `item-${i}`, name: `Project ${i}`}));
const badges = identities.map(item => identityBadge(item, identities, 'project'));
assert.equal(new Set(badges.map(b => b.match(/--identity-hue:([^\"]+)/)[1])).size, identities.length);
assert.match(identityBadge(identities[0], identities), /agent-badge.*<svg/);
assert.doesNotMatch(badges[0], /<svg/);
assert.equal(identityBadge(identities[10], identities, 'project'), badges[10], 'Filtering must keep the full collection color');
assert.doesNotMatch(identityBadge({id:'unsafe',name:'<>'}, [], 'project'), /<>/);
console.log('Identity checks passed: unique project colors, person icons, stable colors, escaped initials.');

const truncated = { blocks: [], tokens: 0 };
applyEvent(truncated, 'done', { stop_reason: 'max_tokens' });
assert.equal(truncated.finished, true);
assert.match(truncated.error, /incomplete/);
