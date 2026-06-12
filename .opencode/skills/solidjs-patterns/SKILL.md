---
name: solidjs-patterns
description: |
  SolidJS v1.9+ reactivity, components, and patterns for TypeScript apps.
  Use when writing SolidJS components, JSX, signals, stores, control flow,
  or debugging reactivity issues. Covers the critical differences from React.
  Trigger phrases: SolidJS, solid-js, createSignal, createResource, createStore,
  createMemo, createEffect, onMount, onCleanup, Show, For, Switch, Match,
  JSX in Solid, Solid component, signal vs store, React to Solid migration,
  Solid props destructure, async data Solid, Solid lifecycle.
---

# SolidJS Patterns (v1.9+)

## When to Use

- Writing or reviewing SolidJS components (.tsx / .jsx)
- Migrating from React to SolidJS
- Debugging "why isn't this updating?" reactivity issues
- Choosing between `createSignal`, `createStore`, and `createMemo`
- Fetching async data in Solid
- Using control-flow components (`Show`, `For`, `Switch`)

---

## 1. Props Access: Never Destructure

In Solid, props are reactive getters under the hood. Destructuring extracts the
value at call time and **breaks the reactive connection**. Always access props
via `props.xxx`.

```tsx
// ❌ WRONG — destructuring breaks reactivity
function User(props: { name: string }) {
  const { name } = props;
  return <h1>{name}</h1>; // never updates
}

// ✅ CORRECT — access via props
function User(props: { name: string }) {
  return <h1>{props.name}</h1>; // stays reactive
}
```

If you must split props, use `splitProps`, which preserves reactivity:

```tsx
import { splitProps } from "solid-js";

const [local, rest] = splitProps(props, ["name", "age"]);
```

---

## 2. Signals in JSX: Call Accessors, Pass Values

Signals return a **getter function** and a **setter function**. In JSX, you must
**call the getter** to read the value. Pass **resolved values** (not the getter
itself) as props to child components.

```tsx
import { createSignal } from "solid-js";

// ✅ CORRECT
const [id, setId] = createSignal(0);

return (
  <>
    <span>{id()}</span>              {/* call the getter */}
    <User id={id()} name="Brenley" /> {/* pass the value, not the accessor */}
  </>
);
```

```tsx
// ❌ WRONG — passing the accessor function as a prop
<User id={id} name="Brenley" />;

// This forces the child to treat props.id as a function:
function User(props: { id: Accessor<number>; name: string }) {
  return <h1>{props.id()} – {props.name}</h1>; // awkward mixed types
}
```

**Rule:** Pass resolved values. Let reactivity live in the parent's JSX.

---

## 3. Control Flow Components

Solid provides dedicated control-flow components. They are optimized for
fine-grained updates and are idiomatic.

### `<Show>` — conditional rendering (replaces `&&` / ternary)

```tsx
import { Show } from "solid-js";

// ✅ CORRECT
<Show when={open()} fallback={<EmptyState />}>
  <SidebarMenu />
</Show>

// ❌ AVOID — raw JS in JSX still works, but is less idiomatic
{open() && <SidebarMenu />}
```

### `<For>` — list rendering (replaces `.map()`)

```tsx
import { For } from "solid-js";

// ✅ CORRECT — preserves item identity, minimal DOM updates
<For each={items()} fallback={<div>No items</div>}>
  {(item, index) => <div>{index()}: {item}</div>}
</For>

// ❌ AVOID — re-creates all nodes on every change
{items().map(item => <div>{item}</div>)}
```

Note: `index` in `<For>` is an **accessor function** — call `index()` to read it.

### `<Switch>` / `<Match>` — multi-branch conditions

```tsx
import { Switch, Match } from "solid-js";

<Switch fallback={<p>Unknown status</p>}>
  <Match when={status() === "loading"}>
    <p>Loading...</p>
  </Match>
  <Match when={status() === "success"}>
    <p>Saved</p>
  </Match>
  <Match when={status() === "error"}>
    <p>Failed</p>
  </Match>
</Switch>
```

---

## 4. State Management Cheat Sheet

| Primitive | Use case |
|---|---|
| `createSignal` | Primitive values, simple objects, references. Whole-value replacement. |
| `createStore` | Complex/nested objects. Fine-grained property-level updates. |
| `createMemo` | Derived/computed values. Memoized, runs only when deps change. |
| `createEffect` | Side effects: DOM manipulation, third-party libs. **Use sparingly.** |

### createSignal vs createStore

```tsx
// Signal — whole object replacement
const [board, setBoard] = createSignal({ notes: ["a"], boards: ["b"] });
setBoard(prev => ({ ...prev, notes: [...prev.notes, "c"] }));

// Store — fine-grained, mutable-style updates
const [board, setBoard] = createStore({ notes: ["a"], boards: ["b"] });
setBoard("notes", notes => [...notes, "c"]); // only notes subscribers update
```

### createMemo — derived values

```tsx
const [count, setCount] = createSignal(0);
const doubled = createMemo(() => count() * 2);

// doubled() is cached — reused across multiple reads without re-computation
```

### createEffect — side effects (use sparingly)

```tsx
createEffect(() => {
  console.log("count changed:", count());
  // Use for: DOM access, subscribing to external stores, third-party libs
});
```

**Never set signals inside effects for derived data** — use `createMemo` instead.

---

## 5. Async Data: createResource (NEVER createEffect + fetch)

```tsx
// ❌ WRONG — anti-pattern with many problems
const [posts, setPosts] = createSignal([]);
createEffect(async () => {
  const data = await fetch("/api/posts").then(r => r.json());
  setPosts(data);
});

// ✅ CORRECT — use createResource
const [posts] = createResource(() =>
  fetch("/api/posts").then(r => r.json())
);
```

`createResource` provides:
- `posts()` — the resolved value
- `posts.loading` — boolean loading state
- `posts.error` — error object if fetch fails
- `posts.state` — `"unresolved" | "pending" | "ready" | "refreshing" | "errored"`
- Integrates with `<Suspense>` and `<ErrorBoundary>`
- `mutate()` — optimistic updates
- `refetch()` — manual re-fetch

### With a reactive source signal:

```tsx
const [userId, setUserId] = createSignal(1);
const [user] = createResource(userId, async (id) => {
  const res = await fetch(`/api/users/${id}`);
  return res.json();
});
// Automatically re-fetches when userId changes
```

### With Suspense:

```tsx
import { Suspense } from "solid-js";

<Suspense fallback={<div>Loading...</div>}>
  <Switch>
    <Match when={user.error}>
      <span>Error: {user.error.message}</span>
    </Match>
    <Match when={user()}>
      <div>{user().name}</div>
    </Match>
  </Switch>
</Suspense>
```

---

## 6. Lifecycle: onMount and onCleanup

Solid **does NOT** support React's return-function-from-effect cleanup pattern.

```tsx
// ❌ WRONG — React pattern, does NOT work in Solid
createEffect(() => {
  const timer = setInterval(() => {}, 1000);
  return () => clearInterval(timer); // ignored in Solid
});

// ✅ CORRECT — use onCleanup inside the reactive scope
createEffect(() => {
  const timer = setInterval(() => {}, 1000);
  onCleanup(() => clearInterval(timer));
});
```

### onMount — run once after initial render

```tsx
import { onMount } from "solid-js";

function Component() {
  onMount(() => {
    console.log("mounted — refs are ready, browser-only code");
  });
  return <div>...</div>;
}
```

- Does **not** run during SSR
- Refs are assigned by the time `onMount` runs
- Returning a function from `onMount` does **not** register cleanup — use `onCleanup` inside it

### onCleanup — runs when scope is disposed or re-executes

```tsx
import { onCleanup } from "solid-js";

// In a component — runs on unmount
onCleanup(() => clearInterval(timer));

// Inside createEffect — runs before each re-execution
createEffect(() => {
  const sub = subscribeTo(topic());
  onCleanup(() => sub.unsubscribe());
});
```

---

## 7. React → SolidJS Translation Table

| React | SolidJS | Notes |
|---|---|---|
| `useState(x)` | `createSignal(x)` | Returns `[getter, setter]`, getter is a **function** |
| `useState` objects | `createStore(obj)` | Fine-grained property-level reactivity |
| `useMemo(fn, deps)` | `createMemo(fn)` | Dependencies auto-tracked, no deps array |
| `useEffect(fn, deps)` | `createEffect(fn)` | Dependencies auto-tracked, no deps array |
| `useEffect` return cleanup | `onCleanup(fn)` inside effect | Must call `onCleanup` explicitly |
| `useEffect([], [])` | `onMount(fn)` | Runs once, no dependency tracking |
| `{cond && <X/>}` | `<Show when={cond()}>` | Idiomatic control flow |
| `{arr.map(x => <X/>)}` | `<For each={arr()}>` | Preserves item identity |
| `switch/case` in JSX | `<Switch><Match when={...}>` | First-match-wins semantics |
| `useContext(ctx)` | `useContext(ctx)` | Same API, works with Solid's reactivity |
| `fetch` in `useEffect` | `createResource` | Built-in loading/error states |
| Destructuring props | `props.xxx` | **NEVER** destructure |
| `useCallback` | Not needed | Components only run once |
| `React.memo` | Not needed | Fine-grained updates out of the box |
| `useRef` | `ref` prop + variable | `let el; <div ref={el}>` |

---

## 8. Key Mental Model: Component Body Runs Once

Solid components are **setup functions** that run once. Only JSX expressions and
reactive scopes (`createEffect`, `createMemo`) track signal reads.

```tsx
function Counter() {
  const [count, setCount] = createSignal(0);

  // ❌ Runs only once — not tracked
  console.log("Count:", count());

  // ✅ Reactive — JSX is a tracking scope
  return <span>Count: {count()}</span>;
}
```

To make a computation reactive outside JSX, wrap it in a function and call it
inside a reactive scope:

```tsx
// ✅ Derived value accessed in JSX
const doubled = () => count() * 2;
// In JSX: <div>{doubled()}</div>

// ✅ Better: createMemo for expensive computations
const doubled = createMemo(() => count() * 2);
```

---

## 9. No `isSignal` Helper (by Design)

Solid intentionally provides no `isSignal` utility. The framework's philosophy
is that **child components should not need to know whether a prop came from a
signal or not**. Always resolve signals in JSX (`{signal()}`) or pass resolved
values as props. This keeps prop types simple and components decoupled.

```tsx
// ❌ Passing an accessor forces special handling:
function Child(props: { value: Accessor<number> }) {
  return <div>{props.value()}</div>; // "is this a signal or not?"
}

// ✅ Pass the resolved value:
function Child(props: { value: number }) {
  return <div>{props.value}</div>;
}
```

---

## 10. Anti-Patterns

### Props destructuring

```tsx
// ❌ WRONG
const { name } = props;  // breaks reactivity
// ✅ RIGHT
props.name               // always reactive
```

### createEffect for derived state

```tsx
// ❌ WRONG
const [double, setDouble] = createSignal(0);
createEffect(() => setDouble(count() * 2));

// ✅ RIGHT
const double = createMemo(() => count() * 2);
```

### createEffect + fetch

```tsx
// ❌ WRONG
createEffect(async () => {
  setData(await fetch(...).then(r => r.json()));
});

// ✅ RIGHT
const [data] = createResource(() => fetch(...).then(r => r.json()));
```

### Returning cleanup from createEffect (React pattern)

```tsx
// ❌ WRONG
createEffect(() => {
  const sub = subscribe();
  return () => sub.unsubscribe(); // ignored in Solid!
});

// ✅ RIGHT
createEffect(() => {
  const sub = subscribe();
  onCleanup(() => sub.unsubscribe());
});
```

### `.map()` instead of `<For>`

```tsx
// ❌ AVOID — full list re-created on every change
{items().map(item => <Item item={item} />)}

// ✅ PREFER — preserves item identity
<For each={items()}>{item => <Item item={item} />}</For>
```

### Signal read outside tracking scope

```tsx
// ❌ WRONG — only reads once during setup
const doubled = count() * 2;

// ✅ RIGHT — wrapped so reads happen reactively
const doubled = createMemo(() => count() * 2);
// or
const doubled = () => count() * 2; // called inside JSX
```

---

## Drag and Drop (HTML5 DnD API)

```tsx
// draggable tab in a tab bar
<div
  draggable="true"
  onDragStart={(e: DragEvent) => {
    e.dataTransfer!.effectAllowed = "move"
    e.dataTransfer!.setData("application/tab-id", tab.id)
    e.dataTransfer!.setData("application/viewport-id", viewportId)
  }}
  onDragEnd={() => { /* cleanup */ }}
>
  {tab.label}
</div>

// droppable viewport container
<div
  onDragOver={(e: DragEvent) => {
    e.preventDefault()  // CRITICAL: drop won't fire without this
    e.dataTransfer!.dropEffect = "move"
  }}
  onDragEnter={(e: DragEvent) => { e.preventDefault(); highlight(true) }}
  onDragLeave={() => highlight(false)}
  onDrop={(e: DragEvent) => {
    e.preventDefault(); highlight(false)
    const tabId = e.dataTransfer!.getData("application/tab-id")
    const sourceVp = e.dataTransfer!.getData("application/viewport-id")
    if (tabId && sourceVp) moveTab(tabId, sourceVp, targetVpId)
  }}
/>
```

**Critical gotchas:**
- `onDragOver` MUST call `e.preventDefault()` — without it, `onDrop` never fires
- `getData()` only works in `dragstart` and `drop` — NOT in `dragover`/`dragenter`
- `dataTransfer.setData("text/plain", "x")` — Firefox requires at least one recognized type
- `dragenter`/`dragleave` fire on children too — use drag counter or `pointer-events: none` on children during drag

## Dynamic Component

```tsx
import { Dynamic } from "solid-js/web"

// Render different components based on tab type
const tabs = () => [
  { id: "files", component: FileTree },
  { id: "chat",  component: ChatPanel },
]

<For each={tabs()}>
  {(tab) => (
    <Show when={tab.id === activeTabId()}>
      <Dynamic component={tab.component} />
    </Show>
  )}
</For>
```

## Custom Directives (use:xxx)

```tsx
// Define a directive for reusable behavior
function droppable(el: HTMLElement, accessor: Accessor<string>) {
  const vpId = accessor()
  const onDragOver = (e: DragEvent) => { e.preventDefault() }
  const onDrop = (e: DragEvent) => {
    const tabId = e.dataTransfer!.getData("application/tab-id")
    if (tabId) moveTab(tabId, vpId)
  }
  el.addEventListener("dragover", onDragOver)
  el.addEventListener("drop", onDrop)
  onCleanup(() => { el.removeEventListener("dragover", onDragOver); /* ... */ })
}

// Usage
<div use:droppable={"left"} />
```

## Store with produce (nested updates)

```tsx
import { createStore, produce } from "solid-js/store"

const [state, setState] = createStore({
  left: { tabs: [{ id: "a", label: "Files" }], activeTabId: "a" },
  center: { tabs: [], activeTabId: null },
})

function moveTab(tabId: string, from: string, to: string) {
  setState(produce((s) => {
    const tab = s[from].tabs.find(t => t.id === tabId)
    if (!tab) return
    s[from].tabs = s[from].tabs.filter(t => t.id !== tabId)
    if (s[from].activeTabId === tabId) s[from].activeTabId = s[from].tabs[0]?.id ?? null
    s[to].tabs.push(tab)
    s[to].activeTabId = tab.id
  }))
}
```

---

## Reference

- [SolidJS Documentation](https://docs.solidjs.com)
- [Intro to Reactivity](https://docs.solidjs.com/concepts/intro-to-reactivity)
- [Signals](https://docs.solidjs.com/concepts/signals)
- [Conditional Rendering](https://docs.solidjs.com/concepts/control-flow/conditional-rendering)
- [State Management Guide](https://docs.solidjs.com/guides/state-management)
- [Fetching Data Guide](https://docs.solidjs.com/guides/fetching-data)
- [createResource Reference](https://docs.solidjs.com/reference/basic-reactivity/create-resource)
- [createMemo Reference](https://docs.solidjs.com/reference/basic-reactivity/create-memo)
- [Effects](https://docs.solidjs.com/concepts/effects) (onMount, onCleanup)
- [<Show> Reference](https://docs.solidjs.com/reference/components/show)
- [<For> Reference](https://docs.solidjs.com/reference/components/for)
- [<Switch>/<Match> Reference](https://docs.solidjs.com/reference/components/switch-and-match)
- [Dynamic Component](https://docs.solidjs.com/reference/component-apis/dynamic)
- [Custom Directives](https://www.solidjs.com/tutorial/bindings_directives)
- [Solid.js Best Practices (Brenley Dueck)](https://brenelz.com/posts/solid-js-best-practices/)
- [SolidJS Playground](https://playground.solidjs.com/)
