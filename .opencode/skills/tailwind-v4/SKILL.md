---
name: tailwind-v4
description: |
  Tailwind CSS v4 conventions: CSS-first config, no tailwind.config.js,
  @import "tailwindcss", OKLCH colors, @theme, @utility, @custom-variant.
  Use when writing CSS, styling components, configuring Tailwind, adding
  custom themes, implementing dark mode, or debugging build issues.
  Prevents v3 patterns that don't work in v4 (LLMs frequently generate
  outdated v3 code). Trigger phrases: Tailwind CSS, tailwindcss, Tailwind v4,
  @tailwind, PostCSS, tailwind.config, dark mode, @layer, @apply,
  class= vs className, design tokens, OKLCH, @theme, @utility.
---

# Tailwind CSS v4 Patterns

> Target: Tailwind CSS v4.0+ — CSS-first configuration, Oxide engine.

## When to Use

- Setting up Tailwind CSS in a new Vite project
- Migrating from Tailwind v3 to v4
- Adding custom design tokens (colors, fonts, spacing)
- Implementing dark mode with CSS variables
- Creating custom utilities or variants
- Fixing build errors from v3-style configuration
- Responding to LLM-generated Tailwind code (v3 vs v4 validation)

---

## 1. Installation (Vite)

Install **only** `tailwindcss` and `@tailwindcss/vite`. No PostCSS plugin.

```bash
npm install tailwindcss @tailwindcss/vite
```

**vite.config.ts:**
```ts
import { defineConfig } from "vite";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [tailwindcss()],
});
```

Import in your **single** main CSS file:
```css
@import "tailwindcss";
```

**Crucial:** Import `@import "tailwindcss"` in **only one** CSS file. Multiple imports cause dark mode overrides and duplicate styles.

---

## 2. CSS-First Configuration — NO `tailwind.config.js`

Delete your `tailwind.config.js`. All configuration lives in CSS via `@theme`:

```css
@import "tailwindcss";

@theme {
  --font-display: "Satoshi", sans-serif;
  --breakpoint-3xl: 120rem;
  --color-avocado-500: oklch(0.84 0.18 117.33);
  --color-brand: var(--color-avocado-500);
}
```

### Theme variable namespaces

| Namespace | Creates utilities like |
|---|---|
| `--color-*` | `bg-red-500`, `text-sky-300`, `border-emerald-600` |
| `--font-*` | `font-sans`, `font-display` |
| `--text-*` | `text-xl`, `text-body` |
| `--spacing-*` | `p-4`, `m-2`, `gap-6` |
| `--breakpoint-*` | responsive variants `sm:*`, `md:*`, `3xl:*` |
| `--radius-*` | `rounded-sm`, `rounded-xl` |
| `--shadow-*` | `shadow-md`, `shadow-xl` |
| `--animate-*` | `animate-spin`, `animate-fade-in` |

**Override entire namespace:**
```css
@theme {
  --color-*: initial;
  --color-white: #fff;
  --color-midnight: #121063;
}
```

**Reference other variables** with `inline`:
```css
@theme inline {
  --font-sans: var(--font-inter);
}
```

---

## 3. Dark Mode — CSS Variables, NOT `dark:` for Theme Colors

v4 uses native CSS variables for theming. The `dark:` variant still works for **per-utility** overrides, but theme colors should use CSS variable swapping.

### Manual toggle (class strategy):
```css
@import "tailwindcss";
@custom-variant dark (&:where(.dark, .dark *));
```

### Theme with CSS variables:
```css
@import "tailwindcss";

@layer base {
  :root {
    --color-surface: oklch(0.98 0 0);
    --color-text: oklch(0.20 0 0);
  }
  .dark {
    --color-surface: oklch(0.15 0 0);
    --color-text: oklch(0.90 0 0);
  }
}
```

```html
<!-- Use in HTML via arbitrary values -->
<body class="bg-(--color-surface) text-(--color-text)">
```

For per-element dark overrides, `dark:` still works:
```html
<div class="bg-white dark:bg-gray-900 text-black dark:text-white">
```

---

## 4. SolidJS-Specific: `class=` NOT `className=`

SolidJS uses standard HTML attributes, not React's JSX conventions.

```tsx
// ✅ CORRECT
<div class="flex items-center gap-4">...</div>

// ❌ WRONG — React convention, does NOT work in SolidJS
<div className="flex items-center gap-4">...</div>
```

---

## 5. Dynamic Classes (SolidJS Signals)

### Template literals (simple toggles):
```tsx
const [active, setActive] = createSignal(false);

<div class={`p-4 ${active() ? "bg-blue-500" : "bg-gray-200"}`}>
```

### Multiple conditional classes via signals:
```tsx
const [variant, setVariant] = createSignal<"primary" | "secondary">("primary");

const buttonClasses = () => {
  const base = "px-4 py-2 rounded";
  return `${base} ${variant() === "primary" ? "bg-blue-500 text-white" : "bg-gray-200"}`;
};

<button class={buttonClasses()}>Click</button>
```

### Toggling individual classes:
```tsx
const [open, setOpen] = createSignal(false);

<div class="transition" classList={{ "translate-x-0": open(), "-translate-x-full": !open() }}>
```

---

## 6. Responsive Breakpoints

Default breakpoints (override via `--breakpoint-*`):

| Breakpoint | Width | Example |
|-----------|-------|---------|
| `sm` | 640px | `sm:flex-col` |

## Equal-Width Grid (auto-cols-fr)

```html
<!-- Dynamic equal-width columns: N tabs = 1/N each -->
<div class="grid grid-flow-col auto-cols-fr">
  <div class="truncate min-w-0">Tab 1</div>
  <div class="truncate min-w-0">Tab 2</div>
</div>
```

`auto-cols-fr` makes auto-placed columns equal width. `min-w-0` is required for `truncate` to work in grid/flex children.

Custom breakpoints:
```css
@theme {
  --breakpoint-xs: 30rem;
  --breakpoint-3xl: 120rem;
}
```
Use: `xs:block`, `3xl:grid-cols-6`.

---

## 7. Custom Utilities & Variants

### New utility (`@utility`):
```css
@utility content-auto {
  content-visibility: auto;
}
```
Use: `<div class="content-auto">`

### Custom variant (`@custom-variant`):
```css
@custom-variant any-hover {
  @media (any-hover: hover) {
    &:hover {
      @slot;
    }
  }
}
```
Use: `<div class="any-hover:underline">`

### Applying variants in custom CSS (`@variant`):
```css
.my-element {
  background: white;
  @variant dark {
    background: black;
  }
}
```

---

## 8. `@layer` Usage (v4 Compatible)

```css
@layer base {
  h1 { font-size: var(--text-2xl); font-weight: var(--font-weight-bold); }
}
@layer components {
  .card {
    background: var(--color-white);
    border-radius: var(--radius-lg);
    padding: --spacing(6);
    box-shadow: var(--shadow-xl);
  }
}
```

**Note:** `@layer base` does NOT use `@tailwind base` — use `@import "tailwindcss"` instead.

---

## 9. Anti-Patterns: v3→v4 Mistakes LLMs Make

| ❌ v3 (LLMs often generate this) | ✅ v4 (correct) | Why |
|---|---|---|
| **`tailwind.config.js`** | `@theme` in CSS | CSS-first, no JS config |
| **`@tailwind base/components/utilities`** | `@import "tailwindcss"` | Single-line import |
| **PostCSS plugin** | `@tailwindcss/vite` Vite plugin | Faster, simpler |
| **`postcss-import` plugin** | Nothing — built-in | v4 handles `@import` natively |
| **`content: ["./src/**/*.{html,js}"]`** | `@source "../path"` (if needed) | Auto-detection built-in |
| **`darkMode: "class"` in config** | `@custom-variant dark (&:where(.dark, .dark *));` | CSS-configured |
| **`plugins: [require(...)]`** | `@utility` or `@plugin` directive | CSS-native extensions |
| **`bg-opacity-50`** | `bg-black/50` | Opacity as color modifier |
| **`flex-shrink-0`, `flex-grow-0`** | `shrink-0`, `grow-0` | `flex-` prefix removed |
| **`outline-none`** | `outline-hidden` | v4 `outline-none` only resets color |
| **`rounded`** | `rounded-sm` | `rounded` is now a variable |
| **`@apply` with responsive modifiers** | HTML classes, not `@apply` | Breaks in v4 |
| **`ring` without color** | `ring ring-blue-500` | Explicit color required |
| **Multiple `@import "tailwindcss"`** | One CSS file only | Causes cascade/duplicate issues |

---

## 10. New v4 Features Quick Reference

Container queries (`@container`, `@sm:grid-cols-3`), 3D transforms (`rotate-x-12`, `transform-3d`), gradient angles (`bg-linear-45`), `not-*` and `starting` variants, `field-sizing-content`, `color-scheme-dark`, and shorthand `bg-(--my-color)` for `bg-[var(--my-color)]`.

---

## Reference

- [Tailwind CSS v4 Installation (Vite)](https://tailwindcss.com/docs/installation/using-vite)
- [Theme Variables](https://tailwindcss.com/docs/theme)
- [Dark Mode](https://tailwindcss.com/docs/dark-mode)
- [Adding Custom Styles](https://tailwindcss.com/docs/adding-custom-styles)
- [Upgrade Guide (v3→v4)](https://tailwindcss.com/docs/upgrade-guide)
- [Tailwind CSS v4.0 Release Blog Post](https://tailwindcss.com/blog/tailwindcss-v4)
- [Detecting Classes in Source Files](https://tailwindcss.com/docs/detecting-classes-in-source-files)
- [Functions & Directives (v4)](https://tailwindcss.com/docs/functions-and-directives)
