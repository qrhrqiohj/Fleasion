import threading
import time
import requests
import os
import win32crypt
import json
import base64
import re
import uuid
from PySide6.QtWidgets import QWidget, QGridLayout, QSizePolicy, QLineEdit, QComboBox, QPushButton, QVBoxLayout, QHBoxLayout
from PySide6.QtCore import Qt, QEvent, QTimer, QObject, Signal
from PySide6.QtGui import QPixmap, QImage
from game_card_widget import GameCardWidget
from datetime import datetime, timezone
from dateutil import parser
from io import BytesIO
from PIL import Image, ImageDraw
from PIL.ImageQt import ImageQt
from urllib.parse import urlparse, urlunparse


def humanize_time(iso_str: str) -> str:
    if not iso_str:
        return "Unknown"

    # Parse ISO string
    dt = parser.isoparse(iso_str)
    now = datetime.now(timezone.utc)
    diff = now - dt

    seconds = diff.total_seconds()
    minutes = seconds / 60
    hours = minutes / 60
    days = hours / 24
    months = days / 30
    years = days / 365

    if seconds < 60:
        return "just now"
    elif minutes < 60:
        return f"{int(minutes)} minute{'s' if minutes >= 2 else ''} ago"
    elif hours < 24:
        return f"{int(hours)} hour{'s' if hours >= 2 else ''} ago"
    elif days < 30:
        return f"{int(days)} day{'s' if days >= 2 else ''} ago"
    elif months < 12:
        return f"{int(months)} month{'s' if months >= 2 else ''} ago"
    else:
        return f"{int(years)} year{'s' if years >= 2 else ''} ago"


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


class _MainThreadInvoker(QObject):
    call = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.call.connect(self._run, Qt.QueuedConnection)

    def _run(self, fn):
        try:
            print('[DEBUG] _invoker: executing UI callback...')
            fn()
            print('[DEBUG] _invoker: UI callback complete')
        except Exception as e:
            import traceback
            print('[DEBUG] Exception in main-thread invoker:', e)
            traceback.print_exc()


class Main:
    def __init__(self, tab_widget: QWidget):
        self._invoker = _MainThreadInvoker(None)
        self.tab_widget = tab_widget
        self._cards = []
        self._card_by_place_id = {}
        self.thumb_cache = {}
        self._search_cancel_event = threading.Event()

        self.joining_place = False
        self.wanted_join_endpoints = (
            "/v1/join-game",
            "/v1/join-play-together-game",
            "/v1/join-game-instance",
        )

        # Find scroll area
        self.results_scroll = self.tab_widget.findChild(QWidget, "Results")
        if not self.results_scroll:
            raise ValueError(
                "Could not find 'Results' QScrollArea in tab_widget")

        # Container inside scroll area
        self.results_container = self.results_scroll.findChild(
            QWidget, "resultsContainer")
        if not self.results_container:
            self.results_container = QWidget()
            self.results_container.setObjectName("resultsContainer")
            self.results_scroll.setWidget(self.results_container)

        # ---- Place ID input ----
        self.PlaceID_search = self.tab_widget.findChild(
            QLineEdit, "PlaceIDInput")
        if self.PlaceID_search:
            self.PlaceID_search.returnPressed.connect(self.on_search_clicked)

        # ---- Favorite button ----
        self.favorite_btn = self.tab_widget.findChild(
            QWidget, "SubplaceFavoriteButton")
        if self.favorite_btn:
            self.favorite_btn.clicked.connect(self.on_favorite_clicked)

        # ---- Recent / Favorites containers ----
        self.recent_contents = self.tab_widget.findChild(
            QWidget, "RecentPlaceIdsContents")
        self.fav_contents = self.tab_widget.findChild(
            QWidget, "FavoritedPlaceIdsContents")

        self.recent_layout = self.recent_contents.layout() if self.recent_contents else None
        if self.recent_layout is None and self.recent_contents:
            self.recent_layout = QVBoxLayout(self.recent_contents)
            self.recent_contents.setLayout(self.recent_layout)

        self.fav_layout = self.fav_contents.layout() if self.fav_contents else None
        if self.fav_layout is None and self.fav_contents:
            self.fav_layout = QVBoxLayout(self.fav_contents)
            self.fav_contents.setLayout(self.fav_layout)

        # ---- Data + persistence ----
        self.recent_ids = []
        self.favorites = []

        self._load_settings()
        self._rebuild_recent_buttons()
        self._rebuild_favorite_buttons()

        # ---- Search ----
        self.search_input = self.tab_widget.findChild(QLineEdit, "SearchInput")
        if self.search_input:
            self.search_input.textChanged.connect(self.apply_search_and_sort)
            self.search_input.returnPressed.connect(self.apply_search_and_sort)

        # ---- Sort combobox ----
        self.sort_combo = self.tab_widget.findChild(QComboBox, "comboBox")
        if self.sort_combo:
            self.sort_combo.currentIndexChanged.connect(
                self.apply_search_and_sort)

        # Grid layout
        if self.results_container.layout() is None:
            self.results_grid = QGridLayout(self.results_container)
            self.results_container.setLayout(self.results_grid)
        else:
            self.results_grid = self.results_container.layout()

        self.results_grid.setContentsMargins(8, 8, 8, 8)
        self.results_grid.setSpacing(8)
        self.results_grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)

        # Populate demo cards
        # self.populate_test_cards()

        # Initial layout after event loop starts
        QTimer.singleShot(0, self.relayout_cards)

    # =========================
    # Recent/Favorites + Settings
    # =========================

    def _settings_path(self) -> str:
        # Windows: %localappdata%\SubplaceJoiner\settings.json
        base = os.environ.get("LOCALAPPDATA")
        if not base:
            base = os.path.join(os.path.expanduser("~"), "AppData", "Local")
        folder = os.path.join(base, "SubplaceJoiner")
        os.makedirs(folder, exist_ok=True)
        return os.path.join(folder, "settings.json")

    def _load_settings(self):
        path = self._settings_path()
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.recent_ids = [str(x) for x in data.get(
                    "recent_ids", []) if str(x).strip()]
                self.favorites = [str(x) for x in data.get(
                    "favorites", []) if str(x).strip()]
            else:
                self.recent_ids = []
                self.favorites = []
        except Exception as e:
            print("Failed to load settings:", e)
            self.recent_ids = []
            self.favorites = []

    def _save_settings(self):
        path = self._settings_path()
        data = {
            "recent_ids": [str(x) for x in self.recent_ids],
            "favorites": [str(x) for x in self.favorites],
        }
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print("Failed to save settings:", e)

    def _clear_layout_buttons(self, layout):
        if not layout:
            return
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _make_placeid_button(self, place_id: str, handler):
        btn = QPushButton(place_id)
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(lambda _=False, pid=place_id: handler(pid))
        return btn

    def _rebuild_recent_buttons(self):
        if not self.recent_layout:
            return
        self._clear_layout_buttons(self.recent_layout)
        for pid in self.recent_ids:
            self.recent_layout.addWidget(
                self._make_placeid_button(pid, self._on_recent_clicked))
        self.recent_layout.addStretch(1)

    def _rebuild_favorite_buttons(self):
        if not self.fav_layout:
            return
        self._clear_layout_buttons(self.fav_layout)
        for pid in self.favorites:
            self.fav_layout.addWidget(
                self._make_placeid_button(pid, self._on_favorite_clicked))
        self.fav_layout.addStretch(1)

    def _on_recent_clicked(self, place_id: str):
        if self.PlaceID_search:
            self.PlaceID_search.setText(place_id)
        self.on_search_clicked()

    def _on_favorite_clicked(self, place_id: str):
        if self.PlaceID_search:
            self.PlaceID_search.setText(place_id)
        self.on_search_clicked()

    def add_recent_place_id(self, place_id: str):
        place_id = (place_id or "").strip()
        if not place_id.isdigit():
            return

        # move-to-front behavior
        if place_id in self.recent_ids:
            self.recent_ids.remove(place_id)
        self.recent_ids.insert(0, place_id)

        self._save_settings()
        self._rebuild_recent_buttons()

    def add_favorite_place_id(self, place_id: str):
        place_id = (place_id or "").strip()
        if not place_id.isdigit():
            return

        if place_id in self.favorites:
            return

        self.favorites.insert(0, place_id)
        self._save_settings()
        self._rebuild_favorite_buttons()

    def on_favorite_clicked(self):
        # Uses the ID currently in the PlaceID line edit
        if not self.PlaceID_search:
            return
        place_id = self.PlaceID_search.text().strip()
        self.add_favorite_place_id(place_id)

    def on_search_clicked(self):
        place_id = self.PlaceID_search.text().strip()
        if not place_id.isdigit():
            print("Invalid Place ID")
            return

        print("Searching for Place ID:", place_id)
        self.add_recent_place_id(place_id)

        # Cancel any previous search
        self._search_cancel_event.set()

        # Clear old results
        self.clear_results()
        self._card_by_place_id.clear()

        # Reset cancel event for this new search
        self._search_cancel_event = threading.Event()

        # Start new worker
        threading.Thread(target=self._search_worker, args=(
            place_id, self._search_cancel_event), daemon=True).start()

    def _search_worker(self, place_id: str, cancel_event: threading.Event):
        try:
            if cancel_event.is_set():
                print("[SEARCH] cancelled before start")
                return

            # Step 1: Get universe ID
            u = self._get(
                f"https://apis.roblox.com/universes/v1/places/{place_id}/universe", timeout=10)
            u.raise_for_status()
            universe_data = u.json()
            universe_id = universe_data.get("universeId")
            if not universe_id:
                raise Exception("Invalid Place ID or universe not found")

            # Step 1.5: Get root place ID
            universe_details = self._get(
                f"https://games.roblox.com/v1/games?universeIds={universe_id}", timeout=10)
            universe_details.raise_for_status()
            games_data = universe_details.json().get("data", [])
            root_place_id = games_data[0].get(
                "rootPlaceId") if games_data else int(place_id)

            # Step 2: Paginate through places
            all_places = []
            cursor = None
            seen = set()

            while True:
                if cancel_event.is_set():
                    print("[SEARCH] cancelled during pagination")
                    return

                url = f"https://develop.roblox.com/v1/universes/{universe_id}/places?limit=100"
                if cursor:
                    url += f"&cursor={cursor}"

                r = self._get(url, timeout=10)
                r.raise_for_status()
                data = r.json()
                batch = data.get("data", [])
                if not batch:
                    break

                for p in batch:
                    pid = p.get("id")
                    if pid in seen:
                        continue
                    seen.add(pid)

                    # Keep actual name from API
                    p["display_name"] = p.get("name") or f"Place {pid}"
                    p["created"] = None
                    p["updated"] = None
                    p["is_root"] = int(pid) == int(root_place_id)

                    all_places.append(p)

                cursor = data.get("nextPageCursor")
                if not cursor:
                    break

            print(f"[DEBUG] Found {len(all_places)} places")

            # Add new cards immediately
            items = [(p["display_name"], p.get("created"), p.get(
                "updated"), p["id"], root_place_id) for p in all_places]
            self._on_main(lambda: self._add_new_cards(items))

            # Step 3: Load timestamps in background
            cookie = get_roblosecurity() or ""

            def load_timestamps():
                updated_places = []
                for i, p in enumerate(all_places):
                    if cancel_event.is_set():
                        print("[SEARCH] timestamp loader cancelled")
                        return

                    pid = p.get("id")
                    while True:
                        try:
                            asset_url = f"https://economy.roblox.com/v2/assets/{pid}/details"
                            resp = self._get(asset_url, cookies={
                                             ".ROBLOSECURITY": cookie}, timeout=10)
                            resp.raise_for_status()
                            asset_data = resp.json()

                            p["created"] = asset_data.get("Created")
                            p["updated"] = asset_data.get("Updated")
                            print(
                                f"[DEBUG] {p['display_name']}: created={p['created']}, updated={p['updated']}")
                            break
                        except requests.HTTPError as err:
                            status = getattr(err.response, "status_code", None)
                            if status in (429, 500, 502, 503, 504):
                                print(
                                    f"[WARN] Rate-limited on {pid}, retrying in 1s…")
                                time.sleep(1)
                                continue
                            else:
                                print(f"[WARN] HTTP error on {pid}: {err}")
                                break
                        except Exception as ex:
                            print(
                                f"[WARN] Could not fetch asset details for {pid}: {ex}")
                            break

                    updated_places.append(p)

                    # Update UI every 5 places or at end
                    if (i + 1) % 5 == 0 or i == len(all_places) - 1:
                        places_copy = updated_places.copy()
                        items = [(p["display_name"], p.get("created"),
                                  p.get("updated")) for p in places_copy]
                        self._on_main(lambda pc=items: self._update_cards(pc))

            threading.Thread(target=load_timestamps, daemon=True).start()

            # Step 4: Load thumbnails in background
            def load_thumbnails():
                for i, p in enumerate(all_places):
                    if cancel_event.is_set():
                        print("[THUMB] Thumbnail loader cancelled")
                        return

                    place_id = p.get("id")
                    display_name = p.get("display_name")
                    if not place_id or not display_name:
                        continue

                    try:
                        pixmap = self._fetch_thumb_pixmap(place_id)
                        print(
                            f"[DEBUG] Fetched thumbnail for {display_name} ({place_id}): {'yes' if pixmap else 'no'}")
                        if pixmap:
                            print(
                                f"[DEBUG] Scheduling thumbnail update for {display_name}")
                            # Update UI safely
                            # capture now, before scheduling
                            pid_int = int(place_id)

                            def apply_pix(pid=pid_int, name=display_name, pix=pixmap):
                                card = self._card_by_place_id.get(pid)
                                if card:
                                    card.set_thumbnail(pix)
                            self._on_main(apply_pix)

                    except Exception as e:
                        print(
                            f"[WARN] Failed to fetch thumbnail for {display_name} ({place_id}): {e}")

                    # Throttle requests a bit every 5 thumbnails to reduce load
                    if (i + 1) % 5 == 0:
                        time.sleep(0.2)

            # Start the thumbnail loader in a background thread
            threading.Thread(target=load_thumbnails, daemon=True).start()

        except Exception as e:
            print("[ERROR] Search failed:", e)

    def _fetch_thumb_pixmap(self, place_id) -> QPixmap | None:
        if place_id in self.thumb_cache:
            return self._pil_to_qpix(self.thumb_cache[place_id])

        try:
            meta = self._get(
                f"https://thumbnails.roblox.com/v1/places/gameicons?placeIds={place_id}&size=512x512&format=Png", timeout=10)
            meta.raise_for_status()
            data = meta.json()
            img_url = data.get("data", [{}])[0].get("imageUrl")
            if not img_url:
                return None

            img_response = self._get(img_url, timeout=10)
            img_response.raise_for_status()

            pil = Image.open(BytesIO(img_response.content)).convert("RGBA")

            # Keep aspect ratio, max dimension 128px
            max_size = 128
            pil.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)

            self.thumb_cache[place_id] = pil
            return self._pil_to_qpix(pil)

        except Exception as e:
            print(f"[WARN] Failed to fetch thumbnail {place_id}: {e}")
            return None

    def _pil_to_qpix(self, pil_img) -> QPixmap | None:
        if pil_img is None:
            return None
        if ImageQt is None:
            b = BytesIO()
            pil_img.save(b, format='PNG')
            b.seek(0)
            qimg = QImage.fromData(b.read(), 'PNG')
            return QPixmap.fromImage(qimg)
        qimg = ImageQt(pil_img)
        if isinstance(qimg, QImage):
            return QPixmap.fromImage(qimg)
        return QPixmap.fromImage(QImage(qimg))

    def populate_test_cards(self):
        sample = [
            ("Game One", "2024-01-01", "2025-12-25"),
            ("Game Two", "2023-03-12", "2025-11-02"),
            ("Game Three", "2022-08-20", "2025-10-18"),
            ("Game Four", "2021-06-05", "2025-09-01"),
            ("Game Five", "2020-02-14", "2025-08-09"),
            ("Game Six", "2019-12-30", "2025-07-22"),
        ]
        self._add_new_cards(sample)

    def _add_new_cards(self, items):
        existing_names = {getattr(c, 'name', None) for c in self._cards}
        added_any = False

        for item in items:
            # Unpack depending on tuple length
            if len(item) == 5:
                name, created, updated, pid, root = item
            elif len(item) == 4:
                name, created, updated, pid = item
                root = None
            else:
                name, created, updated = item
                pid = None
                root = None

            if name in existing_names:
                continue

            card = GameCardWidget(self.results_container)
            card.set_data(name=name, created=created, updated=updated)

            card.place_id = int(pid) if pid is not None else None
            card.is_root = bool(
                root is not None and pid is not None and int(pid) == int(root))
            card.created_iso = created
            card.updated_iso = updated

            if pid is not None:
                card.on_join(lambda _, place_id=pid,
                             root_id=root: self._join_place(place_id, root_id))

            card.on_open(lambda n=name: print("Open in browser:", n))
            card.setMinimumWidth(0)
            card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

            self._cards.append(card)
            if pid is not None:
                self._card_by_place_id[int(pid)] = card
            existing_names.add(name)
            added_any = True

        if added_any:
            self.apply_search_and_sort()

    def _update_cards(self, items):
        """
        Update existing cards only.
        items: list of tuples (name, created, updated)
        """
        existing_map = {card.ui.nameLabel.text(): card for card in self._cards}

        for name, created, updated in items:
            card = existing_map.get(name)
            if not card:
                continue

            # keep raw ISO for sorting later
            card.created_iso = created
            card.updated_iso = updated

            # update visible labels
            card.set_data(
                name,
                humanize_time(created),
                humanize_time(updated)
            )

        # re-apply filtering/sorting as timestamps appear
        self.apply_search_and_sort()

    def _join_place(self, place_id, root_place_id=None):
        if self.joining_place:
            print("Already joining a place, please wait...")
            return
        print(f"Joining place ID: {place_id}")
        if root_place_id and int(place_id) != int(root_place_id):
            success = self.join_root(root_place_id)
            if success:
                print(
                    f"Pre-seed join successful for root place ID: {root_place_id}")
            else:
                print(
                    f"Pre-seed join failed for root place ID: {root_place_id}")
            self.joining_place = True
        os.startfile(f"roblox://experiences/start?placeId={place_id}")

    def join_root(self, root_place_id: int):
        try:
            cookie = get_roblosecurity()
            if cookie:
                sess = self._new_session(cookie)
                payload = {
                    "placeId": int(root_place_id),
                    "isTeleport": True,
                    "isImmersiveAdsTeleport": False,
                    "gameJoinAttemptId": str(uuid.uuid4()),
                }
                print("[JOIN PRESEED FIRING]", json.dumps(payload, indent=2))
                r = sess.post("https://gamejoin.roblox.com/v1/join-game",
                              json=payload, timeout=15)
                print("[JOIN PRESEED STATUS]", r.status_code)
                try:
                    print("[JOIN PRESEED BODY]", r.text[:800])
                except Exception:
                    pass
                data = {}
                try:
                    data = r.json()
                except Exception:
                    pass
                # Status 2 == ready to join
                return (r.status_code == 200 and data.get("status") == 2)
        except Exception as e:
            print("[JOIN PRESEED ERROR]", e)
            return False

    def _new_session(self, cookie: str | None):
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
        try:
            r = sess.post("https://auth.roblox.com/v2/logout", timeout=10)
            token = r.headers.get(
                "x-csrf-token") or r.headers.get("X-CSRF-TOKEN")
            if token:
                sess.headers["X-CSRF-TOKEN"] = token
        except Exception:
            pass
        return sess

    def _safe_parse_iso(self, iso_str):
        try:
            if not iso_str:
                return None
            return parser.isoparse(iso_str)
        except Exception:
            return None

    def apply_search_and_sort(self):
        # Search filter
        text = ""
        if getattr(self, "search_input", None):
            text = (self.search_input.text() or "").strip().lower()

        for card in self._cards:
            name = (card.ui.nameLabel.text() or "").lower()
            pid = getattr(card, "place_id", None)

            match = True
            if text:
                match = (text in name) or (
                    pid is not None and text in str(pid))

            card.setVisible(match)

        # Sort
        mode = ""
        if getattr(self, "sort_combo", None):
            mode = (self.sort_combo.currentText() or "").strip()

        visible_cards = [c for c in self._cards if c.isVisible()]

        def sort_placeid(c):
            return getattr(c, "place_id", 0) or 0

        def sort_created(c):
            dt = self._safe_parse_iso(getattr(c, "created_iso", None))
            return dt.timestamp() if dt else float("-inf")

        def sort_updated(c):
            dt = self._safe_parse_iso(getattr(c, "updated_iso", None))
            return dt.timestamp() if dt else float("-inf")

        if "PlaceID" in mode:
            reverse = "↓" in mode
            visible_cards.sort(key=sort_placeid, reverse=reverse)
        elif "Created" in mode:
            reverse = "↓" in mode
            visible_cards.sort(key=sort_created, reverse=reverse)
        elif "Updated" in mode:
            reverse = "↓" in mode
            visible_cards.sort(key=sort_updated, reverse=reverse)

        hidden_cards = [c for c in self._cards if not c.isVisible()]
        self._cards = visible_cards + hidden_cards

        self.relayout_cards()

    def clear_results(self):
        # Remove all widgets from layout and delete them
        while self.results_grid.count():
            item = self.results_grid.takeAt(0)
            if item and item.widget():
                w = item.widget()
                w.setParent(None)
                w.deleteLater()  # ensures widget is properly destroyed
        # Clear internal list
        self._cards.clear()

    def relayout_cards(self):
        if not self._cards or self.results_scroll.viewport().width() == 0:
            return

        self.results_container.setUpdatesEnabled(False)

        # Clear positions
        while self.results_grid.count():
            self.results_grid.takeAt(0)

        card_w = 175
        spacing = self.results_grid.spacing() or 8
        margins = self.results_grid.contentsMargins()
        avail = self.results_scroll.viewport().width() - (margins.left() + margins.right())

        per_row = max(1, int((avail + spacing) // (card_w + spacing)))
        per_row = min(per_row, 8)

        visible_cards = [c for c in self._cards if c.isVisible()]
        for i, card in enumerate(visible_cards):
            r = i // per_row
            c = i % per_row
            self.results_grid.addWidget(card, r, c)

            # Refresh thumbnail to match new size
            # card.refresh_thumbnail()

        self.results_container.setUpdatesEnabled(True)
        self.results_container.update()

    def _get(self, url, timeout=10, headers=None, cookies=None):
        try:
            print(f"[HTTP GET] {url}")
            r = requests.get(url, timeout=timeout, proxies={},
                             cookies=cookies, headers=headers)
            try:
                length = r.headers.get(
                    'Content-Length') or len(r.content or b'')
                snippet = (
                    r.text[:300] + '...') if r.text and len(r.text) > 300 else r.text
                print(f"[HTTP GET DONE] {r.status_code} length={length}")
                ct = r.headers.get('Content-Type', '')
                if 'application/json' in ct.lower() or 'text' in ct.lower():
                    print("[HTTP GET BODY SNIPPET]:", snippet)
            except Exception:
                pass
            return r
        except Exception as e:
            print(f"[HTTP GET ERROR] {url} -> {e}")
            raise

    def _on_main(self, fn):
        inv = getattr(self, '_invoker', None)
        if inv is not None:
            print('[DEBUG] _on_main: queuing UI work via signal')
            inv.call.emit(fn)
            return
        print('[DEBUG] _on_main: fallback QTimer.singleShot')
        try:
            QTimer.singleShot(0, fn)
        except Exception as e:
            import traceback
            print('[DEBUG] _on_main fallback failed:', e)
            traceback.print_exc()

    def event(self, event):
        if event.type() == QEvent.Resize:
            self.relayout_cards()

    def on_focus(self):
        self.relayout_cards()

    def request(self, flow):

        url = flow.request.pretty_url
        parsed_url = urlparse(url)
        content_type = flow.request.headers.get("Content-Type", "").lower()
        if (self.joining_place and
            any(p == parsed_url.path for p in self.wanted_join_endpoints) and
            "gamejoin.roblox.com" in url and
                "application/json" in content_type):
            try:
                body_json = flow.request.json()
            except Exception:
                return

            if "isTeleport" not in body_json:
                body_json["isTeleport"] = True
                print("[JOIN] Added teleport flag")

            flow.request.set_text(json.dumps(body_json))

    def response(self, flow):
        url = flow.request.pretty_url
        parsed_url = urlparse(url)

        if self.joining_place and any(p == parsed_url.path for p in self.wanted_join_endpoints):

            # If there's no response, print null as JSON
            if not hasattr(flow, "response") or flow.response is None:
                print("null")
                return

            try:
                data = flow.response.json()
                if data.get("status") == 2:
                    self.joining_place = False
            except Exception:
                # fallback: get text and output as a JSON string
                pass
