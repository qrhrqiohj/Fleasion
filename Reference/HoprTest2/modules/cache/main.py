from PresetWindow import Ui_Form as PresetWindowUI
from game_card_widget import GameCardWidget
from dialog4_ui import Ui_Dialog as Dialog4UI
from dialog3_ui import Ui_Dialog as Dialog3UI
from dialog2_ui import Ui_Dialog as Dialog2UI
from dialog1_ui import Ui_Dialog as Dialog1UI
from PySide6.QtCore import QFile, QSortFilterProxyModel
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QTreeView, QTableView, QWidget, QDialog, QPushButton, QHBoxLayout, QGridLayout, QSizePolicy, QLineEdit, QCheckBox,
    QMenu, QAbstractItemView, QHeaderView, QStyledItemDelegate, QApplication, QLabel, QSlider, QFrame, QVBoxLayout,
    QTextEdit, QFileDialog, QSplitter
)
from PySide6.QtGui import QStandardItemModel, QStandardItem, QPixmap
from PySide6.QtCore import Qt, QObject, QEvent, QPersistentModelIndex, QTimer
from pyvistaqt import QtInteractor
import os
import gzip
import subprocess
import sys
import tempfile
import pygame
import json
import time
import win32crypt
import base64
import re
import threading
import requests
import struct
import shutil
from pathlib import Path
from shiboken6 import isValid
from mutagen import File as MutagenFile
from urllib.parse import urlparse, urlunparse
from datetime import datetime
import gc
import pyvista as pv
import vtk
vtk.vtkObject.GlobalWarningDisplayOff()


# ASSET TYPES


ASSET_TYPES = [
    (1, "Image"),
    (2, "TShirt"),
    (3, "Audio"),
    (4, "Mesh"),
    (5, "Lua"),
    (6, "HTML"),
    (7, "Text"),
    (8, "Hat"),
    (9, "Place"),
    (10, "Model"),
    (11, "Shirt"),
    (12, "Pants"),
    (13, "Decal"),
    (16, "Avatar"),
    (17, "Head"),
    (18, "Face"),
    (19, "Gear"),
    (21, "Badge"),
    (22, "GroupEmblem"),
    (24, "Animation"),
    (25, "Arms"),
    (26, "Legs"),
    (27, "Torso"),
    (28, "RightArm"),
    (29, "LeftArm"),
    (30, "LeftLeg"),
    (31, "RightLeg"),
    (32, "Package"),
    (33, "YouTubeVideo"),
    (34, "GamePass"),
    (35, "App"),
    (37, "Code"),
    (38, "Plugin"),
    (39, "SolidModel"),
    (40, "MeshPart"),
    (41, "HairAccessory"),
    (42, "FaceAccessory"),
    (43, "NeckAccessory"),
    (44, "ShoulderAccessory"),
    (45, "FrontAccessory"),
    (46, "BackAccessory"),
    (47, "WaistAccessory"),
    (48, "ClimbAnimation"),
    (49, "DeathAnimation"),
    (50, "FallAnimation"),
    (51, "IdleAnimation"),
    (52, "JumpAnimation"),
    (53, "RunAnimation"),
    (54, "SwimAnimation"),
    (55, "WalkAnimation"),
    (56, "PoseAnimation"),
    (57, "EarAccessory"),
    (58, "EyeAccessory"),
    (59, "LocalizationTableManifest"),
    (61, "EmoteAnimation"),
    (62, "Video"),
    (63, "TexturePack"),
    (64, "TShirtAccessory"),
    (65, "ShirtAccessory"),
    (66, "PantsAccessory"),
    (67, "JacketAccessory"),
    (68, "SweaterAccessory"),
    (69, "ShortsAccessory"),
    (70, "LeftShoeAccessory"),
    (71, "RightShoeAccessory"),
    (72, "DressSkirtAccessory"),
    (73, "FontFamily"),
    (74, "FontFace"),
    (75, "MeshHiddenSurfaceRemoval"),
    (76, "EyebrowAccessory"),
    (77, "EyelashAccessory"),
    (78, "MoodAnimation"),
    (79, "DynamicHead"),
    (80, "CodeSnippet"),
]


def get_roblosecurity():
    path = os.path.expandvars(
        r"%LocalAppData%/Roblox/LocalStorage/RobloxCookies.dat")
    try:
        if not os.path.exists(path):
            return None
        with open(path, "r") as f:
            data = json.load(f)
        cookies_data = data.get("CookiesData")
        if not cookies_data or not win32crypt:
            return None
        enc = base64.b64decode(cookies_data)
        dec = win32crypt.CryptUnprotectData(enc, None, None, None, 0)[1]
        s = dec.decode(errors="ignore")
        m = re.search(r"\.ROBLOSECURITY\s+([^\s;]+)", s)
        return m.group(1) if m else None
    except Exception:
        return None


# SORT PROXY


class SortProxy(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._search_text = ""
        self._search_cols = None
        self._allowed_type_ids = None  # None = all
        # list of callables(row,parent,model)->bool
        self._conditions = []

        self.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.setDynamicSortFilter(True)

    def set_type_filter(self, type_ids_or_none):
        self._allowed_type_ids = type_ids_or_none
        self.invalidateFilter()

    def set_search(self, text: str, cols=None, conditions=None):
        self._search_text = (text or "").strip().lower()
        self._search_cols = cols
        self._conditions = conditions or []
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):
        m = self.sourceModel()

        # asset type menu filter (Finder Type column = 2)
        if self._allowed_type_ids is not None:
            idx_type = m.index(source_row, 2, source_parent)
            type_id = m.data(idx_type, Qt.UserRole)
            if type_id not in self._allowed_type_ids:
                return False

        # structured conditions
        for cond in self._conditions:
            if not cond(source_row, source_parent, m):
                return False

        # normal substring search
        if not self._search_text:
            return True

        cols = self._search_cols
        if cols is None:
            cols = range(m.columnCount())

        needle = self._search_text
        for c in cols:
            idx = m.index(source_row, c, source_parent)
            val = m.data(idx)
            if val is None:
                continue
            if needle in str(val).lower():
                return True

        return False

    def lessThan(self, left, right):
        col = left.column()
        m = self.sourceModel()

        if col in (0, 2):
            return str(m.data(left)) < str(m.data(right))

        l = m.data(left, Qt.UserRole)
        r = m.data(right, Qt.UserRole)

        if l is None or r is None:
            return str(m.data(left)) < str(m.data(right))

        return l < r

# Hover delegate


class HoverDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.hover_row = -1

    def paint(self, painter, option, index):
        from PySide6.QtGui import QColor
        from PySide6.QtWidgets import QStyle

        option.state &= ~QStyle.State_HasFocus

        if index.row() == self.hover_row and not (option.state & QStyle.State_Selected):
            painter.save()
            painter.fillRect(option.rect, QColor("#3d3d3d"))
            painter.restore()

        super().paint(painter, option, index)

# UI loader


def load_ui(path, parent=None):
    loader = QUiLoader()
    f = QFile(path)
    f.open(QFile.ReadOnly)
    ui = loader.load(f, parent)
    f.close()
    return ui


class AudioPlayer:
    def __init__(self, parent, filepath, preview_frame):
        self.parent = parent
        self.filepath = filepath
        self.preview_frame = preview_frame
        self.is_playing = False
        self.position = 0
        self.duration = 0
        self.active = True
        self.start_time = 0

        try:
            audio = MutagenFile(filepath)
            self.duration = audio.info.length if audio else 0
            print(
                f"Audio loaded: {self.filepath}, Duration: {self.format_time(self.duration)}")
        except Exception as e:
            print(f"Failed to load audio duration {self.filepath}: {e}")
            self.duration = 0

        pygame.mixer.init()
        self.setup_ui()
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_progress)
        self.timer.start(100)

    def setup_ui(self):
        layout = self.preview_frame.layout()
        if not layout:
            print("No layout found in preview_frame for AudioPlayer")
            return

        file_name = os.path.basename(self.filepath)
        size = os.path.getsize(self.filepath)
        layout.addWidget(QLabel(f"File: {file_name}"))
        ftype = "MP3" if self.filepath.endswith('.mp3') else "OGG"
        layout.addWidget(QLabel(
            f"Type: {ftype}, Size: {self.format_size(size)}, Duration: {self.format_time(self.duration)}"))

        controls_frame = QFrame()
        controls_layout = QHBoxLayout(controls_frame)

        self.play_pause_button = QPushButton(
            "Play" if not self.is_playing else "Pause")
        self.play_pause_button.clicked.connect(self.toggle_play_pause)
        controls_layout.addWidget(self.play_pause_button)

        controls_layout.addWidget(QLabel("Volume:"))
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(int(self.parent.persistent_volume * 100))
        self.volume_slider.valueChanged.connect(self.set_volume)
        controls_layout.addWidget(self.volume_slider)

        layout.addWidget(controls_frame)

        self.progress_slider = QSlider(Qt.Horizontal)
        self.progress_slider.setRange(0, int(self.duration * 1000))
        self.progress_slider.sliderPressed.connect(self.start_scrub)
        self.progress_slider.sliderReleased.connect(self.seek_audio)
        layout.addWidget(self.progress_slider)

        self.time_label = QLabel(f"00:00 / {self.format_time(self.duration)}")
        layout.addWidget(self.time_label)

        button_frame = QFrame()
        button_layout = QHBoxLayout(button_frame)
        button_layout.addWidget(QPushButton(
            "Close Preview", clicked=lambda: self.parent.close_preview(self.preview_frame, deselect=True)))
        button_layout.addWidget(QPushButton(
            "Open Externally", clicked=lambda: self.open_externally(self.filepath)))
        layout.addWidget(button_frame)

        self.preview_frame.show()
        self.preview_frame.update()

    def toggle_play_pause(self):
        if not self.active:
            return
        if not self.is_playing:
            if self.position >= self.duration:
                self.position = 0
                self.progress_slider.setValue(0)
            pygame.mixer.music.load(self.filepath)
            pygame.mixer.music.play(loops=0)
            pygame.mixer.music.set_pos(self.position)
            pygame.mixer.music.set_volume(self.parent.persistent_volume)
            self.start_time = time.time() - self.position
            self.is_playing = True
            self.play_pause_button.setText("Pause")
        else:
            self.position = self.get_current_position()
            pygame.mixer.music.stop()
            self.is_playing = False
            self.play_pause_button.setText("Play")

    def set_volume(self, value):
        if not self.active:
            return
        volume = value / 100
        pygame.mixer.music.set_volume(volume)
        self.parent.persistent_volume = volume

    def start_scrub(self):
        if not self.active or not self.is_playing:
            return
        self.position = self.get_current_position()
        pygame.mixer.music.stop()
        self.is_playing = False
        self.play_pause_button.setText("Play")

    def seek_audio(self):
        if not self.active:
            return
        self.position = self.progress_slider.value() / 1000
        self.position = max(0, min(self.position, self.duration))
        self.time_label.setText(
            f"{self.format_time(self.position)} / {self.format_time(self.duration)}")
        if self.is_playing:
            pygame.mixer.music.load(self.filepath)
            pygame.mixer.music.play(loops=0)
            pygame.mixer.music.set_pos(self.position)
            self.start_time = time.time() - self.position

    def get_current_position(self):
        if self.is_playing:
            return time.time() - self.start_time
        return self.position

    def update_progress(self):
        if not self.active or not self.preview_frame.isVisible():
            return
        if self.is_playing:
            current_pos = self.get_current_position()
            if current_pos >= self.duration:
                pygame.mixer.music.stop()
                self.is_playing = False
                self.position = self.duration
                self.progress_slider.setValue(int(self.duration * 1000))
                self.time_label.setText(
                    f"{self.format_time(self.duration)} / {self.format_time(self.duration)}")
                self.play_pause_button.setText("Play")
            else:
                self.progress_slider.setValue(int(current_pos * 1000))
                self.time_label.setText(
                    f"{self.format_time(current_pos)} / {self.format_time(self.duration)}")

    def stop(self):
        self.active = False
        if self.is_playing:
            self.position = self.get_current_position()
            pygame.mixer.music.stop()
        self.timer.stop()

    def format_time(self, seconds):
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{mins:02d}:{secs:02d}"

    def format_size(self, size_in_bytes):
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_in_bytes < 1024.0:
                return f"{size_in_bytes:.2f} {unit}"
            size_in_bytes /= 1024.0
        return f"{size_in_bytes:.2f} TB"

    def open_externally(self, filepath):
        if not os.path.exists(filepath):
            print(f"File does not exist: {filepath}")
            return
        try:
            os.startfile(filepath)
        except Exception as e:
            print(f"Failed to open {filepath} externally: {e}")

# Module entry


class Main(QObject):

    def __init__(self, tab_widget: QWidget):
        self._desired_column_sizes = {}
        self._adjusting_columns = False
        super().__init__(tab_widget)
        self.tab_widget = tab_widget
        self.base_path = os.path.dirname(__file__)

        # Stacked widget
        self.stacked = tab_widget.findChild(QWidget, "stackedWidget")
        self.loader_btn = tab_widget.findChild(QWidget, "CacheLoaderButton")
        self.custom_presets_btn = tab_widget.findChild(
            QWidget, "CustomPresetsButton")
        self.finder_btn = tab_widget.findChild(QWidget, "CacheFinderButton")
        self.presets_btn = tab_widget.findChild(QWidget, "PresetsButton")

        self.loader_btn.clicked.connect(
            lambda: self.stacked.setCurrentIndex(0))
        self.custom_presets_btn.clicked.connect(
            lambda: self.stacked.setCurrentIndex(1))
        self.finder_btn.clicked.connect(
            lambda: self.stacked.setCurrentIndex(2))
        self.presets_btn.clicked.connect(
            lambda: self.stacked.setCurrentIndex(3))

        # Cache finder
        self.table_view = tab_widget.findChild(QWidget, "tableView")
        self.filter_button = tab_widget.findChild(QWidget, "filterButton")
        self.settings_button = tab_widget.findChild(QWidget, "pushButton_14")
        self.previewFrame = tab_widget.findChild(QWidget, "previewFrame")
        if self.previewFrame:
            self.previewFrame.hide()

        self.splitter = tab_widget.findChild(QSplitter, "splitter")
        if self.splitter:
            # Connect to the splitterMoved signal
            self.splitter.splitterMoved.connect(
                lambda pos, index: self._on_column_resized(
                    -1, 0, 0, self.table_view)
            )

        self._setup_table()
        self._setup_filter_menu()
        self._setup_settings_menu()

        # Cache searching wtv
        self.loader_search_loaded = tab_widget.findChild(
            QLineEdit, "lineEdit_2")
        self.loader_search_available = tab_widget.findChild(
            QLineEdit, "SearchAvailableInput")

        def apply_loader_filter():
            text = ""
            if self.loader_search_loaded:
                text = self.loader_search_loaded.text()

            self.loader_proxy.set_search(text, cols=[1, 2, 3])

        if self.loader_search_loaded:
            self.loader_search_loaded.textChanged.connect(
                lambda _: apply_loader_filter())

        if self.loader_search_available:
            self.loader_search_available.textChanged.connect(
                lambda _: apply_loader_filter())

        # Finder/dumper/wtv search
        self.finder_search = tab_widget.findChild(QLineEdit, "lineEdit_5")

        # Column filter checkboxes next to Finder search
        self.finder_cb_name = tab_widget.findChild(QCheckBox, "checkBox_4")
        self.finder_cb_type = tab_widget.findChild(QCheckBox, "checkBox_5")
        self.finder_cb_size = tab_widget.findChild(QCheckBox, "checkBox_6")
        self.finder_cb_date = tab_widget.findChild(QCheckBox, "checkBox_7")
        self.finder_cb_id = tab_widget.findChild(QCheckBox, "checkBox_8")

        for cb in (self.finder_cb_name, self.finder_cb_type, self.finder_cb_size, self.finder_cb_date, self.finder_cb_id):
            if cb:
                cb.setChecked(True)

        if self.finder_search:
            self.finder_search.textChanged.connect(
                lambda _: self._apply_finder_filters())

        for cb in (self.finder_cb_name, self.finder_cb_id, self.finder_cb_type, self.finder_cb_size, self.finder_cb_date):
            if cb:
                cb.toggled.connect(lambda _: self._apply_finder_filters())

        # Cache loader
        self.create_cache_btn = tab_widget.findChild(
            QWidget, "CreateCacheButton")
        self.create_cache_btn.clicked.connect(self.open_cache_dialogs)
        self.loader_table = tab_widget.findChild(QWidget, "tableView_2")
        self._setup_loader_table()

        # Custom presets
        self.preset_tree = tab_widget.findChild(QWidget, "treeView")
        self.create_preset_btn = tab_widget.findChild(
            QWidget, "CreatePresetButton")
        self.apply_preset_btn = tab_widget.findChild(
            QWidget, "ApplyPresetButton")

        self._setup_preset_tree()

        self.create_preset_btn.clicked.connect(self.create_preset)
        self.apply_preset_btn.clicked.connect(self.apply_preset)

        self.delivery_endpoint = "/v1/assets/batch"

        self.cache_logs = {}

        threading.Thread(target=self.name_resolver_loop, daemon=True).start()

        # Presets
        self.presets_search = tab_widget.findChild(
            QLineEdit, "PresetsSearchLine")

        self._preset_search_timer = QTimer(self.tab_widget)
        self._preset_search_timer.setSingleShot(True)
        self._preset_search_timer.timeout.connect(
            self._apply_presets_search_filter)

        if self.presets_search:
            self.presets_search.textChanged.connect(
                lambda: self._preset_search_timer.start(80))

        self.presets_scroll = tab_widget.findChild(QWidget, "Results")
        if self.presets_scroll:
            self.presets_container = self.presets_scroll.findChild(
                QWidget, "resultsContainer")
            if not self.presets_container:
                self.presets_container = QWidget()
                self.presets_container.setObjectName("resultsContainer")
                self.presets_scroll.setWidget(self.presets_container)

            # Set up grid layout for preset cards
            if self.presets_container.layout() is None:
                self.presets_grid = QGridLayout(self.presets_container)
                self.presets_container.setLayout(self.presets_grid)
            else:
                self.presets_grid = self.presets_container.layout()

            self.presets_grid.setContentsMargins(8, 8, 8, 8)
            self.presets_grid.setSpacing(8)
            self.presets_grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)

            self._preset_cards = []
            self._populate_test_preset_cards()
            self._preset_relayout_pending = False
            QTimer.singleShot(0, self._relayout_preset_cards)

            pygame.mixer.init()
            self.persistent_volume = 1.0
            self.audio_players = {}
            self.temp_files = {}
            tools_dir = os.path.join(self.base_path, "tools")

            # After tools_dir = os.path.join(self.base_path, "tools")
            self.rojo_path = os.path.join(tools_dir, "rojo", "rojo.exe")

            # Put these in something like: modules/modules/cache/tools/animpreview/
            self.animpreview_script = os.path.join(
                tools_dir, "animpreview", "animpreview.py")
            self.animpreview_project_template = os.path.join(
                tools_dir, "animpreview", "default.project.json")

            self.animpreview_r15_rig = os.path.join(
                tools_dir, "animpreview", "R15Rig.rbxmx")
            self.animpreview_r6_rig = os.path.join(
                tools_dir, "animpreview", "R6Rig.rbxmx")

            self.temp_dirs = {}

    # Cache loader

    # Dialog flow

    def open_cache_dialogs(self):
        # Dialog 1
        dialog1 = QDialog(self.tab_widget)
        ui1 = Dialog1UI()
        ui1.setupUi(dialog1)
        if not dialog1.exec():
            return

        # Dialog 2
        dialog2 = QDialog(self.tab_widget)
        ui2 = Dialog2UI()
        ui2.setupUi(dialog2)
        self.add_import_button(ui2)
        if not dialog2.exec():
            return

        # Dialog 3
        dialog3 = QDialog(self.tab_widget)
        ui3 = Dialog3UI()
        ui3.setupUi(dialog3)
        self.add_import_button(ui3)
        dialog3.exec()

    def add_import_button(self, ui):
        import_btn = QPushButton("Import")
        layout = QHBoxLayout()
        layout.addWidget(import_btn)

        ui.buttonBox.layout().addLayout(layout)
        import_btn.clicked.connect(lambda: print("Import clicked!"))

    # Cache finder

    def _setup_table(self):
        self.model = QStandardItemModel(0, 5, self.tab_widget)
        self.model.setHorizontalHeaderLabels(
            ["Name", "ID", "Type", "Size", "Date"]
        )

        self.proxy = SortProxy(self.tab_widget)
        self.proxy.setSourceModel(self.model)

        tv = self.table_view
        tv.setModel(self.proxy)
        # Show preview frame when user clicks a row
        if getattr(self, "previewFrame", None):
            sel = tv.selectionModel()
            if sel:
                sel.selectionChanged.connect(self._on_finder_selection_changed)
        tv.setSelectionBehavior(QAbstractItemView.SelectRows)
        # Allow multi-select
        tv.setSelectionMode(QAbstractItemView.ExtendedSelection)
        tv.setSortingEnabled(True)
        tv.verticalHeader().setVisible(False)
        tv.sortByColumn(0, Qt.AscendingOrder)

        # Enable mouse tracking for hover effects
        tv.setMouseTracking(True)

        # Remove focus outline
        tv.setFocusPolicy(Qt.StrongFocus)

        # Make rows more compact
        tv.verticalHeader().setDefaultSectionSize(20)

        # Ensure full row highlighting (stretch last section)
        tv.horizontalHeader().setStretchLastSection(True)

        # Align header text to the left
        tv.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        # Make all columns resizable by user
        header = tv.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)

        # Set initial widths
        QTimer.singleShot(0, lambda: (
            self.table_view.setColumnWidth(0, 250),
            self.table_view.setColumnWidth(1, 100),
            self.table_view.setColumnWidth(2, 100),
            self.table_view.setColumnWidth(3, 80),
            self.table_view.setColumnWidth(4, 180),
        ))

        header.sectionResized.connect(
            lambda i, old, new, tv=self.table_view: self._on_column_resized(
                i, old, new, tv)
        )

        # Make header more compact
        tv.horizontalHeader().setMinimumHeight(22)
        tv.horizontalHeader().setMaximumHeight(22)
        tv.horizontalHeader().setMinimumWidth(32)

        # Install hover delegate
        self.hover_delegate = HoverDelegate(tv)
        tv.setItemDelegate(self.hover_delegate)

        # Install event filter for hover tracking
        tv.viewport().installEventFilter(self)
        tv.viewport().setMouseTracking(True)

        # Enable context menu
        tv.setContextMenuPolicy(Qt.CustomContextMenu)
        tv.customContextMenuRequested.connect(self._show_context_menu)

        # Install event filter for keyboard shortcuts on table view
        tv.installEventFilter(self)

    def _on_column_resized(self, logical_index, old_size, new_size, view=None):
        """
        Handles column resizing for both QTableView and QTreeView.
        `view` is the table/tree that triggered the resize. Defaults to main table.
        """
        if view is None:
            view = self.table_view  # fallback

        # Get header safely
        if isinstance(view, QTreeView):
            header = view.header()
        elif isinstance(view, QTableView):
            header = view.horizontalHeader()
        else:
            return  # unknown type

        count = header.count()
        viewport_right = header.viewport().width()

        # Guard against recursion
        if getattr(self, "_adjusting_columns", False):
            return

        # Store user-desired sizes per view
        if logical_index >= 0:
            if not hasattr(self, "_desired_column_sizes"):
                self._desired_column_sizes = {}
            if view not in self._desired_column_sizes:
                self._desired_column_sizes[view] = {}
            self._desired_column_sizes[view][logical_index] = new_size

        self._adjusting_columns = True
        try:
            # Right → left (visual order)
            for visual in range(count):
                logical = header.logicalIndex(visual)
                left = header.sectionPosition(logical)

                # Get last user-desired size, default to current
                desired = self._desired_column_sizes.get(view, {}).get(
                    logical, header.sectionSize(logical)
                )

                # Optional: skip 0 if it's tree indentation for QTreeView
                # if isinstance(view, QTreeView) and logical == 0:
                #     continue

                offset = 32 * (count - visual) - 32
                max_right = viewport_right - offset
                max_width = max_right - left
                if max_width < 0:
                    max_width = 0

                new_width = min(desired, max_width)

                if header.sectionSize(logical) != new_width:
                    header.resizeSection(logical, new_width)
        finally:
            self._adjusting_columns = False

    def _on_finder_selection_changed(self, selected, deselected):
        if not getattr(self, "previewFrame", None):
            return

        if not selected.indexes():
            return

        # Get the selected asset
        proxy_index = selected.indexes()[0]
        source_index = self.proxy.mapToSource(proxy_index)
        row = source_index.row()

        # Get asset ID from the ID column (column 1)
        id_item = self.model.item(row, 1)
        if not id_item:
            return

        asset_id = id_item.data(Qt.UserRole)

        # Get cache data
        cache_info = self.cache_logs.get(asset_id)
        if not cache_info or "cache_data" not in cache_info:
            self.previewFrame.hide()
            return

        cache_data = cache_info.get("cache_data")
        asset_type_id = cache_info.get("assetTypeId")

        # Display preview
        self.display_preview_enhanced(
            cache_data, asset_type_id, self.previewFrame)

    def display_preview_enhanced(self, cache_data, asset_type_id, preview_frame):
        self.close_preview(preview_frame)

        if not cache_data:
            return

        # Create temp file
        ext = self._get_extension_for_type(asset_type_id, cache_data)
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            tmp.write(cache_data)
            temp_path = tmp.name

        self.temp_files[preview_frame] = [temp_path]

        # Ensure layout exists
        if not preview_frame.layout():
            layout = QVBoxLayout(preview_frame)
            preview_frame.setLayout(layout)

        # Determine file type and display
        file_type = self._identify_file_type(cache_data)
        if asset_type_id == 24:
            file_type = "RBXM Animation"

        if file_type in ["PNG", "GIF", "JPEG", "JFIF"]:
            self._display_image_preview(temp_path, preview_frame)
        elif file_type in ["OGG", "MP3"]:
            self._display_audio_preview(temp_path, preview_frame)
        elif file_type.startswith("Mesh"):
            self._display_mesh_preview(cache_data, temp_path, preview_frame)
        elif file_type in ["JSON", "Translation (JSON)", "TTF (JSON)"]:
            self._display_json_preview(cache_data, preview_frame)
        elif file_type in ["XML", "EXTM3U"]:
            self._display_text_preview(cache_data, preview_frame)
        elif file_type == "RBXM Animation":
            self._display_animation_preview(
                cache_data, temp_path, preview_frame)
        else:
            self._display_file_info(temp_path, file_type, preview_frame)

        preview_frame.show()
        preview_frame.update()
        QTimer.singleShot(
            0, lambda: self._on_column_resized(-1, 0, 0, self.table_view))

    def _identify_file_type(self, data):
        if not data or len(data) < 12:
            return "Unknown"

        begin = data[:min(48, len(data))].decode('utf-8', errors='ignore')

        if "PNG\r\n" in begin or data[:8] == b'\x89PNG\r\n\x1a\n':
            return "PNG"
        elif begin.startswith("GIF8"):
            return "GIF"
        elif "JFIF" in begin or data[:2] == b'\xff\xd8':
            return "JPEG"
        elif "OggS" in begin:
            return "OGG"
        elif any(x in begin for x in ["TSSE", "Lavf", "ID3"]) or data[:3] == b'ID3':
            return "MP3"
        elif "<roblox!" in begin:
            return "RBXM Animation"
        elif "<roblox xml" in begin or begin.startswith("<?xml"):
            return "XML"
        elif '"version' not in begin and "version" in begin:
            mesh_version = data[:12].decode('utf-8', errors='ignore')
            return f"Mesh ({mesh_version[8:12]})"
        elif '{"locale":"' in begin:
            return "Translation (JSON)"
        elif '"name": "' in begin or begin.strip().startswith('{'):
            return "JSON"
        elif begin.startswith("#EXTM3U"):
            return "EXTM3U"
        else:
            return "Unknown"

    def _get_extension_for_type(self, asset_type_id, data):
        ftype = self._identify_file_type(data)

        ext_map = {
            "PNG": ".png",
            "GIF": ".gif",
            "JPEG": ".jpg",
            "JFIF": ".jpg",
            "OGG": ".ogg",
            "MP3": ".mp3",
            "XML": ".xml",
            "JSON": ".json",
            "EXTM3U": ".m3u",
        }

        if ftype.startswith("Mesh"):
            return ".mesh"

        return ext_map.get(ftype, ".bin")

    def _display_image_preview(self, filepath, preview_frame):
        layout = preview_frame.layout()

        pixmap = QPixmap(filepath).scaled(
            400, 400, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        img_label = QLabel()
        img_label.setPixmap(pixmap)
        img_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(img_label)

        size = os.path.getsize(filepath)
        info_text = f"Size: {self._format_size(size)} | Dimensions: {pixmap.width()}x{pixmap.height()}"
        layout.addWidget(QLabel(info_text))

        self._add_preview_buttons(filepath, preview_frame)

    def _display_audio_preview(self, filepath, preview_frame):
        player = AudioPlayer(self, filepath, preview_frame)
        self.audio_players[preview_frame] = player

    def _convert_srgb_to_linear(self, png_path):
        try:
            from PIL import Image
            import math

            def srgb2lin(s):
                s = s / 255.0
                if s <= 0.0404482362771082:
                    lin = s / 12.92
                else:
                    lin = pow(((s + 0.055) / 1.055), 2.4)
                return lin

            im = Image.open(png_path)
            new = []
            for pixel in im.getdata():
                if len(pixel) == 3:
                    new.append((
                        math.floor(srgb2lin(pixel[0]) / 2058.61501702 * 255),
                        math.floor(srgb2lin(pixel[1]) / 2058.61501702 * 255),
                        math.floor(srgb2lin(pixel[2]) / 2058.61501702 * 255),
                    ))
                else:
                    new.append((
                        math.floor(srgb2lin(pixel[0]) / 2058.61501702 * 255),
                        math.floor(srgb2lin(pixel[1]) / 2058.61501702 * 255),
                        math.floor(srgb2lin(pixel[2]) / 2058.61501702 * 255),
                        pixel[3]
                    ))
            im.close()
            newim = Image.new(im.mode, im.size)
            newim.putdata(new)
            newim.save(png_path)
        except Exception as e:
            print(f"Failed to apply sRGB conversion: {e}")

    def _display_mesh_preview(self, mesh_data, temp_path, preview_frame):
        try:
            obj_path = self._convert_mesh_to_obj(mesh_data)

            if obj_path and os.path.exists(obj_path):
                self.temp_files[preview_frame].append(obj_path)
                self._display_3d_model(obj_path, preview_frame)
            else:
                self._display_file_info(temp_path, "Mesh", preview_frame)
        except Exception as e:
            print(f"Failed to display mesh: {e}")
            self._display_file_info(temp_path, "Mesh", preview_frame)

    def _convert_mesh_to_obj(self, mesh_data):
        try:
            import mesh_processing

            # Create temp OBJ file
            with tempfile.NamedTemporaryFile(delete=False, suffix='.obj') as tmp:
                obj_path = tmp.name

            # Convert mesh data to OBJ
            obj_content = mesh_processing.convert(
                mesh_data, output_path=obj_path)

            if obj_content and os.path.exists(obj_path) and os.path.getsize(obj_path) > 0:
                print(f"Successfully converted mesh to OBJ: {obj_path}")
                return obj_path
            else:
                print("Mesh conversion produced empty or invalid OBJ file")
                return None

        except ImportError:
            print(
                "mesh_processing module not found. Please ensure mesh_processing.py is in the same directory.")
            return None
        except Exception as e:
            print(f"Mesh conversion failed: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _display_3d_model(self, obj_path, preview_frame):
        layout = preview_frame.layout()

        try:
            plotter = QtInteractor(preview_frame)
            layout.addWidget(plotter.interactor)

            model = pv.read(obj_path)

            actor = plotter.add_mesh(model, color='lightblue')

            xmin, xmax, ymin, ymax, zmin, zmax = actor.GetBounds()
            cx = (xmin + xmax) / 2
            cy = (ymin + ymax) / 2
            cz = (zmin + zmax) / 2

            size = max(xmax - xmin, ymax - ymin, zmax - zmin)
            dist = size * 2.5 if size > 0 else 10.0

            cam = plotter.camera
            cam.focal_point = (cx, cy, cz)
            cam.position = (cx, cy, cz + dist)
            cam.up = (0, 1, 0)
            cam.view_angle = 30
            cam.SetClippingRange(0.001, dist * 50)
            cam.Azimuth(205)
            plotter.render()

            plotter.set_background((0.95, 0.95, 0.95))
            plotter.add_axes()

            self.temp_files[preview_frame].append(plotter)

            info_label = QLabel(
                f"3D Model | Vertices: {model.n_points} | Faces: {model.n_cells}")
            layout.addWidget(info_label)

            self._add_preview_buttons(
                obj_path, preview_frame, show_obj_options=True)
        except Exception as e:
            print(f"Failed to display 3D model: {e}")
            layout.addWidget(QLabel(f"Error loading 3D model: {e}"))

    def _display_json_preview(self, data, preview_frame):
        import json
        layout = preview_frame.layout()

        try:
            json_obj = json.loads(data)
            formatted = json.dumps(json_obj, indent=2)
        except:
            formatted = data.decode('utf-8', errors='ignore')

        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setPlainText(formatted)
        layout.addWidget(text_edit)

        self._add_preview_buttons(None, preview_frame)

    def _display_text_preview(self, data, preview_frame):
        layout = preview_frame.layout()

        text = data.decode('utf-8', errors='ignore')
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setPlainText(text)
        layout.addWidget(text_edit)

        self._add_preview_buttons(None, preview_frame)

    def _display_animation_preview(self, data: bytes, temp_path: str, preview_frame):
        layout = preview_frame.layout()

        # Basic checks
        if not os.path.exists(self.rojo_path):
            layout.addWidget(QLabel(f"Rojo not found: {self.rojo_path}"))
            self._add_preview_buttons(temp_path, preview_frame)
            return

        if not os.path.exists(self.animpreview_script):
            layout.addWidget(
                QLabel(f"animpreview.py not found: {self.animpreview_script}"))
            self._add_preview_buttons(temp_path, preview_frame)
            return

        def run_preview() -> str:
            workdir = tempfile.mkdtemp(prefix="animpreview_")
            workdir_p = Path(workdir)

            src_anim = workdir_p / "input_anim.rbxm"
            src_anim.write_bytes(data)

            tpl = json.loads(
                Path(self.animpreview_project_template).read_text(encoding="utf-8"))
            asset_name = "Animation"
            tpl["name"] = asset_name

            tree = tpl.get("tree", {})
            keys = [k for k in tree.keys() if k != "$className"]
            node = tree.pop(keys[0]) if keys else {}
            if not isinstance(node, dict):
                node = {}

            tree[asset_name] = node
            tree[asset_name]["$path"] = str(src_anim)
            tpl["tree"] = tree

            out_project = workdir_p / "default.project.json"
            out_project.write_text(json.dumps(tpl, indent=2), encoding="utf-8")

            out_anim = workdir_p / "output_anim.rbxmx"
            cmd = [self.rojo_path, "build", str(
                out_project), "-o", str(out_anim)]

            subprocess.run(cmd, capture_output=True, text=True, check=True)
            return str(out_anim)

        # call build once
        try:
            out_anim_path = run_preview()
        except Exception as e:
            layout.addWidget(QLabel(f"Failed to build preview: {e}"))
            self._add_preview_buttons(temp_path, preview_frame)
            return

        # Decide rig type from built rbxmx
        try:
            anim_text = Path(out_anim_path).read_text(
                encoding="utf-8", errors="ignore")
        except Exception:
            anim_text = ""

        is_r15 = any(k in anim_text for k in (
            "UpperTorso", "LowerTorso",
            "LeftUpperArm", "LeftLowerArm", "LeftHand",
            "RightUpperArm", "RightLowerArm", "RightHand",
            "LeftUpperLeg", "LeftLowerLeg", "LeftFoot",
            "RightUpperLeg", "RightLowerLeg", "RightFoot",
        ))
        rig_path = self.animpreview_r15_rig if is_r15 else self.animpreview_r6_rig

        old = getattr(self, "_embedded_anim_widget", None)

        if old is not None:
            # widget may already be gone (PySide keeps python wrapper alive)
            if isValid(old):
                old.setParent(None)
                old.deleteLater()

        self._embedded_anim_widget = None

        # import animpreview & create widget
        animpreview_dir = os.path.dirname(
            os.path.abspath(self.animpreview_script))
        if animpreview_dir not in sys.path:
            sys.path.insert(0, animpreview_dir)

        import importlib
        animpreview = importlib.import_module("animpreview")

        mesh_dir = os.path.join(animpreview_dir, "R15AndR6Parts")

        viewer = animpreview.AnimPreviewWidget(
            rig_path, out_anim_path, mesh_dir=mesh_dir)
        layout.addWidget(viewer)
        self._embedded_anim_widget = viewer

    def _display_file_info(self, filepath, file_type, preview_frame):
        layout = preview_frame.layout()

        size = os.path.getsize(filepath)

        layout.addWidget(QLabel(f"File Type: {file_type}"))
        layout.addWidget(QLabel(f"File Size: {self._format_size(size)}"))

        self._add_preview_buttons(filepath, preview_frame)

    def _add_preview_buttons(self, filepath, preview_frame, show_obj_options=False):
        layout = preview_frame.layout()

        button_frame = QFrame()
        button_layout = QHBoxLayout(button_frame)

        close_btn = QPushButton("Close Preview")
        close_btn.clicked.connect(
            lambda: self.close_preview(preview_frame, deselect=True))
        button_layout.addWidget(close_btn)

        if filepath:
            if show_obj_options:
                open_btn = QPushButton("Open OBJ")
                open_menu = QMenu(preview_frame)
                open_menu.addAction("Open with Default",
                                    lambda: self._open_externally(filepath))
                open_menu.addAction(
                    "Select Program", lambda: self._select_program_to_open(filepath))
                open_btn.setMenu(open_menu)
                button_layout.addWidget(open_btn)
            else:
                open_btn = QPushButton("Open Externally")
                open_btn.clicked.connect(
                    lambda: self._open_externally(filepath))
                button_layout.addWidget(open_btn)

        layout.addWidget(button_frame)

    def close_preview(self, preview_frame, deselect=False):
        # Stop audio if playing
        if preview_frame in self.audio_players:
            self.audio_players[preview_frame].stop()
            del self.audio_players[preview_frame]

        # Clear layout
        if preview_frame.layout():
            while preview_frame.layout().count():
                child = preview_frame.layout().takeAt(0)
                if child.widget():
                    child.widget().deleteLater()

        # Delete temp files
        if preview_frame in self.temp_files:
            for temp_item in self.temp_files[preview_frame]:
                try:
                    if os.path.isdir(temp_item):
                        shutil.rmtree(temp_item, ignore_errors=True)
                    elif os.path.exists(temp_item):
                        os.remove(temp_item)
                except Exception as e:
                    print(f"Failed to delete temp file/dir: {e}")
            del self.temp_files[preview_frame]

        preview_frame.hide()

        if deselect:
            self.table_view.clearSelection()

        self._on_column_resized(-1, 0, 0, self.table_view)

    def _open_externally(self, filepath):
        if not os.path.exists(filepath):
            print(f"File does not exist: {filepath}")
            return
        try:
            os.startfile(filepath)
        except Exception as e:
            print(f"Failed to open file: {e}")

    def _select_program_to_open(self, filepath):
        program = QFileDialog.getOpenFileName(
            self.tab_widget,
            "Select Program",
            "",
            "Executable files (*.exe);;All files (*.*)"
        )[0]

        if program:
            try:
                subprocess.run([program, filepath], check=True)
            except Exception as e:
                print(f"Failed to open with selected program: {e}")

    def _format_size(self, size_in_bytes):
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_in_bytes < 1024.0:
                return f"{size_in_bytes:.2f} {unit}"
            size_in_bytes /= 1024.0
        return f"{size_in_bytes:.2f} TB"

    def add_row(self, name, asset_id, type_name, size_text, size_bytes, date_text, date_sort):
        items = [
            QStandardItem(name),
            QStandardItem(str(asset_id)),
            QStandardItem(type_name),
            QStandardItem(size_text),
            QStandardItem(date_text),
        ]

        for i in range(1, 5):
            items[i].setEditable(False)

        items[3].setData(size_bytes, Qt.UserRole)
        items[4].setData(date_sort, Qt.UserRole)
        items[1].setData(int(asset_id), Qt.UserRole)
        items[2].setData(self.cache_logs.get(
            asset_id, {}).get("assetTypeId"), Qt.UserRole)

        row = self.model.rowCount()
        self.model.appendRow(items)

        if asset_id in self.cache_logs:
            index = self.model.index(row, 0)
            self.cache_logs[asset_id]["name_index"] = QPersistentModelIndex(
                index)

    def _update_row_name(self, asset_id, name):
        info = self.cache_logs.get(asset_id)
        if not info:
            return

        idx = info.get("name_index")
        if not idx or not idx.isValid():
            return

        self.model.setData(idx, name)

    def _setup_loader_table(self):
        tv = getattr(self, "loader_table", None)
        if tv is None:
            return

        # Model: Enabled checkbox + fields
        self.loader_model = QStandardItemModel(0, 4, self.tab_widget)
        self.loader_model.setHorizontalHeaderLabels(
            ["On", "Name", "Use", "Replace"])

        self.loader_proxy = SortProxy(self.tab_widget)
        self.loader_proxy.setSourceModel(self.loader_model)

        tv.setModel(self.loader_proxy)
        tv.setSelectionBehavior(QAbstractItemView.SelectRows)
        tv.setSelectionMode(QAbstractItemView.ExtendedSelection)
        tv.setSortingEnabled(True)
        tv.verticalHeader().setVisible(False)
        tv.sortByColumn(1, Qt.AscendingOrder)

        header = tv.horizontalHeader()

        header.sectionResized.connect(
            lambda i, old, new, tv=self.loader_table: self._on_column_resized(
                i, old, new, tv)
        )

        # Match sizing/feel of finder
        tv.verticalHeader().setDefaultSectionSize(20)
        tv.horizontalHeader().setMinimumHeight(22)
        tv.horizontalHeader().setMaximumHeight(22)
        tv.horizontalHeader().setMinimumWidth(40)
        tv.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        tv.horizontalHeader().setStretchLastSection(True)

        # No inline editing
        tv.setEditTriggers(QAbstractItemView.NoEditTriggers)

        # Hover effect like finder
        tv.setMouseTracking(True)
        self.loader_hover_delegate = HoverDelegate(tv)
        tv.setItemDelegate(self.loader_hover_delegate)
        tv.viewport().installEventFilter(self)
        tv.viewport().setMouseTracking(True)

        # Checkbox column width
        QTimer.singleShot(0, lambda: (
            tv.setColumnWidth(0, 50)
        ))

        # Click anywhere toggles the checkbox

        def toggle_row(proxy_index):
            src_index = self.loader_proxy.mapToSource(proxy_index)
            r = src_index.row()
            item = self.loader_model.item(r, 0)
            if item is None:
                return
            item.setCheckState(Qt.Unchecked if item.checkState()
                               == Qt.Checked else Qt.Checked)

        tv.clicked.connect(toggle_row)
        self.add_rule(True, "blah blah blah", "freaky a", "freaky b")
        self.add_rule(False, "oihdawiodhasdk,a", "ok", "123")

    def add_rule(self, enabled: bool, name: str, from_key: str, to_key: str):
        on_item = QStandardItem()
        on_item.setFlags(Qt.ItemIsEnabled |
                         Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
        on_item.setCheckable(True)
        on_item.setCheckState(Qt.Checked if enabled else Qt.Unchecked)

        name_item = QStandardItem(name)
        from_item = QStandardItem(from_key)
        to_item = QStandardItem(to_key)

        # Non-editable cells
        for it in (name_item, from_item, to_item):
            it.setEditable(False)

        self.loader_model.appendRow([on_item, name_item, from_item, to_item])

    def _setup_preset_tree(self):
        tree = self.preset_tree

        # Create model with 2 columns
        self.preset_model = QStandardItemModel(0, 2, self.tab_widget)
        self.preset_model.setHorizontalHeaderLabels(["Name", "Total Caches"])

        tree.setModel(self.preset_model)
        tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        tree.setSortingEnabled(True)
        tree.setAnimated(True)

        # Make columns resizable
        tree.header().setSectionResizeMode(0, QHeaderView.Interactive)
        tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)

        header = tree.header()
        header.sectionResized.connect(
            lambda i, old, new, tv=self.preset_tree: self._on_column_resized(
                i, old, new, tv)
        )

        # Set initial column widths
        tree.setColumnWidth(0, 200)

        # Compact headers like tables
        tree.header().setMinimumHeight(22)
        tree.header().setMaximumHeight(22)
        tree.header().setMinimumWidth(40)

        tree.header().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)

    def add_preset(self, preset_name: str, cache_names: list):
        # Parent row
        name_item = QStandardItem(preset_name)
        count_item = QStandardItem(str(len(cache_names)))

        # Make parent items non-editable
        name_item.setEditable(False)
        count_item.setEditable(False)

        # Add parent to model
        self.preset_model.appendRow([name_item, count_item])

        # Add children (cache names)
        for cache_name in cache_names:
            child_name = QStandardItem(cache_name)
            child_count = QStandardItem("")  # Empty for child rows

            child_name.setEditable(False)
            child_count.setEditable(False)

            name_item.appendRow([child_name, child_count])

    def create_preset(self):
        # Show dialog to get preset name
        dialog = QDialog(self.tab_widget)
        ui = Dialog4UI()
        ui.setupUi(dialog)

        if not dialog.exec():
            return

        preset_name = ui.lineEdit.text().strip()
        if not preset_name:
            return

        # Get all enabled caches from loader table
        enabled_caches = []
        for row in range(self.loader_model.rowCount()):
            checkbox_item = self.loader_model.item(row, 0)
            name_item = self.loader_model.item(row, 1)

            if checkbox_item and name_item and checkbox_item.checkState() == Qt.Checked:
                enabled_caches.append(name_item.text())

        if not enabled_caches:
            print("No enabled caches to add to preset")
            return

        # Add preset to tree
        self.add_preset(preset_name, enabled_caches)
        print(
            f"Created preset '{preset_name}' with {len(enabled_caches)} caches")

    def apply_preset(self):
        # Get selected item
        indexes = self.preset_tree.selectionModel().selectedIndexes()
        if not indexes:
            print("No preset selected")
            return

        # Get the selected item (use first column)
        selected_index = indexes[0]
        item = self.preset_model.itemFromIndex(selected_index)

        # If it's a child item, get its parent
        if item.parent():
            item = item.parent()

        preset_name = item.text()

        # Get all cache names under this preset
        cache_names = []
        for row in range(item.rowCount()):
            child = item.child(row, 0)
            if child:
                cache_names.append(child.text())

        # First uncheck all caches
        for row in range(self.loader_model.rowCount()):
            checkbox_item = self.loader_model.item(row, 0)
            if checkbox_item:
                checkbox_item.setCheckState(Qt.Unchecked)

        # Then check only the caches in the preset
        enabled_count = 0
        for row in range(self.loader_model.rowCount()):
            name_item = self.loader_model.item(row, 1)
            checkbox_item = self.loader_model.item(row, 0)

            if name_item and checkbox_item and name_item.text() in cache_names:
                checkbox_item.setCheckState(Qt.Checked)
                enabled_count += 1

        print(
            f"Applied preset '{preset_name}' - enabled {enabled_count}/{len(cache_names)} caches")

    def _parse_size_to_bytes(self, s: str):
        # supports: 123, 10kb, 4.5mb, 1gb
        s = s.strip().lower().replace(" ", "")
        mult = 1
        if s.endswith("kb"):
            mult = 1024
            s = s[:-2]
        elif s.endswith("mb"):
            mult = 1024**2
            s = s[:-2]
        elif s.endswith("gb"):
            mult = 1024**3
            s = s[:-2]
        elif s.endswith("b"):
            mult = 1
            s = s[:-1]
        try:
            return float(s) * mult
        except Exception:
            return None

    def _build_finder_conditions(self, raw: str):
        if not raw:
            return "", []

        tokens = raw.strip().split()
        conditions = []
        leftovers = []

        for t in tokens:
            tl = t.lower().replace(" ", "")

            # size comparisons
            if tl.startswith("size>") or tl.startswith("size<"):
                op = ">" if ">" in tl else "<"
                val = tl.split(op, 1)[1]
                b = self._parse_size_to_bytes(val)
                if b is None:
                    leftovers.append(t)
                    continue

                def cond(row, parent, m, op=op, b=b):
                    idx = m.index(row, 3, parent)  # Size col
                    size_bytes = m.data(idx, Qt.UserRole)
                    if size_bytes is None:
                        return False
                    return (size_bytes > b) if op == ">" else (size_bytes < b)

                conditions.append(cond)
                continue

            leftovers.append(t)

        return " ".join(leftovers), conditions

    def _apply_finder_filters(self):
        # asset type filter from menu
        if self.all_action.isChecked():
            allowed = None
        else:
            allowed = {tid for tid, act in self.type_actions.items()
                       if act.isChecked()}
            if not allowed:
                # none selected => show nothing
                allowed = set()

        self.proxy.set_type_filter(allowed)

        # search + size conditions
        text = self.finder_search.text() if getattr(self, "finder_search", None) else ""
        leftover, conditions = self._build_finder_conditions(text)

        cols = None
        if hasattr(self, "finder_cb_name"):
            cols = []
            if self.finder_cb_name.isChecked():
                cols.append(0)
            if self.finder_cb_id.isChecked():
                cols.append(1)
            if self.finder_cb_type.isChecked():
                cols.append(2)
            if self.finder_cb_size.isChecked():
                cols.append(3)
            if self.finder_cb_date.isChecked():
                cols.append(4)
            cols = cols or None

        self.proxy.set_search(leftover, cols=cols, conditions=conditions)

    # Test preset cards

    def _populate_test_preset_cards(self):
        test_presets = [
            ("Jailbreak", "2024-01-15", "2025-12-20"),
            ("Adopt Me lol", "2023-06-20", "2025-11-30"),
            ("Brookhaven", "2022-09-10", "2025-10-25"),
            ("Tower of Hell", "2021-03-05", "2025-09-15"),
            ("Bloxburg", "2020-12-01", "2025-08-10"),
            ("Arsenal", "2019-11-22", "2025-07-18"),
            ("Jailbreak", "2024-01-15", "2025-12-20"),
            ("Adopt Me lol", "2023-06-20", "2025-11-30"),
            ("Brookhaven", "2022-09-10", "2025-10-25"),
            ("Tower of Hell", "2021-03-05", "2025-09-15"),
            ("Bloxburg", "2020-12-01", "2025-08-10"),
            ("Arsenal", "2019-11-22", "2025-07-18"),
            ("Jailbreak", "2024-01-15", "2025-12-20"),
            ("Adopt Me lol", "2023-06-20", "2025-11-30"),
            ("Brookhaven", "2022-09-10", "2025-10-25"),
            ("Tower of Hell", "2021-03-05", "2025-09-15"),
            ("Bloxburg", "2020-12-01", "2025-08-10"),
            ("Arsenal", "2019-11-22", "2025-07-18"),
            ("Jailbreak", "2024-01-15", "2025-12-20"),
            ("Adopt Me lol", "2023-06-20", "2025-11-30"),
            ("Brookhaven", "2022-09-10", "2025-10-25"),
            ("Tower of Hell", "2021-03-05", "2025-09-15"),
            ("Bloxburg", "2020-12-01", "2025-08-10"),
            ("Arsenal", "2019-11-22", "2025-07-18"),
            ("Jailbreak", "2024-01-15", "2025-12-20"),
            ("Adopt Me lol", "2023-06-20", "2025-11-30"),
            ("Brookhaven", "2022-09-10", "2025-10-25"),
            ("Tower of Hell", "2021-03-05", "2025-09-15"),
            ("Bloxburg", "2020-12-01", "2025-08-10"),
            ("Arsenal", "2019-11-22", "2025-07-18"),
            ("Jailbreak", "2024-01-15", "2025-12-20"),
            ("Adopt Me lol", "2023-06-20", "2025-11-30"),
            ("Brookhaven", "2022-09-10", "2025-10-25"),
            ("Tower of Hell", "2021-03-05", "2025-09-15"),
            ("Bloxburg", "2020-12-01", "2025-08-10"),
            ("Arsenal", "2019-11-22", "2025-07-18"),
        ]

        for i, (name, created, updated) in enumerate(test_presets):
            card = GameCardWidget(self.presets_container)
            card.set_data(name=name, created=created, updated=updated)
            card._game_name = name
            card.clicked.connect(lambda n=name: self._open_preset_window(n))
            card.setMinimumWidth(0)
            card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

            # Add to grid
            row = i // 3
            col = i % 3
            self.presets_grid.addWidget(card, row, col)

            self._preset_cards.append(card)

    # Presets

    def _open_preset_window(self, preset_name: str):
        dialog = QDialog(self.tab_widget)
        dialog.setWindowTitle(f"Preset: {preset_name}")
        dialog.resize(500, 450)

        ui = PresetWindowUI()
        ui.setupUi(dialog)

        # Set up the tree view
        preset_model = QStandardItemModel(0, 2, dialog)
        preset_model.setHorizontalHeaderLabels(["Name", "Total Caches"])

        ui.treeView.setModel(preset_model)
        ui.treeView.setEditTriggers(QAbstractItemView.NoEditTriggers)
        ui.treeView.setSortingEnabled(True)
        ui.treeView.setAnimated(True)

        # Column sizing
        ui.treeView.header().setSectionResizeMode(0, QHeaderView.Interactive)
        ui.treeView.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        ui.treeView.setColumnWidth(0, 300)

        # Compact headers
        ui.treeView.header().setMinimumHeight(22)
        ui.treeView.header().setMaximumHeight(22)
        ui.treeView.header().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        # Add some demo data for this preset
        demo_presets = [
            (f"{preset_name} - Default",
             ["blah blah blah", "sound_ambience_01.ogg", "texture_pack_01"]),
            (f"{preset_name} - Alternative",
             ["oihdawiodhasdk,a", "custom_model.rbxm"]),
            (f"{preset_name} - Experimental",
             ["test_cache_1", "test_cache_2", "test_cache_3", "test_cache_4"]),
        ]

        for name, caches in demo_presets:
            name_item = QStandardItem(name)
            count_item = QStandardItem(str(len(caches)))

            name_item.setEditable(False)
            count_item.setEditable(False)

            preset_model.appendRow([name_item, count_item])

            # Add children
            for cache in caches:
                child_name = QStandardItem(cache)
                child_count = QStandardItem("")

                child_name.setEditable(False)
                child_count.setEditable(False)

                name_item.appendRow([child_name, child_count])

        # Connect Apply button
        ui.ApplyButton.clicked.connect(
            lambda: self._apply_preset_from_window(ui.treeView, dialog))

        dialog.exec()

    def _relayout_preset_cards(self):
        if not self.presets_scroll:
            return

        cards = getattr(self, "_preset_filtered_cards", None)
        if cards is None:
            cards = getattr(self, "_preset_cards", [])
        if not cards:
            return

        vw = self.presets_scroll.viewport().width()
        if vw <= 0:
            return

        self.presets_container.setUpdatesEnabled(False)

        # Clear layout
        while self.presets_grid.count():
            self.presets_grid.takeAt(0)

        # compute columns
        card_w = 240
        spacing = self.presets_grid.spacing() or 8
        margins = self.presets_grid.contentsMargins()
        avail = vw - (margins.left() + margins.right())
        per_row = max(1, int((avail + spacing) // (card_w + spacing)))

        # 🧢
        per_row = min(per_row, 8)

        allowed = set(cards)
        for c in getattr(self, "_preset_cards", []):
            c.setVisible(c in allowed)

        # Add only the cards we want
        for i, card in enumerate(cards):
            r = i // per_row
            c = i % per_row
            self.presets_grid.addWidget(card, r, c)

        self.presets_container.setUpdatesEnabled(True)
        self.presets_container.update()

    def _apply_preset_from_window(self, tree_view, dialog):
        indexes = tree_view.selectionModel().selectedIndexes()
        if not indexes:
            print("No preset selected")
            return

        model = tree_view.model()
        selected_index = indexes[0]
        item = model.itemFromIndex(selected_index)

        # If it's a child item, get its parent
        if item.parent():
            item = item.parent()

        preset_name = item.text()

        # Get all cache names under this preset
        cache_names = []
        for row in range(item.rowCount()):
            child = item.child(row, 0)
            if child:
                cache_names.append(child.text())

        # First uncheck all caches
        for row in range(self.loader_model.rowCount()):
            checkbox_item = self.loader_model.item(row, 0)
            if checkbox_item:
                checkbox_item.setCheckState(Qt.Unchecked)

        # Then check only the caches in the preset
        enabled_count = 0
        for row in range(self.loader_model.rowCount()):
            name_item = self.loader_model.item(row, 1)
            checkbox_item = self.loader_model.item(row, 0)

            if name_item and checkbox_item and name_item.text() in cache_names:
                checkbox_item.setCheckState(Qt.Checked)
                enabled_count += 1

        print(
            f"Applied preset '{preset_name}' - enabled {enabled_count}/{len(cache_names)} caches")

        # Close dialog and switch to loader tab
        dialog.accept()

    def _apply_presets_search_filter(self):
        text = self.presets_search.text().strip().lower()

        if not text:
            self._preset_filtered_cards = None
            self._relayout_preset_cards()
            return

        matches = []
        for card in self._preset_cards:
            name = getattr(card, "_game_name", "")
            if text in name.lower():
                matches.append(card)

        # sorting
        matches.sort(key=lambda c: getattr(c, "_game_name", "").lower())

        self._preset_filtered_cards = matches
        self._relayout_preset_cards()

    # Filter menu

    def _setup_filter_menu(self):
        menu = QMenu(self.filter_button)

        asset_menu = menu.addMenu("Asset type")

        self.all_action = asset_menu.addAction("All")
        self.all_action.setCheckable(True)
        self.all_action.setChecked(True)

        self.type_actions = {}
        asset_menu.addSeparator()

        for asset_id, name in ASSET_TYPES:
            act = asset_menu.addAction(name)
            act.setCheckable(True)
            self.type_actions[asset_id] = act

        self.all_action.toggled.connect(self._on_all_toggled)
        for act in self.type_actions.values():
            act.toggled.connect(self._on_item_toggled)

        self.filter_button.setMenu(menu)

        self.all_action.toggled.connect(lambda _: self._apply_finder_filters())
        for act in self.type_actions.values():
            act.toggled.connect(lambda _: self._apply_finder_filters())

    def _on_all_toggled(self, checked):
        for act in self.type_actions.values():
            act.setEnabled(not checked)

    def _on_item_toggled(self):
        any_checked = any(a.isChecked() for a in self.type_actions.values())
        self.all_action.blockSignals(True)
        self.all_action.setChecked(not any_checked)
        self.all_action.blockSignals(False)

    # Settings menu

    def _setup_settings_menu(self):
        menu = QMenu(self.settings_button)

        self.show_names_action = menu.addAction("Show Names")
        self.show_names_action.setCheckable(True)
        self.show_names_action.setChecked(True)
        self.show_names_action.toggled.connect(self._on_show_names_toggled)
        self.export_raw = menu.addAction("Export Raw")
        self.export_raw.setCheckable(True)
        self.export_raw.setChecked(False)
        self.export_raw.toggled.connect(self._on_export_raw_toggled)
        namemenu = menu.addMenu("Export File Name")

        self.name_action = namemenu.addAction("Name")
        self.name_action.setCheckable(True)
        self.name_action.setChecked(True)
        self.id_action = namemenu.addAction("Id")
        self.id_action.setCheckable(True)
        self.id_action.setChecked(True)
        self.Hash_action = namemenu.addAction("Hash")
        self.Hash_action.setCheckable(True)
        self.Hash_action.setChecked(False)

        self.settings_button.setMenu(menu)

    # Context menu

    def _show_context_menu(self, position):
        tv = self.table_view

        # index under cursor (proxy index)
        index = tv.indexAt(position)
        has_index = index.isValid()

        # selected rows (for Delete)
        selected_rows = tv.selectionModel().selectedRows()

        menu = QMenu(tv)

        # Copy cell
        copy_action = menu.addAction("Copy")
        copy_action.setEnabled(has_index)

        def do_copy():
            # Copy display text of the right-clicked cell
            text = self.proxy.data(index, Qt.DisplayRole)
            if text is None:
                text = ""
            QApplication.clipboard().setText(str(text))

        copy_action.triggered.connect(do_copy)

        menu.addSeparator()

        # Delete slected rows
        delete_action = menu.addAction("Delete")
        delete_action.setEnabled(bool(selected_rows))
        delete_action.triggered.connect(
            lambda: self._delete_selected_rows(selected_rows))

        export_action = menu.addAction("Export")
        export_action.setEnabled(bool(selected_rows))
        export_action.triggered.connect(
            lambda: self._export_selected_rows(selected_rows))

        menu.exec(tv.viewport().mapToGlobal(position))

    def _export_selected_rows(self, selected_indexes):
        if not selected_indexes:
            return

        # Create a unique folder per export session
        date_folder = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        base_export_dir = os.path.join("modules", "export", date_folder)

        # Get unique source rows from the proxy selection
        rows = {self.proxy.mapToSource(idx).row() for idx in selected_indexes}

        for row in rows:
            asset_id = self.model.data(self.model.index(row, 1))
            if asset_id is None:
                continue

            try:
                log = self.cache_logs[int(asset_id)]
            except (KeyError, ValueError):
                print(f"Skipping invalid asset ID: {asset_id}")
                continue

            asset_type_id = log.get("assetTypeId")
            cache_data = log.get("cache_data")
            resolved_name = log.get("resolved_name")
            location = log.get("location")
            if location:
                parsed_location = urlparse(location)
                cache_hash = parsed_location.path.rsplit("/", 1)[-1]

            parts = []

            # Include resolved name if checked
            if getattr(self, "name_action", None) and self.name_action.isChecked():
                if resolved_name:
                    parts.append(resolved_name)

            # Include asset ID if checked
            if getattr(self, "id_action", None) and self.id_action.isChecked():
                parts.append(str(asset_id))

            # Include hash if checked
            if getattr(self, "Hash_action", None) and self.Hash_action.isChecked():
                if cache_hash:
                    parts.append(cache_hash)

            # Join parts to make final filename
            if parts:
                name = " - ".join(parts)
            else:
                # fallback if nothing selected
                name = str(asset_id)

            # Sanitize for Windows
            safe_name = re.sub(r'[<>:"/\\|?*]', '_', name)

            file_type = self._identify_file_type(cache_data)
            if asset_type_id == 24:
                file_type = "RBXM Animation"


            # ---------------- RAW EXPORT ----------------
            if getattr(self, "export_raw", None) and self.export_raw.isChecked():
                # Raw export → no extensions, no mesh conversion
                # Decide folder based on asset type
                if file_type in ["PNG", "GIF", "JPEG", "JFIF"]:
                    folder = "image"
                elif file_type in ["OGG", "MP3"]:
                    folder = "audio"
                elif file_type.startswith("Mesh"):
                    folder = "mesh"
                elif file_type in ["JSON", "Translation (JSON)", "TTF (JSON)"]:
                    folder = "json"
                elif file_type in ["XML", "EXTM3U"]:
                    folder = "xml"
                elif file_type == "RBXM Animation":
                    folder = "animation"
                else:
                    folder = "unknown"

                export_dir = os.path.join(base_export_dir, folder)
                os.makedirs(export_dir, exist_ok=True)

                file_path = os.path.join(export_dir, safe_name)
                if cache_data:
                    with open(file_path, "wb") as f:
                        f.write(cache_data)
                continue  # Skip all other logic for raw export

            # ---------------- NORMAL EXPORT ----------------
            if file_type in ["PNG", "GIF", "JPEG", "JFIF"]:
                export_dir = os.path.join(base_export_dir, "image")
                os.makedirs(export_dir, exist_ok=True)

                ext = file_type.lower()
                if ext == "jfif":
                    ext = "jpg"

                file_path = os.path.join(export_dir, f"{safe_name}.{ext}")
                if cache_data:
                    with open(file_path, "wb") as f:
                        f.write(cache_data)

            elif file_type in ["OGG", "MP3"]:
                export_dir = os.path.join(base_export_dir, "audio")
                os.makedirs(export_dir, exist_ok=True)

                ext = file_type.lower()
                file_path = os.path.join(export_dir, f"{safe_name}.{ext}")
                if cache_data:
                    with open(file_path, "wb") as f:
                        f.write(cache_data)

            elif file_type.startswith("Mesh"):
                # Only convert & move mesh if export_raw is True
                path = self._convert_mesh_to_obj(cache_data)
                if not path or not os.path.exists(path):
                    continue

                export_dir = os.path.join(base_export_dir, "mesh")
                os.makedirs(export_dir, exist_ok=True)

                new_filename = f"{safe_name}.obj"
                new_path = os.path.join(export_dir, new_filename)

                try:
                    shutil.move(path, new_path)
                except Exception as e:
                    print(f"Failed to move mesh {asset_id}: {e}")

            elif file_type in ["JSON", "Translation (JSON)", "TTF (JSON)"]:
                export_dir = os.path.join(base_export_dir, "json")
                os.makedirs(export_dir, exist_ok=True)

                file_path = os.path.join(export_dir, f"{safe_name}.json")
                if cache_data:
                    with open(file_path, "wb") as f:
                        f.write(cache_data)

            elif file_type in ["XML", "EXTM3U"]:
                export_dir = os.path.join(base_export_dir, "xml")
                os.makedirs(export_dir, exist_ok=True)
                
                ext = file_type.lower()
                if ext == "extm3u":
                    ext = "m3u"
                file_path = os.path.join(export_dir, f"{safe_name}.{ext}")
                if cache_data:
                    with open(file_path, "wb") as f:
                        f.write(cache_data)

            elif file_type == "RBXM Animation":
                export_dir = os.path.join(base_export_dir, "animation")
                os.makedirs(export_dir, exist_ok=True)

                file_path = os.path.join(export_dir, f"{safe_name}.rbxm")
                if cache_data:
                    with open(file_path, "wb") as f:
                        f.write(cache_data)

            else:
                export_dir = os.path.join(base_export_dir, "unknown")
                os.makedirs(export_dir, exist_ok=True)

                file_path = os.path.join(export_dir, safe_name)
                if cache_data:
                    with open(file_path, "wb") as f:
                        f.write(cache_data)

    def _delete_selected_rows(self, selected_indexes):
        # Map proxy indexes to source indexes and sort in reverse order
        source_rows = []
        for proxy_index in selected_indexes:
            source_index = self.proxy.mapToSource(proxy_index)
            source_rows.append(source_index.row())

        # Sort in reverse so we delete from bottom to top (prevents index shifting)
        source_rows = sorted(set(source_rows), reverse=True)

        # Delete rows from source model
        for row in source_rows:
            self.model.removeRow(row)

    # Event filter

    def eventFilter(self, obj, event):
        from PySide6.QtGui import QKeySequence

        tables = [self.table_view, getattr(self, "loader_table", None)]
        tables = [t for t in tables if t is not None]
        viewports = [t.viewport() for t in tables]

        # Ctrl + a supportalorta
        if obj in (tables + viewports) and event.type() == QEvent.KeyPress:
            if event.matches(QKeySequence.SelectAll):
                if obj in viewports:
                    obj.parent().selectAll()
                else:
                    obj.selectAll()
                return True

        # Hover effect yaya
        if obj in (self.table_view.viewport(), getattr(self, "loader_table", None).viewport() if getattr(self, "loader_table", None) else None):
            view = self.table_view if obj == self.table_view.viewport() else self.loader_table
            delegate = self.hover_delegate if view == self.table_view else self.loader_hover_delegate

            if event.type() == QEvent.MouseMove:
                index = view.indexAt(event.pos())
                if index.isValid():
                    row = index.row()
                    if row != delegate.hover_row:
                        delegate.hover_row = row
                        view.viewport().update()
                else:
                    if delegate.hover_row != -1:
                        delegate.hover_row = -1
                        view.viewport().update()

            elif event.type() == QEvent.Leave:
                if delegate.hover_row != -1:
                    delegate.hover_row = -1
                    view.viewport().update()

        return super().eventFilter(obj, event)

    def parse_body(self, content: bytes, encoding: str):
        if encoding == "gzip":
            try:
                content = gzip.decompress(content)
            except OSError:
                # Not actually gzipped, just fall back to raw bytes
                pass
        try:
            return json.loads(content)
        except Exception as e:
            print("Failed to parse JSON:", e)
            return None

    def rebuild_body(self, data, encoding: str) -> bytes:
        raw = json.dumps(data, separators=(",", ":")).encode()

        if encoding == "gzip":
            return gzip.compress(raw)

        return raw

    def _new_session(self, cookie: str | None, xCSRF=False):
        sess = requests.Session()
        sess.trust_env = False
        sess.proxies = {}
        sess.headers.update({
            "User-Agent": "Roblox/WinInet",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Referer": "https://www.roblox.com/",
            "Origin": "https://www.roblox.com",
        })
        if cookie:
            sess.headers["Cookie"] = f".ROBLOSECURITY={cookie};"
        # X-CSRF
        if xCSRF:
            try:
                r = sess.post("https://auth.roblox.com/v2/logout", timeout=10)
                token = r.headers.get(
                    "x-csrf-token") or r.headers.get("X-CSRF-TOKEN")
                if token:
                    sess.headers["X-CSRF-TOKEN"] = token
            except Exception:
                pass
        return sess

    def fetch_asset_names(self, asset_ids, cookie):
        """
        Fetch asset names from Roblox Develop API.
        asset_ids: list of integers
        Returns: dict {asset_id: name}
        """
        if not cookie or not asset_ids:
            return None

        sess = self._new_session(cookie)
        base_url = "https://develop.roblox.com/v1/assets"
        # Build query string: assetIds=123,456,789
        query = ",".join(str(aid) for aid in asset_ids)
        url = f"{base_url}?assetIds={query}"

        try:
            r = sess.get(url, timeout=10)
            r.raise_for_status()
        except Exception as e:
            print(f"[fetch_asset_names] Failed to fetch {asset_ids}: {e}")
            return None

        data = r.json().get("data", [])
        result = {}
        for item in data:
            asset_id = item.get("id")
            name = item.get("name", "Unknown")
            if asset_id is not None:
                result[asset_id] = name

        return result

    def name_resolver_loop(self):
        while True:
            # Skip if Show Names is OFF
            if not self.show_names_action.isChecked():
                time.sleep(0.2)
                continue
            cookie = get_roblosecurity()
            if not cookie:
                print(
                    "[Name Resolver] No .ROBLOSECURITY cookie found. Please log in to Roblox.")
                time.sleep(5)
                continue

            # Build pending list dynamically from cache_logs
            pending_assets = [
                asset_id
                for asset_id, info in self.cache_logs.items()
                if isinstance(info, dict)
                and info.get("resolved_name") is None
                # skip entries without a table row
                and info.get("name_index") is not None
            ]

            if not pending_assets:
                time.sleep(0.2)
                continue

            # Determine batch size and delay
            batch_size = 50
            delay = 0.2 if len(pending_assets) > 50 else 0.5

            # Take the first batch
            batch = pending_assets[:batch_size]

            # Fetch names
            try:
                names = self.fetch_asset_names(batch, cookie)
            except Exception as e:
                print(f"[Name Resolver] Fetch failed: {e}")
                # Retry next loop
                time.sleep(delay)
                continue

            if not names:
                # Retry next loop
                time.sleep(delay)
                continue

            # Update cache_logs and UI
            for asset_id, name in names.items():
                info = self.cache_logs.get(asset_id)
                if not info or info.get("name_index") is None:
                    continue

                # Store resolved name
                info["resolved_name"] = name

                # Only update UI if Show Names is ON
                if self.show_names_action.isChecked():
                    self._update_row_name(asset_id, name)

            # Wait before next batch
            time.sleep(delay)

    def _on_show_names_toggled(self, checked: bool):
        for asset_id, info in self.cache_logs.items():
            idx = info.get("name_index")
            if not idx or not idx.isValid():
                continue

            if checked:
                # Show Names enabled
                # Update UI to resolved_name if it exists
                resolved = info.get("resolved_name")
                if resolved:
                    self._update_row_name(asset_id, resolved)
                else:
                    # It will be picked up by the resolver loop automatically
                    continue
            else:
                # Show hash by taking the last part of the location URL
                location = info.get("location")
                if location:
                    parsed_location = urlparse(location)
                    cache_hash = parsed_location.path.rsplit('/', 1)[-1]
                else:
                    cache_hash = "Unknown"

                self._update_row_name(asset_id, cache_hash)

    def _on_export_raw_toggled(self, checked: bool):
        print("Export Raw toggled", checked)

    def _on_export_converted_toggled(self, checked: bool):
        print("Export Converted toggled", checked)

    def event(self, event):
        if event.type() == QEvent.Resize:

            self._on_column_resized(-1, 0, 0, self.table_view)
            self._on_column_resized(-1, 0, 0, self.loader_table)
            self._on_column_resized(-1, 0, 0, self.preset_tree)

            # debounce so it doesn't rebuild 200 times while dragging
            if not getattr(self, "_preset_relayout_pending", False):
                self._preset_relayout_pending = True

                def run():
                    self._preset_relayout_pending = False
                    self._relayout_preset_cards()

                QTimer.singleShot(0, run)

        return False

    def request(self, flow):
        url = flow.request.pretty_url
        parsed_url = urlparse(url)
        content_encoding = flow.request.headers.get(
            "Content-Encoding", ""
        ).lower()
        if parsed_url.hostname == "assetdelivery.roblox.com":

            raw_content = flow.request.raw_content
            if raw_content:

                data = self.parse_body(raw_content, content_encoding)

                if isinstance(data, list):

                    modified = False

                    for entry in data:
                        if isinstance(entry, dict):
                            asset_type = entry.get("assetType", "")
                            if asset_type in ("Image", "TexturePack"):
                                if "contentRepresentationPriorityList" in entry:
                                    del entry["contentRepresentationPriorityList"]
                                    modified = True

                    if modified:
                        flow.request.raw_content = self.rebuild_body(
                            data, content_encoding
                        )
                        flow.request.headers["Content-Length"] = str(
                            len(flow.request.raw_content)
                        )

    def response(self, flow):
        url = flow.request.pretty_url
        parsed_url = urlparse(url)
        req_content_encoding = flow.request.headers.get(
            "Content-Encoding", ""
        ).lower()
        content_encoding = flow.response.headers.get(
            "Content-Encoding", ""
        ).lower()

        if "assetdelivery.roblox.com" == parsed_url.hostname:
            if parsed_url.path == self.delivery_endpoint:
                body_req_json = self.parse_body(
                    flow.request.content, req_content_encoding)
                body_res_json = self.parse_body(
                    flow.response.content, content_encoding)
                if not body_res_json or not body_req_json:
                    return

                for index, item in enumerate(body_req_json):
                    if "assetId" in item:
                        ID = item["assetId"]

                        if ID in self.cache_logs:
                            continue

                        if index < len(body_res_json):
                            res_item = body_res_json[index]

                            # Safely get fields
                            location = res_item.get("location")
                            asset_type = res_item.get("assetTypeId")

                            if location is not None and asset_type is not None:
                                self.cache_logs[ID] = {}
                                self.cache_logs[ID]["location"] = location
                                self.cache_logs[ID]["assetTypeId"] = asset_type

        if "fts.rbxcdn.com" == parsed_url.hostname:
            req_base = url.split("?")[0]
            asset_type_id = None
            for asset_id, info in self.cache_logs.items():
                if not isinstance(info, dict):
                    continue
                location = info.get("location")
                if not location:
                    continue
                if "cache_data" in info:
                    continue
                cached_base = location.split("?")[0]
                if cached_base == req_base:

                    content_size_bytes = len(
                        flow.response.content) if flow.response.content is not None else 0

                    info["cache_data"] = flow.response.content
                    info["cache_status"] = flow.response.status_code
                    info["cache_fetched_at"] = time.time()
                    cache_hash = parsed_url.path.rsplit('/', 1)[-1]
                    asset_type_id = info.get("assetTypeId")
                    asset_type = "Unknown"
                    for at_id, at_name in ASSET_TYPES:
                        if at_id == asset_type_id:
                            asset_type = at_name
                            break

                    if content_size_bytes == 0:
                        size_text = "0 B"
                    elif content_size_bytes < 1024:
                        size_text = f"{content_size_bytes} B"
                    elif content_size_bytes < 1024 * 1024:
                        size_text = f"{content_size_bytes / 1024:.2f} KB"
                    else:
                        size_text = f"{content_size_bytes / (1024 * 1024):.2f} MB"

                    now = datetime.utcnow()
                    date_text = now.strftime("%a %b %d %H:%M:%S %Y")
                    date_sort = int(time.time())
                    self.add_row(
                        name=cache_hash,
                        asset_id=asset_id,
                        type_name=asset_type,
                        size_text=size_text,
                        size_bytes=float(content_size_bytes),
                        date_text=date_text,
                        date_sort=date_sort,
                    )
                    break
