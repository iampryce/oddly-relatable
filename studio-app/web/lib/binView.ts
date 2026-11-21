// Bin page helpers: readable sizes and the confirm text that lists exactly what "Delete forever" removes.
export function formatBytes(n: number | null | undefined): string {
  const b = n || 0;
  if (b < 1024) return `${b} B`;
  const u = ['KB', 'MB', 'GB', 'TB'];
  let x = b / 1024, i = 0;
  while (x >= 1024 && i < u.length - 1) { x /= 1024; i++; }
  return `${x.toFixed(x < 10 ? 1 : 0)} ${u[i]}`;
}

export function foreverText(items: {label: string; size_bytes: number}[], total: number): string {
  const list = items.slice(0, 30).map(i => `• ${i.label} (${formatBytes(i.size_bytes)})`).join('\n') + (items.length > 30 ? `\n… and ${items.length - 30} more` : '');
  return `Delete forever ${items.length} item(s)? Their database records and files are removed and ${formatBytes(total)} is freed. This cannot be undone.\n\n${list}`;
}
