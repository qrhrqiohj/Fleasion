from PySide6.QtWidgets import QWidget, QSizePolicy
from PySide6.QtGui import QPixmap, QImage
from PySide6.QtCore import Qt, QTimer
from PIL import Image, ImageDraw

from gameCard import Ui_GameCard   # <-- THIS is the correct import


class GameCardWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.ui = Ui_GameCard()
        self.ui.setupUi(self)

        # Nice default behavior
        vertical_policy = self.ui.thumbLabel.sizePolicy().verticalPolicy()

        # Set horizontal to Expanding, vertical stays the same
        self.ui.thumbLabel.setSizePolicy(QSizePolicy.Expanding, vertical_policy)
        self.ui.thumbLabel.setScaledContents(False)
        self.ui.thumbLabel.setMinimumWidth(1)

        self._current_pixmap = None


    def set_data(self, name: str, created: str, updated: str):
        self.ui.nameLabel.setText(name)
        self.ui.createdLabel.setText(f"Created: {created}")
        self.ui.updatedLabel.setText(f"Updated: {updated}")
    
    def qpixmap_to_pil(pixmap: QPixmap) -> Image.Image:
        qimg = pixmap.toImage().convertToFormat(QImage.Format_RGBA8888)

        width = qimg.width()
        height = qimg.height()

        buffer = qimg.bits().tobytes()

        return Image.frombytes(
            "RGBA",
            (width, height),
            buffer,
        )

    def refresh_thumbnail(self):
        if hasattr(self, "_current_pixmap") and self._current_pixmap:
            pix = self._current_pixmap
            self.set_thumbnail(pix)

    def set_thumbnail(self, pixmap: QPixmap | None, radius: int = 4, scale_factor: int = 2):
        self._current_pixmap = pixmap
        label = self.ui.thumbLabel

        if not pixmap or pixmap.isNull():
            label.setText("No thumbnail")
            return

        label_w = label.width()
        label_h = label.height()

        if label_w == 0 or label_h == 0:
            return

        # ---- QPixmap -> PIL ----
        qimg = pixmap.toImage().convertToFormat(QImage.Format_RGBA8888)
        img = Image.frombytes(
            "RGBA",
            (qimg.width(), qimg.height()),
            qimg.bits().tobytes(),
        )

        src_w, src_h = img.size
        label_ratio = label_w / label_h
        src_ratio = src_w / src_h

        # ---- Center crop ----
        if src_ratio > label_ratio:
            new_w = int(src_h * label_ratio)
            left = (src_w - new_w) // 2
            box = (left, 0, left + new_w, src_h)
        else:
            new_h = int(src_w / label_ratio)
            top = (src_h - new_h) // 2
            box = (0, top, src_w, top + new_h)

        img = img.crop(box)

        # ---- Overscale ----
        big_w = label_w * scale_factor
        big_h = label_h * scale_factor
        img = img.resize((big_w, big_h), Image.LANCZOS)

        # ---- Rounded corners at high resolution ----
        mask = Image.new("L", (big_w, big_h), 0)
        draw = ImageDraw.Draw(mask)
        draw.rounded_rectangle(
            (0, 0, big_w, big_h),
            radius=radius * scale_factor,
            fill=255,
        )
        img.putalpha(mask)

        # ---- Downscale to final size ----
        img = img.resize((label_w, label_h), Image.LANCZOS)

        # ---- PIL -> QPixmap ----
        out_qimg = QImage(
            img.tobytes("raw", "RGBA"),
            img.width,
            img.height,
            QImage.Format_RGBA8888,
        )

        label.setPixmap(QPixmap.fromImage(out_qimg))





    def on_join(self, fn):
        self.ui.joinButton.clicked.connect(fn)

    def on_open(self, fn):
        self.ui.openButton.clicked.connect(fn)
    