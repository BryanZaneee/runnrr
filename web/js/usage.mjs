// Reasoning is included in output. Cache read/write are included in input.
const escape = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const count = (value) => Number(value || 0).toLocaleString();
const money = (value) =>
  value == null
    ? "Unavailable"
    : `$${Number(value).toLocaleString(undefined, { minimumFractionDigits: 4, maximumFractionDigits: 6 })}`;
const duration = (value) =>
  value == null ? "Unavailable" : `${(value / 1000).toFixed(2)} s`;
const row = (label, value) =>
  `<dt>${escape(label)}</dt><dd>${escape(value)}</dd>`;

export function tokenBreakdown(tokens) {
  if (!tokens) return '<p class="panel-note">Token usage unavailable.</p>';
  return `<dl class="thread-details usage-numbers">${row("Input", count(tokens.input))}${row("Uncached input", count(Math.max(0, tokens.input - tokens.cache_read - tokens.cache_write)))}${row("Cache read · part of input", count(tokens.cache_read))}${row("Cache write · part of input", count(tokens.cache_write))}${row("Output · includes reasoning", count(tokens.output))}${row("Reasoning · part of output", count(tokens.reasoning))}${row("Total processed", count(tokens.input + tokens.output))}${row("Cache hit rate", tokens.input ? `${((100 * tokens.cache_read) / tokens.input).toFixed(1)}%` : "Unavailable")}</dl>`;
}

export function turnUsage(turn, index, open = false) {
  const m = turn.metrics;
  const quality = m?.usage_status || (turn.usage ? "partial" : "unavailable");
  const label =
    quality === "unavailable"
      ? "Usage unavailable"
      : `${count(turn.tokens)} tokens · ${quality}${m?.usage_estimated ? " · estimated" : ""}`;
  return `<details class="turn-usage" data-turn="usage-${index}" ${open ? "open" : ""}><summary>${escape(label)}${m?.cost_usd != null ? ` · ~${money(m.cost_usd)}` : ""}</summary>${quality !== "unavailable" ? tokenBreakdown(turn.usage) : ""}${m ? `<dl class="thread-details usage-numbers">${row("Estimated API cost", money(m.cost_usd))}${row("Cache-read savings", money(m.cache_savings_usd))}${row("Elapsed", duration(m.duration_ms))}${row("First token · text or thinking", duration(m.ttft_ms))}${row("First response text", duration(m.first_text_ms))}${row("Model calls", count(m.hops))}${row("Tools / failed", `${count(m.tool_calls)} / ${count(m.tool_errors)}`)}</dl>${contextMeter(m)}${m.reasoning_estimated ? '<p class="panel-note">The reasoning split is estimated; it does not increase the output total.</p>' : ""}` : ""}<p class="panel-note">${quality !== "complete" ? "Partial or missing reports can understate usage. " : ""}Costs use configured model rates, not an invoice. DeepSeek rates are an off-peak floor.</p></details>`;
}

export function contextMeter(m) {
  if (m?.context_tokens == null || !m.context_window) return "";
  return `<div class="usage-context"><label>Last reported prompt · ${count(m.context_tokens)} / ${count(m.context_window)} tokens</label><meter aria-label="Last reported prompt as a share of the model context window" min="0" max="${Number(m.context_window)}" value="${Number(m.context_tokens)}"></meter><p class="panel-note">${((100 * m.context_tokens) / m.context_window).toFixed(1)}% of context. This is the latest call’s input, not cumulative usage or a prediction of the next prompt.</p></div>`;
}

export function threadUsage(turns) {
  const observed = turns.filter((t) => t.usage);
  if (!observed.length) return "";
  const tokens = {
    input: 0,
    output: 0,
    reasoning: 0,
    cache_read: 0,
    cache_write: 0,
  };
  for (const t of observed)
    for (const key of Object.keys(tokens)) tokens[key] += t.usage[key] || 0;
  const priced = turns.filter((t) => t.metrics?.cost_usd != null);
  const cost = priced.reduce((sum, t) => sum + t.metrics.cost_usd, 0);
  return `${tokenBreakdown(tokens)}<p class="panel-note">Known estimated cost: ${money(cost)} · ${turns.length - priced.length} turns without pricing. ${turns.filter((t) => t.metrics?.usage_status !== "complete").length} turns have partial or unavailable usage.</p>${contextMeter(turns.at(-1)?.metrics)}`;
}

export function usagePanel(state, models, profiles) {
  const { data, error, loading, days, model, profile, budget } = state;
  const options = (items, selected) =>
    items
      .map(
        (item) =>
          `<option value="${escape(item.id)}" ${item.id === selected ? "selected" : ""}>${escape(item.label || item.id)}</option>`,
      )
      .join("");
  const header = `<div class="panel-intro"><h3>Model usage</h3><p>Chat usage across this runtime. History survives reloads and restarts; conversations stay temporary.</p></div><form id="usage-filters" class="usage-filters"><label>Period<select name="days">${[7, 30, 90, 365].map((n) => `<option value="${n}" ${days === n ? "selected" : ""}>Last ${n} days · UTC</option>`).join("")}</select></label><label>Model<select name="model"><option value="">All models</option>${options(models, model)}</select></label><label>Assistant<select name="profile"><option value="">All assistants</option>${options(profiles, profile)}</select></label><button type="submit" ${loading ? "disabled" : ""}>${loading ? "Loading…" : "Refresh usage"}</button></form>`;
  if (error)
    return `${header}<p role="alert" class="error-card">${escape(error)}</p>`;
  if (!data)
    return `${header}<p role="status" class="panel-note">Loading usage…</p>`;
  const t = data.totals;
  const groups = (title, items) =>
    `<h3 class="usage-heading">${title}</h3><div class="usage-table"><table><thead><tr><th scope="col">${title === "By day" ? "UTC day" : title.slice(3)}</th><th scope="col">Tokens</th><th scope="col">Known cost</th></tr></thead><tbody>${items.map((item) => `<tr><th scope="row">${escape(item.label)}</th><td>${count(item.tokens_total)}</td><td>${money(item.known_cost_usd)}${item.unpriced_turns || item.incomplete_turns ? " *" : ""}</td></tr>`).join("")}</tbody></table></div>`;
  const max = Math.max(1, ...data.days.map((day) => day.tokens_total));
  return `${header}<p class="panel-note">${escape(data.since)} – ${escape(data.until)} · UTC · chat calls only</p>${budget ? `<div class="usage-context"><label>Runtime budget today · ${count(budget.used)} / ${count(budget.limit)}</label><meter aria-label="Runtime token budget used today" min="0" max="${Number(budget.limit)}" value="${Number(budget.used)}"></meter><p class="panel-note">Includes outstanding reservations and other budgeted work; may exceed reported chat usage.</p></div>` : '<p class="panel-note">Runtime budget unavailable.</p>'}<div class="usage-cards"><div><span>Processed tokens</span><strong>${count(t.tokens_total)}</strong></div><div><span>Known API estimate</span><strong>${money(t.known_cost_usd)}</strong></div><div><span>Turns / sessions</span><strong>${count(t.turns)} / ${count(t.sessions)}</strong></div><div><span>Cache-read savings</span><strong>${money(t.cache_savings_usd)}</strong></div></div>${t.turns ? `${tokenBreakdown(t)}<dl class="thread-details usage-numbers">${row("Input cost · uncached", money(t.cost_input))}${row("Cache read / write cost", `${money(t.cost_cache_read)} / ${money(t.cost_cache_write)}`)}${row("Output cost · includes reasoning", money(t.cost_output))}${row("Average elapsed", duration(t.avg_duration_ms))}${row("Average first token", duration(t.avg_ttft_ms))}${row("Model calls / tools", `${count(t.hops)} / ${count(t.tool_calls)}`)}${row("Failed turns / tools", `${count(t.failed_turns)} / ${count(t.tool_errors)}`)}</dl><p class="panel-note">${count(t.unpriced_turns)} turns without pricing · ${count(t.incomplete_turns)} partial/unavailable · ${count(t.estimated_turns)} estimated token reports · ${count(t.reasoning_estimated_turns)} estimated reasoning splits. * Incomplete costs exclude unknown usage. Cache savings exclude write premiums.</p><div class="usage-chart" role="img" aria-label="Daily processed tokens; exact values in the By day table">${data.days.map((day) => `<span style="height:${Math.max(2, (100 * day.tokens_total) / max)}%" title="${escape(day.label)}: ${count(day.tokens_total)} tokens"></span>`).join("")}</div>${groups("By day", data.days)}${groups("By model", data.models)}${groups("By provider", data.providers)}${groups("By assistant", data.profiles)}` : '<p class="panel-note">No recorded chat usage in this period. New requests will appear here.</p>'}<p class="panel-note">Estimated USD from configured rates, not provider invoices. DeepSeek uses off-peak rates. History starts when tracking is installed; evals, embedding, reranking and paid tool fees are excluded.</p>`;
}
