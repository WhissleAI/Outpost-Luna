# Outpost Luna design system

All tokens are in `frontend/src/tokens.css`, imported first by `main.js`. Component CSS uses only these variables. The
names below are stable, and their values may still be tuned. If you need a new token, ask the shell owner, and don't
hard-code a value.

## Principles

- **One primary action per screen.** Use the filled accent button. Everything else is secondary (surface-2) or
  quiet (text button).
- **Colour carries meaning.** There is one accent, `--color-accent`, for actions, selection and progress. Use
  `--color-success` for correct and earned. Use amber `--color-warning` and red `--color-danger` only for real
  cautions and alerts, never for decoration.
- **Two type families.** Inter is the UI font. JetBrains Mono is for telemetry, numbers and instrument legends. Both
  are self-hosted, because the app runs offline.
- **No emoji in the UI.** Use `icon(name)` and `patch(id)` from `frontend/src/assets/icons.js` (owned by the Art agent).
- **Kid-sized targets.** Interactive controls are at least `--control-md` (44px). A primary action is
  `--control-lg` (52px).

## Tokens

### Type

| token | value | use |
|---|---|---|
| `--font-ui` | Inter Variable | everything |
| `--font-mono` | JetBrains Mono 400/600 | telemetry, numbers, instrument legends |
| `--text-xs` | 12px | eyebrows, captions on controls |
| `--text-sm` | 14px | secondary text, small buttons |
| `--text-md` | 16px | body, buttons, answers |
| `--text-lg` | 20px | questions, card titles |
| `--text-xl` | 28px | screen titles |
| `--text-2xl` | 40px | hero (home, patch earned) |
| `--leading-tight` / `--leading-snug` / `--leading-normal` | 1.15 / 1.3 / 1.5 | |
| `--weight-regular` / `--weight-medium` / `--weight-semibold` / `--weight-bold` | 400 / 500 / 600 / 700 | |
| `--tracking-tight` / `--tracking-caps` | -0.015em / 0.08em | titles / uppercase eyebrows and legends |

### Space

There are six steps: `--space-1` 4px · `--space-2` 8px · `--space-3` 12px · `--space-4` 16px · `--space-5` 24px ·
`--space-6` 40px.

### Radii

`--radius-sm` 6px (chips, tags) · `--radius-md` 10px (buttons, inputs, rows) · `--radius-lg` 16px (cards, panels) ·
`--radius-xl` 24px (hero surfaces, dialogs) · `--radius-full`.

### Sizes

| token | value | use |
|---|---|---|
| `--control-sm` | 36px | icon buttons in bars |
| `--control-md` | 44px | default control |
| `--control-lg` | 52px | primary action |
| `--topbar-h` | 56px | top bar |
| `--panel-w` | 420px | side panel next to the Moon |
| `--dock-w` | 640px | comm strip |

### Colour

Values switch with the theme: light, dark (OS preference or `data-theme`), and high contrast
(`data-contrast="high"`, set by Access).

| token | use |
|---|---|
| `--color-bg` | app background |
| `--color-surface` | cards, panels |
| `--color-surface-2` / `--color-surface-3` | hover and inset rows, secondary buttons / pressed |
| `--color-line` / `--color-line-strong` | hairlines / control borders |
| `--color-text` / `--color-text-2` / `--color-text-3` | primary / secondary / tertiary text (all AA) |
| `--color-accent` / `--color-accent-hover` / `--color-on-accent` / `--color-accent-soft` | the one accent / hover / text on accent / selected tint |
| `--color-success` (+`-soft`) | correct answer, earned |
| `--color-warning` (+`-soft`) | real cautions only |
| `--color-danger` (+`-soft`) | real alerts only |
| `--color-focus` | focus ring |
| `--color-scrim` | behind dialogs |

These are dark in **both** themes:

| token | use |
|---|---|
| `--color-space` / `--color-space-2` | the sky behind the Moon |
| `--color-on-space` / `--color-on-space-2` | text on the sky |
| `--color-glass` / `--color-glass-line` | panels floating over the Moon |
| `--color-panel` / `--color-panel-2` | cabin panel metal |
| `--color-display` / `--color-phosphor` / `--color-phosphor-dim` | display-unit glass and its text |
| `--color-lamp-caution` / `--color-lamp-warning` / `--color-lamp-info` | annunciator lamps (amber / red / blue) |
| `--color-power` / `--color-life` / `--color-dose` | the three resources in charts and gauges |

### Elevation, focus and motion

| token | use |
|---|---|
| `--shadow-1` | resting card |
| `--shadow-2` | floating panel |
| `--shadow-3` | dialog |
| `--focus-ring` | the box-shadow to use on `:focus-visible` |
| `--focus-width` / `--focus-offset` / `--color-focus` | parts of the focus ring |
| `--ease-out` / `--ease-in-out` | easing |
| `--dur-fast` / `--dur-base` / `--dur-slow` | 120 / 200 / 360 ms; all 0 under less motion (OS setting or `data-motion="reduce"`) |

### Layers

`--z-stage` · `--z-overlay` (HUD on the globe) · `--z-panel` · `--z-dock` (comm strip, captions) · `--z-toast` ·
`--z-modal`.

## Components

The shell owner owns these, in `styles.css`, and other agents reuse the classes:

| class | what |
|---|---|
| `.btn` | default button: surface-2 background, `--control-md` tall |
| `.btn-primary` | the one accent action, `--control-lg` tall |
| `.btn-quiet` | a text button |
| `.btn-icon` | square icon button; needs an `aria-label` |
| `.chip` | a selectable pill; uses `aria-pressed` |
| `.eyebrow` | small uppercase label (`--text-xs`, `--tracking-caps`, `--color-text-3`) |
| `.card` | the answer card (`#card`) |
| `.toast` | a transient notice |
| `.voice` | the voice state in the comm strip: `is-idle` / `is-listening` / `is-hearing` / `is-thinking` / `is-speaking` / `is-notice` |

## Legacy names

`styles.css` keeps aliases for the old short names (`--bg`, `--ink`, `--accent`, `--s3`, …), all pointing at tokens, so
older CSS keeps working during the rewrite. Don't use them in new CSS. They will be removed once nothing references
them.

The old `--space` / `--space-2` **colour** variables were renamed to `--color-space` / `--color-space-2`, because
`--space-N` is now the spacing scale.

## Fonts

Fonts are bundled with `@fontsource`, and there is no CDN. `@fontsource/barlow-condensed` and
`@fontsource/share-tech-mono` stay installed only because `mission/cabin.js` still imports them. The Mission agent
should switch the cabin to `--font-ui` and `--font-mono` and drop both packages. The easy-read option (Access) loads
`@fontsource/atkinson-hyperlegible` on demand.

## Extension points (shell)

- **Settings sections:** other modules add a section by pushing to `window.__outpost.settingsSections`
  (`[{id, title, after?, html() → string, bind?(sectionEl)}]`). `after` names the section it follows; the default is
  `listen`. A section whose `html()` is empty is not listed. "Camera & gestures" (feat/gestures) plugs in here.
- **Floating things vs the voice bar:** `window.__outpost.voiceBar` has `anchor`, `rect`, `ANCHORS`, `spot(anchor)`,
  `moveTo(anchor)`, `addObstacle(selector)` and `removeObstacle(selector)`. Each move fires `outpost:voicebar`
  (`{anchor, rect}`). A movable self-view preview or a gesture-hint chip should:
  1. register itself with `addObstacle`, so the bar keeps clear of it;
  2. snap to one of the same six anchors (`spot()` gives the top-left for its own size), avoiding the bar's.
- **Glass:** any panel floating over the Moon uses `--color-overlay`, `--color-overlay-line` and `--blur-overlay`.
