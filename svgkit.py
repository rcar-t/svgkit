#!/usr/bin/env python3
"""svgkit: write hand-styled SVG diagrams as short Python, and check any SVG for colliding text.

MIT License, Copyright (c) 2026 Rhonda Toh

Copy this one file into a repository (for example tools/svgkit.py). Standard library only,
Python 3.8+.

    python3 tools/svgkit.py build [paths...]     # run every diagram source, write its SVG, check it
    python3 tools/svgkit.py check [paths...]     # check SVGs, hand-written ones too
    python3 tools/svgkit.py check docs --png     # also render each SVG to PNG with headless Chrome
    python3 tools/svgkit.py measure "some text"  # estimated width in px

A diagram source is a .py file that imports svgkit, kept beside the SVG it writes:

    # docs/load-test.py
    from svgkit import Diagram

    d = Diagram(760, label="Load test timeline")
    t = d.timeline(140)
    t.mark(80, "start")
    t.window(330, 620, "measured: 10 min")
    d.save()                                     # writes docs/load-test.svg

What the checker reports, for each <text>, from estimated text boxes:
- text-overlap   two texts overlap
- text-overflow  a text runs past (or touches) the edge of the rect it sits in
- text-on-box    a text straddles the edge of a rect it does not sit in
- text-on-line   a stroked line or path runs through a text
- outside        a text runs past the viewBox
- xml            the file is not well-formed XML, or not an SVG
Add data-check="off" to an element (or a group) to leave it out of every check.
"""
import argparse
import html
import math
import os
import re
import runpy
import shutil
import subprocess
import sys
import tempfile
import traceback
import unicodedata
import xml.etree.ElementTree as ET

# ---------------------------------------------------------------------------------------------
# House style

FONT_FAMILY = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif"
FONT_SIZE = 12
TEXT = "#1f2430"
MUTED = "#6b7280"
LINE = "#475569"

# kind: (stroke, fill)
KINDS = {
    "app": ("#4f46e5", "#eef0fd"),
    "state": ("#0e7c86", "#e8f5f6"),
    "kafka": ("#b45309", "#fff7ed"),
    "topic": ("#b45309", "#fff7ed"),
    "neutral": ("#475569", "#f6f7fb"),
    "plain": ("#475569", "#fff"),
    "quiet": ("#9ca3af", "#f6f7fb"),
}

HEAD = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" font-family="%s" '
    'font-size="%d" role="img" aria-label="{label}">\n'
    '  <defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
    'orient="auto"><path d="M0 0 L10 5 L0 10z" fill="%s"/></marker></defs>\n'
) % (FONT_FAMILY, FONT_SIZE, LINE)

LINE_HEIGHT = 16    # between lines of one text
TITLE_GAP = 18      # between a box's title and its first subtitle line
BOX_PAD_X = 14      # room left and right of the text in a box sized to its text
BOX_PAD_Y = 12
ARROW_GAP = 2       # an arrow stops this far short of the box it points at
ASCENT = 0.72       # text box height above the baseline, in em (cap and ascender height)
DESCENT = 0.21      # and below it (descenders)
CAP = 0.71          # cap height in em, used to centre text vertically

# ---------------------------------------------------------------------------------------------
# Text width
#
# Advance widths in thousandths of an em for the house font as Chrome draws it on macOS
# (SF Pro Text at 12 px), measured with getComputedTextLength. Summing them is within 0.5% of
# the browser for ordinary text; kerned pairs such as "AV" come out slightly wide, the safe side.

_NORMAL = [
    281, 311, 478, 630, 630, 925, 711, 297, 382, 382, 472, 630, 297, 472, 297, 305, 630, 464, 604,
    627, 644, 618, 637, 588, 639, 637, 297, 297, 630, 630, 630, 513, 918, 674, 657, 716, 727, 596,
    572, 747, 742, 268, 538, 659, 568, 874, 742, 771, 635, 771, 653, 637, 634, 737, 674, 968, 679,
    655, 662, 382, 305, 382, 630, 546, 500, 552, 614, 560, 614, 571, 362, 609, 588, 247, 247, 543,
    253, 870, 584, 591, 610, 609, 390, 514, 363, 584, 542, 774, 524, 543, 539, 382, 259, 382, 630]
_BOLD = [
    258, 356, 569, 671, 671, 1036, 745, 348, 429, 429, 484, 671, 348, 484, 348, 335, 685, 512, 643,
    669, 687, 664, 684, 623, 694, 684, 348, 348, 671, 671, 671, 557, 927, 732, 693, 741, 748, 622,
    598, 760, 783, 318, 601, 710, 595, 907, 768, 787, 674, 787, 694, 675, 660, 760, 721, 1009, 729,
    708, 676, 429, 335, 429, 671, 590, 500, 590, 651, 587, 651, 601, 413, 646, 632, 287, 287, 602,
    295, 932, 627, 620, 647, 647, 440, 557, 417, 627, 583, 847, 581, 597, 566, 429, 299, 429, 671]
_EXTRA_CHARS = "…–—→←↑↓≤≥µ×·°±≈≠é’‘“”•∞½"
_EXTRA_NORMAL = [805, 584, 874, 906, 906, 781, 781, 630, 630, 614, 630, 297, 472, 630, 630, 630,
                 571, 297, 297, 459, 459, 472, 904, 813]
_EXTRA_BOLD = [954, 627, 907, 943, 943, 815, 815, 671, 671, 667, 671, 348, 484, 671, 671, 671,
               601, 348, 348, 553, 553, 484, 915, 926]
_EXTRA = (dict(zip(_EXTRA_CHARS, _EXTRA_NORMAL)), dict(zip(_EXTRA_CHARS, _EXTRA_BOLD)))


def collapse(s):
    """Text as SVG lays it out by default: runs of whitespace become one space, ends trimmed."""
    return " ".join(str(s).split())


def text_width(s, size=FONT_SIZE, bold=False):
    """Estimated width in px of one line of text, after SVG whitespace collapsing."""
    table, extra = (_BOLD, _EXTRA[1]) if bold else (_NORMAL, _EXTRA[0])
    total = 0
    for ch in collapse(s):
        o = ord(ch)
        if 32 <= o < 127:
            total += table[o - 32]
        elif ch in extra:
            total += extra[ch]
        elif unicodedata.combining(ch):
            continue
        elif unicodedata.east_asian_width(ch) in ("W", "F"):
            total += 1000
        else:
            total += 640 if bold else 600
    return total * size / 1000.0


# ---------------------------------------------------------------------------------------------
# Geometry


class Box:
    """A rectangle: a box, a group, a text's estimated extent. Points for arrows hang off it."""

    def __init__(self, x, y, w, h):
        self.x, self.y, self.w, self.h = float(x), float(y), float(w), float(h)

    x2 = property(lambda self: self.x + self.w)
    y2 = property(lambda self: self.y + self.h)
    cx = property(lambda self: self.x + self.w / 2)
    cy = property(lambda self: self.y + self.h / 2)

    def top(self, dx=0):
        return (self.cx + dx, self.y)

    def bottom(self, dx=0):
        return (self.cx + dx, self.y2)

    def left(self, dy=0):
        return (self.x, self.cy + dy)

    def right(self, dy=0):
        return (self.x2, self.cy + dy)

    def at(self, fx, fy):
        """The point at fractions fx, fy of the width and height: at(0, 0) is the top-left corner."""
        return (self.x + fx * self.w, self.y + fy * self.h)

    def __repr__(self):
        return "Box(%s, %s, %s, %s)" % (_n(self.x), _n(self.y), _n(self.w), _n(self.h))


def _n(v):
    """A number as written into the SVG: an integer when it is one, else one decimal."""
    v = round(float(v), 1)
    return str(int(v)) if v == int(v) else str(v)


def _esc(s, quote=True):
    return html.escape(str(s), quote=quote)


def _color(c, default=TEXT):
    """A colour from a hex value, a kind name (its stroke), or 'text' / 'muted' / 'line'."""
    if c is None:
        return default
    if c in KINDS:
        return KINDS[c][0]
    return {"text": TEXT, "muted": MUTED, "line": LINE}.get(c, c)


def _lines(s):
    if s is None:
        return []
    if isinstance(s, (list, tuple)):
        return [str(x) for x in s]
    return str(s).split("\n")


def box_size(title=None, subtitle=None, bold=True, size=FONT_SIZE):
    """The (width, height) a box needs to fit its title and subtitle lines, padding included."""
    lines = [(t, bold) for t in _lines(title)] + [(t, False) for t in _lines(subtitle)]
    w = max([text_width(t, size, b) for t, b in lines] or [0]) + 2 * BOX_PAD_X
    h = _block_span(len(_lines(title)), len(lines)) + size + 2 * BOX_PAD_Y
    return (2 * math.ceil(w / 2), 2 * math.ceil(h / 2))


def _block_span(n_title, n):
    """Distance from the first to the last baseline of a box's text block."""
    if n <= 1:
        return 0
    if n_title and n > n_title:
        return (n_title - 1) * LINE_HEIGHT + TITLE_GAP + (n - n_title - 1) * LINE_HEIGHT
    return (n - 1) * LINE_HEIGHT


# ---------------------------------------------------------------------------------------------
# Diagrams

_SOURCE = None      # the diagram source being run by `build`, so save() knows where it lives
_STALE = False      # build --stale: compare instead of writing
_WRITTEN = []       # (path, changed) for each save() during the current source


class Diagram:
    """One SVG in the house style. Elements are drawn in the order they are added."""

    def __init__(self, width=760, height=None, label=None, margin=10):
        if not label:
            raise ValueError("a diagram needs a label: it becomes the SVG's aria-label")
        self.width, self.height, self.label, self.margin = width, height, label, margin
        self.items = []
        self.bottom = 0.0

    # -- building blocks ----------------------------------------------------------------------

    def raw(self, svg, bottom=0):
        """Add SVG markup as it is. Pass bottom (its lowest y) if the height is automatic."""
        self.items.append("  " + svg.strip())
        self.bottom = max(self.bottom, bottom)

    def _reach(self, *ys):
        self.bottom = max([self.bottom] + [float(y) for y in ys])

    def rect(self, x, y, w, h, kind="plain", rx=0, dashed=False, fill=None, stroke=None,
             stroke_width=None):
        stroke = _color(stroke, KINDS[kind][0])
        fill = fill or KINDS[kind][1]
        a = '<rect x="%s" y="%s" width="%s" height="%s"' % (_n(x), _n(y), _n(w), _n(h))
        if rx:
            a += ' rx="%s"' % _n(rx)
        a += ' fill="%s" stroke="%s"' % (fill, stroke)
        if stroke_width:
            a += ' stroke-width="%s"' % _n(stroke_width)
        if dashed:
            a += ' stroke-dasharray="%s"' % (dashed if isinstance(dashed, str) else "4 3")
        self.items.append("  " + a + "/>")
        self._reach(y + h)
        return Box(x, y, w, h)

    def text(self, x, y, s, color=None, anchor="start", bold=False, size=None):
        """Text with its baseline at y. A newline starts another line, 16 px lower. Returns its
        estimated box."""
        size = size or FONT_SIZE
        color = _color(color)
        lines = _lines(s)
        boxes = []
        for i, line in enumerate(lines):
            ly = y + i * LINE_HEIGHT
            a = '<text x="%s" y="%s"' % (_n(x), _n(ly))
            if anchor != "start":
                a += ' text-anchor="%s"' % anchor
            if bold:
                a += ' font-weight="700"'
            if size != FONT_SIZE:
                a += ' font-size="%s"' % _n(size)
            self.items.append("  %s fill=\"%s\">%s</text>" % (a, color, _esc(line, False)))
            boxes.append(text_box(x, ly, line, anchor, bold, size))
        x1 = min(b.x for b in boxes)
        x2 = max(b.x2 for b in boxes)
        box = Box(x1, boxes[0].y, x2 - x1, boxes[-1].y2 - boxes[0].y)
        self._reach(box.y2)
        return box

    def note(self, x, y, s, anchor="start"):
        """Muted text, for captions and side notes."""
        return self.text(x, y, s, MUTED, anchor)

    def box(self, x, y, w=None, h=None, title=None, subtitle=None, kind="plain", rx=8, dashed=False,
            emphasis=False, bold=True, fill=None, stroke=None, stroke_width=None):
        """A box with a title and muted subtitle lines (a string with newlines, or a list),
        centred. Leave w or h out to size the box to its text. emphasis draws a heavier border
        and colours the title like the border."""
        fw, fh = box_size(title, subtitle, bold)
        w = fw if w is None else w
        h = fh if h is None else h
        if emphasis and stroke_width is None:
            stroke_width = 1.5
        b = self.rect(x, y, w, h, kind, rx, dashed, fill, stroke, stroke_width)
        titles, subs = _lines(title), _lines(subtitle)
        span = _block_span(len(titles), len(titles) + len(subs))
        base = round(y + (h - span - CAP * FONT_SIZE) / 2 + CAP * FONT_SIZE)
        title_color = _color(stroke, KINDS[kind][0]) if emphasis else TEXT
        for i, t in enumerate(titles):
            self.text(b.cx, base, t, title_color, "middle", bold)
            base += LINE_HEIGHT if i < len(titles) - 1 else TITLE_GAP
        for t in subs:
            self.text(b.cx, base, t, MUTED, "middle")
            base += LINE_HEIGHT
        b.title, b.subtitle = title, subtitle
        return b

    def group(self, x, y, w, h, title=None, kind="neutral", dashed=False, rx=10, fill=None,
              stroke=None, stroke_width=None, title_color=None):
        """A container drawn behind what sits in it (add it first), titled at the top left."""
        if dashed is True:
            dashed = "5 4"
        b = self.rect(x, y, w, h, kind, rx, dashed, fill, stroke, stroke_width)
        if title:
            self.text(x + 14, y + 20, title, title_color, bold=True)
        return b

    # -- lines ----------------------------------------------------------------------------------

    def route(self, points, label=None, dashed=False, color=None, head=True, label_at=None,
              label_anchor=None, fill=None, width=None):
        """A line through points, with an arrowhead at the end unless head is False. The label
        goes beside the longest segment unless label_at gives its (x, y). fill (a colour or a
        kind) fills the shape the points enclose; width sets the stroke width."""
        pts = [(float(x), float(y)) for x, y in points]
        color = _color(color, LINE)
        d = "M%s %s" % (_n(pts[0][0]), _n(pts[0][1]))
        for (px, py), (x, y) in zip(pts, pts[1:]):
            if py == y:
                d += " H%s" % _n(x)
            elif px == x:
                d += " V%s" % _n(y)
            else:
                d += " L%s %s" % (_n(x), _n(y))
        if fill in KINDS:
            fill = KINDS[fill][1]
        self._path(d, color, dashed, head, fill or (len(pts) > 2 and "none"), width)
        self._reach(*[y for _, y in pts])
        if label:
            self._label(pts, label, color, label_at, label_anchor)
        return pts

    def arrow(self, a, b, label=None, dashed=False, color=None, head=True, label_at=None,
              label_anchor=None):
        """An arrow from a to b. Each end is an (x, y) point or a Box. Between two boxes it runs
        straight across where they face each other, or bends once if they do not."""
        return self.route(_connect(a, b), label, dashed, color, head, label_at, label_anchor)

    def line(self, a, b, dashed=False, color=None):
        return self.route([a, b], dashed=dashed, color=color, head=False)

    def curve(self, p0, c1, c2, p1, label=None, dashed=False, color=None, head=True, label_at=None,
              label_anchor="start"):
        """A cubic Bézier from p0 to p1 with control points c1 and c2."""
        color = _color(color, LINE)
        d = "M%s %s C%s %s %s %s %s %s" % tuple(_n(v) for v in p0 + c1 + c2 + p1)
        self._path(d, color, dashed, head, "none")
        self._reach(p0[1], c1[1], c2[1], p1[1])
        if label:
            mid = _cubic(p0, c1, c2, p1, 0.5)
            self._label([mid, mid], label, color, label_at or (mid[0] + 8, mid[1] + 4), label_anchor)

    def _path(self, d, color, dashed, head, fill, width=None):
        a = '<path d="%s" stroke="%s"' % (d, color)
        if width:
            a += ' stroke-width="%s"' % _n(width)
        if dashed:
            a += ' stroke-dasharray="%s"' % (dashed if isinstance(dashed, str) else "4 3")
        if fill:
            a += ' fill="%s"' % fill
        if head:
            a += ' marker-end="url(#a)"'
        self.items.append("  " + a + "/>")

    def _label(self, pts, label, color, at, anchor):
        color = MUTED if color == LINE else color
        if at is None:
            seg = max(zip(pts, pts[1:]), key=lambda s: math.hypot(s[1][0] - s[0][0], s[1][1] - s[0][1]))
            (x1, y1), (x2, y2) = seg
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            if x1 == x2:
                at, anchor = (mx + 8, my + 4), anchor or "start"
            else:
                at, anchor = (mx, my - 8), anchor or "middle"
        return self.text(at[0], at[1], label, color, anchor or "middle")

    # -- timelines ------------------------------------------------------------------------------

    def timeline(self, y, x1=60, x2=None, label="time", domain=None, mark_top=None):
        """A time axis at height y. Marks and windows are placed along it; see Timeline.
        mark_top is where marks' lines start by default (90 px above the axis)."""
        return Timeline(self, y, x1, self.width - 20 if x2 is None else x2, label, domain,
                        y - 90 if mark_top is None else mark_top)

    # -- output ---------------------------------------------------------------------------------

    def svg(self):
        h = self.height if self.height is not None else math.ceil(self.bottom + self.margin)
        head = HEAD.format(w=_n(self.width), h=_n(h), label=_esc(self.label))
        return head + "\n".join(self.items) + "\n</svg>\n"

    def check(self, tolerance=1):
        """Problems the checker finds in this diagram, as a list of Problem."""
        return check_text(self.svg(), "<diagram>", tolerance)

    def save(self, path=None):
        """Write the SVG. A relative path, or none, is taken beside the diagram source: by
        default the source's name with .svg. Leaves the file alone if it would not change."""
        src = _SOURCE or getattr(sys.modules.get("__main__"), "__file__", None)
        if path is None:
            if not src:
                raise ValueError("save() needs a path when not run from a diagram source")
            path = os.path.splitext(os.path.basename(src))[0] + ".svg"
        if not os.path.isabs(path):
            path = os.path.join(os.path.dirname(os.path.abspath(src)) if src else os.getcwd(), path)
        out = self.svg()
        old = None
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                old = f.read()
        changed = old != out
        if changed and not _STALE:
            with open(path, "w", encoding="utf-8") as f:
                f.write(out)
        _WRITTEN.append((path, changed))
        if _SOURCE is None:
            for p in check_text(out, path):
                print(p, file=sys.stderr)
        return path


class Timeline:
    """An axis with vertical marks and shaded windows. Positions are x coordinates, or values in
    domain=(start, end) if one was given, spread over the axis."""

    def __init__(self, d, y, x1, x2, label, domain, mark_top):
        self.d, self.y, self.x1, self.x2, self.domain, self.mark_top = d, y, x1, x2, domain, mark_top
        self.labels = []
        d.route([(x1, y), (x2, y)])
        if label:
            d.note(x2, y + 16, label, "end")

    def x(self, t):
        if self.domain is None:
            return t
        a, b = self.domain
        return self.x1 + (t - a) / float(b - a) * (self.x2 - self.x1)

    def mark(self, t, label, top=None, color=None, anchor="middle", label_y=None):
        """A dashed vertical line from top down to the axis, labelled in bold above it. Without
        label_y, a label that would collide with an earlier mark's label moves up 16 px at a
        time, its line growing with it."""
        x = self.x(t)
        top = self.mark_top if top is None else top
        ly = top - 6 if label_y is None else label_y
        if label_y is None:
            while any(_hits(text_box(x, ly, label, anchor, True), b, 4) for b in self.labels):
                ly -= LINE_HEIGHT
                top -= LINE_HEIGHT
        color = _color(color)
        self.d.raw('<path d="M%s %s V%s" stroke="%s" stroke-dasharray="3 3"/>'
                   % (_n(x), _n(top), _n(self.y), color))
        b = self.d.text(x, ly, label, color, anchor, bold=True)
        self.labels.append(b)
        return b

    def window(self, t1, t2, label=None, kind="state", height=22, top=None):
        """A shaded span from t1 to t2, sitting on the axis unless top is given."""
        x1, x2 = self.x(t1), self.x(t2)
        top = self.y - 2 - height if top is None else top
        stroke, fill = KINDS[kind]
        b = self.d.rect(x1, top, x2 - x1, height, fill=fill, stroke=stroke)
        if label:
            base = round(top + (height + CAP * FONT_SIZE) / 2)
            self.d.text((x1 + x2) / 2, base, label, stroke, "middle", bold=True)
        return b


def _connect(a, b):
    """The points of an arrow from a to b, where each is a point or a Box."""
    if isinstance(a, Box) and isinstance(b, Box):
        lo, hi = max(a.y, b.y), min(a.y2, b.y2)
        if lo < hi:
            y = (lo + hi) / 2
            if b.x >= a.x2:
                return [(a.x2, y), (b.x - ARROW_GAP, y)]
            if b.x2 <= a.x:
                return [(a.x, y), (b.x2 + ARROW_GAP, y)]
        lo, hi = max(a.x, b.x), min(a.x2, b.x2)
        if lo < hi:
            x = (lo + hi) / 2
            if b.y >= a.y2:
                return [(x, a.y2), (x, b.y - ARROW_GAP)]
            if b.y2 <= a.y:
                return [(x, a.y), (x, b.y2 + ARROW_GAP)]
        # no shared span: leave a sideways, then turn into b's top or bottom
        sx = a.x2 if b.cx > a.cx else a.x
        ey = b.y - ARROW_GAP if b.cy > a.cy else b.y2 + ARROW_GAP
        return [(sx, a.cy), (b.cx, a.cy), (b.cx, ey)]
    if isinstance(a, Box):
        return [p for p in reversed(_connect_point(b, a, 0))]
    if isinstance(b, Box):
        return _connect_point(a, b, ARROW_GAP)
    return [a, b]


def _connect_point(p, box, gap):
    """From point p to the nearest edge of box, square to that edge where possible."""
    px, py = p
    if box.x <= px <= box.x2:
        return [p, (px, box.y - gap if py < box.y else box.y2 + gap)]
    if box.y <= py <= box.y2:
        return [p, (box.x - gap if px < box.x else box.x2 + gap, py)]
    end = (box.x - gap, box.cy) if px < box.x else (box.x2 + gap, box.cy)
    return [p, end]


def _cubic(p0, c1, c2, p1, t):
    u = 1 - t
    return tuple(u * u * u * a + 3 * u * u * t * b + 3 * u * t * t * c + t * t * t * d
                 for a, b, c, d in zip(p0, c1, c2, p1))


def text_box(x, y, s, anchor="start", bold=False, size=FONT_SIZE):
    """The estimated box of one line of text with its baseline at y."""
    w = text_width(s, size, bold)
    x1 = x - w / 2 if anchor == "middle" else x - w if anchor == "end" else x
    return Box(x1, y - ASCENT * size, w, (ASCENT + DESCENT) * size)


def _hits(a, b, margin=0):
    return (a.x < b.x2 + margin and b.x < a.x2 + margin and
            a.y < b.y2 + margin and b.y < a.y2 + margin)


# ---------------------------------------------------------------------------------------------
# Checker


class Problem:
    def __init__(self, file, rule, message, boxes=()):
        self.file, self.rule, self.message, self.boxes = file, rule, message, list(boxes)

    def __str__(self):
        return "%s: %s: %s" % (self.file, self.rule, self.message)

    def __repr__(self):
        return "Problem(%r, %r)" % (self.rule, self.message)


class _Text:
    def __init__(self, box, s, raw_x, raw_y):
        self.box, self.s, self.raw_x, self.raw_y = box, s, raw_x, raw_y

    def __str__(self):
        s = self.s if len(self.s) <= 40 else self.s[:37] + "..."
        return '"%s" at (%s, %s)' % (s, self.raw_x, self.raw_y)


class Analysis:
    """What the checker reads from an SVG: text boxes, rects, stroked line segments, viewBox."""

    def __init__(self):
        self.texts, self.rects, self.segments, self.viewbox = [], [], [], None


_SKIP = {"defs", "marker", "symbol", "clipPath", "mask", "pattern", "style", "title", "desc",
         "metadata", "script", "linearGradient", "radialGradient", "filter"}
_NUM = r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?"


def _local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _attrs(el):
    a = dict((_local(k), v) for k, v in el.attrib.items())
    for part in a.pop("style", "").split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            a[k.strip()] = v.strip()
    return a


def _num(v, default=None):
    m = re.match(r"\s*(" + _NUM + ")", v or "")
    return float(m.group(1)) if m else default


def _font_size(v, inherited):
    if not v:
        return inherited
    n = _num(v)
    if n is None:
        return inherited
    if v.strip().endswith("em"):
        return n * inherited
    if v.strip().endswith("%"):
        return n * inherited / 100
    return n


def _translate(v):
    """(dx, dy) for a transform that is only translates; None for anything else."""
    v = (v or "").strip()
    dx = dy = 0.0
    while v:
        m = re.match(r"translate\(\s*(%s)(?:[\s,]+(%s))?\s*\)\s*,?\s*" % (_NUM, _NUM), v)
        if not m:
            return None
        dx += float(m.group(1))
        dy += float(m.group(2) or 0)
        v = v[m.end():]
    return dx, dy


def analyze(root):
    """Read an SVG's parsed root element into an Analysis."""
    an = Analysis()
    a = _attrs(root)
    vb = [float(v) for v in re.findall(_NUM, a.get("viewBox", ""))]
    if len(vb) == 4:
        an.viewbox = Box(*vb)
    elif _num(a.get("width")) and _num(a.get("height")):
        an.viewbox = Box(0, 0, _num(a["width"]), _num(a["height"]))
    state = {"size": 16.0, "bold": False, "anchor": "start", "baseline": "auto", "dx": 0.0,
             "dy": 0.0, "stroke": "none", "fill": "black", "stroke-opacity": "1", "opacity": "1"}
    _walk(root, state, an)
    return an


def _walk(el, state, an):
    name = _local(el.tag)
    if name in _SKIP:
        return
    a = _attrs(el)
    if a.get("data-check") == "off" or a.get("display") == "none" or a.get("visibility") == "hidden":
        return
    st = dict(state)
    if "transform" in a:
        t = _translate(a["transform"])
        if t is None:
            return      # scaled or rotated: the estimates would be wrong, so leave it out
        st["dx"] += t[0]
        st["dy"] += t[1]
    st["size"] = _font_size(a.get("font-size"), st["size"])
    w = a.get("font-weight")
    if w:
        st["bold"] = w in ("bold", "bolder") or (_num(w) or 400) >= 600
    for k, attr in (("anchor", "text-anchor"), ("baseline", "dominant-baseline"), ("stroke", "stroke"),
                    ("fill", "fill"), ("stroke-opacity", "stroke-opacity"), ("opacity", "opacity")):
        if a.get(attr):
            st[k] = a[attr]
    if _opacity(st["opacity"]) < 0.3:
        return
    if name == "text":
        _read_text(el, a, st, an)
        return
    if name == "rect":
        w, h = _num(a.get("width"), 0), _num(a.get("height"), 0)
        if w > 0 and h > 0 and not (_none(st["fill"]) and _none(st["stroke"])):
            an.rects.append(Box(_num(a.get("x"), 0) + st["dx"], _num(a.get("y"), 0) + st["dy"], w, h))
    stroked = not _none(st["stroke"]) and not _faint(st["stroke"]) and _opacity(st["stroke-opacity"]) >= 0.3
    if stroked and name in ("path", "line", "polyline", "polygon"):
        if name == "path":
            polys = _path_polylines(a.get("d", ""))
        elif name == "line":
            polys = [[(_num(a.get("x1"), 0), _num(a.get("y1"), 0)), (_num(a.get("x2"), 0), _num(a.get("y2"), 0))]]
        else:
            nums = [float(v) for v in re.findall(_NUM, a.get("points", ""))]
            poly = list(zip(nums[0::2], nums[1::2]))
            polys = [poly + poly[:1] if name == "polygon" else poly]
        for poly in polys:
            for p, q in zip(poly, poly[1:]):
                an.segments.append(((p[0] + st["dx"], p[1] + st["dy"]), (q[0] + st["dx"], q[1] + st["dy"])))
    for child in el:
        _walk(child, st, an)


def _none(c):
    return c.strip() in ("none", "transparent")


def _opacity(v):
    n = _num(v, 1.0)
    return n / 100 if v.strip().endswith("%") else n


def _faint(c):
    """Whether a stroke colour is so light (gridlines, hairlines) that text may sit on it."""
    m = re.match(r"\s*#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})\s*$", c)
    if not m:
        return c.strip() in ("white", "whitesmoke", "snow", "ivory")
    h = m.group(1)
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    rgb = [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    lin = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2] > FAINT


def _read_text(el, a, st, an):
    """Split a <text> into lines (a <tspan> with its own x, y or dy starts one) and box each."""
    x0, y0 = _num(a.get("x"), 0), _num(a.get("y"), 0)
    lines = [[x0, y0, a.get("x", "0"), a.get("y", "0"), []]]     # x, y, raw x, raw y, pieces

    def add(s, size, bold):
        if s:
            lines[-1][4].append((s, size, bold))

    add(el.text, st["size"], st["bold"])
    for child in el:
        if _local(child.tag) != "tspan":
            add(child.tail, st["size"], st["bold"])
            continue
        ca = _attrs(child)
        if ca.get("data-check") == "off":
            add(child.tail, st["size"], st["bold"])
            continue
        size = _font_size(ca.get("font-size"), st["size"])
        cw = ca.get("font-weight")
        bold = (cw in ("bold", "bolder") or (_num(cw) or 400) >= 600) if cw else st["bold"]
        if any(k in ca for k in ("x", "y", "dy")):
            cur = lines[-1]
            nx = _num(ca.get("x"), cur[0])
            ny = _num(ca.get("y"), cur[1]) + _num(ca.get("dy"), 0)
            lines.append([nx, ny, ca.get("x", cur[2]), ca.get("y", _n(ny)), []])
        add("".join(child.itertext()), size, bold)
        add(child.tail, st["size"], st["bold"])
    shift = {"middle": 0.35, "central": 0.35, "hanging": ASCENT, "text-before-edge": ASCENT}
    for x, y, rx, ry, pieces in lines:
        chars = _collapse_chars([(ch, size, bold) for s, size, bold in pieces for ch in s])
        if not chars:
            continue
        s = "".join(c[0] for c in chars)
        size = max(c[1] for c in chars)
        w = sum(text_width(ch, sz, b) if ch != " " else text_width("a a", sz, b) - text_width("aa", sz, b)
                for ch, sz, b in chars)
        anchor = st["anchor"]
        x += st["dx"]
        y += st["dy"] + shift.get(st["baseline"], 0) * size
        x1 = x - w / 2 if anchor == "middle" else x - w if anchor == "end" else x
        box = Box(x1, y - ASCENT * size, w, (ASCENT + DESCENT) * size)
        an.texts.append(_Text(box, s, rx, ry))


def _collapse_chars(chars):
    """collapse() over (char, size, bold) triples: one space per run of whitespace, ends trimmed."""
    out = []
    for ch, size, bold in chars:
        if ch.isspace():
            if out and out[-1][0] != " ":
                out.append((" ", size, bold))
        else:
            out.append((ch, size, bold))
    while out and out[-1][0] == " ":
        out.pop()
    return out


def _path_polylines(d):
    """The polylines a path's outline follows; curves are sampled, arcs become chords."""
    toks = re.findall(r"[A-Za-z]|" + _NUM, d)
    nargs = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7}
    out, poly = [], []
    x = y = sx = sy = 0.0
    cmd, prev, ctrl = None, None, None
    i = 0
    while i < len(toks):
        t = toks[i]
        if t.isalpha():
            cmd = t
            i += 1
            if cmd in "Zz":
                poly.append((sx, sy))
                x, y, prev = sx, sy, "Z"
            continue
        up = (cmd or "").upper()
        if up not in nargs or i + nargs[up] > len(toks) or any(v.isalpha() for v in toks[i:i + nargs[up]]):
            break
        v = [float(n) for n in toks[i:i + nargs[up]]]
        i += nargs[up]
        rel = cmd.islower()
        ox, oy = (x, y) if rel else (0.0, 0.0)
        if up == "M":
            if len(poly) > 1:
                out.append(poly)
            x, y = ox + v[0], oy + v[1]
            poly, sx, sy = [(x, y)], x, y
            cmd = "l" if rel else "L"
        elif up == "L" or up == "T" or up == "A":
            ex, ey = (ox + v[-2], oy + v[-1])
            if up == "T":
                c = (2 * x - ctrl[0], 2 * y - ctrl[1]) if prev in ("Q", "T") and ctrl else (x, y)
                poly += [_quad((x, y), c, (ex, ey), k / 8.0) for k in range(1, 9)]
                ctrl = c
            else:
                poly.append((ex, ey))
            x, y = ex, ey
        elif up == "H":
            x = ox + v[0]
            poly.append((x, y))
        elif up == "V":
            y = oy + v[0]
            poly.append((x, y))
        elif up in ("C", "S"):
            if up == "C":
                c1 = (ox + v[0], oy + v[1])
                rest = v[2:]
            else:
                c1 = (2 * x - ctrl[0], 2 * y - ctrl[1]) if prev in ("C", "S") and ctrl else (x, y)
                rest = v
            c2, e = (ox + rest[0], oy + rest[1]), (ox + rest[2], oy + rest[3])
            poly += [_cubic((x, y), c1, c2, e, k / 12.0) for k in range(1, 13)]
            ctrl, (x, y) = c2, e
        elif up == "Q":
            c, e = (ox + v[0], oy + v[1]), (ox + v[2], oy + v[3])
            poly += [_quad((x, y), c, e, k / 8.0) for k in range(1, 9)]
            ctrl, (x, y) = c, e
        prev = up
    if len(poly) > 1:
        out.append(poly)
    return out


def _quad(p0, c, p1, t):
    u = 1 - t
    return tuple(u * u * a + 2 * u * t * b + t * t * d for a, b, d in zip(p0, c, p1))


def _seg_hits(p, q, r):
    """Whether the segment p-q passes through the inside of Box r (Liang-Barsky clipping)."""
    x0, y0 = p
    dx, dy = q[0] - x0, q[1] - y0
    t0, t1 = 0.0, 1.0
    for pk, qk in ((-dx, x0 - r.x), (dx, r.x2 - x0), (-dy, y0 - r.y), (dy, r.y2 - y0)):
        if pk == 0:
            if qk <= 0:
                return False
            continue
        t = qk / pk
        if pk < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 >= t1:
            return False
    return True


def _shrink(b, d):
    return Box(b.x + d, b.y + d, max(b.w - 2 * d, 0), max(b.h - 2 * d, 0))


def _inside(b, x, y):
    return b.x <= x <= b.x2 and b.y <= y <= b.y2


def _rect_str(r):
    return "(%s, %s, %s x %s)" % (_n(r.x), _n(r.y), _n(r.w), _n(r.h))


FAINT = 0.7         # relative luminance above which a stroke is too faint to count as a line
EDGE_CLEARANCE = 2  # px a text must keep from the left and right edges of its box


def find_problems(an, file="", tolerance=1):
    """Problems in an Analysis. Overlaps smaller than tolerance px either way are let through."""
    probs = []
    texts = an.texts
    for i, a in enumerate(texts):
        for b in texts[i + 1:]:
            ox = min(a.box.x2, b.box.x2) - max(a.box.x, b.box.x)
            oy = min(a.box.y2, b.box.y2) - max(a.box.y, b.box.y)
            if ox > tolerance and oy > tolerance:
                probs.append(Problem(file, "text-overlap", "%s overlaps %s by %s x %s px"
                                     % (a, b, _n(ox), _n(oy)), [a.box, b.box]))
    for t in texts:
        b = t.box
        holders = [r for r in an.rects if _inside(r, b.cx, b.cy)]
        if holders:
            r = min(holders, key=lambda r: r.w * r.h)
            gaps = [("left", b.x - r.x, EDGE_CLEARANCE - tolerance), ("right", r.x2 - b.x2, EDGE_CLEARANCE - tolerance),
                    ("top", b.y - r.y, -tolerance), ("bottom", r.y2 - b.y2, -tolerance)]
            bad = [(side, gap) for side, gap, least in gaps if gap < least]
            if bad:
                side, gap = min(bad, key=lambda g: g[1])
                how = ("runs %s px past" % _n(-gap)) if gap < 0 else "is %s px from" % _n(gap)
                probs.append(Problem(file, "text-overflow", "%s %s the %s edge of its box %s"
                                     % (t, how, side, _rect_str(r)), [b, r]))
        inner = _shrink(b, tolerance)
        for r in an.rects:
            if not _inside(r, b.cx, b.cy) and _hits(inner, r) and not _contains(r, inner):
                probs.append(Problem(file, "text-on-box", "%s crosses the edge of the box %s"
                                     % (t, _rect_str(r)), [b, r]))
        for p, q in an.segments:
            if _seg_hits(p, q, inner):
                probs.append(Problem(file, "text-on-line", "%s is crossed by the line (%s, %s)-(%s, %s)"
                                     % (t, _n(p[0]), _n(p[1]), _n(q[0]), _n(q[1])), [b]))
                break
        v = an.viewbox
        if v is not None and not _contains(_grow(v, tolerance), b):
            probs.append(Problem(file, "outside", "%s runs past the viewBox %s" % (t, _rect_str(v)), [b]))
    return probs


def _contains(outer, inner):
    return (outer.x <= inner.x and inner.x2 <= outer.x2 and outer.y <= inner.y and inner.y2 <= outer.y2)


def _grow(b, d):
    return Box(b.x - d, b.y - d, b.w + 2 * d, b.h + 2 * d)


def _parse(text, file):
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        return None, [Problem(file, "xml", "not well-formed XML: %s" % e)]
    if _local(root.tag) != "svg":
        return None, [Problem(file, "xml", "the root element is <%s>, not <svg>" % _local(root.tag))]
    return root, []


def check_text(text, file="<svg>", tolerance=1):
    """Problems in SVG source text."""
    root, probs = _parse(text, file)
    if root is None:
        return probs
    return find_problems(analyze(root), file, tolerance)


def check_file(path, tolerance=1):
    with open(path, "rb") as f:
        data = f.read()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return [Problem(path, "xml", "not UTF-8")]
    return check_text(text, path, tolerance)


# ---------------------------------------------------------------------------------------------
# Rendering to PNG with headless Chrome

CHROME_PATHS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
]


def find_chrome(given=None):
    for c in [given, os.environ.get("SVGKIT_CHROME")] + CHROME_PATHS:
        if c and os.path.exists(c):
            return c
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"):
        p = shutil.which(name)
        if p:
            return p
    return None


def overlay(text, problems=(), tolerance=1):
    """The SVG with every estimated text box outlined in grey and the boxes in problems in red."""
    root, _ = _parse(text, "")
    if root is None:
        return text
    an = analyze(root)
    marks = ['<g data-check="off" fill="none" stroke-width="0.75">']
    for t in an.texts:
        marks.append('<rect x="%s" y="%s" width="%s" height="%s" stroke="#94a3b8" stroke-dasharray="2 2"/>'
                     % (_n(t.box.x), _n(t.box.y), _n(t.box.w), _n(t.box.h)))
    for p in problems:
        for b in p.boxes:
            marks.append('<rect x="%s" y="%s" width="%s" height="%s" stroke="#dc2626" stroke-width="1.25"/>'
                         % (_n(b.x), _n(b.y), _n(b.w), _n(b.h)))
    marks.append("</g>")
    i = text.rfind("</svg>")
    return text[:i] + "\n".join(marks) + "\n" + text[i:]


def render_png(svg_text, png_path, chrome, scale=2):
    """Draw svg_text on a white page at its viewBox size and screenshot it to png_path."""
    root, _ = _parse(svg_text, "")
    w, h = 800, 600
    if root is not None:
        an = analyze(root)
        if an.viewbox is not None:
            w, h = int(math.ceil(an.viewbox.w)), int(math.ceil(an.viewbox.h))
    body = re.sub(r"^\s*(<\?xml[^>]*\?>|<!DOCTYPE[^>]*>)\s*", "", svg_text)
    work = tempfile.mkdtemp(prefix="svgkit-chrome-")
    try:
        page = os.path.join(work, "page.html")
        with open(page, "w", encoding="utf-8") as f:
            f.write("<!doctype html><meta charset=utf-8><style>html,body{margin:0;background:#fff}"
                    "svg{display:block;width:%dpx;height:%dpx}</style>%s" % (w, h, body))
        cmd = [chrome, "--headless", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
               "--no-default-browser-check", "--user-data-dir=" + os.path.join(work, "profile"),
               "--force-device-scale-factor=%s" % scale, "--window-size=%d,%d" % (w, h),
               "--screenshot=" + os.path.abspath(png_path), "file://" + page]
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        if not os.path.exists(png_path):
            raise RuntimeError("Chrome wrote no screenshot: %s" % r.stderr.decode("utf-8", "replace")[-500:])
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return png_path


# ---------------------------------------------------------------------------------------------
# Command line

_SKIP_DIRS = {"node_modules", "__pycache__", "venv", ".venv"}
_IMPORTS = re.compile(r"^\s*(?:from\s+svgkit\s+import|import\s+svgkit\b)", re.M)


def _walk_files(paths, ext):
    for p in paths:
        if os.path.isfile(p):
            yield p
            continue
        for d, dirs, files in os.walk(p):
            dirs[:] = sorted(x for x in dirs if not x.startswith(".") and x not in _SKIP_DIRS)
            for f in sorted(files):
                if f.endswith(ext):
                    yield os.path.join(d, f)


def find_sources(paths):
    """Diagram sources under paths: .py files that import svgkit, except this file and names
    starting with _ (shared helpers)."""
    me = os.path.abspath(__file__)
    out = []
    for f in _walk_files(paths, ".py"):
        if os.path.basename(f).startswith("_") or os.path.abspath(f) == me:
            continue
        with open(f, encoding="utf-8", errors="replace") as fh:
            if _IMPORTS.search(fh.read()):
                out.append(f)
    return out


def _rel(p):
    r = os.path.relpath(p)
    return p if r.startswith("..") else r


def report(problems, files, out=None):
    """Print problems grouped by file and a summary line."""
    out = out or sys.stdout
    by_file = {}
    for p in problems:
        by_file.setdefault(p.file, []).append(p)
    for f, ps in by_file.items():
        print("%s: %d problem%s" % (_rel(f), len(ps), "" if len(ps) == 1 else "s"), file=out)
        for p in ps:
            print("  %-14s %s" % (p.rule, p.message), file=out)
    n = len(files)
    if problems:
        print("checked %d SVG file%s: %d problem%s in %d file%s" % (
            n, "" if n == 1 else "s", len(problems), "" if len(problems) == 1 else "s",
            len(by_file), "" if len(by_file) == 1 else "s"), file=out)
    else:
        print("checked %d SVG file%s: no problems" % (n, "" if n == 1 else "s"), file=out)


def cmd_check(args):
    files = list(_walk_files(args.paths, ".svg"))
    problems = []
    for f in files:
        problems += check_file(f, args.tolerance)
    report(problems, files)
    if args.png or args.boxes:
        chrome = find_chrome(args.chrome)
        if not chrome:
            print("no Chrome found: pass --chrome or set SVGKIT_CHROME", file=sys.stderr)
            return 2
        out = args.out or tempfile.mkdtemp(prefix="svgkit-")
        os.makedirs(out, exist_ok=True)
        print("rendering %d SVG file%s to %s" % (len(files), "" if len(files) == 1 else "s", out))
        for f in files:
            with open(f, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            if args.boxes:
                text = overlay(text, [p for p in problems if p.file == f], args.tolerance)
            name = re.sub(r"[\\/]+", "__", _rel(f).lstrip("./"))[:-4] + ".png"
            png = os.path.join(out, name)
            try:
                render_png(text, png, chrome)
                print("  " + png)
            except (RuntimeError, subprocess.SubprocessError, OSError) as e:
                print("  %s: could not render: %s" % (f, e), file=sys.stderr)
                return 2
    return 1 if problems else 0


def run_source(path, stale=False):
    """Run one diagram source. Returns ([(svg path, changed)], error text or None)."""
    global _SOURCE, _STALE, _WRITTEN
    _SOURCE, _STALE, _WRITTEN = os.path.abspath(path), stale, []
    here = os.getcwd()
    sys.path.insert(0, os.path.dirname(_SOURCE))
    err = None
    try:
        os.chdir(os.path.dirname(_SOURCE))
        runpy.run_path(_SOURCE, run_name="__main__")
    except SystemExit as e:
        if e.code not in (None, 0):
            err = "exited with %s" % e.code
    except Exception:
        err = traceback.format_exc()
    finally:
        os.chdir(here)
        sys.path.remove(os.path.dirname(_SOURCE))
        written = _WRITTEN
        _SOURCE, _STALE, _WRITTEN = None, False, []
    return written, err


def cmd_build(args):
    sources = find_sources(args.paths)
    if not sources:
        print("no diagram sources (.py files that import svgkit) under %s" % " ".join(args.paths))
        return 0
    failed, outputs, stale = 0, [], []
    for src in sources:
        written, err = run_source(src, args.stale)
        if err:
            failed += 1
            print("%s: failed\n%s" % (_rel(src), "    " + err.rstrip().replace("\n", "\n    ")))
            continue
        if not written:
            print("%s: wrote no SVG (it never calls save())" % _rel(src))
        for path, changed in written:
            outputs.append(path)
            if args.stale:
                if changed:
                    stale.append(path)
                    print("%s: out of date (rerun build)" % _rel(path))
            else:
                print("%s %s" % ("wrote    " if changed else "unchanged", _rel(path)))
    problems = []
    if not args.no_check and not args.stale:
        for f in outputs:
            problems += check_file(f, args.tolerance)
        report(problems, outputs)
    if failed:
        print("%d of %d source%s failed" % (failed, len(sources), "" if len(sources) == 1 else "s"))
    return 1 if failed or problems or stale else 0


def cmd_measure(args):
    for s in args.text:
        print("%s  %s" % (_n(text_width(s, args.size, args.bold)), s))
    return 0


def main(argv=None):
    sys.modules.setdefault("svgkit", sys.modules[__name__])
    ap = argparse.ArgumentParser(prog="svgkit", description="Write SVG diagrams from Python sources and check SVGs for colliding text.")
    sub = ap.add_subparsers(dest="cmd")
    b = sub.add_parser("build", help="run every diagram source and write its SVG, then check it")
    b.add_argument("paths", nargs="*", default=["."], help="folders or source files (default: .)")
    b.add_argument("--stale", action="store_true", help="write nothing; fail if any SVG differs from its source")
    b.add_argument("--no-check", action="store_true", help="skip checking the SVGs written")
    b.add_argument("--tolerance", type=float, default=1, help="px of overlap let through (default 1)")
    c = sub.add_parser("check", help="check SVG files for colliding text")
    c.add_argument("paths", nargs="*", default=["."], help="folders or SVG files (default: .)")
    c.add_argument("--png", action="store_true", help="also render each SVG to PNG with headless Chrome")
    c.add_argument("--boxes", action="store_true", help="render with estimated text boxes drawn (implies --png)")
    c.add_argument("--out", help="folder for the PNGs (default: a new temporary folder)")
    c.add_argument("--chrome", help="path to Chrome or Chromium")
    c.add_argument("--tolerance", type=float, default=1, help="px of overlap let through (default 1)")
    m = sub.add_parser("measure", help="print the estimated width of text in px")
    m.add_argument("text", nargs="+")
    m.add_argument("--bold", action="store_true")
    m.add_argument("--size", type=float, default=FONT_SIZE)
    args = ap.parse_args(argv)
    if not args.cmd:
        ap.print_help(sys.stderr)
        return 2
    for p in getattr(args, "paths", []):
        if not os.path.exists(p):
            print("no such file or folder: %s" % p, file=sys.stderr)
            return 2
    return {"build": cmd_build, "check": cmd_check, "measure": cmd_measure}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
