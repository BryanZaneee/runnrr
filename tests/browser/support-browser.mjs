(async () => {
  const results = [], requests = [], $ = id => document.getElementById(id);
  const assert = (value, message) => { if (!value) throw new Error(message); results.push(message); };
  const wait = async fn => { for (let i=0;i<100;i++) { if(fn()) return; await new Promise(r=>setTimeout(r,50)); } throw new Error('Timed out'); };
  const originalFetch = window.fetch;
  let fail = false, hold = false;
  window.fetch = (url, options) => {
    if (url !== '/api/chat') return originalFetch(url, options);
    requests.push(JSON.parse(options.body));
    if (hold) return new Promise((resolve, reject) => options.signal.addEventListener('abort', () => reject(new DOMException('Stopped', 'AbortError')), {once:true}));
    if (fail) return Promise.resolve(new Response('', {status:503}));
    const events = [
      ['tool_use_start', {name:'search_kb'}],
      ['tool_result', {name:'search_kb',source_items:[{label:'Coffee knowledge'}]}],
      ['delta', {text:'Let me help with your request. <script>window.injected=true</script>'}],
      ['done', {}],
    ];
    return Promise.resolve(new Response(events.map(([event,data])=>`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`).join(''), {headers:{'Content-Type':'text/event-stream'}}));
  };
  try {
    if ($('panel-toggle').getAttribute('aria-expanded') !== 'true') $('panel-toggle').click();
    document.querySelector('[data-panel="support"]').click();
    assert($('panel-content').textContent.includes('Simulated customers, real agent responses'), 'Simulation is explicitly labeled');
    document.querySelector('[data-support-start]').click();
    await wait(()=>requests.length === 3 && !document.querySelector('[data-support-start]').disabled);
    assert(requests.every(r=>r.profile==='customer-service' && r.project_id===null), 'Demo sends real chat requests with the support assistant');
    assert(new Set(requests.map(r=>r.session_id)).size===3, 'Each customer has separate conversation context');
    assert(document.querySelectorAll('[data-support-case]').length===3, 'Monitor lists all simulated customers');
    assert(document.querySelector('.support-monitor').textContent.includes('search_kb · done'), 'Monitor displays completed tool activity');
    assert(document.querySelector('.support-monitor').textContent.includes('Let me help'), 'Monitor shows streamed response');
    assert(!window.injected && !document.querySelector('.support-monitor script'), 'Monitor sanitizes model output');
    const headers={'X-Workspace-Owner':localStorage.getItem('runnrr-workspace-key')};
    const saved=await originalFetch('/api/threads',{headers}).then(r=>r.json());
    assert(requests.every(r=>saved.threads.some(t=>t.id===r.session_id)), 'Demo threads save their metadata to SQLite');
    fail=true;
    document.querySelector('[data-support-start]').click();
    await wait(()=>requests.length===4 && !document.querySelector('[data-support-start]').disabled);
    assert(document.querySelector('.support-monitor [role="alert"]'), 'Failed requests display an error and stop the run');
    assert(document.querySelector('.support-inbox').textContent.includes('Needs attention'), 'Failed conversation is not marked complete');
    fail=false;hold=true;
    document.querySelector('[data-support-start]').click();
    await wait(()=>requests.length===5);
    document.querySelector('[data-support-stop]').click();
    await wait(()=>!document.querySelector('[data-support-start]').disabled);
    assert(document.querySelector('.support-monitor').textContent.includes('Demo run stopped'), 'Stop cancels the request and labels the incomplete response');
    assert(requests.length===5, 'Stopping does not launch the next customer conversation');
    return {passed:results.length,checks:results};
  } finally { window.fetch=originalFetch; }
})()
