// Check actual transition lifecycles, layout recovery, and keyboard exclusion.
(async () => {
  const $ = id => document.getElementById(id);
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  let passed = 0;
  const assert = (value, message) => { if (!value) throw new Error(message); passed++; };
  const settle = async () => {
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    await Promise.all(document.getAnimations().map(animation => animation.finished.catch(() => {})));
  };
  const toggle = async (id, button, closing) => {
    const controls = document.querySelector('.header-actions');
    const before = controls.getBoundingClientRect();
    $(button).click();
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    const transitions = $(id).getAnimations();
    assert(reduced ? !transitions.length : transitions.some(a => ['margin-left', 'margin-right', 'transform'].includes(a.transitionProperty)), `${id} ${closing ? 'closes' : 'opens'} ${reduced ? 'without motion' : 'with a slide'}`);
    assert($(id).inert === closing, `${id} excludes closed controls from keyboard focus`);
    if (id === 'workspace-panel') {
      do {
        const box = controls.getBoundingClientRect();
        if (Math.abs(box.x - before.x) > 1 || Math.abs(box.y - before.y) > 1)
          throw new Error('Right sidebar animation moves the header controls');
        await new Promise(resolve => requestAnimationFrame(resolve));
      } while ($(id).getAnimations().length);
      assert(true, 'Header controls stay fixed throughout the panel animation');
    }
    await settle();
  };
  await settle();
  const originalLeft = $('main').getBoundingClientRect().left;
  await toggle('sidebar', 'close-nav', true);
  assert($('main').getBoundingClientRect().left === 0, 'Desktop navigation releases its space');
  await toggle('sidebar', 'open-nav', false);
  assert($('main').getBoundingClientRect().left === originalLeft, 'Desktop navigation restores its space');
  await toggle('workspace-panel', 'close-panel', true);
  assert(getComputedStyle($('workspace-panel')).display === 'none', 'Workspace panel leaves layout after closing');
  await toggle('workspace-panel', 'panel-toggle', false);
  // Reverse an unfinished transition to catch stale completion handlers.
  $('close-panel').click();
  $('panel-toggle').click();
  await settle();
  assert(!$('workspace-panel').hidden && !$('workspace-panel').inert, 'Rapid toggling leaves the panel open and interactive');
  const frame = document.createElement('iframe');
  frame.style.cssText = 'position:fixed;width:390px;height:844px;border:0';
  frame.src = '/?sidebar-check';
  document.body.append(frame);
  try {
    await new Promise(resolve => frame.onload = resolve);
    const d = frame.contentDocument, w = frame.contentWindow;
    const wait = async () => {
      await new Promise(resolve => w.requestAnimationFrame(() => w.requestAnimationFrame(resolve)));
      await Promise.all(d.getAnimations().map(a => a.finished.catch(() => {})));
    };
    await wait();
    assert(d.getElementById('sidebar').inert, 'Mobile navigation starts outside keyboard focus');
    for (const [id, open, close] of [['sidebar', 'open-nav', 'close-nav'], ['workspace-panel', 'panel-toggle', 'close-panel']]) {
      const controls = d.querySelector('.header-actions');
      const before = controls.getBoundingClientRect();
      d.getElementById(open).click();
      if (id === 'workspace-panel') {
        do {
          const box = controls.getBoundingClientRect();
          if (Math.abs(box.x - before.x) > 1 || Math.abs(box.y - before.y) > 1)
            throw new Error('Mobile panel animation moves the header controls');
          await new Promise(resolve => w.requestAnimationFrame(resolve));
        } while (d.getElementById(id).getAnimations().length);
        assert(true, 'Mobile header controls stay fixed throughout panel opening');
      }
      await wait();
      d.getElementById(close).click();
      await new Promise(resolve => w.requestAnimationFrame(() => w.requestAnimationFrame(resolve)));
      const animations = d.getElementById(id).getAnimations();
      assert(reduced ? !animations.length : animations.some(a => a.transitionProperty === 'transform'), `${id} mobile close respects motion preference`);
      await wait();
      assert(getComputedStyle(d.getElementById(id)).display === 'none', `${id} mobile drawer is fully hidden`);
    }
    assert(d.documentElement.scrollWidth <= w.innerWidth, 'Mobile slides do not cause horizontal overflow');
  } finally { frame.remove(); }
  return { passed, reducedMotion: reduced };
})()
