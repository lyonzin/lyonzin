"""Created by Lyon. (Ailton Rocha)

Card do perfil do GitHub (lyonzin/lyonzin) no estilo neofetch do Andrew6rant: gera dark_mode.svg e
light_mode.svg nesta pasta, com o ASCII do avatar (ascii.json) à esquerda e a ficha à direita, incluindo
os números do GitHub (stats.py). Determinístico: mesma data e mesmos números, mesmo SVG.

No repositório tudo fica em card/ (card.py, stats.py, render.py, ascii.json, cache/ e os dois SVGs); o
workflow .github/workflows/card.yml roda `python card/card.py` todo dia às 04:00 UTC e a cada push no
main, com o token em ACCESS_TOKEN (segredo METRICS_TOKEN). Sem token, os números vêm de cache/stats.json.
Local (PowerShell): $env:ACCESS_TOKEN = gh auth token; python card.py

O ascii.json vem de export_card_ascii.py (fora do repo, junto do ascii_grid.py e do avatar).
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from xml.etree import ElementTree

from render import LINE_CHARS, RULE, THEMES, Segment, Theme, render_card
from stats import Stats, get_stats

HERE = Path(__file__).resolve().parent
ASCII_FILE = HERE / "ascii.json"
OUTPUTS = {"dark": HERE / "dark_mode.svg", "light": HERE / "light_mode.svg"}
TITLE = "Ailton Rocha (lyonzin): ficha do perfil no estilo neofetch"
HOST = "ailton@rocha"
CAREER_START = date(2014, 1, 1)  # Uptime: anos completos em segurança desde 2014
PROFILE: tuple[tuple[str, str] | None, ...] = (
    ("OS", "Windows 11, Kali Linux, Debian"),
    ("Uptime", ""),  # calculado em uptime()
    ("Host", "HARDWAY"),
    ("Kernel", "Threat Hunter & Detection Engineer"),
    ("IDE", "VS Code, Neovim, Claude Code"),
    None,
    ("Languages.Programming", "Python, PowerShell, C++, Bash"),
    ("Languages.Query", "CQL, SPL, SQL"),
    ("Languages.Real", "Português, English (basic)"),
    None,
    ("Hobbies.Hacking", "Hack The Box Pro Labs"),
    ("Hobbies.Building", "AI agents, MCP servers"),
    ("Hobbies.Gaming", "Counter-Strike 2"),
)
CONTACT = (("Portfolio", "lyonzin.github.io"), ("LinkedIn", "aiiltonrocha"), ("GitHub", "lyonzin"))
LEAD = ". "
SEPARATOR = " | "
STAT_LEFT = 33  # largura do primeiro campo das linhas de stats; o segundo fecha em LINE_CHARS
STAT_RIGHT = LINE_CHARS - len(LEAD) - len(SEPARATOR) - STAT_LEFT
LOC_KEYS = ("Lines of Code on GitHub", "Lines of Code")  # a curta entra se o número não couber
MISSING = "n/a"
AA_TEXT, AA_GRAPHIC = 4.5, 3.0  # WCAG 2.x: texto e elemento gráfico
TEXT_ROLES = ("text", "key", "value", "add", "delete")
STRONG_INKS, TEXTURE_INKS = (3, 4, 5), (2,)  # ink-80, ink-100, bloom; ink-60 (cabelo e malha)


def uptime(today: date) -> str:
    started = (today.month, today.day) >= (CAREER_START.month, CAREER_START.day)
    years = today.year - CAREER_START.year - (0 if started else 1)
    return f"{years} year{'' if years == 1 else 's'} in cyber security"


def filler(gap: int) -> str:
    """Pontos entre a chave e o valor, como no Andrew: 1 vira espaço, 2 vira '. '."""
    return {1: " ", 2: ". "}.get(gap, " " + "." * (gap - 2) + " ")


def field(key: str, value: list[Segment], width: int) -> list[Segment]:
    """'Chave: ..... valor' com exatamente `width` caracteres; a chave 'A.B' pinta os dois lados."""
    gap = width - len(key) - 1 - sum(len(text) for text, _ in value)
    if gap < 1:
        raise ValueError(f"campo {key!r} não cabe em {width} colunas")
    parts = key.split(".")
    keyed = [segment for part in parts for segment in ((".", "text"), (part, "key"))][1:]
    return [*keyed, (":", "text"), (filler(gap), "dots"), *value]


def rule_line(title: str) -> list[Segment]:
    return [(f"{title} {RULE * (LINE_CHARS - len(title) - 1)}", "text")]


def profile_lines(today: date) -> list[list[Segment] | None]:
    lines: list[list[Segment] | None] = [rule_line(HOST)]
    for row in PROFILE:
        if row is None:
            lines.append([(LEAD.rstrip(), "dots")])
            continue
        value = uptime(today) if row[0] == "Uptime" else row[1]
        lines.append([(LEAD, "dots"), *field(row[0], [(value, "value")], LINE_CHARS - len(LEAD))])
    lines += [None, rule_line("- Contact")]
    lines += [[(LEAD, "dots"), *field(key, [(value, "value")], LINE_CHARS - len(LEAD))] for key, value in CONTACT]
    return lines


def count(stats: Stats | None, name: str) -> str:
    return MISSING if stats is None else f"{getattr(stats, name):,}"


def loc_line(stats: Stats | None) -> list[Segment]:
    net = MISSING if stats is None else f"{stats.additions - stats.deletions:,}"
    value = [(net, "value"), (" ( ", "text"), (count(stats, "additions") + "++", "add"), (", ", "text"),
             (count(stats, "deletions") + "--", "delete"), (" )", "text")]
    width = LINE_CHARS - len(LEAD)
    for key in LOC_KEYS:
        if width - len(key) - 1 - sum(len(text) for text, _ in value) >= 1:
            return [(LEAD, "dots"), *field(key, value, width)]
    raise ValueError("a linha de linhas de código não cabe nem com a chave curta")


def stats_lines(stats: Stats | None) -> list[list[Segment] | None]:
    repos = [(count(stats, "repos"), "value"), (" {", "text"), ("Contributed", "key"), (": ", "text"),
             (count(stats, "contributed"), "value"), ("}", "text")]
    # sem Followers por decisão do dono (05/11/2026): Repos ocupa a linha inteira, Commits divide com Stars
    first = [(LEAD, "dots"), *field("Repos", repos, LINE_CHARS - len(LEAD))]
    second = [(LEAD, "dots"), *field("Commits", [(count(stats, "commits"), "value")], STAT_LEFT), (SEPARATOR, "text"),
              *field("Stars", [(count(stats, "stars"), "value")], STAT_RIGHT)]
    return [None, rule_line("- GitHub Stats"), first, second, loc_line(stats)]


def luminance(color: str) -> float:
    channels = [int(color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    red, green, blue = (c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(first: str, second: str) -> float:
    high, low = sorted((luminance(first), luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def verify_theme(name: str, theme: Theme) -> None:
    """AA: texto da ficha e tintas fortes do ASCII a 4,5:1 do fundo; a textura (ink-60) a 3:1."""
    checks = [(role, getattr(theme, role), AA_TEXT) for role in TEXT_ROLES]
    checks += [(f"ink {level}", theme.inks[level], AA_TEXT) for level in STRONG_INKS]
    checks += [(f"ink {level}", theme.inks[level], AA_GRAPHIC) for level in TEXTURE_INKS]
    for label, color, minimum in checks:
        ratio = contrast(color, theme.background)
        if ratio < minimum:
            raise ValueError(f"tema {name}: {label} {color} com {ratio:.2f}:1, abaixo de {minimum}:1")


def main() -> None:
    rows = json.loads(ASCII_FILE.read_text(encoding="utf-8"))["rows"]
    stats, source = get_stats()
    lines = profile_lines(date.today()) + stats_lines(stats)
    for name, theme in THEMES.items():
        verify_theme(name, theme)
        svg = render_card(rows, lines, theme, TITLE)
        ElementTree.fromstring(svg)  # XML bem formado ou falha aqui
        OUTPUTS[name].write_text(svg, encoding="utf-8", newline="\n")
        print(f"{OUTPUTS[name].name}: {len(svg.encode('utf-8')) / 1024:.1f} KB")
    if stats is None:
        print(f"aviso: números: {source}; sem cache, o card mostra {MISSING}", file=sys.stderr)
    else:
        print(f"números: {source}")


if __name__ == "__main__":
    main()
