// Thread organization is page-local until durable backend sessions are available.
export function createThread(profileId, model, now = Date.now()) {
  return {
    id: crypto.randomUUID(),
    profileId,
    model,
    title: "New thread",
    turns: [],
    draft: "",
    pinned: false,
    settled: false,
    snoozedUntil: null,
    busy: false,
    failed: false,
    created: now,
    updated: now,
  };
}

export function threadShelf(thread) {
  if (thread.snoozedUntil) return "snoozed";
  if (thread.settled) return "settled";
  return thread.pinned ? "pinned" : "active";
}

export function organizeThread(
  thread,
  action,
  wakeAt = null,
  now = Date.now(),
) {
  if (action === "settle" && thread.busy) return false;
  if (action === "snooze" && (!Number.isFinite(wakeAt) || wakeAt <= now))
    return false;
  if (action === "pin") thread.pinned = !thread.pinned;
  else if (action === "settle") {
    thread.settled = true;
    thread.pinned = false;
    thread.snoozedUntil = null;
  } else if (action === "restore" || action === "wake") {
    thread.settled = false;
    thread.snoozedUntil = null;
  } else if (action === "snooze") {
    thread.settled = false;
    thread.snoozedUntil = wakeAt;
  } else return false;
  return true;
}

export function wakeThreads(threads, now = Date.now()) {
  let changed = false;
  for (const thread of threads) {
    if (thread.snoozedUntil && thread.snoozedUntil <= now) {
      thread.snoozedUntil = null;
      changed = true;
    }
  }
  return changed;
}
