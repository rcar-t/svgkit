# svgkit

**Write hand-styled SVG diagrams as short Python, and check any SVG for colliding text.**

svgkit is a single Python file with no dependencies. Copy it into a repository and you get two things:

- a small drawing API with a fixed house style (boxes, groups, arrows, notes, timelines) whose text is measured, so boxes can be sized to their text;
- a checker that reads any SVG, generated or hand-written, estimates where every `<text>` lands and reports text that overlaps other text, runs out of its box, is crossed by a line or runs past the viewBox.

```sh
python3 tools/svgkit.py build docs     # run every diagram source under docs/, write the SVGs, check them
python3 tools/svgkit.py check docs     # check every SVG under docs/
```

## Quick start

Copy `svgkit.py` into your repository, for example into `tools/`. It needs Python 3.8 or later and nothing else.

Put a diagram's source beside the SVG it writes. `docs/load-test.py` writes `docs/load-test.svg`:

```python
from svgkit import Diagram

d = Diagram(760, label="Load test timeline")
d.note(10, 22, "Input: requests at a steady rate for 15 minutes. Repeat: 3 runs.")

t = d.timeline(140, mark_top=66)
t.mark(80, "start")
t.mark(140, "server ready")
t.mark(190, "load starts")          # would hit "server ready", so it moves up a row
t.window(190, 330, "warm-up 5 min", kind="quiet")
t.window(330, 620, "measured: 10 min")
d.save()
```

Then build:

```sh
python3 tools/svgkit.py build .
# wrote     docs/load-test.svg
# checked 1 SVG file: no problems
```

[`examples/`](examples) holds two complete sources and the SVGs they write.

## Writing diagrams

Every SVG svgkit writes has the same house style. It uses the system UI font at 12 px, an arrowhead marker, `role="img"` and an `aria-label` (taken from `label`, which is required). There is no background, so the page behind the SVG shows through.

Coordinates are in px, with y increasing downwards. Text is placed by its baseline. Elements are drawn in the order you add them, so add a group before the boxes inside it.

### Colours

Shapes take a `kind`, which sets their stroke and fill:

| Kind | Stroke | Fill | Use for |
|---|---|---|---|
| `app` | `#4f46e5` | `#eef0fd` | the application under test |
| `state` | `#0e7c86` | `#e8f5f6` | state, measurement, output |
| `kafka`, `topic` | `#b45309` | `#fff7ed` | Kafka, topics, input data |
| `neutral` | `#475569` | `#f6f7fb` | containers |
| `plain` | `#475569` | `#fff` | everything else (the default) |
| `quiet` | `#9ca3af` | `#f6f7fb` | things in the background, such as a warm-up |

Wherever a `color` is taken, you can pass a hex value, a kind name (meaning its stroke colour), `"text"` (`#1f2430`), `"muted"` (`#6b7280`) or `"line"` (`#475569`).

### Drawing

| Call | Draws |
|---|---|
| `Diagram(width=760, height=None, label=...)` | A new diagram. Without a height, the height fits the content plus a 10 px margin. |
| `d.box(x, y, w=None, h=None, title=..., subtitle=None, kind="plain")` | A rounded box with a bold title and muted subtitle lines (a string with `\n`, or a list), centred. Leave out `w` or `h` to size the box to its text. `emphasis=True` thickens the border and colours the title to match it. `dashed=True`, `rx`, `fill`, `stroke` and `bold` are also taken. |
| `d.group(x, y, w, h, title=None, kind="neutral")` | A container with its title at the top left. `dashed=True` gives a `5 4` dash. |
| `d.arrow(a, b, label=None, dashed=False, color=None)` | An arrow from `a` to `b`. Each end is an `(x, y)` point or a box. Between two boxes, the arrow runs straight across where they face each other, or bends once if they don't. It stops 2 px short of its target. |
| `d.route(points, label=None, ..., head=True, fill=None, width=None)` | A line through several points, with an arrowhead at the end unless `head=False`. |
| `d.curve(p0, c1, c2, p1, label=None, ...)` | A cubic Bézier curve. |
| `d.line(a, b)` | A line with no arrowhead. |
| `d.text(x, y, s, color="text", anchor="start", bold=False, size=None)` | Text. A `\n` starts a new line 16 px lower. |
| `d.note(x, y, s, anchor="start")` | Muted text, for captions. |
| `d.rect(x, y, w, h, kind="plain", rx=0)` | A bare rectangle. |
| `d.raw(svg, bottom=0)` | SVG markup, added as it is. |

An arrow's label goes 8 px above the middle of its longest segment, or 8 px to the right if that segment is vertical. To place it yourself, pass `label_at=(x, y)` and `label_anchor`. A label on a coloured arrow takes the arrow's colour; on a default arrow it is muted.

Shapes return a `Box`, and so does text (its estimated extent). Use them to place other things:

| Box attribute | Meaning |
|---|---|
| `x`, `y`, `w`, `h`, `x2`, `y2`, `cx`, `cy` | Edges, size and centre. |
| `top(dx=0)`, `bottom(dx=0)`, `left(dy=0)`, `right(dy=0)` | The middle of a side as an `(x, y)` point, shifted along the side by `dx` or `dy`. |
| `at(fx, fy)` | The point at fractions of the width and height. `at(0, 0)` is the top-left corner. |

```python
web = d.box(190, 60, title="Web server", subtitle="2 replicas")
queue = d.box(380, 50, title="Job queue", kind="topic")
d.arrow(web, queue, "enqueue")
d.arrow(web.bottom(), (web.cx, 200), "logs", dashed=True)
```

### Timelines

`t = d.timeline(y, x1=60, x2=width-20, label="time", domain=None, mark_top=y-90)` draws an axis with an arrowhead. Positions along it are x coordinates. If you give `domain=(start, end)`, they are values in that range instead, spread over the axis.

| Call | Draws |
|---|---|
| `t.mark(t, label, top=None, color="text", anchor="middle", label_y=None)` | A dashed vertical line from `top` (default `mark_top`) down to the axis, with a bold label 6 px above it. If the label would hit an earlier mark's label, it moves up 16 px at a time and its line grows with it. Pass `label_y` to place the label yourself instead. |
| `t.window(t1, t2, label=None, kind="state", height=22, top=None)` | A shaded span sitting on the axis, with a bold label in the kind's colour. |

### Sizes and measuring

| Function | Returns |
|---|---|
| `text_width(s, size=12, bold=False)` | The estimated width of one line of text, in px. |
| `box_size(title, subtitle=None, bold=True)` | The `(w, h)` that `box` would choose. Use it to give a row of boxes the same width. |
| `text_box(x, y, s, anchor="start", bold=False, size=12)` | The estimated `Box` of a line of text. |
| `d.check()` | The problems the checker finds in the diagram so far. |
| `d.svg()` | The SVG as a string. |
| `d.save(path=None)` | Writes the SVG beside the source. The default name is the source's name with `.svg`. A source can call `save("other.svg")` on several diagrams to write several files. A file whose content wouldn't change is left alone, so live reload only fires on real changes. |

Widths come from a table of advance widths for the house font as Chrome draws it on macOS (SF Pro Text). For ordinary text the estimate is within 0.5% of the browser. Kerned pairs such as `AV` come out slightly wide, which errs on the safe side. Characters not in the table get 0.6 em, and wide East Asian characters get 1 em.

## Building

```text
python3 svgkit.py build [paths...] [--stale] [--no-check] [--tolerance PX]
```

`build` finds every diagram source under the given folders (the default is `.`) and runs each one from its own folder. It prints which SVGs it wrote and then checks them.

- **A diagram source** is a `.py` file that contains `import svgkit` or `from svgkit import`. Files whose names start with `_` are skipped, so a shared `_style.py` can sit beside the sources and be imported by them. Hidden folders, `node_modules`, `__pycache__` and `venv` are skipped too.
- **`--stale`** writes nothing. It fails if any SVG differs from what its source would write, which is useful in CI.
- **The exit code** is 0 when every source ran and no problems were found, and 1 otherwise. A source that raises an error is reported with its traceback, and the remaining sources still run.

Sources are run by `build`, not with `python3 load-test.py`, so they need no import-path setup.

## Checking

```text
python3 svgkit.py check [paths...] [--png] [--boxes] [--out DIR] [--chrome PATH] [--tolerance PX]
```

`check` reads every `.svg` under the given paths (the default is `.`) and reports:

| Rule | Reported when |
|---|---|
| `text-overlap` | Two texts overlap. |
| `text-overflow` | A text runs past the edge of the smallest rect its centre is in, or comes within 2 px of its left or right edge. |
| `text-on-box` | A text straddles the edge of a rect that its centre isn't in. |
| `text-on-line` | A stroked line or path passes through a text. Curves are followed. |
| `outside` | A text runs past the viewBox. |
| `xml` | The file isn't well-formed XML, or its root isn't `<svg>`. |

```text
docs/load-test.svg: 1 problem
  text-on-line   "measured: 10 min" at (475, 131) is crossed by the line (470, 50)-(470, 140)
checked 1 SVG file: 1 problem in 1 file
```

Positions are the `x` and `y` written in the file, so you can search for them. The exit code is 0 with no problems, 1 with problems, and 2 for a usage error, such as a missing path or no Chrome when `--png` is given.

**How texts are read.** The checker takes `font-size`, `font-weight`, `text-anchor`, `dominant-baseline` and `translate(...)` transforms from the element and its ancestors, including `style="..."`. A `<tspan>` with its own `x`, `y` or `dy` starts a new line. Elements under any other transform, such as rotated axis titles, are left out because their position can't be estimated. So are `<defs>`, hidden elements and anything with opacity below 0.3.

**What counts as an obstacle.** Rects count unless they have neither fill nor stroke. Lines and paths count only if they are stroked, and not with a faint stroke: a colour as light as `#e6e8ef`, or a stroke opacity below 0.3. This means chart gridlines don't flag the labels drawn over them.

**Opting out.** Add `data-check="off"` to any element or group to leave it out of every check, both as a text and as an obstacle. Use it for a deliberate overlap.

**Tolerance.** Overlaps of 1 px or less in either direction are let through. Change this with `--tolerance`.

### Looking at the result

`--png` renders every SVG to a PNG at twice its size, on a white page, using headless Chrome. The PNGs go to a new temporary folder (or `--out`) and their paths are printed. `--boxes` renders the same way but outlines every estimated text box in grey and each problem in red, which shows at a glance what the checker saw.

Chrome is looked for at `--chrome`, then `$SVGKIT_CHROME`, then `/Applications/Google Chrome.app/...`, then `google-chrome` or `chromium` on the `PATH`.

## Measuring

```sh
python3 svgkit.py measure "Build server" --bold
# 72.4  Build server
```

This prints the estimated width in px, which is handy for hand-written SVGs.

## Using it from a task runner

```yaml
# Taskfile.yml
tasks:
  diagrams:
    desc: Regenerate every SVG from its Python source, then check it
    cmd: python3 tools/svgkit.py build .
  diagrams:check:
    desc: Check every SVG, and fail if any is out of date with its source
    cmds:
      - python3 tools/svgkit.py build --stale .
      - python3 tools/svgkit.py check .
  diagrams:look:
    desc: Render every SVG to PNG with the estimated text boxes drawn
    cmd: python3 tools/svgkit.py check {{.CLI_ARGS | default "."}} --boxes
```

## Development

```sh
python3 -m unittest test_svgkit.py     # API, checker and commands
python3 -m unittest test_browser       # widths against Chrome, and PNG rendering; skipped without Chrome
python3 svgkit.py build examples       # rebuild the examples
```

The width table was measured with `getComputedTextLength` in headless Chrome on macOS. `test_browser` re-measures a set of strings and fails if any estimate is more than 2% off.

## Limitations

- **Estimates, not layout.** The checker doesn't render anything. It reasons about estimated text boxes, and other fonts (Segoe UI on Windows, Roboto on Linux) run a few percent wider or narrower than the table. Keep a few px of room, and use `--png` for the final look.
- **No automatic layout.** You place every shape. svgkit sizes boxes to their text, routes simple arrows and staggers timeline labels, but it doesn't move things apart for you. The checker tells you what to move.
- **Only translate transforms** are followed. Text under rotate, scale or matrix transforms is skipped.
- **Arcs** in paths are treated as straight lines from end to end.

## License

[MIT](LICENSE)
