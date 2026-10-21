import { marked } from "./vendor/marked.mjs";
import DOMPurify from "./vendor/purify.mjs";
import { safeUrl } from "./chat.mjs";

const blocks = new WeakMap();

export function renderTextBlock(block) {
  const cached = blocks.get(block);
  if (cached?.text === block.text) return cached.html;
  const html = markdown(block.text);
  blocks.set(block, { text: block.text, html });
  return html;
}

function markdown(text) {
  const clean = DOMPurify.sanitize(marked.parse(text, { breaks: true }), {
    ALLOWED_TAGS: [
      "p",
      "br",
      "strong",
      "em",
      "del",
      "a",
      "code",
      "pre",
      "blockquote",
      "ul",
      "ol",
      "li",
      "h1",
      "h2",
      "h3",
      "h4",
      "hr",
      "table",
      "thead",
      "tbody",
      "tr",
      "th",
      "td",
    ],
    ALLOWED_ATTR: ["href", "title", "start"],
  });
  const template = document.createElement("template");
  template.innerHTML = clean;
  for (const a of template.content.querySelectorAll("a")) {
    const url = safeUrl(a.getAttribute("href"));
    if (!url) a.removeAttribute("href");
    else {
      a.href = url;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
    }
  }
  return template.innerHTML;
}
