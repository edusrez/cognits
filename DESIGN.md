---
name: Cognits
description: >
  Dark-first, TUI-inspired AI tutoring interface. Monochrome grays, bordered
  squares, no chromatic accent. Tool status uses empty-square to filled-square
  pattern borrowed from the Textual TUI SPINNER array.
colors:
  # Surface ladder (dark to light, 5 steps)
  canvas: "#000000"
  surface-0: "#0d0d0d"
  surface-1: "#111111"
  surface-2: "#1a1a1a"
  surface-3: "#333333"
  # Border ladder (blurred to accent)
  border-blurred: "#333333"
  border: "#555555"
  border-accent: "#888888"
  # Text hierarchy (ink is always #e0e0e0 in the web UI)
  ink: "#e0e0e0"
  ink-muted: "#9a9a9a"
  ink-subtle: "#6a6a6a"
  ink-faint: "#5a5a5a"
  # Functional (monochrome-compatible — only non-gray colors)
  error: "#e74c3c"
  error-soft: "#f87171"
  warning: "#f0c040"
  # Fill = TUI foreground, used for completed/filled indicator states
  fill: "#cccccc"
typography:
  family-sans: >
    "Inter", "Inter Variable", ui-sans-serif, system-ui, -apple-system,
    BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial,
    "Noto Sans", sans-serif
  family-mono: >
    ui-monospace, "SF Mono", "Cascadia Code", "Source Code Pro",
    "Fira Code", "JetBrains Mono", Menlo, Consolas,
    "DejaVu Sans Mono", monospace
  sizes:
    metadata: 10px
    tab-label: 11px
    caption: 11px
    body: 13px
    body-sm: 12px   # text-xs
    body-base: 14px # text-sm
    heading-sm: 16px
    heading: 18px
    heading-lg: 20px
rounded:
  none: 0
  subtle: 4px     # Tailwind `rounded` / 0.25rem — DragOverlay, skill nodes
  full: 9999px    # Only used for mastery-badge dots
motion:
  duration-fast: 100ms
  duration-normal: 200ms
  duration-slow: 300ms
  ease-out: cubic-bezier(0, 0, 0.2, 1)
  ease-in-out: cubic-bezier(0.4, 0, 0.2, 1)
components:
  tool-status-indicator:
    size: 8px
    idle: { frame: "#555555", fill: "transparent" }
    running: { frame: "#555555", fill: "#0d0d0d", note: "empty square (U+25A1)" }
    success: { frame: "#555555", fill: "#cccccc", note: "filled square (U+25A0)" }
    error: { frame: "#e74c3c", fill: "#0d0d0d", note: "red frame, empty" }
---

# Cognits — frontend visual design language

## 1. Visual theme & philosophy

Cognits is a **TUI-inspired, dark-first** AI tutoring interface. It takes its
visual identity from the Textual TUI in `src/cognits/tui.py` — a terminal-native
aesthetic built around bordered panels, gray square indicators, and a strict
monochrome grayscale palette.

**Core tenets:**

- **Dark-first.** There is no light mode. The canvas is pure black (`#000000`).
  Every surface is a step on a gray ladder from `#0d0d0d` to `#333333`.
  Shadows are never used for elevation — depth is communicated through
  background-color contrast and hairline borders (the "Linear.app" approach).

- **Monochrome only.** The only non-gray colors are functional:
  - Red (`#e74c3c` / `#f87171`) for errors and delete actions.
  - Amber (`#f0c040`) for warnings (file truncation notices, stale status).
  **Do not introduce blue, green, or any chromatic accent.** The chat pulse
  dot (blue) and the skill-tree selected border (blue-gray) are being removed
  in parallel tasks. The design is monochrome.

- **Bordered squares as status indicators.** Tool/progress status follows the
  pattern established by the TUI `SPINNER` array (tui.py:29-42): an empty
  white square (`U+25A1`) transitions to a filled black square (`U+25A0`).
  In the web UI this is rendered as a bordered square whose interior fill
  transitions from transparent (`#0d0d0d`) to filled (`#cccccc`).

- **Information-dense, terminal-native feel.** High data density, hairline
  borders (`1px`), minimal chrome, compact spacing. The UI assumes a
  keyboard-and-mouse desktop context.

- **No spinners, no pulse animations for status.** The only animation for
  tool status is the square-fill transition. The `animate-pulse` usage on
  the loading bar (`App.tsx:183`) is a boot-phase placeholder and is not
  part of the steady-state design language.

## 2. Color palette

### Surface ladder

| Token | Hex | Usage |
|---|---|---|
| `canvas` | `#000000` | Root body background (`bg-black`) |
| `surface-0` | `#0d0d0d` | TUI background, image viewer area |
| `surface-1` | `#111111` | TUI panel surface, secondary surfaces |
| `surface-2` | `#1a1a1a` | Dropdown menus, context menus, note panes, toggle-active bg |
| `surface-3` | `#333333` | Skill-tree selected node background |

### Border ladder

| Token | Hex | Usage |
|---|---|---|
| `border-blurred` | `#333333` | Blurred/unfocused TUI border |
| `border` | `#555555` | Default TUI border (`border: solid #555`) |
| `border-accent` | `#888888` | Skill-tree selected node border, slider thumb border |

The web UI also uses opacity-based border variants on a white base for finer
granularity:

- `border-white/5` — hairline separators (metadata bars)
- `border-white/10` — tab borders, code block separators
- `border-white/15` — context progress bar border
- `border-white/20` — **default input/button/card border** (most common)
- `border-white/30` — checkbox border

These are equivalent to `rgba(255,255,255,0.05)` through `rgba(255,255,255,0.30)`.

### Text hierarchy

| Token | Hex | Usage |
|---|---|---|
| `ink` | `#e0e0e0` | Primary text, headings, inline code, code titles |
| `ink-muted` | `#9a9a9a` | Labels, secondary info, collapsed section headers |
| `ink-subtle` | `#6a6a6a` | Metadata, footnote text, disabled-inactive labels |
| `ink-faint` | `#5a5a5a` | Thinking/reasoning blocks, code comments (italic), tab agent status |

Also in use:
- `#c0c0c0` — Setup wizard body text (brightness between ink and ink-muted)
- `#8b949e` — Loading placeholders, code strings/symbols
- `#4a4a4a` — Disabled dropdown options (`cursor-not-allowed`)

### Functional colors

| Token | Hex | Usage |
|---|---|---|
| `error` | `#e74c3c` | Error messages, error borders, delete actions |
| `error-soft` | `#f87171` | Error backgrounds (`bg-red-500/10`), code keywords `hljs-keyword` |
| `warning` | `#f0c040` | File-truncation warnings, code-view notice bars |

### TUI palette mapping

The Textual TUI (`COGNITS_THEME` in `tui.py:48-67`) defines the canonical
terminal palette:

```
background  #0D0D0D  →  surface-0
surface     #111111  →  surface-1
panel       #1A1A1A  →  surface-2
primary     #666666  →  (accent-adjacent, used sparingly)
secondary   #444444  →  (mid-gray, between surface-3 and border)
accent      #888888  →  border-accent
foreground  #CCCCCC  →  fill / completed indicator
border      #555555  →  border
border-blurred #333333 →  border-blurred
```

### Code syntax highlighting (highlight-theme.css)

The code highlighting palette is also monochrome + functional red:

| Role | Color |
|---|---|
| Base text, titles | `#e0e0e0` |
| Comments, emphasis | `#5a5a5a` (italic) |
| Attributes, params, variables | `#9a9a9a` |
| Numbers, booleans, meta | `#6a6a6a` |
| Strings, symbols, additions | `#8b949e` |
| Keywords, deletions | `#f87171` |

## 3. Typography

### Font families

**Sans-serif** (chat markdown body, UI labels, buttons):
```
"Inter", "Inter Variable", ui-sans-serif, system-ui,
-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
"Helvetica Neue", Arial, "Noto Sans", sans-serif
```

**Monospace** (code blocks, inline code, token-cost display):
```
ui-monospace, "SF Mono", "Cascadia Code", "Source Code Pro",
"Fira Code", "JetBrains Mono", Menlo, Consolas,
"DejaVu Sans Mono", monospace
```

The TUI uses Textual's default terminal fonts (not configurable).

### Size hierarchy

| Token | px | Tailwind | Usage |
|---|---|---|---|
| metadata | 10 | `text-[10px]` | Image dimension labels, file info bar, tab agent-status row |
| tab-label | 11 | `text-[11px]` | Tab bar labels, report metadata |
| caption | 11 | `text-[11px]` | Slider min/max labels, report dates |
| body | 13 | `text-[13px]` | **Default body text** — buttons, inputs, session items, file tree |
| body-sm | 12 | `text-xs` | Setup wizard description text |
| body-base | 14 | `text-sm` | Setup wizard body, skill tree |
| h5 | 16 | `text-base` / `1em` | Chat markdown H5 |
| h4 | ~18 | `1.1em` | Chat markdown H4 |
| h3 | 20 | `text-lg` / `1.25em` | Skill tree heading, study plan heading |
| h2 | 24 | `1.5em` | Chat markdown H2, mastery dashboard heading |
| h1 | 32 | `2em` | Chat markdown H1 |

Chat font size is user-configurable from 11 px to 24 px (default ~14 px) via
Shift+scroll or a slider in Settings.

Code blocks render at `0.9em` (relative to the configurable chat font size).
Thinking/reasoning blocks render at `0.9em` in `#5a5a5a`.

## 4. Spacing & layout

### Base unit

The app uses Tailwind's default spacing scale: `0.25rem` increments (4px base).
The predominant spacing values are:

| Spacing | Rem | px | Typical usage |
|---|---|---|---|
| `gap-0.5` | `0.125rem` | 2 | Tool status list items |
| `gap-1` | `0.25rem` | 4 | Tab content, icon groups, file viewer header |
| `gap-1.5` | `0.375rem` | 6 | Tool status rows, button+label groups |
| `gap-2` | `0.5rem` | 8 | Session list, notebook items, setting sections |
| `gap-3` | `0.75rem` | 12 | Settings panel, report search layout |
| `gap-4` | `1rem` | 16 | Setup wizard step sections |
| `p-2` | `0.5rem` | 8 | Sessions sidebar, image viewer padding |
| `p-3` | `0.75rem` | 12 | Settings, report search, chat scroll area |
| `p-4` | `1rem` | 16 | Skills tree, study plan, mastery dashboard |
| `px-2` | `0.5rem` | 8 | Inputs, dropdowns |
| `px-3` | `0.75rem` | 12 | Buttons, cards, session items |
| `px-4` | `1rem` | 16 | Note view, file view padding |
| `py-1` | `0.25rem` | 4 | Slider fields, tab items |
| `py-1.5` | `0.375rem` | 6 | Buttons, inputs, session items (standard) |
| `py-2` | `0.5rem` | 8 | Chat message padding |
| `py-3` | `0.75rem` | 12 | Chat message padding, code view |

### Layout structure

The app uses a **viewport/tab system** (`Viewport.tsx`). Each viewport is a
container with a tab bar (28px height) and a content area. Viewports are
tiled dynamically via the desktop store (resizable, movable).

Chat input (`Write.tsx`) sits in a dedicated viewport below the chat
messages viewport. The chat area (`Chat.tsx`) scrolls independently with
`overflow-anchor` for auto-scroll.

Session sidebar (`Sessions.tsx`) and notebook/report search
(`LearnitView.tsx`) use list-based layouts with drag-reorder support via
`list-drag-ghost` and `list-drag-dimmed` CSS classes.

## 5. Shapes & borders

### Border radius

The app is **predominantly sharp-cornered** (0px radius) — buttons, inputs,
dropdowns, panels, tabs, and chat messages all have square corners.

Border radius (`rounded` = `4px`) is used only in:

- **Drag overlay labels** (`DragOverlay.tsx`): `rounded` class
- **Skill tree node items** (`SkillsTree.tsx`): `rounded` class
- **Mastery dashboard stat cards** (`MasteryDashboard.tsx`): `rounded` class
- **Mastery badges** (`SkillsTree.tsx:50`): `rounded-full` (only for dots)

### Border widths

All visible borders are `1px` (hairline). The app never uses `border-2`
or thicker. Border colors use the opacity-based system
(`border-white/{5,10,15,20,30}`) or solid hex values (`border-[#555]`,
`border-[#888]`, `border-[#3a3a3a]`).

The TUI uses `border: solid #555` for its main panel border
(tui.py line 80).

### The bordered-panel aesthetic

Following the TUI, many components follow the pattern:
```
border border-white/20 bg-transparent
```
This creates a hairline-bordered rectangle on the dark canvas, with no fill.
Active/toggled states fill with `bg-white/10`, and hover adds `hover:bg-white/5`.

## 6. Elevation & depth

**No shadows for elevation.** Depth is communicated exclusively through
background-color contrast (the surface ladder in section 2) and border
visibility. This follows the same approach as Linear.app.

The **only exceptions** are:

- **Context menus** (`ContextMenu.tsx`): `shadow-lg` on the dropdown overlay
  to separate it from the panel stack.
- **Dropdown menus** (`Dropdown.tsx`): `shadow-lg` on the option list.
- **PDF viewer toolbar** (`PdfView.tsx:194`): `shadow-lg` on the floating
  toolbar button.

### Focus ring

Global keyboard focus uses:
```css
:not(input):not(textarea):focus-visible {
  outline: 2px solid rgba(255, 255, 255, 0.25);
  outline-offset: 1px;
}
```
Input elements use `focus:border-white/40` instead of outline.

### Active keyboard selection

Viewport keyboard navigation uses:
```css
box-shadow: inset 0 0 0 2px rgba(255, 255, 255, 0.25);
background: #1a1a1a;
```

### Dimming

`filter: brightness(0.5)` is used for dimmed tabs and drag targets.
`filter: brightness(0.35)` is used for dimmed content areas.
`opacity: 0.4` is used for drag ghosts and disabled items.

## 7. Components

### 7.1 Tool status indicator

This is the signature component of the Cognits design language. It is a
**bordered square** whose interior fill communicates state, directly
translated from the TUI `SPINNER` array pattern (tui.py:29-42).

**States:**

| State | Frame | Fill | Unicode | CSS pattern |
|---|---|---|---|---|
| Idle | `#555` | transparent (inherits surface) | (not shown) | Not rendered; tool entry does not exist |
| Running | `#555` | `#0d0d0d` (surface-0) | `U+25A1` (empty square) | `border border-[#555] bg-[#0d0d0d]` |
| Success | `#555` | `#cccccc` (fill) | `U+25A0` (filled square) | `border border-[#555] bg-[#cccccc]` |
| Error | `#e74c3c` | `#0d0d0d` (surface-0) | `U+25A0` with red frame | `border border-[#e74c3c] bg-[#0d0d0d]` |

**Size:** 8px (`w-2 h-2` in Tailwind, which equals `8px` at 16px base).

**Transition:** `running -> success` fills the interior from `#0d0d0d` to
`#cccccc` over `200ms ease-out`. `running -> error` changes the frame color
from `#555` to `#e74c3c` over `100ms`.

**State transition rules:**
- `running` when the agent's status string does not end with `...`
  (the `...` suffix is the TUI convention for "in progress").
- `success` when the status no longer ends with `...` and does not contain
  "error" or "fail".
- `error` when status contains "error" or "fail".

**Do NOT use:**
- Pulse animations (`animate-pulse`) for tool status.
- Spinners, rotating icons, or gradient loading bars.
- Blue dots (the current `bg-blue-400 animate-pulse` in `Chat.tsx:163`
  is being removed).

**TUI equivalent:**
The TUI `SPINNER` (tui.py:29-42) animates a filled square (`U+25A0`) moving
across a line of empty squares (`U+25A1`). The web UI collapses this into a
static indicator per agent: the fill-versus-empty binary maps to the
running/success binary.

### 7.2 Chat messages

**User messages:** Right-aligned, bordered card:
```
border border-white/20 px-3 py-1.5 bg-white/5 max-w-[85%]
```

**Agent messages (maestro):** Full-width, no border:
```
py-1 w-full
```
Content rendered via `StreamingMessage` component using `streaming-markdown`
parser with `chat-markdown` CSS class.

**Streaming animation:**
During streaming, the `.chat-markdown.streaming` class applies
`flow-fade-in 0.3s ease-out` to each new block element.

**Tool status area (below messages):**
When tools are active, rendered in `#5a5a5a italic` with `font-size: 80%`.
The collapsible header shows a `U+25B8` (right-pointing) / `U+25BE`
(down-pointing) triangle toggle.

**Report attachments:**
Bordered clickable card with title and "Read full" link.

**Error messages:**
Red-bordered box:
```
border border-red-500/40 bg-red-500/10 text-red-300
```

### 7.3 Skill tree nodes

**Default state:**
```
border border-gray-700 hover:border-gray-500 text-xs rounded
```

**Selected state:**
```
border-[#888] bg-[#333]
```
(monochrome, **not** blue — the `border-blue-400` that existed in
`SkillsTree.tsx` is being removed).

**Mastery badges:**
```
inline-block w-2.5 h-2.5 rounded-full
```
Colored by mastery level (grayscale intensity).

### 7.4 Buttons & interactive elements

**Default button:**
```
border border-white/20 px-3 py-1.5 text-[13px] transition-colors cursor-pointer
```

**States:**
- Hover: `hover:bg-white/5` (subtle) or `hover:bg-white/10` (stronger)
- Active/toggled-on: `bg-white/10 text-[#e0e0e0]`
- Inactive/toggled-off: `hover:bg-white/5 text-[#6a6a6a]`
- Disabled: `opacity-40 cursor-not-allowed` or `opacity-30`

**Text-only interactive:**
- `hover:text-[#e0e0e0]` — for icon buttons, close buttons, tool labels
- `hover:text-[#9a9a9a] transition-colors` — collapsed section headers

### 7.5 Inputs & forms

**Text input:**
```
bg-transparent border border-white/20 px-2 py-1 text-[13px]
text-[#e0e0e0] outline-hidden focus:border-white/40
```

**Textarea:**
Same as input, plus `resize-none` (most) or `resize` (settings).
Note title inputs are single-line with `overflow-hidden`.

**Dropdown:**
Wraps the trigger button + `shadow-lg` option list
(`bg-[#1a1a1a] border border-white/20`).

**Slider:**
Custom styled with a `#666` thumb (`1px solid #888` border, square corners)
on a `rgba(255,255,255,0.15)` track. Disabled: `#3a3a3a` / `#4a4a4a`.

**Font slider (chat):**
12px square thumb, 4px-height track, no border radius on thumb.

### 7.6 Navigation

**Session sidebar** (`Sessions.tsx`):
List of bordered cards (`border border-white/20 px-3 py-1.5 text-[13px]`).
Active session has `bg-white/10`. Drag-reorderable with ghost state.

**Tab bar** (`TabBar.tsx`):
28px height, tabs as bordered cells (`border border-white/10 text-[11px]`).
Active tab: `text-[#e0e0e0]`. Inactive tabs: `text-[#6a6a6a]`.
Status row below the label in `text-[10px] text-[#5a5a5a]`.
Token-progress bar: `h-1.5 border border-white/15` with
`bg-white/20 transition-[width] duration-300`.

**Context menus** (`ContextMenu.tsx`):
```
fixed z-50 bg-[#1a1a1a] border border-white/20 shadow-lg min-w-[90px]
```
Submenu indicator: `U+203A` (single right-pointing angle quotation mark)
in `#5a5a5a`.

## 8. Motion & animation

### Motion tokens

| Token | Value | Usage |
|---|---|---|
| `duration-fast` | `100ms` | Hover transitions (`transition-colors`), resizer hover, viewport keyboard focus |
| `duration-normal` | `200ms` | Fade-in animation (`animate-fade-in`), tool-status fill transition, dropdown appearance |
| `duration-slow` | `300ms` | Tab progress-bar width, flow-fade-in for streaming blocks, viewport linking |
| `ease-out` | `cubic-bezier(0, 0, 0.2, 1)` | Fade-in, flow-fade-in, viewport keyboard transition |
| `ease-in-out` | `cubic-bezier(0.4, 0, 0.2, 1)` | Resizer background transition |

### RAF-batched token streaming

Streaming text renders at the display's native refresh rate via
`requestAnimationFrame`-batched token draining (`chat-store.ts:46-60`).
The drain function calculates a target of **~1200 characters/second**
(`targetCharsPerMs = 1.2`) based on `performance.now()` delta-time between
frames. On tool boundaries, `flushAll()` immediately renders the entire
pending buffer (no accumulated delay).

**Design intent:** This provides smooth, hardware-aligned rendering without
the jank of per-token DOM updates. The rate limit prevents the display from
overwhelming the user while keeping latency imperceptible.

### Animation reference

| Animation | Element | Duration | Easing | Trigger |
|---|---|---|---|---|
| `fade-in` | Favicon images, menu items | 200ms | ease-out | Mount |
| `flow-fade-in` | Streaming markdown blocks | 300ms | ease-out | New block during streaming |
| `dots` (keyframe) | Tool status text (`...`) | 1.2s | steps(3) | `status.endsWith("...")` |
| Tool-status fill | Status indicator square | 200ms | ease-out | State transition `running -> success` |
| Hover background | Buttons, menu items | 100ms | — | `:hover` |
| Progress bar width | Tab bar token gauge | 300ms | — | Token count changes |

### `prefers-reduced-motion`

The app honors `prefers-reduced-motion: reduce` by rendering all animations
with `0ms` duration, effectively snap-rendering. Implementations use
`@media (prefers-reduced-motion: reduce)` to override `animation-duration`
and `transition-duration` to `0s`.

**Explicit rule:** Do not use `animate-pulse`, `animate-spin`, or gradient
loading bars for any status indicator. The fill transition is the only
status indicator.

## 9. Iconography

**Unicode-based** wherever possible, matching the TUI:

| Glyph | Unicode | Usage |
|---|---|---|
| `U+25A0` | `■` | Filled square (success indicator) |
| `U+25A1` | `□` | Empty square (running indicator) |
| `U+25B8` | `▸` | Collapsed tool section toggle |
| `U+25BE` | `▾` | Expanded tool section toggle |
| `U+203A` | `›` | Context menu submenu indicator |
| `U+00D7` | `×` | Tab close button |
| `U+2193` | `↓` | Scroll-to-bottom button |

**Favicons:** DuckDuckGo domain icons are fetched for researched sites
and displayed at 14px (`w-3.5 h-3.5`) with `animate-fade-in`.

**File/folder icons** (`FileTree.tsx`): Rendered in `#6a6a6a` at 14px width.
Node names in `#e0e0e0`.

## 10. Do's and don'ts

### Do

- **Do** use the bordered-square + fill pattern for ALL tool/execution status
  indicators.
- **Do** keep the aesthetic TUI-inspired: gray frames (`#555`), dark interiors
  (`#0d0d0d`), monochrome fill (`#cccccc`).
- **Do** use hairline borders (`border-white/20`) and surface-ladder
  backgrounds (`bg-[#1a1a1a]`) for depth instead of shadows.
- **Do** use `transition-colors` on interactive elements for a cohesive
  100ms hover response.
- **Do** honor `prefers-reduced-motion` by setting
  `animation-duration: 0s !important` and `transition-duration: 0s !important`.

### Don't

- **Don't** introduce pulse animations (`animate-pulse`), spinners
  (`animate-spin`), or gradient loading bars for tool status. The fill
  transition is the only status indicator.
- **Don't** introduce blue (`bg-blue-*`, `text-blue-*`, `border-blue-*`),
  green-as-accent, or any chromatic accent. The design is monochrome.
  The only non-gray colors are functional red and amber.
- **Don't** create light-mode variants or CSS media queries for `prefers-color-scheme: light`.
  The app is dark-first and no light mode will exist.
- **Don't** use shadows (`shadow-*`) for elevation except on context menus
  and dropdowns, where `shadow-lg` is the approved exception.
- **Don't** use `border-2` or thicker borders — all borders are `1px`.
- **Don't** use rounded corners (`rounded-*`) for buttons, inputs, or panels
  — the app is predominantly sharp-cornered (`rounded-none`).

## 11. Responsive behavior

Cognits is a **desktop-first** application. It does not target mobile
viewports. The minimum supported width is ~900px.

**Sidebar collapse:** The sessions sidebar can be hidden via the UI (toggle
button). When collapsed, the chat area expands to fill the width.

**Viewport/tab system:** Multiple viewports can be stacked horizontally or
vertically. Each viewport has a tab bar that can hold multiple content tabs
(chat, settings, skills, reports, notes, files, etc.). Tabs are draggable
between viewports.

**No touch-optimized targets exist.** The UI assumes mouse and keyboard
interaction.

## 12. Iteration guide

### Adding a new component

1. **Check this document first.** Read the existing component patterns in
   section 7. Find the closest analog (e.g., a new list-based view follows
   the session/notebook pattern: `border border-white/20 px-3 py-1.5 text-[13px]`).

2. **Use existing tokens.** Never introduce new hex values. All colors must
   come from the palette in section 2. All spacing must use the Tailwind
   scale documented in section 4. All border radii must be `0` or `rounded`
   (4px).

3. **No new colors.** If you need a color that doesn't exist in the palette,
   discuss with the team — do not add it unilaterally.

4. **Respect the monochrome rule.** The only non-gray colors are functional
   red (`#e74c3c`, `#f87171`) and warning amber (`#f0c040`).

### Adding a new state to a component

1. **Extend the component's state table** in the YAML frontmatter of this
   document under the `components:` key.

2. **Follow the existing pattern.** For tool status: add the new state with
   `frame`, `fill`, and `note` fields. For buttons: add the new state
   with `bg`, `border`, and `text` fields.

### Validation

Validate this document with:
```bash
npx @google/design.md lint DESIGN.md
```

Validate the YAML frontmatter:
```bash
python3 -c "import yaml; doc = open('DESIGN.md').read().split('---'); print(yaml.safe_load(doc[1]))"
```
