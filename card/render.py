"""Created by Lyon. (Ailton Rocha)

Desenha o card do perfil (985 x 530) no padrão do Andrew6rant: ASCII do avatar à esquerda e a ficha
à direita, em linhas ". Chave: ..... valor" com os valores alinhados à direita pela contagem de pontos.
Cada linha é uma <text> com textLength e passo fixo por caractere: a coluna não depende da fonte
monoespaçada que o leitor tiver. Cores em atributo: o SVG lê inteiro mesmo sem CSS.
"""
from __future__ import annotations

from dataclasses import dataclass
from xml.sax.saxutils import escape

CARD_W, CARD_H, RADIUS = 985, 530, 15
FONT_STACK = "Consolas,ui-monospace,SFMono-Regular,Menlo,monospace"
INFO_X, INFO_TOP, LINE_H, INFO_FONT = 390, 50, 20, 16
GLYPH_EM = 0.6  # avanço nominal de uma monoespaçada, em em
PITCH = GLYPH_EM * INFO_FONT  # passo da coluna da ficha: 60 caracteres vão de x=390 a x=966
LINE_CHARS = 60
RULE = "─"  # régua da ficha (box drawing); travessão nunca
ASCII_X, ASCII_BOX_W, ASCII_BOX_H = 15, 365, 500
CELL_EM = 0.75  # passo da célula do ASCII em em, igual ao do banner: célula quadrada
BASELINE_SHARE = 11 / 12  # do topo da célula até a linha de base
NBSP = " "
WALL_INK = 0  # parede do retrato: no card some, o fundo do card faz o papel dela
Segment = tuple[str, str]  # (texto, papel): text, key, value, dots, add, delete


@dataclass(frozen=True)
class Theme:
    background: str
    text: str
    key: str
    value: str
    dots: str
    add: str
    delete: str
    inks: tuple[str, ...]  # tinta do ASCII por nível: 0 parede (não desenhada), 1 ink-40 até 5 bloom


THEMES = {
    "dark": Theme("#161b22", "#c9d1d9", "#ffa657", "#a5d6ff", "#616e7f", "#3fb950", "#f85149",
                  ("#1a2742", "#2b4372", "#4a6fb0", "#7b9fdc", "#a9c6ff", "#e6f0ff")),
    # Azuis escuros sobre o fundo claro: o degrau mais aceso no escuro vira o mais escuro aqui (o glifo
    # fino cobre pouco da célula, então a tinta precisa ser funda), e o bloom (olhos e raio) vira o azul
    # vivo do GitHub para continuar sendo o ponto de luz.
    "light": Theme("#f6f8fa", "#24292f", "#953800", "#0a3069", "#c2cfde", "#1a7f37", "#cf222e",
                   ("#d5dde8", "#7d95b8", "#456a9e", "#1c3f73", "#0a2551", "#0969da")),
}


def merge(segments: list[Segment]) -> list[Segment]:
    """Junta segmentos vizinhos do mesmo papel: menos <tspan>."""
    merged: list[Segment] = []
    for text, role in segments:
        if merged and merged[-1][1] == role:
            merged[-1] = (merged[-1][0] + text, role)
        else:
            merged.append((text, role))
    return merged


def text_line(y: float, segments: list[Segment], theme: Theme) -> str:
    content = "".join(
        escape(text) if role == "text" else f'<tspan fill="{getattr(theme, role)}">{escape(text)}</tspan>'
        for text, role in merge(segments)
    )
    length = sum(len(text) for text, _ in segments) * PITCH
    return f'<text x="{INFO_X}" y="{y:g}" textLength="{length:g}" lengthAdjust="spacing">{content}</text>'


def info_markup(lines: list[list[Segment] | None], theme: Theme) -> str:
    """A ficha: uma linha de LINE_H por item; None é linha vazia."""
    return "\n".join(
        text_line(INFO_TOP + index * LINE_H, line, theme) for index, line in enumerate(lines) if line
    )


def ascii_row(glyphs: str, inks: str, theme: Theme) -> str:
    """Uma linha do retrato: uma <tspan> por sequência de mesma tinta; parede e vão viram espaço fixo."""
    runs: list[list[str]] = []
    for glyph, ink in zip(glyphs, inks, strict=True):
        is_blank = glyph == NBSP or int(ink) == WALL_INK
        if is_blank and runs:
            runs[-1][1] += NBSP
        elif is_blank or not runs or runs[-1][0] != ink:
            runs.append([ink, NBSP if is_blank else glyph])
        else:
            runs[-1][1] += glyph
    return "".join(
        text if int(ink) == WALL_INK else f'<tspan fill="{theme.inks[int(ink)]}">{text}</tspan>' for ink, text in runs
    )


def ascii_markup(rows: list[list[str]], theme: Theme) -> str:
    """Retrato centrado na altura do card, com célula quadrada no maior tamanho que cabe na caixa."""
    cols = len(rows[0][0])
    cell = min(ASCII_BOX_W / cols, ASCII_BOX_H / len(rows))
    top = (CARD_H - cell * len(rows)) / 2
    length = (cols - 1) * cell + GLYPH_EM * cell / CELL_EM
    lines = [
        f'<text x="{ASCII_X}" y="{top + (index + BASELINE_SHARE) * cell:.2f}" textLength="{length:.2f}" '
        f'lengthAdjust="spacing">{ascii_row(glyphs, inks, theme)}</text>'
        for index, (glyphs, inks) in enumerate(rows)
        if any(int(ink) != WALL_INK for ink in inks)
    ]
    return f'<g font-size="{cell / CELL_EM:.2f}">\n' + "\n".join(lines) + "\n</g>"


def render_card(rows: list[list[str]], lines: list[list[Segment] | None], theme: Theme, title: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{CARD_W}" height="{CARD_H}" viewBox="0 0 {CARD_W} {CARD_H}" '
        f'font-family="{FONT_STACK}" role="img" aria-label="{escape(title)}">\n'
        f"<title>{escape(title)}</title>\n"
        f'<rect width="{CARD_W}" height="{CARD_H}" rx="{RADIUS}" fill="{theme.background}"/>\n'
        f"{ascii_markup(rows, theme)}\n"
        f'<g font-size="{INFO_FONT}" fill="{theme.text}">\n{info_markup(lines, theme)}\n</g>\n'
        "</svg>\n"
    )
