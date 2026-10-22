import { applyEvent } from "./chat.mjs";

export function createThreadStore(api, onError) {
  const queues = new Map();
  const saved = new Map();
  const fields = [
    "id",
    "profileId",
    "model",
    "projectId",
    "title",
    "draft",
    "pinned",
    "settled",
    "snoozedUntil",
    "created",
    "updated",
  ];
  function snapshot(thread) {
    return JSON.stringify(
      Object.fromEntries(fields.map((key) => [key, thread[key] ?? null])),
    );
  }
  function save(thread) {
    const body = snapshot(thread);
    if (saved.get(thread.id) === body)
      return queues.get(thread.id) || Promise.resolve();
    saved.set(thread.id, body);
    const pending = (queues.get(thread.id) || Promise.resolve())
      .catch(() => {})
      .then(() => api("/api/threads", { method: "POST", body }))
      .catch((error) => {
        saved.delete(thread.id);
        onError("Thread could not be saved: " + error.message);
        throw error;
      });
    queues.set(thread.id, pending);
    return pending;
  }
  async function load() {
    const data = await api("/api/threads");
    return data.threads.map(({ history, ...thread }) => {
      saved.set(thread.id, snapshot(thread));
      thread.turns = history.map((record) => {
        const turn = {
          prompt: record.prompt,
          blocks: [],
          tokens: 0,
          finished: false,
          error: null,
        };
        for (const { event, ...data } of record.events)
          applyEvent(turn, event, data);
        if (!turn.finished)
          applyEvent(turn, "error", {
            message:
              "This response was interrupted. Start a fresh thread to continue.",
          });
        return turn;
      });
      thread.busy = false;
      thread.failed = Boolean(thread.turns.at(-1)?.error);
      return thread;
    });
  }
  async function remove(thread) {
    await (queues.get(thread.id) || Promise.resolve());
    await api(`/api/threads/${thread.id}/delete`, { method: "POST" });
    saved.delete(thread.id);
  }
  return { save, load, remove };
}
