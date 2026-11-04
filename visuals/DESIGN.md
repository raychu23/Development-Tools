---
version: alpha
name: raymond-dev-tools
description: One design language for README visuals, doc pages and dashboards. Colors = GitHub Primer primitives (semantic names, light + dark), so visuals match the page they sit on.
source: primer/primitives functional/themes light.css + dark.css (checked 2026-11-04) · research: 4 log/research-design-language.md
colors:
  canvas:     { light: "#ffffff", dark: "#0d1117" }
  surface:    { light: "#f6f8fa", dark: "#161b22" }
  border:     { light: "#d0d7de", dark: "#30363d" }
  text:       { light: "#1f2328", dark: "#e6edf3" }
  text-muted: { light: "#59636e", dark: "#8b949e" }
  accent:     { light: "#0969da", dark: "#2f81f7" }
  success:    { light: "#1a7f37", dark: "#3fb950" }
  danger:     { light: "#cf222e", dark: "#f85149" }
  attention:  { light: "#9a6700", dark: "#d29922" }
typography:
  font-ui: "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans', Helvetica, Arial, sans-serif"   # GitHub's own stack
  font-mono: "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, monospace"                     # names of real things: commands, files
  scale: { xs: 12px, sm: 14px, base: 16px, lg: 20px, xl: 24px, h1: 32px }
spacing: { xs: 4px, sm: 8px, md: 16px, lg: 24px, xl: 32px }
rounded: { sm: 4px, md: 6px, lg: 12px }
line: { width: 1.5px, default: solid, secondary: dashed }
---

## Rules for every visual

1. Write the one question it answers before drawing. No question, no visual.
2. Grouping does the work. Use arrows only for the main direction of travel, and read in one direction.
3. Every word names a real thing: a command, file, number or skill. Grep the repo for it first.
4. Use color for meaning only: accent = the main path, success = done, danger = refused/blocked, attention = runs on its own.
5. Ship light + dark, wrapped in `<picture>`, with alt text written as a full sentence that explains the image.
6. Before showing anyone, take zoomed screenshots in light AND dark. No text may touch a line or border.
