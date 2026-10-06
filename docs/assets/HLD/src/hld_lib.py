"""Tiny SVG emitter for the Volt Debt HLD set.

Deliberately explicit: every box carries its own coordinates. Auto-layout would
have hidden the one thing these diagrams exist to show — which layer a thing sits
in — behind a solver's opinion. Coordinates are cheap; a wrong layer is not.

Rendered by src/render.py; PNGs come from the same SVGs through headless Chrome
(see src/build.sh), so the two files can never disagree.
"""

FONT = ("-apple-system,BlinkMacSystemFont,'Inter','Helvetica Neue',"
        "'Noto Sans Thai','Thonburi',Arial,sans-serif")
MONO = "'SF Mono','JetBrains Mono',Menlo,Consolas,monospace"

INK = "#14161a"
MUTED = "#6b7280"
FAINT = "#9aa1ac"
PAPER = "#fbfaf8"
HAIR = "#d9dce2"

# family -> (stroke, fill, wash) — wash is the group container tint
TONES = {
    "client":   ("#2f5fbe", "#e8eefb", "#f3f6fd"),
    "api":      ("#6b46c1", "#eee9fb", "#f6f3fd"),
    "domain":   ("#0d7f63", "#e3f4ef", "#f1faf7"),
    "data":     ("#a86412", "#fbefdd", "#fdf7ee"),
    "external": ("#a8433b", "#fbe9e7", "#fdf4f3"),
    "infra":    ("#465061", "#e9ecf1", "#f4f6f8"),
    "neutral":  ("#8b93a1", "#f0f1f4", "#f7f8f9"),
    "refusal":  ("#8b5cf6", "#f6f2ff", "#faf8ff"),
}


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


class Canvas:
    def __init__(self, width, height, layer, title, subtitle):
        self.w, self.h = width, height
        self.parts = []
        self.layer = layer
        self.title = title
        self.subtitle = subtitle

    # ---- primitives ----------------------------------------------------
    def raw(self, s):
        self.parts.append(s)

    def text(self, x, y, s, size=13, fill=INK, weight=400, anchor="start",
             font=FONT, spacing=0, opacity=1):
        self.raw(
            '<text x="%.1f" y="%.1f" font-family="%s" font-size="%s" fill="%s" '
            'font-weight="%s" text-anchor="%s" letter-spacing="%s" opacity="%s">%s</text>'
            % (x, y, font, size, fill, weight, anchor, spacing, opacity, esc(s)))

    def rect(self, x, y, w, h, rx=10, fill="#fff", stroke=None, sw=1.4, dash=None, opacity=1):
        d = ' stroke-dasharray="%s"' % dash if dash else ""
        st = ' stroke="%s" stroke-width="%s"' % (stroke, sw) if stroke else ""
        self.raw('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="%s" fill="%s"%s%s opacity="%s"/>'
                 % (x, y, w, h, rx, fill, st, d, opacity))

    def line(self, x1, y1, x2, y2, stroke=HAIR, sw=1.2, dash=None):
        d = ' stroke-dasharray="%s"' % dash if dash else ""
        self.raw('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="%s"%s/>'
                 % (x1, y1, x2, y2, stroke, sw, d))

    # ---- composites ----------------------------------------------------
    def group(self, x, y, w, h, label, tone="neutral", note=None):
        stroke, _fill, wash = TONES[tone]
        self.rect(x, y, w, h, rx=14, fill=wash, stroke=stroke, sw=1.2, dash="none", opacity=1)
        self.rect(x, y, w, h, rx=14, fill="none", stroke=stroke, sw=1.2, opacity=0.55)
        self.text(x + 16, y + 24, label.upper(), size=11.5, fill=stroke, weight=700, spacing=1.1)
        if note:
            self.text(x + w - 16, y + 24, note, size=11, fill=MUTED, anchor="end")

    def node(self, x, y, w, h, title, lines=(), tone="neutral", code=None, badge=None):
        stroke, fill, _ = TONES[tone]
        self.rect(x, y, w, h, rx=9, fill="#ffffff", stroke=stroke, sw=1.3)
        self.rect(x, y, w, 4.5, rx=2.2, fill=stroke, opacity=0.9)
        ty = y + 24
        self.text(x + 12, ty, title, size=13, fill=INK, weight=650)
        ty += 15
        for ln in lines:
            self.text(x + 12, ty, ln, size=11, fill=MUTED)
            ty += 13.5
        if code:
            self.text(x + 12, y + h - 9, code, size=10, fill=FAINT, font=MONO)
        if badge:
            bw = 7.0 * len(badge) + 14
            self.rect(x + w - bw - 9, y + 11, bw, 16, rx=8, fill=fill, stroke="none")
            self.text(x + w - bw / 2 - 9, y + 22.5, badge, size=9.5, fill=stroke,
                      weight=700, anchor="middle", spacing=0.5)

    def chip(self, x, y, w, h, label, tone="neutral", sub=None):
        stroke, fill, _ = TONES[tone]
        self.rect(x, y, w, h, rx=h / 2 if h < 34 else 9, fill=fill, stroke=stroke, sw=1.1)
        if sub:
            self.text(x + w / 2, y + h / 2 - 1, label, size=11.5, fill=INK, weight=600, anchor="middle")
            self.text(x + w / 2, y + h / 2 + 12, sub, size=9.5, fill=MUTED, anchor="middle")
        else:
            self.text(x + w / 2, y + h / 2 + 4, label, size=11.5, fill=INK, weight=600, anchor="middle")

    def arrow(self, points, label=None, tone="neutral", dashed=False, label_at=0.5,
              label_dy=-7, head_both=False, sw=1.6, label_anchor="middle"):
        stroke = TONES[tone][0]
        d = " ".join(("M" if i == 0 else "L") + " %.1f %.1f" % p for i, p in enumerate(points))
        dash = ' stroke-dasharray="6 5"' if dashed else ""
        mid = ' marker-start="url(#head-%s)"' % tone if head_both else ""
        self.raw('<path d="%s" fill="none" stroke="%s" stroke-width="%s" '
                 'stroke-linejoin="round" stroke-linecap="round"%s '
                 'marker-end="url(#head-%s)"%s/>' % (d, stroke, sw, dash, tone, mid))
        if label:
            i = max(0, min(len(points) - 2, int(label_at * (len(points) - 1))))
            (x1, y1), (x2, y2) = points[i], points[i + 1]
            lx, ly = (x1 + x2) / 2, (y1 + y2) / 2 + label_dy
            tw = 6.1 * len(label) + 12
            ax = {"middle": lx - tw / 2, "start": lx, "end": lx - tw}[label_anchor]
            self.rect(ax, ly - 11, tw, 16, rx=8, fill=PAPER, stroke="none")
            self.text(ax + tw / 2, ly + 0.5, label, size=10.5, fill=stroke, weight=600, anchor="middle")

    def note(self, x, y, w, h, lines, title=None, tone="neutral"):
        stroke, _f, wash = TONES[tone]
        self.rect(x, y, w, h, rx=9, fill=wash, stroke=stroke, sw=1.1, dash="5 4")
        ty = y + 21
        if title:
            self.text(x + 13, ty, title, size=11.5, fill=stroke, weight=700)
            ty += 16
        for ln in lines:
            self.text(x + 13, ty, ln, size=11, fill=INK if ln.startswith("•") else MUTED)
            ty += 14.5

    # ---- UML / DFD primitives (added 2026-09-20 for the dataflow and use-case sets;
    # existing sheets never call them, so their output is unchanged) --------------
    def circle(self, cx, cy, r, fill="#fff", stroke=None, sw=1.3, dash=None, opacity=1):
        d = ' stroke-dasharray="%s"' % dash if dash else ""
        st = ' stroke="%s" stroke-width="%s"' % (stroke, sw) if stroke else ""
        self.raw('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="%s"%s%s opacity="%s"/>'
                 % (cx, cy, r, fill, st, d, opacity))

    def ellipse(self, cx, cy, rx, ry, label, tone="neutral", lines=(), sub=None,
                code=None, size=11.5):
        """A UML use case. `label` may be a list of lines; `sub` is a smaller line
        under it (the guard or the role badge)."""
        stroke, fill, _ = TONES[tone]
        self.raw('<ellipse cx="%.1f" cy="%.1f" rx="%.1f" ry="%.1f" fill="%s" '
                 'stroke="%s" stroke-width="1.5"/>' % (cx, cy, rx, ry, fill, stroke))
        body = label if isinstance(label, (list, tuple)) else [label]
        body = list(body)
        extra = len(body) + (1 if sub else 0)
        ty = cy - (extra - 1) * 7.5 + 4
        for ln in body:
            self.text(cx, ty, ln, size=size, fill=INK, weight=650, anchor="middle")
            ty += 15
        if sub:
            self.text(cx, ty - 1, sub, size=9.5, fill=stroke, weight=700, anchor="middle")
        if code:
            self.text(cx, cy + ry + 13, code, size=9.5, fill=FAINT, font=MONO, anchor="middle")

    def person(self, cx, y, label, sub=None, tone="client"):
        """A UML actor as a stick figure. `y` is the top of the head; label below."""
        stroke = TONES[tone][0]
        r, top = 10.0, y + 10
        shoulder = top + r + 10
        hip = shoulder + 27
        self.circle(cx, top, r, fill="#fff", stroke=stroke, sw=1.8)
        self.line(cx, top + r, cx, hip, stroke=stroke, sw=1.8)
        self.line(cx - 19, shoulder, cx + 19, shoulder, stroke=stroke, sw=1.8)
        self.line(cx, hip, cx - 15, hip + 18, stroke=stroke, sw=1.8)
        self.line(cx, hip, cx + 15, hip + 18, stroke=stroke, sw=1.8)
        self.text(cx, hip + 38, label, size=11.5, fill=INK, weight=700, anchor="middle")
        if sub:
            self.text(cx, hip + 52, sub, size=9.5, fill=MUTED, anchor="middle")

    def store(self, x, y, w, h, ident, label, tone="data"):
        """A DFD data store: the open-ended double line, id cell on the left."""
        stroke = TONES[tone][0]
        self.rect(x, y, w, h, rx=6, fill="#ffffff", stroke="none")
        self.rect(x, y, w, h, rx=6, fill="none", stroke=stroke, sw=1.4)
        self.line(x, y + 22, x + w, y + 22, stroke=stroke, sw=1.2)
        self.line(x + 54, y, x + 54, y + h, stroke=stroke, sw=1.2)
        self.text(x + 27, y + 16.5, ident, size=11, fill=stroke, weight=700, anchor="middle")
        body = label if isinstance(label, (list, tuple)) else [label]
        ty = y + 39
        for ln in body:
            self.text(x + 66, ty, ln, size=10.5, fill=INK)
            ty += 14

    def process(self, cx, cy, r, number, label, lines=(), tone="domain"):
        """A DFD process: numbered circle with the name under it."""
        stroke, fill, _ = TONES[tone]
        self.circle(cx, cy, r, fill="#ffffff", stroke=stroke, sw=1.6)
        self.text(cx, cy - r + 20, number, size=10.5, fill=stroke, weight=800, anchor="middle")
        body = label if isinstance(label, (list, tuple)) else [label]
        ty = cy - 2 + (0 if len(body) > 1 else 4)
        for ln in body:
            self.text(cx, ty, ln, size=11, fill=INK, weight=650, anchor="middle")
            ty += 12.5
        ty += 2
        for ln in lines:
            self.text(cx, ty, ln, size=9.5, fill=MUTED, anchor="middle")
            ty += 11.5

    def legend(self, x, y, items):
        self.text(x, y, "LEGEND", size=10, fill=FAINT, weight=700, spacing=1.1)
        cx = x + 58
        for label, tone in items:
            stroke, fill, _ = TONES[tone]
            self.rect(cx, y - 9, 12, 12, rx=3, fill=fill, stroke=stroke, sw=1.2)
            self.text(cx + 18, y, label, size=10.5, fill=MUTED)
            cx += 18 + 6.2 * len(label) + 22

    # ---- document ------------------------------------------------------
    def header(self):
        self.text(52, 52, self.layer, size=11.5, fill=TONES["neutral"][0], weight=700, spacing=1.6)
        self.text(52, 82, self.title, size=25, fill=INK, weight=700)
        self.text(52, 105, self.subtitle, size=12.5, fill=MUTED)
        self.line(52, 124, self.w - 52, 124, stroke=HAIR)

    def footer(self, text, right="Volt Debt Collection — HLD"):
        # `right` defaults to the HLD set's own label so existing sheets are unchanged;
        # the GCP staging set passes its own.
        self.line(52, self.h - 54, self.w - 52, self.h - 54, stroke=HAIR)
        self.text(52, self.h - 33, text, size=10, fill=FAINT, font=MONO)
        self.text(self.w - 52, self.h - 33, right, size=10, fill=FAINT, anchor="end")

    def svg(self):
        defs = ['<defs>']
        for tone, (stroke, _f, _w) in TONES.items():
            defs.append(
                '<marker id="head-%s" viewBox="0 0 10 10" refX="8.5" refY="5" '
                'markerWidth="6.5" markerHeight="6.5" orient="auto-start-reverse">'
                '<path d="M 0 1 L 9 5 L 0 9 z" fill="%s"/></marker>' % (tone, stroke))
        defs.append('</defs>')
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
            'viewBox="0 0 %d %d" font-family="%s">' % (self.w, self.h, self.w, self.h, FONT)
            + "".join(defs)
            + '<rect width="%d" height="%d" fill="%s"/>' % (self.w, self.h, PAPER)
            + "".join(self.parts) + "</svg>")

    def save(self, path):
        with open(path, "w") as fh:
            fh.write(self.svg())
        return path
