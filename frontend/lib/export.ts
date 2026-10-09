/**
 * Export a thread as Markdown: questions, answers with readable citations, chart data as tables,
 * and a source list per answer. Handy for sharing findings or pasting into notes.
 */

import type { Message } from "@/components/chat/chat-provider";
import type { Citation } from "@/lib/sse";

function cite(c: Citation | undefined): string {
  if (!c) return "";
  return c.kind === "web" ? ` ([${c.site}](${c.url}))` : ` (p. ${c.page}, ${c.filename})`;
}

export function threadToMarkdown(title: string, messages: Message[]): string {
  const lines = [`# ${title}`, "", `_Exported from FilingLens on ${new Date().toLocaleString()}_`, ""];
  for (const m of messages) {
    if (m.role === "user") {
      lines.push(`## ${m.content}`, "");
      continue;
    }
    if (m.status !== "done") continue;
    const byLabel = new Map((m.citations ?? []).map((c) => [c.label, c]));
    lines.push(m.content.replace(/\[([CW]\d+)\]/g, (_, label: string) => cite(byLabel.get(label))), "");
    if (m.chart) {
      const ch = m.chart;
      lines.push(`**${ch.title}**${ch.unit ? ` (${ch.unit})` : ""}`, "");
      const xs = [...new Set(ch.series.flatMap((s) => s.points.map((p) => p.x)))];
      lines.push(`| Period | ${ch.series.map((s) => s.name).join(" | ")} |`, `|---|${ch.series.map(() => "---:").join("|")}|`);
      for (const x of xs) {
        lines.push(`| ${x} | ${ch.series.map((s) => s.points.find((p) => p.x === x)?.y.toLocaleString() ?? "–").join(" | ")} |`);
      }
      lines.push("");
    }
    if (m.meta?.key_terms?.length) {
      lines.push("**Key terms** (general definitions):", "");
      for (const t of m.meta.key_terms) lines.push(`- **${t.term}**: ${t.definition}`);
      lines.push("");
    }
    const sources = [...new Map((m.citations ?? []).map((c) => [c.kind === "web" ? c.url : `${c.doc_id}:${c.page}`, c])).values()];
    if (sources.length) {
      lines.push("Sources:", ...sources.map((c) => `- ${c.kind === "web" ? `${c.title || c.site}: ${c.url}` : `${c.filename}, page ${c.page}`}`), "");
    }
  }
  return lines.join("\n");
}

export function downloadText(filename: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/markdown;charset=utf-8" }));
  const a = Object.assign(document.createElement("a"), { href: url, download: filename });
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
