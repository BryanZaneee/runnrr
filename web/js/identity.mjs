// Use the full collection so filtering never changes an identity's color.
export function identityBadge(item, items, kind = "agent") {
  const index = Math.max(
    0,
    items.findIndex((entry) => entry.id === item?.id),
  );
  const hue = (index * 137.508 + (kind === "agent" ? 215 : 15)) % 360;
  const initials = (item?.name || item?.label || "R")
    .slice(0, 2)
    .toUpperCase()
    .replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
  const person =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><circle cx="12" cy="8" r="3.5"/><path stroke-linecap="round" d="M5 20v-2a7 7 0 0 1 14 0v2"/></svg>';
  return `<span class="avatar identity-badge ${kind}-badge" style="--identity-hue:${hue}" aria-hidden="true">${kind === "agent" ? person : initials}</span>`;
}
