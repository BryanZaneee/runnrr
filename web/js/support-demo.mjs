import { renderTextBlock } from "./transcript.mjs";

const examples = [
  {
    customer: "Maya",
    subject: "Opening hours",
    prompt:
      "Hi! What are your opening hours, and can I reserve a table for Saturday morning?",
  },
  {
    customer: "Jordan",
    subject: "Order problem",
    prompt:
      "I ordered a latte but received the wrong drink. Can you help me get this sorted out?",
  },
  {
    customer: "Sam",
    subject: "Dietary options",
    prompt:
      "Do you have dairy-free drinks and gluten-free food? I have a serious allergy—what should I know before ordering?",
  },
];

export function createSupportDemo({
  available,
  create,
  send,
  refresh,
  escape,
  openThread,
}) {
  let cases = [],
    running = false,
    controller = null,
    selected = 0;
  function render(root) {
    root.innerHTML = `<div class="panel-intro"><h3>Customer service demo</h3><p>Simulated customers, real agent responses. Watch the assistant consult its knowledge and draft replies.</p><p>No replies are sent to a real customer inbox. Uses your selected model and runtime budget.</p></div>
      <div class="support-controls"><button class="primary-button" data-support-start ${running || !available() ? "disabled" : ""}>${cases.length ? "Run again" : "Send agent to demo inbox"}</button>${running ? "<button data-support-stop>Stop run</button>" : ""}</div>
      <p class="panel-note">Keep this page open while the run is active. Each conversation is saved as a thread.</p>
      <div class="support-inbox">${cases.map((item, i) => `<button class="panel-link" data-support-case="${i}" aria-pressed="${selected === i}"><span>${escape(item.customer)} · ${escape(item.subject)}</span><small>${item.thread?.busy ? "Responding" : item.thread?.failed ? "Needs attention" : item.thread?.turns.length ? "Complete" : "Waiting"}</small></button>`).join("")}</div>
      <section class="support-monitor" aria-label="Customer conversation monitor" aria-live="polite">${cases[selected] ? conversation(cases[selected]) : '<p class="panel-note">Start a run to monitor the conversations here.</p>'}</section>`;
    root.querySelector("[data-support-start]").onclick = start;
    root
      .querySelector("[data-support-stop]")
      ?.addEventListener("click", () => controller.abort());
    root.querySelectorAll("[data-support-case]").forEach(
      (button) =>
        (button.onclick = () => {
          selected = Number(button.dataset.supportCase);
          refresh();
        }),
    );
    root
      .querySelector("[data-support-open]")
      ?.addEventListener("click", () => openThread(cases[selected].thread.id));
  }
  function conversation(item) {
    const turn = item.thread?.turns.at(-1);
    return `<h4>${escape(item.customer)} · ${escape(item.subject)}</h4><div class="user-message">${escape(item.prompt)}</div>
      ${
        turn
          ? `<div class="markdown">${turn.blocks
              .filter((b) => b.kind === "text")
              .map(renderTextBlock)
              .join("")}</div><ul class="panel-note">${turn.blocks
              .filter((b) => b.kind === "tool")
              .map((b) => `<li>${escape(b.name)} · ${escape(b.status)}</li>`)
              .join(
                "",
              )}</ul>${turn.error ? `<p role="alert">${escape(turn.error)}</p>` : ""}<button data-support-open>Open full thread</button>`
          : '<p class="panel-note">Waiting for the assistant.</p>'
      }`;
  }
  async function start() {
    if (running || !available()) return;
    running = true;
    controller = new AbortController();
    cases = examples.map((item) => ({ ...item, thread: null }));
    selected = 0;
    refresh();
    try {
      for (let i = 0; i < cases.length; i++) {
        if (controller.signal.aborted) break;
        selected = i;
        const item = cases[i];
        item.thread = create(`Support demo · ${item.customer}`, item.prompt);
        refresh();
        const ok = await send(item.thread, controller.signal);
        if (!ok) break;
      }
    } finally {
      running = false;
      refresh();
    }
  }
  return { render };
}
