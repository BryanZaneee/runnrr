// Wire handling is separate from rendering so a stream always updates its own chat.
export async function readEvents(body, receive) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  function drain() {
    let match;
    while ((match = /\r?\n\r?\n/.exec(buffer))) {
      const frame = buffer.slice(0, match.index);
      buffer = buffer.slice(match.index + match[0].length);
      let event = "message";
      const data = [];
      for (const line of frame.split(/\r?\n/)) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        if (line.startsWith("data:"))
          data.push(line.slice(5).replace(/^ /, ""));
      }
      if (data.length) receive(event, JSON.parse(data.join("\n")));
    }
  }
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      drain();
    }
    buffer += decoder.decode();
    drain();
    if (buffer.trim())
      throw new Error("The connection ended before the response was complete.");
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

export function applyEvent(turn, event, data) {
  turn.revision = (turn.revision || 0) + 1;
  if (event === "delta") {
    let block = turn.blocks.at(-1);
    if (block?.kind !== "text") {
      block = { kind: "text", text: "" };
      turn.blocks.push(block);
    }
    block.text += data.text || "";
    turn.thinking = false;
  } else if (event === "thinking_delta") {
    // Provider reasoning is not transcript content; show activity only.
    turn.thinking = true;
  } else if (event === "tool_use_start") {
    turn.thinking = false;
    turn.blocks.push({
      kind: "tool",
      name: data.name,
      status: "running",
      sources: [],
    });
  } else if (event === "tool_result") {
    let block = turn.blocks.find(
      (b) =>
        b.kind === "tool" && b.name === data.name && b.status === "running",
    );
    if (!block) {
      block = { kind: "tool", name: data.name };
      turn.blocks.push(block);
    }
    Object.assign(block, {
      status: data.is_error ? "error" : "done",
      summary: data.source_summary,
      sources: data.source_items || [],
      duration: data.duration_ms,
    });
  } else if (event === "usage") {
    turn.estimated ||= Boolean(data.estimated);
    turn.usage ||= {
      input: 0,
      output: 0,
      reasoning: 0,
      cache_read: 0,
      cache_write: 0,
    };
    for (const [key, wire] of Object.entries({
      input: "input_tokens",
      output: "output_tokens",
      reasoning: "reasoning_tokens",
      cache_read: "cache_read_input_tokens",
      cache_write: "cache_creation_input_tokens",
    })) {
      turn.usage[key] += Number(data[wire] || 0);
    }
    for (const key of ["input_tokens", "output_tokens"]) {
      turn.tokens += Number(data[key] || 0);
    }
  } else if (event === "metrics") {
    turn.metrics = data;
    turn.usage = data.tokens;
    turn.tokens = data.tokens_total;
    turn.estimated = Boolean(data.usage_estimated);
  } else if (event === "error") {
    turn.error = data.message || "The agent could not finish this request.";
    turn.finished = true;
    turn.thinking = false;
    for (const b of turn.blocks)
      if (b.kind === "tool" && b.status === "running") b.status = "interrupted";
  } else if (event === "done") {
    if (data.stop_reason === "max_tokens") {
      turn.error =
        "The response reached the model’s output limit and is incomplete.";
      for (const b of turn.blocks)
        if (b.kind === "tool" && b.status === "running")
          b.status = "interrupted";
    }
    turn.finished = true;
    turn.thinking = false;
  }
}

export function safeUrl(value) {
  try {
    const url = new URL(value);
    return ["https:", "http:"].includes(url.protocol) ? url.href : null;
  } catch {
    return null;
  }
}
