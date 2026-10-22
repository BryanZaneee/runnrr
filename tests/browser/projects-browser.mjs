// Run in the local browser. Imports a disposable folder and mocks only chat.
(async () => {
  const results=[], $=id=>document.getElementById(id);
  const assert=(v,m)=>{if(!v)throw new Error(m);results.push(m);};
  const wait=async fn=>{for(let i=0;i<100;i++){if(fn())return;await new Promise(r=>setTimeout(r,50));}throw new Error('Timed out');};
  const click=s=>document.querySelector(s).click();
  const change=(id,value)=>{$(id).value=value;$(id).dispatchEvent(new Event('input',{bubbles:true}));};
  const headers={'X-Workspace-Owner':localStorage.getItem('runnrr-workspace-key')};
  let projectId=null; const originalFetch=window.fetch;
  try {
    $('new-chat').click();assert($('picker-heading').textContent==='Choose an assistant','New thread asks for assistant first');
    click('[data-choice="research-analyst"]');assert($('picker-heading').textContent==='Choose a project','Assistant selection moves to project step');
    click('[data-choice=""]');assert(!$('project-picker').open && $('assistant-select').value==='research-analyst','No project starts an assistant-only thread');
    $('add-project').click();change('project-name','Temporary folder QA');
    const file=new File(['The sample delivery color is lavender.'],'overview.md',{type:'text/markdown'});
    Object.defineProperty(file,'webkitRelativePath',{value:'Notes/overview.md'});
    const data=new DataTransfer();data.items.add(file);$('project-files').files=data.files;$('project-files').dispatchEvent(new Event('change',{bubbles:true}));
    await wait(()=>$('project-file-summary').textContent.startsWith('1 files'));
    $('add-project-form').requestSubmit();await wait(()=>$('project-picker').open&&!$('add-project-dialog').open);
    let list=await originalFetch('/api/projects',{headers}).then(r=>r.json());
    projectId=list.projects.find(p=>p.name==='Temporary folder QA').id;
    assert(Boolean(projectId),'Folder contents are saved in the backend');
    change('picker-query','Temporary folder');assert(document.querySelectorAll('[data-choice]').length===1,'Project search filters the list');
    $('project-picker').close();$('new-chat').click();click('[data-choice="research-analyst"]');click(`[data-choice="${projectId}"]`);
    assert($('header-identity').textContent.includes('Temporary folder QA'),'Selected project appears in the thread header');
    let payload;
    window.fetch=(url,options)=>{
      if(url!=='/api/chat')return originalFetch(url,options);
      payload=JSON.parse(options.body);
      return Promise.resolve(new Response('event: delta\ndata: {"text":"Test response"}\n\nevent: done\ndata: {}\n\n',{headers:{'Content-Type':'text/event-stream'}}));
    };
    change('composer-input','What is the delivery color?');$('composer-form').requestSubmit();await wait(()=>Boolean(payload));
    assert(payload.project_id===projectId && payload.profile==='research-analyst','Chat sends the selected project and assistant');
    assert($('close-nav').querySelector('img').src!==$('panel-toggle').querySelector('img').src,'Left and right sidebar icons are distinct');
    const box=$('workspace-settings').getBoundingClientRect();assert(box.x<80&&box.bottom>innerHeight-80,'Settings is in the bottom-left corner');
    $('workspace-settings').click();assert($('settings-dialog').open,'Settings opens a working dialog');$('settings-dialog').close();
    list=await originalFetch('/api/projects',{headers}).then(r=>r.json());assert(list.projects.some(p=>p.id===projectId),'Project remains available on a new backend read');
    return {passed:results.length,checks:results};
  } finally {
    window.fetch=originalFetch;
    if(projectId)await originalFetch(`/api/projects/${projectId}/delete`,{method:'POST',headers});
  }
})()
