"""Estilo visual: panel de estadísticas sobrio, gris carbón plano, números grandes y color solo para el rendimiento."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QPushButton

from ..i18n import language

BG = "#0f1014"
SURFACE = "#17191e"
SURFACE_2 = "#1e2127"
BORDER = "#272a31"
TEXT = "#eef0f3"
MUTED = "#8b919d"
SUBTLE = "#5f6570"
ACCENT = "#ff4f7b"
GOOD = "#3fcf8e"
MID = "#f2c14e"
BAD = "#ff5c5c"
CT_COLOR = "#5aa9ff"
T_COLOR = "#f0a24b"
# Compatibilidad con los gráficos
CYAN, PURPLE, GREEN, DANGER, AMBER = CT_COLOR, ACCENT, GOOD, BAD, T_COLOR


def fmt_num(value, decimals: int = 1, empty: str = "—") -> str:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return empty
    text = f"{value:,.{decimals}f}"
    # En español la coma es el decimal y el punto separa miles; en inglés, al revés.
    return text if language() == "en" else text.replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_pct(value, empty: str = "—") -> str:
    if value is None:
        return empty
    return f"{round(value * 100):.0f}%" if language() == "en" else f"{round(value * 100):.0f} %"


def fmt_metric(value, kind: str) -> str:
    if kind == "pct":
        return fmt_pct(value)
    return fmt_num(value, {"num2": 2, "num1": 1, "num0": 0}.get(kind, 1))


def rating_color(value) -> str:
    """Escala de color del rating, como en los sitios de estadísticas: rojo, amarillo, verde."""
    if value is None:
        return SUBTLE
    if value >= 1.15:
        return GOOD
    if value >= 0.95:
        return "#b6d96a" if value >= 1.05 else MID
    if value >= 0.85:
        return "#f29a4e"
    return BAD


def score_color(score) -> str:
    """Color según percentil orientado (0 a 100, alto es bueno)."""
    if score is None:
        return SUBTLE
    if score >= 70:
        return GOOD
    if score >= 55:
        return "#b6d96a"
    if score >= 45:
        return MID
    if score >= 30:
        return "#f29a4e"
    return BAD


def icon(kind: str, color: str = MUTED, size: int = 20) -> QIcon:
    """Íconos vectoriales propios, sin fuentes externas."""
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(size / 24 * 2, size / 24 * 2)
    painter.setPen(QPen(QColor(color), 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    if kind == "profile":
        painter.drawEllipse(QRectF(8, 3.5, 8, 8))
        painter.drawArc(QRectF(4, 13.5, 16, 14), 20 * 16, 140 * 16)
    elif kind == "grenade":
        painter.drawEllipse(QRectF(5, 8, 13, 13))
        painter.drawLine(QPointF(9, 8), QPointF(10, 4.5))
        painter.drawLine(QPointF(10, 4.5), QPointF(16, 4.5))
        painter.drawArc(QRectF(15, 2.5, 5, 5), 90 * 16, 270 * 16)
    elif kind == "list":
        for y in (6, 12, 18):
            painter.drawPoint(QPointF(4.5, y))
            painter.drawLine(QPointF(8, y), QPointF(20, y))
    elif kind == "rank":
        for i, h in enumerate((6, 11, 16)):
            painter.drawRoundedRect(QRectF(4 + i * 6, 20 - h, 4, h), 1, 1)
    elif kind == "map":
        path = QPainterPath(QPointF(3, 6))
        for x, y in ((9, 3.5), (15, 6), (21, 3.5), (21, 18), (15, 20.5), (9, 18), (3, 20.5)):
            path.lineTo(x, y)
        path.closeSubpath()
        painter.drawPath(path)
        painter.drawLine(QPointF(9, 3.5), QPointF(9, 18))
        painter.drawLine(QPointF(15, 6), QPointF(15, 20.5))
    elif kind == "target":
        painter.drawEllipse(QRectF(5, 5, 14, 14))
        for a, b in (((12, 1.5), (12, 7)), ((12, 17), (12, 22.5)), ((1.5, 12), (7, 12)), ((17, 12), (22.5, 12))):
            painter.drawLine(QPointF(*a), QPointF(*b))
    elif kind == "bolt":
        path = QPainterPath(QPointF(13.5, 2.5))
        for x, y in ((5, 13.5), (11.5, 13.5), (10.5, 21.5), (19, 10.5), (12.5, 10.5)):
            path.lineTo(x, y)
        path.closeSubpath()
        painter.drawPath(path)
    elif kind == "bulb":
        painter.drawArc(QRectF(5.5, 2.5, 13, 13), -30 * 16, 240 * 16)
        painter.drawLine(QPointF(9, 14), QPointF(9.5, 17))
        painter.drawLine(QPointF(15, 14), QPointF(14.5, 17))
        painter.drawLine(QPointF(9.5, 17.5), QPointF(14.5, 17.5))
        painter.drawLine(QPointF(10.5, 20.5), QPointF(13.5, 20.5))
    elif kind == "history":
        painter.drawArc(QRectF(3.5, 3.5, 17, 17), 60 * 16, 300 * 16)
        painter.drawLine(QPointF(12, 7.5), QPointF(12, 12))
        painter.drawLine(QPointF(12, 12), QPointF(15.5, 14))
        painter.drawLine(QPointF(3.5, 5), QPointF(4.2, 9.2))
        painter.drawLine(QPointF(4.2, 9.2), QPointF(8.3, 8.4))
    elif kind == "link":
        painter.drawRoundedRect(QRectF(2.5, 8.5, 10, 7), 3.5, 3.5)
        painter.drawRoundedRect(QRectF(11.5, 8.5, 10, 7), 3.5, 3.5)
    elif kind == "import":
        painter.drawLine(QPointF(12, 3), QPointF(12, 15))
        painter.drawLine(QPointF(8, 11), QPointF(12, 15))
        painter.drawLine(QPointF(16, 11), QPointF(12, 15))
        painter.drawLine(QPointF(4, 15), QPointF(4, 21))
        painter.drawLine(QPointF(4, 21), QPointF(20, 21))
        painter.drawLine(QPointF(20, 21), QPointF(20, 15))
    elif kind == "help":
        painter.drawEllipse(QRectF(3, 3, 18, 18))
        painter.drawArc(QRectF(9, 7, 6, 6), -60 * 16, 240 * 16)
        painter.drawLine(QPointF(12, 13), QPointF(12, 14.5))
        painter.drawPoint(QPointF(12, 17.5))
    elif kind == "scan":
        painter.drawArc(QRectF(4, 4, 16, 16), 35 * 16, 295 * 16)
        painter.drawLine(QPointF(20, 4), QPointF(20, 10))
        painter.drawLine(QPointF(20, 4), QPointF(14, 4))
    elif kind == "folder":
        path = QPainterPath(QPointF(3, 6))
        for x, y in ((9, 6), (11, 8), (21, 8), (21, 19), (3, 19)):
            path.lineTo(x, y)
        path.closeSubpath()
        painter.drawPath(path)
    elif kind == "check":
        painter.drawLine(QPointF(5, 12.5), QPointF(10, 17.5))
        painter.drawLine(QPointF(10, 17.5), QPointF(19.5, 6.5))
    elif kind == "send":
        path = QPainterPath(QPointF(3, 11))
        for x, y in ((21, 3.5), (14, 21), (11, 13.5)):
            path.lineTo(x, y)
        path.closeSubpath()
        painter.drawPath(path)
        painter.drawLine(QPointF(11, 13.5), QPointF(21, 3.5))
    elif kind == "external":
        painter.drawRoundedRect(QRectF(4, 6, 14, 14), 2, 2)
        painter.drawLine(QPointF(11, 13), QPointF(20, 4))
        painter.drawLine(QPointF(14, 4), QPointF(20, 4))
        painter.drawLine(QPointF(20, 4), QPointF(20, 10))
    elif kind == "duel":
        for a, b, g1, g2 in (((4, 4), (17, 17), (13, 19), (19, 13)), ((20, 4), (7, 17), (11, 19), (5, 13))):
            painter.drawLine(QPointF(*a), QPointF(*b))
            painter.drawLine(QPointF(*g1), QPointF(*g2))
    elif kind == "shield":
        path = QPainterPath(QPointF(12, 2.5))
        path.cubicTo(QPointF(15, 4.5), QPointF(18, 5), QPointF(20, 5))
        path.cubicTo(QPointF(20, 13), QPointF(17, 18.5), QPointF(12, 21.5))
        path.cubicTo(QPointF(7, 18.5), QPointF(4, 13), QPointF(4, 5))
        path.cubicTo(QPointF(6, 5), QPointF(9, 4.5), QPointF(12, 2.5))
        painter.drawPath(path)
        painter.drawRoundedRect(QRectF(9, 11, 6, 5), 1, 1)
        painter.drawArc(QRectF(10, 8, 4, 5), 0, 180 * 16)
    elif kind == "skull":
        painter.drawArc(QRectF(4, 2.5, 16, 15), -20 * 16, 220 * 16)
        painter.drawLine(QPointF(5.2, 13.5), QPointF(8, 16.5))
        painter.drawLine(QPointF(18.8, 13.5), QPointF(16, 16.5))
        painter.drawLine(QPointF(8, 16.5), QPointF(8, 20.5))
        painter.drawLine(QPointF(16, 16.5), QPointF(16, 20.5))
        painter.drawLine(QPointF(8, 20.5), QPointF(16, 20.5))
        painter.setBrush(QColor(color))
        painter.drawEllipse(QRectF(7.5, 9, 3.5, 3.5))
        painter.drawEllipse(QRectF(13, 9, 3.5, 3.5))
    elif kind == "flash":
        painter.drawRoundedRect(QRectF(7, 8, 9, 13), 2, 2)
        painter.drawLine(QPointF(9, 8), QPointF(9, 5.5))
        painter.drawLine(QPointF(9, 5.5), QPointF(14, 5.5))
        for a, b in (((18, 6), (21, 3.5)), ((18.5, 9.5), (22, 9.5)), ((17, 3.5), (17.5, 1.5))):
            painter.drawLine(QPointF(*a), QPointF(*b))
    elif kind == "burst":
        path = QPainterPath(QPointF(12, 2))
        for x, y in ((14, 8), (20, 5), (17, 11), (22, 14), (16, 15), (17, 21), (12, 17), (7, 21), (8, 15), (2, 14),
                     (7, 11), (4, 5), (10, 8)):
            path.lineTo(x, y)
        path.closeSubpath()
        painter.drawPath(path)
    elif kind == "swap":
        painter.drawLine(QPointF(3.5, 8), QPointF(19, 8))
        painter.drawLine(QPointF(15, 4), QPointF(19, 8))
        painter.drawLine(QPointF(15, 12), QPointF(19, 8))
        painter.drawLine(QPointF(20.5, 16), QPointF(5, 16))
        painter.drawLine(QPointF(9, 12), QPointF(5, 16))
        painter.drawLine(QPointF(9, 20), QPointF(5, 16))
    elif kind in ("down", "up"):
        painter.setPen(QPen(QColor(color), 2.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        for y in (5, 12):
            a, b = (y, y + 6) if kind == "down" else (y + 6, y)
            painter.drawPolyline([QPointF(5, a), QPointF(12, b), QPointF(19, a)])
    elif kind == "crown":
        path = QPainterPath(QPointF(3.5, 18))
        for x, y in ((2.5, 7), (8, 11.5), (12, 4.5), (16, 11.5), (21.5, 7), (20.5, 18)):
            path.lineTo(x, y)
        path.closeSubpath()
        painter.setBrush(QColor(color))
        painter.drawPath(path)
    else:
        painter.setBrush(QColor(color))
        painter.drawEllipse(QRectF(9, 9, 6, 6))
    painter.end()
    pixmap.setDevicePixelRatio(2)
    return QIcon(pixmap)


def app_icon() -> QIcon:
    """Logo: barras de estadística con una mira, sobre gris carbón."""
    size = 256
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#1b1d23"))
    p.drawRoundedRect(QRectF(8, 8, 240, 240), 52, 52)
    for i, (h, color) in enumerate(((70, "#5f6570"), (112, "#b6d96a"), (156, ACCENT))):
        p.setBrush(QColor(color))
        p.drawRoundedRect(QRectF(58 + i * 52, 196 - h, 36, h), 10, 10)
    p.end()
    return QIcon(pixmap)


def label(text: str, name: str = "", wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)  # nombres de jugadores pueden traer '<...>'
    if name:
        widget.setObjectName(name)
    widget.setWordWrap(wrap)
    return widget


def button(text: str, kind: str = "", primary: bool = False) -> QPushButton:
    widget = QPushButton(text)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    widget.setMinimumHeight(36)
    if kind:
        widget.setIcon(icon(kind, "#ffffff" if primary else "#c4c8d0", 17))
        widget.setIconSize(QSize(17, 17))
    if primary:
        widget.setObjectName("primaryButton")
    return widget


def panel(name: str = "card") -> QFrame:
    frame = QFrame()
    frame.setObjectName(name)
    return frame


STYLE = f"""
QMainWindow, QDialog {{ background: {BG}; color: {TEXT}; }}
QWidget {{ color: {TEXT}; font-family: 'Segoe UI Variable Text', 'Segoe UI'; font-size: 13px; }}
QWidget#root {{ background: qradialgradient(cx:0.15, cy:0.0, radius:1.2, fx:0.15, fy:0.0, stop:0 #141a1d, stop:1 {BG}); }}
QWidget#canvas {{ background: transparent; }}
QLabel {{ background: transparent; }}
QFrame#sidebar {{ background: qlineargradient(x1:0, y1:0, x2:0.6, y2:1, stop:0 #12281c, stop:0.35 #101814, stop:1 #0f1113);
                  border-right: 1px solid #1f2a24; }}
QFrame#sideCard {{ background: rgba(255,255,255,8); border: 1px solid rgba(255,255,255,18); border-radius: 12px; }}
QFrame#card {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #191d24, stop:1 #14171c);
               border: 1px solid #262b33; border-radius: 14px; }}
QFrame#cardFlat {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 10px; }}
QFrame#goodCard {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #191d24, stop:1 #14171c);
                   border: 1px solid #262b33; border-left: 3px solid {GOOD}; border-radius: 12px; }}
QFrame#badCard {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #191d24, stop:1 #14171c);
                  border: 1px solid #262b33; border-left: 3px solid {BAD}; border-radius: 12px; }}
QFrame#heroCard {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1d1a22, stop:0.5 #171a21, stop:1 #191520);
                   border: 1px solid #3a2a33; border-radius: 16px; }}
QFrame#playerCard {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #221d18, stop:0.55 #1a1c22, stop:1 #241820);
                     border: 1px solid #5a4630; border-radius: 16px; }}
QFrame#tableHead {{ background: #1c2027; border-radius: 8px; }}
QLabel#tableHeadText {{ color: {MUTED}; font-size: 12px; font-weight: 700; }}
QLabel#tableSection {{ color: {MUTED}; font-size: 12px; font-weight: 800; letter-spacing: 1px; padding: 10px 12px 4px 12px; }}
QFrame#rowAlly {{ background: rgba(90,169,255,10); border: 1px solid #22272f; border-left: 3px solid {CT_COLOR}; border-radius: 8px; }}
QFrame#rowRival {{ background: rgba(240,162,75,10); border: 1px solid #2b2620; border-left: 3px solid {T_COLOR}; border-radius: 8px; }}
QFrame#rowMe {{ background: rgba(255,79,123,30); border: 1px solid {ACCENT}; border-left: 3px solid {ACCENT}; border-radius: 8px; }}
QFrame#rowBest {{ background: rgba(63,207,142,16); border: 1px solid {GOOD}; border-left: 3px solid {GOOD}; border-radius: 8px; }}
QLabel#meChip {{ color: white; background: {ACCENT}; border-radius: 5px; padding: 1px 6px; font-size: 11px; font-weight: 800; }}
QFrame#tile {{ background: #1c2027; border: 1px solid #2a2f37; border-radius: 10px; }}
QFrame#tileGood {{ background: #18212c; border: 1px solid #36608f; border-radius: 10px; }}
QFrame#tileBad {{ background: #2a181c; border: 1px solid #7a3340; border-radius: 10px; }}
QFrame#tileUtil {{ background: #231e17; border: 1px solid #5f4424; border-radius: 10px; }}
QFrame#rowAlly:hover {{ background: rgba(90,169,255,34); border-color: #2f4a6e; }}
QFrame#rowRival:hover {{ background: rgba(240,162,75,32); border-color: #5a4329; }}
QFrame#rowMe:hover {{ background: rgba(255,79,123,48); }}
QFrame#rowBest:hover {{ background: rgba(63,207,142,32); }}
QFrame#tile:hover {{ border-color: #4a515c; background: #20252d; }}
QFrame#tileGood:hover {{ border-color: {CT_COLOR}; }}
QFrame#tileBad:hover {{ border-color: {BAD}; }}
QFrame#tileUtil:hover {{ border-color: {T_COLOR}; }}
QPushButton#backButton {{ background: rgba(255,255,255,10); border: 1px solid rgba(255,255,255,26); border-radius: 8px;
                          padding: 6px 14px; color: #dfe2e7; font-size: 13px; font-weight: 700; }}
QPushButton#backButton:hover {{ background: rgba(255,79,123,40); border-color: {ACCENT}; color: #ffffff; }}
QLabel#matchMap {{ font-family: 'Segoe UI Variable Display'; font-size: 44px; font-weight: 800; }}
QLabel#matchScore {{ font-family: 'Segoe UI Variable Display'; font-size: 26px; font-weight: 800; }}
QLabel#cardPlayer {{ font-family: 'Segoe UI Variable Display'; font-size: 22px; font-weight: 700; }}
QLabel#resultWin, QLabel#resultLoss, QLabel#resultTie {{ font-family: 'Segoe UI Variable Display'; font-size: 20px; font-weight: 800;
                                                        border-radius: 6px; padding: 2px 12px; }}
QLabel#resultWin {{ color: {GOOD}; background: #15241d; border: 1px solid #24432f; }}
QLabel#resultLoss {{ color: #ffd9de; background: #4a1c24; border: 1px solid #7a3340; }}
QLabel#resultTie {{ color: {MID}; background: #2a2416; border: 1px solid #4d4126; }}
QPushButton#tabButton {{ background: rgba(255,255,255,8); border: 1px solid rgba(255,255,255,18); border-bottom: 3px solid transparent;
                         border-radius: 0; border-top-left-radius: 8px; border-top-right-radius: 8px;
                         padding: 9px 18px; color: #aeb3bc; font-size: 15px; font-weight: 700; }}
QPushButton#tabButton:hover {{ color: {TEXT}; background: rgba(255,255,255,16); }}
QPushButton#tabButton:checked {{ color: #ff6b8f; border-color: rgba(255,79,123,90); border-bottom: 3px solid {ACCENT};
                                 background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(255,79,123,10), stop:1 rgba(255,79,123,55)); }}
QWidget#matchView QFrame#card {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(28,32,40,232), stop:1 rgba(20,22,28,240));
                                   border: 1px solid rgba(255,79,123,95); border-radius: 16px; }}
QWidget#matchView QFrame#playerCard {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(40,34,30,225), stop:0.6 rgba(26,28,34,225), stop:1 rgba(48,24,32,225));
                                         border: 1px solid #6a5238; border-radius: 18px; }}
QFrame#tableHeadLeft {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1d5fc0, stop:1 #2a74d6);
                        border-top-left-radius: 8px; border-bottom-left-radius: 8px; }}
QFrame#tableHeadRight {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2a74d6, stop:0.12 #e98f35, stop:1 #e0582e);
                         border-top-right-radius: 8px; border-bottom-right-radius: 8px; }}
QFrame#tableHeadLeft QLabel#tableHeadText, QFrame#tableHeadRight QLabel#tableHeadText {{ color: #ffffff; font-size: 13px; font-weight: 800; }}
QFrame#identityCard {{ background: #17191e; border: 1px solid #3a2a33; border-radius: 14px; }}
QFrame#identityHead {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #6a2230, stop:1 #24161b);
                       border: none; border-top-left-radius: 14px; border-top-right-radius: 14px; }}
QLabel#identityChip {{ color: #ffd9de; background: #c23a4f; border-radius: 5px; padding: 2px 8px; font-size: 10px; font-weight: 800; }}
QLabel#navBadge {{ background: {BAD}; color: white; border-radius: 9px; font-size: 10px; font-weight: 800;
                   min-width: 18px; max-width: 18px; min-height: 18px; max-height: 18px; qproperty-alignment: AlignCenter; }}
QFrame#notice {{ background: #221a1e; border: 1px solid #4a2a35; border-radius: 10px; }}
QFrame#okNotice {{ background: #15211b; border: 1px solid #24432f; border-radius: 10px; }}
QFrame#divider {{ background: {BORDER}; border: none; max-height: 1px; min-height: 1px; }}
QLabel#brand {{ font-family: 'Segoe UI Variable Display'; font-size: 19px; font-weight: 700; }}
QLabel#brandNote {{ color: {MUTED}; font-size: 11px; }}
QLabel#navSection {{ color: {SUBTLE}; font-size: 10px; font-weight: 700; letter-spacing: 1px; padding: 10px 14px 4px 14px; }}
QLabel#pageTitle {{ font-family: 'Segoe UI Variable Display'; font-size: 28px; font-weight: 800; }}
QLabel#pageLead {{ color: {MUTED}; font-size: 13px; }}
QLabel#playerName {{ font-family: 'Segoe UI Variable Display'; font-size: 30px; font-weight: 800; }}
QLabel#sectionTitle {{ font-family: 'Segoe UI Variable Display'; font-size: 18px; font-weight: 700; }}
QLabel#cardTitle {{ color: {MUTED}; font-size: 11px; font-weight: 700; letter-spacing: 0.5px; }}
QLabel#statLabel {{ color: {MUTED}; font-size: 12px; }}
QLabel#kpiValue {{ font-family: 'Segoe UI Variable Display'; font-size: 32px; font-weight: 800; }}
QLabel#bigValue {{ font-family: 'Segoe UI Variable Display'; font-size: 21px; font-weight: 700; }}
QLabel#midValue {{ font-family: 'Segoe UI Variable Display'; font-size: 15px; font-weight: 600; }}
QLabel#smallMuted {{ color: {MUTED}; font-size: 11px; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#body {{ color: #cfd3da; font-size: 13px; }}
QLabel#insightTitle {{ font-family: 'Segoe UI Variable Display'; font-size: 15px; font-weight: 600; }}
QLabel#chip {{ color: #c4c8d0; background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 9px; padding: 2px 9px; font-size: 11px; font-weight: 600; }}
QLabel#chipGood {{ color: {GOOD}; background: #15241d; border: 1px solid #24432f; border-radius: 9px; padding: 2px 9px; font-size: 11px; font-weight: 700; }}
QLabel#chipBad {{ color: {BAD}; background: #2a1719; border: 1px solid #4d2629; border-radius: 9px; padding: 2px 9px; font-size: 11px; font-weight: 700; }}
QLabel#chipWarn {{ color: {MID}; background: #2a2416; border: 1px solid #4d4126; border-radius: 9px; padding: 2px 9px; font-size: 11px; font-weight: 700; }}
QLabel#stepNumber {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 14px; color: {TEXT}; font-weight: 700; qproperty-alignment: AlignCenter; min-width: 28px; max-width: 28px; min-height: 28px; max-height: 28px; }}
QLabel#stepDone {{ background: {GOOD}; border-radius: 14px; color: #0f1014; font-weight: 800; qproperty-alignment: AlignCenter; min-width: 28px; max-width: 28px; min-height: 28px; max-height: 28px; }}
QPushButton {{ background: {SURFACE_2}; border: 1px solid #30343c; border-radius: 8px; padding: 6px 14px; font-weight: 600; color: #dfe2e7; }}
QPushButton:hover {{ background: #262a31; border-color: #3d424b; }}
QPushButton:pressed {{ background: #1a1c21; }}
QPushButton:focus {{ border-color: {ACCENT}; }}
QPushButton:disabled {{ background: #18191d; color: {SUBTLE}; border-color: #23252b; }}
QPushButton#primaryButton {{ background: {ACCENT}; color: #ffffff; border: 0; font-weight: 700; }}
QPushButton#primaryButton:hover {{ background: #ff6a8f; }}
QPushButton#primaryButton:disabled {{ background: #3a2129; color: #8f6a75; }}
QPushButton#navButton {{ border: 0; background: transparent; border-radius: 10px; color: #a9afb9; text-align: left; padding: 10px 14px; font-size: 14px; font-weight: 600; }}
QPushButton#navButton:hover {{ background: rgba(255,255,255,10); color: {TEXT}; }}
QPushButton#navButton:checked {{ background: rgba(255,255,255,20); color: {TEXT}; border: 1px solid rgba(255,255,255,22); }}
QPushButton#linkButton {{ background: transparent; border: 0; color: {ACCENT}; padding: 2px 0; font-weight: 600; text-align: left; }}
QPushButton#linkButton:hover {{ color: #ff8aa6; }}
QPushButton#segment {{ background: transparent; border: 1px solid #30343c; border-radius: 7px; padding: 5px 12px; color: {MUTED}; }}
QPushButton#segment:checked {{ background: #2a2d34; border-color: #4a4f58; color: {TEXT}; }}
QCheckBox {{ color: #cfd3da; spacing: 10px; }}
QCheckBox::indicator {{ width: 17px; height: 17px; border-radius: 4px; border: 1px solid #3d424b; background: {BG}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QLineEdit {{ background: {BG}; border: 1px solid #30343c; border-radius: 8px; padding: 7px 10px; selection-background-color: #5a2a38; }}
QLineEdit:focus {{ border-color: {ACCENT}; }}
QComboBox {{ background: {SURFACE_2}; border: 1px solid #30343c; border-radius: 8px; padding: 5px 10px; min-height: 20px; }}
QComboBox:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {SURFACE_2}; border: 1px solid #30343c; selection-background-color: #2f333b; padding: 4px; outline: 0; }}
QTableWidget {{ background: transparent; alternate-background-color: #1a1c21; border: none; color: #d5d8de; outline: 0; gridline-color: transparent; }}
QTableWidget::item {{ padding: 6px 10px; border-bottom: 1px solid #202328; }}
QTableWidget::item:selected {{ background: #262a31; color: {TEXT}; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{ background: {SURFACE}; color: {SUBTLE}; border: none; border-bottom: 1px solid {BORDER}; padding: 8px 10px; font-size: 11px; font-weight: 700; }}
QTableCornerButton::section {{ background: {SURFACE}; border: none; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #2c2f36; min-height: 32px; border-radius: 4px; }}
QScrollBar::handle:vertical:hover {{ background: #3a3e46; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #2c2f36; min-width: 32px; border-radius: 4px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QProgressBar {{ background: {BG}; border: 1px solid {BORDER}; border-radius: 5px; max-height: 8px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ border-radius: 4px; background: {ACCENT}; }}
QToolTip {{ background: #24272e; color: {TEXT}; border: 1px solid #3a3e46; padding: 6px; }}
QMenu {{ background: {SURFACE_2}; border: 1px solid #30343c; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 5px; }}
QMenu::item:selected {{ background: #2f333b; }}
"""
