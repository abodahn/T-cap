"""Self-contained inline-SVG charts (no JS, no external libs). Monochrome-first:
segments use brand greys by default; pass status colors only where meaning applies.
All functions return a `markupsafe.Markup` string safe to drop into templates."""
import math

from markupsafe import Markup

# Default monochrome ramp for categorical series (brand greys, light→dark).
_RAMP = ["#3C3C3C", "#5F5F5F", "#7E8080", "#9F9FA0", "#C9CACA", "#B4B4B0"]


def _fmt(n):
    return f"{n:g}"


def donut(segments, size=180, thickness=24, center_label="", center_sub=""):
    """segments: list of (label, value, color?) — color optional (falls back to ramp)."""
    total = sum(max(0, s[1]) for s in segments) or 1
    r = (size - thickness) / 2
    cx = cy = size / 2
    circ = 2 * math.pi * r
    parts = [f'<svg viewBox="0 0 {size} {size}" class="tc-donut" role="img" width="{size}" height="{size}">']
    parts.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="var(--hairline)" stroke-width="{thickness}"/>')
    offset = 0.0
    for i, seg in enumerate(segments):
        val = max(0, seg[1])
        if val <= 0:
            continue
        color = seg[2] if len(seg) > 2 and seg[2] else _RAMP[i % len(_RAMP)]
        dash = val / total * circ
        parts.append(
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{color}" '
            f'stroke-width="{thickness}" stroke-dasharray="{dash:.2f} {circ - dash:.2f}" '
            f'stroke-dashoffset="{-offset:.2f}" transform="rotate(-90 {cx} {cy})" '
            f'stroke-linecap="butt"><title>{seg[0]}: {_fmt(val)}</title></circle>')
        offset += dash
    if center_label != "":
        parts.append(
            f'<text x="{cx}" y="{cy - 2}" text-anchor="middle" class="tc-donut__num">{center_label}</text>')
        if center_sub:
            parts.append(
                f'<text x="{cx}" y="{cy + 16}" text-anchor="middle" class="tc-donut__sub">{center_sub}</text>')
    parts.append("</svg>")
    return Markup("".join(parts))


def gauge(percent, size=180, thickness=22, color="var(--brand-grey)", label=""):
    percent = max(0, min(100, percent))
    r = (size - thickness) / 2
    cx = cy = size / 2
    circ = 2 * math.pi * r
    dash = percent / 100 * circ
    return Markup(
        f'<svg viewBox="0 0 {size} {size}" class="tc-donut" width="{size}" height="{size}" role="img">'
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="var(--hairline)" stroke-width="{thickness}"/>'
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{color}" stroke-width="{thickness}" '
        f'stroke-linecap="round" stroke-dasharray="{dash:.2f} {circ - dash:.2f}" '
        f'transform="rotate(-90 {cx} {cy})"/>'
        f'<text x="{cx}" y="{cy - 2}" text-anchor="middle" class="tc-donut__num">{percent:g}%</text>'
        f'<text x="{cx}" y="{cy + 16}" text-anchor="middle" class="tc-donut__sub">{label}</text></svg>')


def sparkline(values, width=260, height=56, color="var(--brand-grey)"):
    if not values:
        return Markup("")
    vmax = max(values) or 1
    vmin = min(values)
    span = (vmax - vmin) or 1
    step = width / (len(values) - 1) if len(values) > 1 else width
    pts = []
    for i, v in enumerate(values):
        x = i * step
        y = height - 6 - (v - vmin) / span * (height - 12)
        pts.append(f"{x:.1f},{y:.1f}")
    poly = " ".join(pts)
    area = f"M0,{height} L" + " L".join(pts) + f" L{width},{height} Z"
    return Markup(
        f'<svg viewBox="0 0 {width} {height}" class="tc-spark" preserveAspectRatio="none" width="100%" height="{height}">'
        f'<path d="{area}" fill="{color}" opacity="0.10"/>'
        f'<polyline points="{poly}" fill="none" stroke="{color}" stroke-width="2" '
        f'stroke-linejoin="round" stroke-linecap="round"/></svg>')


def hbars(rows, color="var(--brand-grey)"):
    """rows: list of (label, value, color?). Renders labelled horizontal bars."""
    mx = max((r[1] for r in rows), default=0) or 1
    out = ['<div class="tc-hbars">']
    for r in rows:
        c = r[2] if len(r) > 2 and r[2] else color
        pct = r[1] / mx * 100
        out.append(
            f'<div class="tc-hbar"><span class="tc-hbar__l">{r[0]}</span>'
            f'<span class="tc-hbar__t"><span style="width:{pct:.0f}%;background:{c}"></span></span>'
            f'<b class="tc-hbar__v">{_fmt(r[1])}</b></div>')
    out.append("</div>")
    return Markup("".join(out))
