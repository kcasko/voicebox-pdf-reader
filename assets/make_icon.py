"""Draws assets/pdfdesk.ico: a page with sound waves. Run again only to change the icon."""

import os
import struct
import sys

from PySide6.QtCore import QBuffer, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPainterPath, QPen

SIZES = [16, 24, 32, 48, 64, 128, 256]


def draw(size):
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.scale(size / 256, size / 256)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(196, 44, 60))
    painter.drawRoundedRect(QRectF(8, 8, 240, 240), 44, 44)
    page = QPainterPath()
    page.moveTo(58, 36)
    page.lineTo(150, 36)
    page.lineTo(198, 84)
    page.lineTo(198, 220)
    page.lineTo(58, 220)
    page.closeSubpath()
    painter.setBrush(QColor(255, 255, 255))
    painter.drawPath(page)
    painter.setBrush(QColor(196, 44, 60))
    speaker = QPainterPath()
    speaker.moveTo(78, 126)
    speaker.lineTo(98, 126)
    speaker.lineTo(124, 102)
    speaker.lineTo(124, 182)
    speaker.lineTo(98, 158)
    speaker.lineTo(78, 158)
    speaker.closeSubpath()
    painter.drawPath(speaker)
    painter.setBrush(Qt.NoBrush)
    painter.setPen(QPen(QColor(196, 44, 60), 11, Qt.SolidLine, Qt.RoundCap))
    for radius in (22, 42):
        painter.drawArc(QRectF(QPointF(124 - radius, 142 - radius), QPointF(124 + radius, 142 + radius)), -50 * 16, 100 * 16)
    painter.end()
    return image


def png_bytes(image):
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


def main():
    app = QGuiApplication(sys.argv)
    images = [png_bytes(draw(size)) for size in SIZES]
    offset = 6 + 16 * len(SIZES)
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "pdfdesk.ico"), "wb") as f:
        f.write(struct.pack("<HHH", 0, 1, len(SIZES)))
        for size, data in zip(SIZES, images):
            f.write(struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset))
            offset += len(data)
        for data in images:
            f.write(data)
    del app


main()
