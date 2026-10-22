// Evaluate on the local workstation. All chat and history responses are synthetic.
(async () => {
  const frame = document.createElement('iframe');
  frame.style.cssText = 'position:fixed;inset:0;width:100%;height:100%;border:0;z-index:200;background:white';
  frame.src = '/?usage-check';
  const loaded = new Promise(resolve => { frame.onload = resolve; });
  document.body.append(frame);
  const results = [];
  const assert = (ok, label) => { if (!ok) throw new Error(label); results.push(label); };
  const wait = async (check) => {
    for (let n=0;n<100;n++) { if (check()) return; await new Promise(r=>setTimeout(r,50)); }
    throw new Error('Usage UI did not reach the expected state');
  };
  try {
    await loaded;
    const w = frame.contentWindow, d = w.document, $ = id => d.getElementById(id);
    await wait(() => $('model-select').options.length && !$('composer-input').disabled);
    const fetch = w.fetch.bind(w);
    const tokens = { input: 100, output: 30, reasoning: 20, cache_read: 60, cache_write: 10 };
    const m = { usage_version: 2, tokens, tokens_total: 130, usage_status: 'partial',
      cost_usd: null, context_tokens: 100, context_window: 1000, ttft_ms: 50,
      duration_ms: 1000, hops: 2, tool_calls: 1, tool_errors: 1, reasoning_estimated: true };
    const totals = { ...tokens, tokens_total: 130, known_cost_usd: 0, cost_usd: null,
      unpriced_turns: 1, incomplete_turns: 1, turns: 1, sessions: 1, hops: 2,
      tool_calls: 1, tool_errors: 1, failed_turns: 1, cache_savings_usd: null };
    let historyUrl = '', fail = false;
    w.fetch = (url, options) => {
      if (String(url).startsWith('/api/usage?')) {
        historyUrl = String(url);
        return Promise.resolve(new Response(JSON.stringify({ since: '2026-10-01', until: '2026-10-16',
          totals, days: [{ ...totals, label: '2026-10-16' }], models: [{...totals, label: '<img src=x onerror=alert(1)>'}],
          providers: [{...totals, label: 'Anthropic'}], profiles: [{...totals, label: 'research-analyst'}] }), {status: fail ? 503 : 200}));
      }
      if (url !== '/api/chat') return fetch(url, options);
      const events = [['delta',{text:'Synthetic metrics check'}], ['usage', {usage_version:2,input_tokens:100,output_tokens:30,reasoning_tokens:20}], ['metrics',m], ['done',{}]];
      return Promise.resolve(new Response(events.map(([event,data])=>`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`).join(''), {headers:{'Content-Type':'text/event-stream'}}));
    };
    $('composer-input').value = 'Synthetic metrics check';
    $('composer-input').dispatchEvent(new w.Event('input', {bubbles:true}));
    $('composer-form').requestSubmit();
    await wait(() => d.querySelector('.turn-usage'));
    const disclosure = d.querySelector('.turn-usage');
    disclosure.open = true;
    assert(disclosure.innerText.includes('130 tokens · partial'), 'Inclusive output and partial label');
    assert(disclosure.innerText.includes('10.0% of context'), 'Latest prompt context meter');
    assert(disclosure.innerText.includes('reasoning split is estimated'), 'Estimated reasoning qualifier');
    assert(disclosure.innerText.includes('Unavailable'), 'Unpriced cost stays unavailable');
    if ($('workspace-panel').hidden) $('panel-toggle').click();
    $('panel-home').click();
    d.querySelector('[data-panel="usage"]').click();
    await wait(() => $('panel-content').innerText.includes('By model'));
    assert($('panel-content').innerText.includes('1 turns without pricing'), 'Historical pricing coverage');
    assert(!d.querySelector('.usage-table img'), 'Historical labels escape HTML');
    const form = $('usage-filters');
    form.elements.days.value = '7';
    form.elements.model.value = $('model-select').value;
    form.requestSubmit();
    await wait(() => !$('usage-filters').querySelector('button').disabled);
    assert(new URLSearchParams(historyUrl.split('?')[1]).get('model') === $('model-select').value, 'Model filter reaches usage API');
    for (const width of [320, 390, 760, 1280]) {
      frame.style.width = `${width}px`;
      await new Promise(resolve => setTimeout(resolve, 40));
      assert(d.documentElement.scrollWidth <= w.innerWidth, `Usage panel fits ${width}px`);
      assert($('usage-filters').getBoundingClientRect().right <= w.innerWidth, `Usage controls reachable at ${width}px`);
    }
    fail = true;
    $('usage-filters').requestSubmit();
    await wait(() => $('panel-content').querySelector('[role="alert"]'));
    assert($('panel-content').innerText.includes('could not be loaded'), 'History failure is explicit');
    assert(d.documentElement.scrollWidth <= w.innerWidth, 'No page overflow');
    return { passed: results, viewport: {width:w.innerWidth,height:w.innerHeight} };
  } finally { frame.remove(); }
})()
