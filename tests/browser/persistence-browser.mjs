(async () => {
  const results=[], assert=(v,m)=>{if(!v)throw new Error(m);results.push(m);};
  const headers={'X-Workspace-Owner':localStorage.getItem('runnrr-workspace-key'),'Content-Type':'application/json'};
  const model=document.querySelector('#model-select').value, now=Date.now();
  for(const extra of [
    {id:'persistent-draft',title:'My saved draft',draft:'Keep this question'},
    {id:'persistent-snooze',title:'Wake after expiry',snoozedUntil:now-1000},
    {id:'persistent-settled',title:'Leave me settled',settled:true},
  ]) {
    const res=await fetch('/api/threads',{method:'POST',headers,body:JSON.stringify({profileId:'customer-service',model,created:now,updated:now,...extra})});
    assert(res.ok,`Saved ${extra.id}`);
  }
  const frame=document.createElement('iframe');
  frame.src='/?persistence-check';document.body.append(frame);
  try {
    await new Promise(r=>frame.onload=r);
    const d=frame.contentDocument;
    for(let i=0;i<100&&!d.querySelector('[data-session="persistent-draft"]');i++)await new Promise(r=>setTimeout(r,50));
    assert(d.querySelector('#sidebar-list [data-session="persistent-draft"]'),'Reload restores saved threads');
    assert(d.querySelector('#sidebar-list [data-session="persistent-snooze"]'),'Expired snooze returns to main section after reload');
    assert(!d.querySelector('#sidebar-list [data-session="persistent-settled"]'),'Settled thread stays out of main section after reload');
    d.querySelector('[data-session="persistent-draft"]').click();
    assert(d.querySelector('#composer-input').value==='Keep this question','Reload restores draft');
    d.querySelector('[data-shelf="settled"]').click();
    assert(d.querySelector('#settled-threads [data-session="persistent-settled"]'),'Settled thread remains in settled section');
    return {passed:results.length,checks:results};
  } finally {frame.remove();}
})()
