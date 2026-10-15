"""进化工厂报告渲染器：瑞士国际主义风格的自包含 HTML。

skill / mcp / sensor 三个工厂的评测报告统一由本模块渲染为单页 HTML：
内联样式 + 线性极简图标，零外部依赖，可独立在浏览器打开，
也可由极简 UI 直接以 iframe 嵌入。

风格要点（瑞士国际主义 / International Typographic Style）：
- 无衬线网格排版、左对齐、强烈字号层级、细分隔线；
- 黑 / 白 / 红三元配色，大留白，编号章节；
- 图标一律线性描边（1.6 线宽），不用彩色填充。
"""

import html as _html


# --------------------------------------------------------------------------- #
# 图标：线性描边，24 网格
# --------------------------------------------------------------------------- #
_ICONS = {
    "check": '<path d="m5 13 4 4L19 7"/>',
    "x": '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    "alert": '<path d="M12 9v4"/><path d="M12 17h.01"/>'
    '<path d="M10.3 3.9 2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "target": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/>'
    '<circle cx="12" cy="12" r="1"/>',
    "layers": '<path d="M12 3 3 8l9 5 9-5-9-5z"/><path d="m3 13 9 5 9-5"/>',
    "server": '<rect x="3" y="4" width="18" height="7" rx="2"/>'
    '<rect x="3" y="13" width="18" height="7" rx="2"/>'
    '<path d="M7 7.5h.01"/><path d="M7 16.5h.01"/>',
    "flask": '<path d="M8 3h8"/>'
    '<path d="M9 3v5.5a5.5 5.5 0 0 1-.9 3L6 15a5 5 0 0 0 4 8h4a5 5 0 0 0 4-8l-2.1-3.5a5.5 5.5 0 0 1-.9-3V3"/>'
    '<path d="M7.5 14h9"/>',
    "zap": '<path d="M13 2 4 14h7l-1 8 9-12h-7z"/>',
    "trendDown": '<path d="m3 7 6 6 4-4 8 8"/><path d="M21 17v-6h-6"/>',
    "coin": '<circle cx="12" cy="12" r="9"/><path d="M12 7v10"/>'
    '<path d="M9.5 9.5h5"/><path d="M9.5 14.5h5"/>',
    "tag": '<path d="M4 4h7l9 9-7 7-9-9z"/><circle cx="8" cy="8" r="1.4"/>',
    "list": '<path d="M8 6h13"/><path d="M8 12h13"/><path d="M8 18h13"/>'
    '<path d="M3 6h.01"/><path d="M3 12h.01"/><path d="M3 18h.01"/>',
    "file": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/>'
    '<path d="M14 3v5h5"/>',
    "graph": '<circle cx="5" cy="6" r="2.5"/><circle cx="19" cy="6" r="2.5"/>'
    '<circle cx="12" cy="18" r="2.5"/><path d="M7.5 6h9"/><path d="M6.5 8.2 10.6 16"/>'
    '<path d="M17.5 8.2 13.4 16"/>',
    "shield": '<path d="M12 3 5 6v6c0 4 3 7 7 8 4-1 7-4 7-8V6z"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 8h.01"/><path d="M11 12h1v4h1"/>',
    "dot": '<circle cx="12" cy="12" r="4"/>',
    "arrow": '<path d="M5 12h14"/><path d="m13 6 6 6-6 6"/>',
}

_STATUS = {
    "pass": ("ok", "通过", "check"),
    "fail": ("err", "失败", "x"),
    "warn": ("warn", "告警", "alert"),
}


def icon(name: str, size: int = 16) -> str:
    """返回线性图标 SVG 字符串（html 片段）"""
    body = _ICONS.get(name, _ICONS["dot"])
    return (
        f'<svg viewBox="0 0 24 24" width="{size}" height="{size}" fill="none" '
        f'stroke="currentColor" stroke-width="1.6" stroke-linecap="round" '
        f'stroke-linejoin="round">{body}</svg>'
    )


def esc(value) -> str:
    """HTML 转义（用于一切来自用例/用户数据的文本）"""
    return _html.escape("" if value is None else str(value), quote=True)


def badge(text, kind: str = "mute") -> str:
    cls = "badge" + (f" {kind}" if kind else "")
    return f'<span class="{cls}">{esc(text)}</span>'


# --------------------------------------------------------------------------- #
# 基础版式块
# --------------------------------------------------------------------------- #
def stat(label, value, unit: str = "", icon_name: str = None, desc: str = "",
         tone: str = "") -> str:
    ic = f"<span class=\"ic\">{icon(icon_name, 15)}</span>" if icon_name else ""
    un = f'<span class="u">{esc(unit)}</span>' if unit else ""
    ds = f'<div class="d">{esc(desc)}</div>' if desc else ""
    tc = f" {tone}" if tone else ""
    return (
        f'<div class="stat{tc}"><div class="k">{ic}{esc(label)}</div>'
        f'<div class="v">{esc(value)}{un}</div>{ds}</div>'
    )


def stats(items, cols: int = 3) -> str:
    inner = "".join(stat(**it) for it in (items or []))
    return (
        f'<div class="grid-stats" style="grid-template-columns:repeat({cols},1fr)">'
        f"{inner}</div>"
    )


def table(headers, rows) -> str:
    """rows 中的单元格为已转义好的 HTML 片段（调用方自行 esc 文本）"""
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def bullets(items) -> str:
    lis = "".join(f"<li>{esc(i)}</li>" for i in (items or []))
    return f'<ul class="clean">{lis}</ul>'


def note(text) -> str:
    return f'<div class="note">{esc(text)}</div>'


def code_block(text) -> str:
    return f'<pre class="code">{esc(text)}</pre>'


def case(title, status: str = "", meta=None, notes=None, blocks=None,
         badge_text: str = None) -> str:
    """单条评测用例卡。meta: [(标签, 文本)]；notes: [文本]；blocks: [HTML 片段]"""
    kind, default_text, ic_name = _STATUS.get(status, ("mute", "", "dot"))
    cls = f"case {status}" if status in _STATUS else "case"
    label = badge_text if badge_text is not None else default_text
    bd = badge(label, kind) if label else ""
    ic = f'<span class="ci">{icon(ic_name, 15)}</span>' if status else ""
    out = [f'<div class="{cls}"><div class="t">{ic}<span>{esc(title)}</span>{bd}</div>']
    if meta:
        pairs = "".join(
            f'<span class="mi"><b>{esc(k)}</b>{esc(v)}</span>' for k, v in meta
        )
        out.append(f'<div class="m">{pairs}</div>')
    for n in (notes or []):
        out.append(f'<div class="pn">{esc(n)}</div>')
    for blk in (blocks or []):
        out.append(blk)
    out.append("</div>")
    return "".join(out)


def cases(items) -> str:
    return "".join(case(**it) for it in (items or []))


def section(number, title, body) -> str:
    num = f'<span class="sec-num">{esc(number)}</span>' if number else ""
    return (
        f'<section><div class="sec-head">{num}<h2>{esc(title)}</h2></div>'
        f'<div class="sec-body">{body}</div></section>'
    )


# --------------------------------------------------------------------------- #
# trace2skill 专属：token 节省卡（黑底白字 + 红色大数字，图标化）
# --------------------------------------------------------------------------- #
def token_savings(saved: int, baseline: int, actual: int, source_label: str = "会话轨迹") -> str:
    """展示「该技能让后台盲测任务少花了多少 token」的图标化结论块。

    saved    = baseline - actual（正数表示技能省下了 token）
    baseline = 该技能来源会话轨迹的累计 token（无技能时的参照成本）
    actual   = 后台盲测（with_skill）精选用例的平均 token
    """
    saved_txt = f"{saved:,}"
    if saved <= 0:
        head = "该技能暂未带来 token 节省"
        tone = "flat"
    else:
        head = f"该技能让后台盲测任务少花了 {saved_txt} tokens"
        tone = "good"
    return (
        f'<div class="saved {tone}">'
        f'<div class="saved-ic">{icon("trendDown", 30)}</div>'
        f'<div class="saved-main">'
        f'<div class="saved-head">{esc(head)}</div>'
        f'<div class="saved-cmp">'
        f'<span class="cmp"><b>{esc(source_label)}</b>{baseline:,} tokens</span>'
        f'<span class="cmp-arrow">{icon("arrow", 14)}</span>'
        f'<span class="cmp"><b>技能盲测均值</b>{actual:,} tokens</span>'
        f'</div></div>'
        f'<div class="saved-num"><span class="sv">{esc(saved_txt)}</span>'
        f'<span class="su">TOKENS SAVED</span></div>'
        f"</div>"
    )


# --------------------------------------------------------------------------- #
# 页面骨架
# --------------------------------------------------------------------------- #
_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
html{-webkit-text-size-adjust:100%}
body{background:#eceae6;color:#0a0a0a;font:15px/1.55 "Helvetica Neue",Helvetica,Arial,"Inter","PingFang SC","Microsoft YaHei",sans-serif;-webkit-font-smoothing:antialiased}
.page{max-width:1040px;margin:0 auto;background:#fff;min-height:100vh;padding:54px 60px 68px}
.masthead{border-bottom:3px solid #0a0a0a;padding-bottom:16px;margin-bottom:22px}
.kicker{font-size:10.5px;letter-spacing:.2em;text-transform:uppercase;color:#6b6b6b;font-weight:700}
h1{font-size:40px;line-height:1.04;letter-spacing:-.02em;font-weight:700;margin-top:12px}
.sub{font-size:14.5px;color:#4a4a4a;margin-top:14px;max-width:62ch}
.meta{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));border-top:1px solid #e2e2e2;border-bottom:1px solid #e2e2e2;margin-bottom:40px}
.meta>div{padding:12px 16px 13px 0;border-right:1px solid #e2e2e2}
.meta>div:last-child{border-right:0}
.meta .k{font-size:10px;letter-spacing:.15em;text-transform:uppercase;color:#6b6b6b;font-weight:700}
.meta .v{font-size:13.5px;margin-top:6px;font-weight:600;word-break:break-word}
section{margin:0 0 42px}
.sec-head{display:flex;align-items:baseline;gap:14px;border-bottom:1px solid #0a0a0a;padding-bottom:8px;margin-bottom:18px}
.sec-num{font-size:12px;font-weight:700;letter-spacing:.12em;color:#e2001a}
h2{font-size:20px;letter-spacing:-.01em;font-weight:700}
h3{font-size:14px;font-weight:700;margin:18px 0 8px;letter-spacing:-.005em}
p{color:#2b2b2b;margin:0 0 10px}
.grid-stats{display:grid;gap:1px;background:#e2e2e2;border:1px solid #e2e2e2;margin-bottom:6px}
.stat{background:#fff;padding:17px 18px 19px}
.stat .k{display:flex;align-items:center;gap:7px;font-size:10px;letter-spacing:.15em;text-transform:uppercase;color:#6b6b6b;font-weight:700}
.stat .k .ic{display:inline-flex;color:#0a0a0a}
.stat .v{font-size:30px;font-weight:700;letter-spacing:-.02em;margin-top:11px;line-height:1}
.stat .u{font-size:12px;color:#6b6b6b;font-weight:600;margin-left:5px;letter-spacing:0}
.stat .d{font-size:12px;color:#6b6b6b;margin-top:9px;line-height:1.5}
.stat.accent .v{color:#e2001a}
.stat.ok .v{color:#0f7a43}
.stat.warn .v{color:#946000}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th{text-align:left;font-size:10px;letter-spacing:.13em;text-transform:uppercase;color:#6b6b6b;font-weight:700;padding:9px 12px;border-bottom:1px solid #0a0a0a;white-space:nowrap}
td{padding:10px 12px;border-bottom:1px solid #e2e2e2;vertical-align:top;color:#2b2b2b;word-break:break-word}
tbody tr:last-child td{border-bottom:0}
code,.mono{font:12px/1.5 ui-monospace,"Cascadia Mono",Consolas,monospace;background:#f2f1ee;padding:2px 5px;border-radius:3px;word-break:break-all;color:#1a1a1a}
pre.code{background:#0f0f0f;color:#eaeaea;font:12px/1.6 ui-monospace,Consolas,monospace;padding:12px 14px;border-radius:4px;overflow:auto;margin:8px 0;white-space:pre-wrap;word-break:break-all}
.case{border:1px solid #e2e2e2;border-left:4px solid #0a0a0a;padding:14px 16px 15px;margin-bottom:11px;background:#fff}
.case.pass{border-left-color:#0f7a43}
.case.fail{border-left-color:#e2001a}
.case.warn{border-left-color:#946000}
.case .t{display:flex;align-items:center;gap:9px;font-size:14.5px;font-weight:700}
.case .t .ci{display:inline-flex;color:#0a0a0a}
.case.pass .t .ci{color:#0f7a43}
.case.fail .t .ci{color:#e2001a}
.case.warn .t .ci{color:#946000}
.case .t>span{flex:1;min-width:0}
.case .m{display:flex;flex-wrap:wrap;gap:16px;margin-top:9px;font-size:12.5px;color:#6b6b6b}
.case .m .mi b{color:#0a0a0a;font-weight:700;margin-right:6px;letter-spacing:.02em}
.case .pn{margin-top:9px;font-size:12.5px;color:#2b2b2b;white-space:pre-wrap;word-break:break-word}
.badge{display:inline-flex;align-items:center;gap:5px;font-size:10px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;padding:3px 8px;border-radius:999px;background:#f0efec;color:#3a3a3a;white-space:nowrap}
.badge.ok{background:#e6f4ec;color:#0f7a43}
.badge.err{background:#fceaea;color:#c40018}
.badge.warn{background:#fdf3e2;color:#946000}
.badge.accent{background:#0a0a0a;color:#fff}
ul.clean{list-style:none}
ul.clean li{position:relative;padding:7px 0 7px 18px;border-bottom:1px solid #f0efec;font-size:13px;color:#2b2b2b}
ul.clean li:before{content:"";position:absolute;left:0;top:14px;width:6px;height:6px;background:#0a0a0a}
.note{font-size:12.5px;color:#6b6b6b;border-left:3px solid #e2e2e2;padding:2px 0 2px 13px;margin:12px 0;line-height:1.65}
.saved{display:flex;align-items:center;gap:20px;border:1px solid #0a0a0a;background:#0a0a0a;color:#fff;padding:20px 22px;margin-bottom:34px}
.saved.flat{background:#f2f1ee;color:#0a0a0a;border-color:#d8d6d1}
.saved-ic{flex:none;display:flex;align-items:center;justify-content:center;width:52px;height:52px;border:1px solid currentColor;border-radius:50%}
.saved-main{flex:1;min-width:0}
.saved-head{font-size:16px;font-weight:700;letter-spacing:-.01em}
.saved-cmp{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-top:10px;font-size:12px;letter-spacing:.02em;opacity:.82}
.saved-cmp .cmp b{font-weight:700;text-transform:uppercase;letter-spacing:.1em;font-size:10px;margin-right:7px;opacity:.7}
.saved-cmp .cmp-arrow{display:inline-flex;opacity:.6}
.saved-num{flex:none;text-align:right}
.saved-num .sv{display:block;font-size:34px;font-weight:700;letter-spacing:-.02em;line-height:1}
.saved.good .saved-num .sv{color:#ff4438}
.saved-num .su{display:block;font-size:9.5px;letter-spacing:.18em;text-transform:uppercase;opacity:.6;margin-top:6px}
footer{margin-top:38px;border-top:1px solid #e2e2e2;padding-top:14px;display:flex;justify-content:space-between;gap:16px;font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:#9a9a9a}
@media print{body{background:#fff}.page{padding:0}.saved{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
"""


def page(title: str, subtitle: str = "", meta=None, blocks=None,
         kicker: str = "PURRCAT · EVOLUTION FACTORY", footer_left: str = "",
         footer_right: str = "") -> str:
    """组装完整自包含 HTML 报告页。

    title/subtitle: 纯文本；meta: [(标签, 文本)]；blocks: [HTML 片段]。
    """
    meta_html = ""
    if meta:
        cells = "".join(
            f'<div><div class="k">{esc(k)}</div><div class="v">{esc(v)}</div></div>'
            for k, v in meta
        )
        meta_html = f'<div class="meta">{cells}</div>'
    sub_html = f'<div class="sub">{esc(subtitle)}</div>' if subtitle else ""
    body = "".join(blocks or [])
    return (
        "<!DOCTYPE html>\n"
        '<html lang="zh-CN"><head><meta charset="UTF-8"/>'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0"/>'
        f"<title>{esc(title)}</title><style>{_CSS}</style></head><body>"
        '<main class="page">'
        '<header class="masthead">'
        f'<div class="kicker">{esc(kicker)}</div>'
        f"<h1>{esc(title)}</h1>{sub_html}</header>"
        f"{meta_html}{body}"
        f'<footer><span>{esc(footer_left)}</span><span>{esc(footer_right)}</span></footer>'
        "</main></body></html>"
    )
