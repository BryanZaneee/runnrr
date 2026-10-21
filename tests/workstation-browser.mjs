// Evaluate this file in a browser on a running Runnrr workstation.
// Uses an isolated same-origin frame and mocks every chat request; no model calls.
(async () => {
  const frame = document.createElement('iframe');
  frame.style.cssText = 'position:fixed;inset:0;width:100%;height:100%;border:0;z-index:200;background:white';
  frame.src = '/?workstation-check';
  document.body.append(frame);
  const results = [], errors = [];
  const wait = async (condition, message) => {
    for (let i=0;i<100;i++) { if (condition()) return; await new Promise(r=>setTimeout(r,50)); }
    throw new Error(message);
  };
  const assert = (value, message) => { if (!value) throw new Error(message); results.push(message); };
  try {
    await new Promise(resolve => { frame.onload = resolve; });
    const w = frame.contentWindow, d = w.document, $ = id => d.getElementById(id);
    w.addEventListener('error', event=>errors.push(event.message));
    await wait(()=>$('model-select').options.length && !$('composer-input').disabled,'Configured runtime did not load');
    const requests = [], originalFetch = w.fetch.bind(w);
    let mode = 'done', finish = null;
    const send = (controller,event,data) => controller.enqueue(new TextEncoder().encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`));
    w.fetch = (path,options) => {
      if (path !== '/api/chat') return originalFetch(path,options);
      requests.push(JSON.parse(options.body));
      if (mode === 'error') return Promise.resolve(new Response('',{status:429}));
      return Promise.resolve(new Response(new ReadableStream({start(controller) {
        send(controller,'tool_use_start',{name:'web_search'});
        send(controller,'tool_result',{name:'web_search',source_items:[{label:'Example source',url:'https://example.com'}]});
        const complete = () => {
          send(controller,'delta',{text:'## A clear next step\n\nYour task is ready.\n\n<script>window.uiInjected=true</script> [unsafe](javascript:alert(1))'});
          send(controller,'usage',{input_tokens:20,output_tokens:10});
          send(controller,'done',{}); controller.close();
        };
        if (mode === 'hold') finish = complete; else complete();
      }}),{headers:{'Content-Type':'text/event-stream'}}));
    };
    const click = selector => { const el=d.querySelector(selector); if (!el) throw new Error(`Missing ${selector}`); el.click(); };
    const input = text => { $('composer-input').value=text; $('composer-input').dispatchEvent(new w.Event('input',{bubbles:true})); };
    const choose = (id,value) => { $(id).value=value; $(id).dispatchEvent(new w.Event('change',{bubbles:true})); };
    const startNew = () => { const id=$('assistant-select').value; $('new-chat').click(); click(`[data-choice="${id}"]`); click('[data-choice=""]'); };
    if ($('panel-toggle').getAttribute('aria-expanded') === 'true') $('panel-toggle').click();
    input('Prepare a weekly summary'); $('composer-form').requestSubmit();
    await wait(()=>$('transcript').textContent.includes('30 tokens'),'First stream did not finish');
    assert(!w.uiInjected && !$('transcript').querySelector('a[href^="javascript:"]'),'Markdown stays sanitized');
    assert($('transcript').querySelector('details') && !$('transcript').querySelector('details').open,'Tool activity is collapsed');
    $('panel-toggle').click(); click('[data-panel="sources"]');
    assert($('panel-content').querySelector('a')?.href === 'https://example.com/','Sources come from stream events');
    if (w.innerWidth > 1100) {
      const before = $('workspace-panel').getBoundingClientRect().width;
      $('panel-resizer').dispatchEvent(new w.KeyboardEvent('keydown',{key:'ArrowLeft',bubbles:true}));
      assert($('workspace-panel').getBoundingClientRect().width > before,'Panel width is adjustable with the keyboard');
    }
    $('close-panel').click();
    const firstId = requests[0].session_id, firstModel = requests[0].model;
    const alternative = [...$('model-select').options].find(o=>o.value !== firstModel);
    if (alternative) {
      choose('model-select',alternative.value);
      assert(!$('transcript').querySelector('.turn'),'Changing model starts a fresh thread');
      input('Keep this draft'); startNew();
      assert($('sidebar-list').textContent.includes('Keep this draft'),'New thread preserves another thread’s draft');
    }
    click(`[data-session="${firstId}"]`);
    input('Follow up on that summary'); $('composer-form').requestSubmit();
    await wait(()=>requests.length === 2 && !$('composer-input').disabled && $('transcript').querySelectorAll('.turn-footer').length === 2,'Follow-up did not finish');
    assert(requests[1].model === firstModel && requests[1].session_id === firstId,'Reopened thread retains original model and session');
    $('thread-actions').click(); click('[data-rename]');
    $('thread-name').value = 'Weekly summary'; $('rename-form').requestSubmit();
    assert($('header-identity').textContent.includes('Weekly summary'),'Rename updates the thread header');
    $('thread-actions').click(); click('[data-organize="pin"]');
    assert($('sidebar-list').textContent.includes('Pinned'),'Pin creates the pinned section');
    $('thread-actions').click(); click('[data-snooze="30"]');
    assert(!$('sidebar-list').querySelector(`[data-session="${firstId}"]`),'Snoozed thread leaves the active list');
    click('[data-shelf="snoozed"]');
    assert($('snoozed-threads').querySelector(`[data-session="${firstId}"]`),'Snoozed thread appears in its shelf');
    click(`[data-session="${firstId}"]`);
    assert($('composer-input').disabled,'Snoozed thread must be restored before sending');
    click('[data-organize="restore"]');
    assert(!$('composer-input').disabled,'Restore makes thread usable');
    $('thread-actions').click(); click('[data-organize="settle"]');
    assert(!$('sidebar-list').querySelector(`[data-session="${firstId}"]`),'Settled thread leaves active work');
    $('undo-action').click();
    assert($('sidebar-list').querySelector(`[data-session="${firstId}"]`),'Undo restores settled thread');
    click(`[data-session="${firstId}"]`); $('thread-actions').click(); click('[data-delete]'); $('delete-form').requestSubmit();
    assert(!d.querySelector(`[data-session="${firstId}"]`),'Delete removes the thread');
    $('undo-action').click();
    assert($('header-identity').textContent.includes('Weekly summary'),'Undo deletion restores conversation');
    mode = 'hold'; startNew(); input('Background task'); $('composer-form').requestSubmit();
    await wait(()=>Boolean(finish),'Deferred stream was not started');
    const busyId = requests.at(-1).session_id;
    $('thread-actions').click();
    assert(d.querySelector('[data-organize="settle"]').disabled && d.querySelector('[data-delete]').disabled,'Busy thread cannot be settled or deleted');
    $('thread-menu').hidePopover(); startNew(); input('An independent draft');
    finish(); await new Promise(r=>setTimeout(r,100));
    assert($('composer-input').value === 'An independent draft' && !$('transcript').querySelector('.turn'),'Background stream cannot overwrite the active thread');
    click(`[data-session="${busyId}"]`);
    assert($('transcript').textContent.includes('Your task is ready'),'Background response is available in its original thread');
    const firstTurn = $('transcript').querySelector('.turn');
    mode = 'done'; input('A follow-up question'); $('composer-form').requestSubmit();
    await wait(() => !$('composer-input').disabled, 'Follow-up did not finish');
    assert($('transcript').querySelector('.turn') === firstTurn, 'Completed transcript nodes survive new responses');
    mode = 'error'; startNew(); input('Test an unavailable request'); $('composer-form').requestSubmit();
    await wait(()=>$('transcript').querySelector('[role="alert"]'),'Error was not shown');
    assert($('composer-input').disabled && $('sidebar-list').textContent.includes('Needs attention'),'Request failure is visible and keeps thread context');
    frame.style.width = '390px'; frame.style.height='844px';
    await new Promise(r=>setTimeout(r,100));
    assert(d.documentElement.scrollWidth <= w.innerWidth,'Mobile layout has no horizontal overflow');
    $('open-nav').click();
    assert($('main').inert && $('sidebar').classList.contains('is-open'),'Mobile navigation opens with background inert');
    $('close-nav').click(); $('panel-toggle').click();
    assert($('chat-column').inert && !$('workspace-panel').hidden,'Mobile panel opens with conversation inert');
    $('close-panel').click();
    assert(!$('chat-column').inert,'Closing mobile panel restores conversation interaction');
    for (const width of [320,760,1024,1440,2048]) {
      frame.style.width = `${width}px`;
      await new Promise(r=>setTimeout(r,30));
      assert(d.documentElement.scrollWidth <= w.innerWidth,`No horizontal overflow at ${width}px`);
      const box = $('send-button').getBoundingClientRect();
      assert(box.right <= w.innerWidth && box.left >= 0,`Send button stays reachable at ${width}px`);
    }
    assert(errors.length === 0,`No browser errors: ${errors.join(', ')}`);
    return {passed:results.length,checks:results,requests:requests.length};
  } finally { frame.remove(); }
})()
