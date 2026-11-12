import asyncio
import threading
import queue
import sys
sys.coinit_flags = 0  # Windows: MTA for the BLE worker, before other imports
import tkinter as tk
from tkinter import ttk
from datetime import datetime
from importlib import metadata
import json
import csv
import os
import shutil
import tempfile
import logging
import traceback
from pathlib import Path

from bleak import BleakScanner
from anenji_ble_direct import read_saihang_direct


def load_battery_names():
    """Load exact BLE advertised names from the external user-local file.

    The public release never embeds actual battery identifiers.
    For PyInstaller EXE put batteries.json next to the EXE.
    """
    base = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    cfg = base / "batteries.json"
    try:
        settings = json.loads(cfg.read_text(encoding="utf-8-sig"))
        names = settings["battery_names"]
        if not isinstance(names, list) or len(names) != 2 or any(not isinstance(n, str) or not n.strip() for n in names):
            raise ValueError("battery_names must contain exactly two non-empty BLE device names")
        return [n.strip() for n in names]
    except Exception as exc:
        raise RuntimeError(f"Invalid or missing {cfg}; create batteries.json using batteries.example.json: {exc}") from exc


BATTERIES = load_battery_names()

SCAN_TIMEOUT = 10.0
SCAN_ATTEMPTS = 2
BETWEEN_RETRIES = 2
BETWEEN_BATTERIES = 2

DELTA_WARNING_MV = 50
DELTA_BAD_MV = 100
VOLTAGE_DIFF_WARNING = 0.10
SOC_DIFF_WARNING = 5
TEMP_WARNING = 45.0
TEMP_BAD = 55.0


class BatteryMonitorApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("ANENJI BMS Monitor 8.13")
        self.geometry("1040x820")
        self.minsize(960, 760)
        self.configure(bg="#111827")

        self.results = {}
        self.is_refreshing = False
        self._ble_events = []
        self._ui_events = queue.Queue()
        self._ble_loop = None
        self._ble_ready = threading.Event()
        self._ble_thread = threading.Thread(
            target=self._ble_loop_worker, daemon=True, name="ANENJI-BLE-MTA"
        )
        self._ble_thread.start()

        self._build_styles()
        self._build_ui()
        self.after(100, self._process_ui_events)
        self.protocol("WM_DELETE_WINDOW", self._close_app)

        # Только ручное чтение по кнопке «Обновить».

    def _build_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")

        style.configure(
            "Treeview",
            background="#0f172a",
            foreground="#e5e7eb",
            fieldbackground="#0f172a",
            rowheight=24,
            font=("Segoe UI", 9),
            borderwidth=0,
        )

        style.configure(
            "Treeview.Heading",
            background="#1f2937",
            foreground="#f9fafb",
            font=("Segoe UI Semibold", 9),
            relief="flat",
        )

        style.map(
            "Treeview",
            background=[("selected", "#1d4ed8")],
            foreground=[("selected", "#ffffff")],
        )

        style.configure(
            "TButton",
            font=("Segoe UI Semibold", 10),
            padding=(16, 9),
        )

    def _build_ui(self):
        header = tk.Frame(self, bg="#111827")
        header.pack(fill="x", padx=24, pady=(14, 6))

        title = tk.Label(
            header,
            text="ANENJI BMS MONITOR",
            font=("Segoe UI Semibold", 22),
            fg="#f9fafb",
            bg="#111827",
        )
        title.pack(side="left")

        self.refresh_button = tk.Button(
            header,
            text="Обновить",
            command=self.refresh_data,
            font=("Segoe UI Semibold", 10),
            bg="#2563eb",
            fg="white",
            activebackground="#1d4ed8",
            activeforeground="white",
            relief="flat",
            padx=18,
            pady=8,
            cursor="hand2",
            disabledforeground="#ffffff",
        )
        self.refresh_button.pack(side="right")

        self.diag_button = tk.Button(
            header,
            text="Сохранить диагностику",
            command=self.save_diagnostics,
            font=("Segoe UI Semibold", 9),
            bg="#374151",
            fg="white",
            activebackground="#4b5563",
            activeforeground="white",
            relief="flat",
            padx=14,
            pady=8,
            cursor="hand2",
        )
        self.diag_button.pack(side="right", padx=(0, 10))

        self.time_label = tk.Label(
            self,
            text="Последнее чтение: —",
            font=("Segoe UI", 9),
            fg="#94a3b8",
            bg="#111827",
        )
        self.time_label.pack(anchor="w", padx=26, pady=(0, 8))

        cards = tk.Frame(self, bg="#111827")
        cards.pack(fill="x", padx=24, pady=(0, 10))

        self.card1 = self._make_card(cards, BATTERIES[0])
        self.card1["frame"].pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.card2 = self._make_card(cards, BATTERIES[1])
        self.card2["frame"].pack(side="left", fill="x", expand=True, padx=(8, 0))

        table_frame = tk.Frame(self, bg="#111827")
        table_frame.pack(fill="both", expand=True, padx=24, pady=(0, 10))

        columns = ("parameter", "b1", "b2")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=18)

        self.tree.heading("parameter", text="Параметр")
        self.tree.heading("b1", text=BATTERIES[0])
        self.tree.heading("b2", text=BATTERIES[1])

        self.tree.column("parameter", width=235, anchor="w")
        self.tree.column("b1", width=340, anchor="center")
        self.tree.column("b2", width=340, anchor="center")

        self.tree.pack(fill="both", expand=True)

        self.tree.tag_configure("ok", background="#0f172a", foreground="#e5e7eb")
        self.tree.tag_configure("warn", background="#3a2b08", foreground="#fde68a")
        self.tree.tag_configure("bad", background="#3f1218", foreground="#fecaca")
        self.tree.tag_configure("accent", background="#13233f", foreground="#bfdbfe")

        footer = tk.Frame(self, bg="#111827")
        footer.pack(fill="x", padx=24, pady=(0, 14))

        self.status_box = tk.Frame(
            footer,
            bg="#16351f",
            highlightthickness=1,
            highlightbackground="#22c55e",
        )
        self.status_box.pack(fill="x")

        self.status_title = tk.Label(
            self.status_box,
            text="СОСТОЯНИЕ БАНКА: ОЖИДАНИЕ",
            font=("Segoe UI Semibold", 12),
            fg="#dcfce7",
            bg="#16351f",
        )
        self.status_title.pack(anchor="w", padx=14, pady=(10, 2))

        self.status_detail = tk.Label(
            self.status_box,
            text="Чтение данных ещё не выполнено.",
            font=("Segoe UI", 10),
            fg="#bbf7d0",
            bg="#16351f",
            justify="left",
            wraplength=950,
        )
        self.status_detail.pack(anchor="w", padx=14, pady=(0, 10))

    def _make_card(self, parent, name):
        frame = tk.Frame(
            parent,
            bg="#0f172a",
            highlightthickness=1,
            highlightbackground="#334155",
        )

        name_label = tk.Label(
            frame,
            text=name,
            font=("Segoe UI Semibold", 13),
            fg="#f8fafc",
            bg="#0f172a",
        )
        name_label.pack(anchor="w", padx=16, pady=(9, 2))

        value_label = tk.Label(
            frame,
            text="—",
            font=("Segoe UI Semibold", 20),
            fg="#60a5fa",
            bg="#0f172a",
        )
        value_label.pack(anchor="w", padx=16)

        sub_label = tk.Label(
            frame,
            text="Ожидание данных",
            font=("Segoe UI", 10),
            fg="#94a3b8",
            bg="#0f172a",
        )
        sub_label.pack(anchor="w", padx=16, pady=(0, 9))

        return {
            "frame": frame,
            "value": value_label,
            "sub": sub_label,
        }

    @staticmethod
    def _battery_name(device, advertisement=None):
        """Match only the locally configured advertised names; never hard-code MAC addresses."""
        names = [getattr(device, "name", None)]
        if advertisement is not None:
            names.append(getattr(advertisement, "local_name", None))
        for name in names:
            if name in BATTERIES:
                return name
        return None

    def _ble_log(self, message):
        self._ble_events.append(f"{datetime.now():%Y-%m-%d %H:%M:%S} | {message}")
        if any(k in message for k in ("способ ", "Подписка FFFC", "Прямое чтение FFFC", "УСПЕХ")):
            self._ui_events.put(("progress", message[-160:]))

    async def _discover(self, seconds, label):
        """BLE-скан с записью обнаруженных BMS и реальных ошибок Windows."""
        self._ble_log(f"{label}: начало сканирования ({seconds:.0f} с)")
        try:
            records = await BleakScanner.discover(timeout=seconds, return_adv=True)
            found = {}
            for _, (device, advertisement) in records.items():
                name = self._battery_name(device, advertisement)
                if name:
                    found[name] = device
                    self._ble_log(f"{label}: обнаружена {name}, address={device.address!r}, "
                                  f"device_name={device.name!r}, adv_name={getattr(advertisement, 'local_name', None)!r}")
            self._ble_log(f"{label}: найдено {len(found)} из {len(BATTERIES)} BMS")
            return found
        except Exception as exc:
            self._ble_log(f"{label}: ОШИБКА СКАНА {type(exc).__name__}: {exc}")
            return {}

    async def _scan_for_batteries(self):
        found = {}
        for attempt in range(1, SCAN_ATTEMPTS + 1):
            found.update(await self._discover(SCAN_TIMEOUT, f"Основной поиск {attempt}/{SCAN_ATTEMPTS}"))
            if len(found) == len(BATTERIES):
                break
            if attempt < SCAN_ATTEMPTS:
                await asyncio.sleep(BETWEEN_RETRIES)
        return found

    async def _rescan_device(self, name):
        matches = await self._discover(8.0, f"Повторный поиск {name}")
        return matches.get(name)

    def _ble_loop_worker(self):
        """One persistent asyncio loop, kept alive while the GUI is open.

        BLE operations are *only* invoked in this dedicated background thread.
        Tkinter is never called from this thread.
        """
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._ble_loop = loop
        self._ble_ready.set()
        try:
            loop.run_forever()
        finally:
            tasks = asyncio.all_tasks(self._ble_loop)
            for task in tasks:
                task.cancel()
            if tasks:
                self._ble_loop.run_until_complete(
                    asyncio.gather(*tasks, return_exceptions=True)
                )
            self._ble_loop.close()

    def _process_ui_events(self):
        try:
            while True:
                event_type, value = self._ui_events.get_nowait()
                if event_type == "results":
                    self._update_ui(value)
                elif event_type == "fatal":
                    self._show_global_error(value)
                elif event_type == "progress" and self.is_refreshing:
                    self.status_detail.config(text=value)
        except queue.Empty:
            pass
        self.after(100, self._process_ui_events)

    def _close_app(self):
        # Do not leave new tasks running after the app is closed.
        self.destroy()
        if self._ble_loop is not None and self._ble_loop.is_running():
            self._ble_loop.call_soon_threadsafe(self._ble_loop.stop)

    @staticmethod
    def _package_version(package):
        try:
            return metadata.version(package)
        except Exception:
            return "unknown"

    async def _read_device(self, name, device):
        """Read over direct Bleak, bypassing aiobmsble's connector/CCCD setup."""
        last_error = None
        # Try the two genuinely different Windows GATT discovery modes first.
        # This is intentionally not an endless sequence of identical retries.
        for attempt, mode in enumerate(("uncached", "default", "cached"), start=1):
            if device is None:
                device = await self._rescan_device(name)
                if device is None:
                    last_error = "Батарея не обнаружена при BLE-поиске"
                    self._ble_log(f"{name}: {mode}: {last_error}")
                    continue
            self._ble_log(f"{name}: способ {attempt}/3 ({mode}), {device.address}")
            try:
                data = await read_saihang_direct(
                    device, mode, lambda msg: self._ble_log(f"{name}: {msg}")
                )
                data["_name"] = name
                self._ble_log(
                    f"{name}: УСПЕХ, напряжение={data.get('voltage')} В, "
                    f"SOC={data.get('battery_level')}%"
                )
                return data
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                self._ble_log(f"{name}: {mode}: {last_error}")
                # Request a fresh BLEDevice on each failed connection.
                device = None
                if attempt < 3:
                    await asyncio.sleep(2.0)
        return {"name": name, "error": str(last_error or "Нет ответа BMS")}

    async def _read_all(self):
        results = {}
        devices = await self._scan_for_batteries()
        # Both batteries get exactly the same read/retry logic; no special casing.
        for index, name in enumerate(BATTERIES):
            results[name] = await self._read_device(name, devices.get(name))
            if index < len(BATTERIES) - 1:
                await asyncio.sleep(3.0)
        return results

    async def _read_all_with_log(self):
        self._ble_log(
            "ANENJI 8.13; "
            f"Python={sys.version.split()[0]}; "
            f"Bleak={self._package_version('bleak')}; "
            f"aiobmsble={self._package_version('aiobmsble')}; "
            "постоянный asyncio loop; прямой BLE с обходом сбоев подписки FFFC"
        )
        try:
            results = await self._read_all()
        except Exception:
            detail = traceback.format_exc()
            self._ble_log("КРИТИЧЕСКАЯ ОШИБКА ОПРОСА: " + detail)
            results = {
                name: {"name": name, "error": "Ошибка опроса, см. BLE-журнал"}
                for name in BATTERIES
            }
        try:
            log_path = self._write_ble_log()
            self._ble_log(f"Журнал сохранён: {log_path}")
        except Exception as exc:
            self._ble_log(f"ОШИБКА ЗАПИСИ BLE-ЖУРНАЛА: {type(exc).__name__}: {exc}")
        self._ui_events.put(("results", results))

    def _write_ble_log(self):
        """Каждая проверка создаёт отдельный TXT, прежние журналы не трогает."""
        directory = self._history_path().parent
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        for suffix in range(1000):
            tail = "" if suffix == 0 else f"_{suffix:02d}"
            path = directory / f"ANENJI_BLE_log_{stamp}{tail}.txt"
            try:
                with path.open("x", encoding="utf-8") as f:
                    f.write("\n".join(self._ble_events) + "\n")
                return path
            except FileExistsError:
                continue
        raise OSError("Не удалось создать уникальное имя BLE-журнала")

    def refresh_data(self):
        if self.is_refreshing:
            return

        self.is_refreshing = True
        self._ble_events = []
        self.results = {}
        self._set_card_reading(self.card1)
        self._set_card_reading(self.card2)
        self._set_table_waiting()
        self.time_label.config(text="Чтение батарей...")
        self.refresh_button.config(state="disabled", text="Чтение...", bg="#1d4ed8", fg="#ffffff", disabledforeground="#ffffff")
        self.status_title.config(text="СОСТОЯНИЕ БАНКА: ЧТЕНИЕ")
        self.status_detail.config(text="Подключение к двум BMS по Bluetooth...")

        if not self._ble_ready.wait(timeout=2.0):
            self._show_global_error("Фоновый Bluetooth-поток не запустился")
            return
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._read_all_with_log(), self._ble_loop
            )
            future.add_done_callback(self._finished_read)
        except Exception as exc:
            self._show_global_error(f"{type(exc).__name__}: {exc}")

    def _finished_read(self, future):
        # This callback runs on the worker; it may only write to the queue.
        try:
            future.result()
        except Exception as exc:
            self._ui_events.put(("fatal", f"{type(exc).__name__}: {exc}"))

    def _show_global_error(self, text):
        # Ошибка общего BLE-опроса: оба окна очищаются, старые данные не остаются.
        self._update_ui({name: {"name": name, "error": text} for name in BATTERIES})

    def _get_cells(self, data):
        cells = list(data.get("cell_voltages", []))
        while len(cells) < 4:
            cells.append(None)
        return cells[:4]

    def _get_temps(self, data):
        result = []

        for item in data.get("temp_values", []):
            value = None

            for getter in (
                lambda x: float(x[0]),
                lambda x: float(x.value),
                lambda x: float(x),
            ):
                try:
                    value = getter(item)
                    break
                except Exception:
                    pass

            if value is not None:
                result.append(value)

        return result

    def _delta_mv(self, data):
        value = data.get("delta_voltage")
        return None if value is None else float(value) * 1000.0

    def _fmt(self, value, digits=2, suffix=""):
        if value is None:
            return "—"
        try:
            return f"{float(value):.{digits}f}{suffix}"
        except Exception:
            return f"{value}{suffix}"

    def _problem_code_text(self, data):
        value = data.get("problem_code")
        if value is None:
            return "—"
        try:
            n = int(value)
            return f"{n} / 0x{n:08X}"
        except Exception:
            return str(value)

    def _bool_text(self, value):
        if value is True:
            return "ДА"
        if value is False:
            return "НЕТ"
        return "—"

    def save_diagnostics(self):
        """Сохраняет отдельный TXT-снимок в общей папке истории."""
        if not any(self._valid(self.results.get(name)) for name in BATTERIES):
            self._set_status(
                "НЕТ ДАННЫХ",
                "Сначала выполните успешное чтение BMS кнопкой «Обновить».",
                level="warn",
            )
            return

        now = datetime.now()
        stamp = now.strftime("%Y%m%d_%H%M%S")
        directory = self._history_path().parent
        lines = [
            "ANENJI BMS diagnostic dump",
            f"Time: {now.strftime('%d.%m.%Y %H:%M:%S')}",
            "",
        ]
        for name in BATTERIES:
            data = self.results.get(name)
            lines.extend(["=" * 72, name, "=" * 72])
            if not self._valid(data):
                error = data.get("error", "Нет свежих данных") if isinstance(data, dict) else "Нет свежих данных"
                lines.append(f"Status: NO DATA; {error}")
            else:
                for key in sorted(data.keys()):
                    lines.append(f"{key}: {repr(data.get(key))}")
            lines.append("")

        report = "\n".join(lines) + "\n"
        try:
            directory.mkdir(parents=True, exist_ok=True)
            # Имя до секунды. При совпадении секунды добавляем числовой суффикс;
            # режим x никогда не перезаписывает старую диагностику.
            for index in range(1000):
                suffix = "" if index == 0 else f"_{index:02d}"
                snapshot = directory / f"ANENJI_BMS_diagnostic_{stamp}{suffix}.txt"
                try:
                    with snapshot.open("x", encoding="utf-8") as f:
                        f.write(report)
                        f.flush()
                        os.fsync(f.fileno())
                    break
                except FileExistsError:
                    continue
            else:
                raise OSError("Невозможно выбрать свободное имя файла диагностики")
        except OSError as exc:
            self._set_status(
                "ОШИБКА СОХРАНЕНИЯ ДИАГНОСТИКИ",
                f"{type(exc).__name__}: {exc}",
                level="bad",
            )
            return

        self._set_status(
            "ДИАГНОСТИКА СОХРАНЕНА",
            f"Новый TXT: {snapshot.name}\nПапка: {directory}",
            level="ok",
        )

    def _history_path(self):
        """Единая папка истории на Рабочем столе Windows (включая OneDrive)."""
        profile = Path(os.environ.get("USERPROFILE", str(Path.home())))
        desktop = profile / "Desktop"
        try:
            import winreg
            registry_key = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, registry_key) as key:
                configured_desktop, _ = winreg.QueryValueEx(key, "Desktop")
            desktop = Path(os.path.expandvars(configured_desktop))
        except (ImportError, OSError, ValueError):
            pass
        return desktop / "ANENJI BMS History" / "ANENJI_BMS_history.csv"

    def _append_history(self, results, timestamp):
        """По одной строке на каждую УСПЕШНО прочитанную батарею."""
        names = [
            "timestamp", "battery", "voltage_V", "soc_pct", "current_A",
            "power_W", "remaining_Ah", "design_capacity_Ah", "battery_health_pct",
            "cycles", "cell1_V", "cell2_V", "cell3_V", "cell4_V",
            "delta_mV", "temperature1_C", "temperature2_C", "temperature3_C",
            "charge_mos", "discharge_mos", "problem", "problem_code",
            "balancer", "battery_charging", "battery_mode", "ble_address"
        ]
        def numeric(value):
            """Excel RU/UA: десятичная запятая, разделитель колонок — точка с запятой."""
            if value is None or value == "":
                return ""
            try:
                return str(float(value)).replace(".", ",")
            except (ValueError, TypeError):
                return ""

        def flag(value):
            return "ON" if value is True else ("OFF" if value is False else "")

        lines = []
        for name in BATTERIES:
            data = results.get(name)
            if not self._valid(data):
                continue
            cells = self._get_cells(data)
            temps = self._get_temps(data)
            lines.append([
                timestamp, name, numeric(data.get("voltage")),
                numeric(data.get("battery_level")), numeric(data.get("current")),
                numeric(data.get("power")), numeric(data.get("cycle_charge")),
                numeric(data.get("design_capacity")), numeric(data.get("battery_health")),
                numeric(data.get("cycles")), *[numeric(x) for x in cells],
                numeric(self._delta_mv(data)),
                *[numeric(temps[i]) if len(temps) > i else "" for i in range(3)],
                flag(data.get("chrg_mosfet")), flag(data.get("dischrg_mosfet")),
                flag(data.get("problem")), data.get("problem_code", ""),
                flag(data.get("balancer")), flag(data.get("battery_charging")),
                str(data.get("battery_mode", "")), str(data.get("_address", ""))
            ])
        if not lines:
            return None

        # Все записи только на Рабочем столе; молчаливого переноса нет.
        path = self._history_path()
        written = self._write_history_csv(path, names, lines)
        return path, written

    @staticmethod
    def _migrate_history_for_excel(path, header):
        """Однократно конвертирует старый CSV с десятичной точкой; сохраняет резервную копию."""
        if not path.exists() or path.stat().st_size == 0:
            return
        numeric_fields = {
            "voltage_V", "soc_pct", "current_A", "power_W", "remaining_Ah",
            "design_capacity_Ah", "battery_health_pct", "cycles",
            "cell1_V", "cell2_V", "cell3_V", "cell4_V", "delta_mV",
            "temperature1_C", "temperature2_C", "temperature3_C", "problem_code"
        }
        with path.open("r", encoding="utf-8-sig", newline="") as source:
            reader = csv.reader(source, delimiter=";")
            try:
                existing_header = next(reader)
            except StopIteration:
                return
            # Не меняем файл чужого формата или с неизвестными колонками.
            if existing_header != header:
                raise ValueError("CSV имеет другой набор колонок. Старый файл сохранён; исправьте его отдельно.")
            numeric_positions = [i for i, name in enumerate(existing_header) if name in numeric_fields]
            old_rows = []
            changed = False
            for row in reader:
                if len(row) != len(header):
                    raise ValueError("В старом CSV обнаружена строка с неверным количеством колонок. Файл не изменён.")
                for i in numeric_positions:
                    value = row[i].strip()
                    # Меняем только корректные числовые поля, не даты и не BLE-адреса.
                    if "." in value and "," not in value:
                        try:
                            float(value)
                        except ValueError:
                            continue
                        row[i] = value.replace(".", ",")
                        changed = True
                old_rows.append(row)
        if not changed:
            return
        backup = path.with_suffix(".before_decimal_fix.csv")
        if not backup.exists():
            shutil.copy2(path, backup)
        fd, temp_name = tempfile.mkstemp(prefix="ANENJI_BMS_", suffix=".csv", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f, delimiter=";", lineterminator="\n")
                writer.writerow(header)
                writer.writerows(old_rows)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    @staticmethod
    def _write_history_csv(path, header, rows):
        """Сохраняет старую историю и дописывает новые значения с десятичной запятой."""
        path.parent.mkdir(parents=True, exist_ok=True)
        BatteryMonitorApp._migrate_history_for_excel(path, header)
        before = path.stat().st_size if path.exists() else 0
        with path.open("a", encoding="utf-8-sig" if before == 0 else "utf-8", newline="") as f:
            writer = csv.writer(f, delimiter=";", lineterminator="\n")
            if before == 0:
                writer.writerow(header)
            writer.writerows(rows)
            f.flush()
            os.fsync(f.fileno())
        after = path.stat().st_size
        if after <= before:
            raise OSError("Размер CSV не увеличился после записи")
        return len(rows)

    def _mos(self, value):
        if value is True:
            return "ON"
        if value is False:
            return "OFF"
        return "—"

    def _charge_mos_text(self, data):
        value = data.get("chrg_mosfet")
        soc = data.get("battery_level")
        problem = bool(data.get("problem"))

        if value is True:
            return "ON"
        if value is False:
            try:
                if not problem and soc is not None and float(soc) >= 98.0:
                    return "OFF (заряжено)"
            except Exception:
                pass
            return "OFF"
        return "—"

    def _top_charge_voltage_split_is_normal(self, d1, d2):
        """
        На самом верху заряда одна BMS может уже закрыть Charge MOS,
        пока вторая ещё заканчивает заряд. В этот короткий период разница
        внутренних напряжений сама по себе не считается предупреждением.
        """
        try:
            if d1.get("problem") or d2.get("problem"):
                return False

            s1 = float(d1.get("battery_level"))
            s2 = float(d2.get("battery_level"))
            i1 = abs(float(d1.get("current", 0.0)))
            i2 = abs(float(d2.get("current", 0.0)))

            one_charge_closed = (
                d1.get("chrg_mosfet") is False
                or d2.get("chrg_mosfet") is False
            )

            return (
                s1 >= 95.0
                and s2 >= 95.0
                and i1 <= 0.20
                and i2 <= 0.20
                and one_charge_closed
            )
        except Exception:
            return False

    def _update_ui(self, results):
        self.results = results
        self.is_refreshing = False
        self.refresh_button.config(state="normal", text="Обновить", bg="#2563eb", fg="#ffffff")

        now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        valid_count = sum(self._valid(results.get(name)) for name in BATTERIES)
        self.time_label.config(
            text=f"Последнее чтение: {now}" if valid_count
            else f"Попытка чтения: {now} (нет данных)"
        )
        csv_error = None
        try:
            history_result = self._append_history(results, now)
            if history_result and valid_count:
                history_file, written = history_result
                self.time_label.config(
                    text=f"Последнее чтение: {now}  |  CSV: +{written} стр.  |  {history_file}"
                )
            elif not valid_count:
                self.time_label.config(text=f"Попытка чтения: {now}  |  CSV: нет новых данных")
        except Exception as exc:
            # Сохраняем показания на экране и явно сообщаем о проблеме с CSV.
            csv_error = f"{type(exc).__name__}: {exc}"
            self.time_label.config(text=f"Последнее чтение: {now}  |  CSV НЕ ЗАПИСАН: {csv_error}")

        d1 = results.get(BATTERIES[0])
        d2 = results.get(BATTERIES[1])

        self._update_card(self.card1, d1)
        self._update_card(self.card2, d2)

        for item in self.tree.get_children():
            self.tree.delete(item)

        # Каждая батарея отображается независимо. У недоступной — пустые поля.
        ok1, ok2 = self._valid(d1), self._valid(d2)
        data1 = d1 if ok1 else {}
        data2 = d2 if ok2 else {}
        d1, d2 = data1, data2

        c1 = self._get_cells(d1)
        c2 = self._get_cells(d2)
        t1 = self._get_temps(d1)
        t2 = self._get_temps(d2)
        delta1 = self._delta_mv(d1)
        delta2 = self._delta_mv(d2)

        rows = [
            ("Напряжение", self._fmt(d1.get("voltage"), 2, " В"),
             self._fmt(d2.get("voltage"), 2, " В"), "accent"),
            ("SOC", self._fmt(d1.get("battery_level"), 0, " %"),
             self._fmt(d2.get("battery_level"), 0, " %"), "accent"),
            ("Battery health", self._fmt(d1.get("battery_health"), 0, " %"),
             self._fmt(d2.get("battery_health"), 0, " %"), "ok"),
            ("Остаток ёмкости", self._fmt(d1.get("cycle_charge"), 2, " А·ч"),
             self._fmt(d2.get("cycle_charge"), 2, " А·ч"), "ok"),
            ("Номинальная ёмкость", self._fmt(d1.get("design_capacity"), 0, " А·ч"),
             self._fmt(d2.get("design_capacity"), 0, " А·ч"), "ok"),
            ("Циклы", self._fmt(d1.get("cycles"), 0),
             self._fmt(d2.get("cycles"), 0), "ok"),
            ("Ток", self._fmt(d1.get("current"), 2, " А"),
             self._fmt(d2.get("current"), 2, " А"), "accent"),
            ("Мощность", self._fmt(d1.get("power"), 1, " Вт"),
             self._fmt(d2.get("power"), 1, " Вт"), "ok"),
            ("Ячейка 1", self._fmt(c1[0], 3, " В"),
             self._fmt(c2[0], 3, " В"), "ok"),
            ("Ячейка 2", self._fmt(c1[1], 3, " В"),
             self._fmt(c2[1], 3, " В"), "ok"),
            ("Ячейка 3", self._fmt(c1[2], 3, " В"),
             self._fmt(c2[2], 3, " В"), "ok"),
            ("Ячейка 4", self._fmt(c1[3], 3, " В"),
             self._fmt(c2[3], 3, " В"), "ok"),
            ("Delta", self._fmt(delta1, 0, " мВ"),
             self._fmt(delta2, 0, " мВ"), self._delta_tag(delta1, delta2)),
            ("Температуры",
             " / ".join(f"{x:.1f} °C" for x in t1) if t1 else "—",
             " / ".join(f"{x:.1f} °C" for x in t2) if t2 else "—",
             self._temp_tag(t1, t2)),
            ("Charge MOS", self._charge_mos_text(d1),
             self._charge_mos_text(d2), "ok"),
            ("Discharge MOS", self._mos(d1.get("dischrg_mosfet")),
             self._mos(d2.get("dischrg_mosfet")), "ok"),
            ("Ошибка BMS", "—" if not ok1 else ("ДА" if d1.get("problem") else "НЕТ"),
             "—" if not ok2 else ("ДА" if d2.get("problem") else "НЕТ"),
             "bad" if d1.get("problem") or d2.get("problem") else "ok"),
            ("Protection code", self._problem_code_text(d1),
             self._problem_code_text(d2),
             "bad" if d1.get("problem") or d2.get("problem") else "ok"),
            ("Battery mode", str(d1.get("battery_mode", "—")),
             str(d2.get("battery_mode", "—")), "ok"),
            ("Battery charging", self._bool_text(d1.get("battery_charging")),
             self._bool_text(d2.get("battery_charging")), "ok"),
            ("Balancer", self._bool_text(d1.get("balancer")),
             self._bool_text(d2.get("balancer")), "ok"),
        ]

        for parameter, v1, v2, tag in rows:
            self.tree.insert("", "end", values=(parameter, v1, v2), tags=(tag,))

        if ok1 and ok2:
            self._update_bank_status(d1, d2, t1, t2)
        else:
            readable = [name for name, ok in zip(BATTERIES, (ok1, ok2)) if ok]
            if readable:
                self._set_status("НЕПОЛНЫЕ ДАННЫЕ",
                    "Прочитана только " + ", ".join(readable) + ". Другая батарея: нет связи. Сумма банка не вычисляется.",
                    level="warn")
            else:
                self._set_status("НЕТ СВЯЗИ", "Не удалось прочитать ни одну батарею.", level="bad")

    def _set_card_reading(self, card):
        card["value"].config(text="ЧТЕНИЕ...", fg="#60a5fa")
        card["sub"].config(text="Ожидание ответа BMS")

    def _set_table_waiting(self):
        # Сохраняем строки параметров на экране, но убираем старые значения.
        parameters = [
            "Напряжение", "SOC", "Battery health", "Остаток ёмкости",
            "Номинальная ёмкость", "Циклы", "Ток", "Мощность",
            "Ячейка 1", "Ячейка 2", "Ячейка 3", "Ячейка 4",
            "Delta", "Температуры", "Charge MOS", "Discharge MOS",
            "Ошибка BMS", "Protection code", "Battery mode",
            "Battery charging", "Balancer",
        ]
        for item in self.tree.get_children():
            self.tree.delete(item)
        for parameter in parameters:
            self.tree.insert("", "end", values=(parameter, "—", "—"))

    def _update_card(self, card, data):
        if not self._valid(data):
            card["value"].config(text="НЕТ СВЯЗИ", fg="#f87171")
            msg = data.get("error", "Нет данных") if isinstance(data, dict) else "Нет данных"
            card["sub"].config(text=msg)
            return

        voltage = self._fmt(data.get("voltage"), 2, " В")
        soc = self._fmt(data.get("battery_level"), 0, "%")
        current = self._fmt(data.get("current"), 2, " А")

        card["value"].config(text=f"{voltage}   •   {soc}", fg="#60a5fa")
        card["sub"].config(
            text=f"Ток: {current}   •   {data.get('_address', '')}"
        )

    def _valid(self, data):
        return isinstance(data, dict) and "error" not in data

    def _show_partial_results(self, d1, d2):
        for name, data in ((BATTERIES[0], d1), (BATTERIES[1], d2)):
            status = "Данные получены" if self._valid(data) else data.get("error", "Нет данных")
            tag = "ok" if self._valid(data) else "bad"
            self.tree.insert("", "end", values=(name, status, ""), tags=(tag,))

        self._set_status(
            "НЕПОЛНЫЕ ДАННЫЕ",
            "Не удалось прочитать обе батареи. Это обычно временный сбой Windows BLE. Нажмите «Обновить».",
            level="warn",
        )

    def _delta_tag(self, d1, d2):
        values = [x for x in (d1, d2) if x is not None]
        if not values:
            return "ok"
        worst = max(values)
        if worst >= DELTA_BAD_MV:
            return "bad"
        if worst >= DELTA_WARNING_MV:
            return "warn"
        return "ok"

    def _temp_tag(self, t1, t2):
        values = t1 + t2
        if not values:
            return "ok"
        worst = max(values)
        if worst >= TEMP_BAD:
            return "bad"
        if worst >= TEMP_WARNING:
            return "warn"
        return "ok"

    def _update_bank_status(self, d1, d2, t1, t2):
        warnings = []
        serious = []

        v1 = d1.get("voltage")
        v2 = d2.get("voltage")
        s1 = d1.get("battery_level")
        s2 = d2.get("battery_level")
        cap1 = d1.get("cycle_charge")
        cap2 = d2.get("cycle_charge")
        delta1 = self._delta_mv(d1)
        delta2 = self._delta_mv(d2)

        details = []

        if v1 is not None and v2 is not None:
            diff = abs(float(v1) - float(v2))
            details.append(f"Δ напряжения: {diff:.3f} В")
            if diff >= VOLTAGE_DIFF_WARNING:
                if not self._top_charge_voltage_split_is_normal(d1, d2):
                    warnings.append(f"разница напряжений {diff:.3f} В")

        if s1 is not None and s2 is not None:
            diff = abs(float(s1) - float(s2))
            details.append(f"Δ SOC: {diff:.0f}%")
            if diff >= SOC_DIFF_WARNING:
                warnings.append(f"разница SOC {diff:.0f}%")

        if cap1 is not None and cap2 is not None:
            diff = abs(float(cap1) - float(cap2))
            details.append(f"Δ ёмкости: {diff:.2f} А·ч")

        current1 = d1.get("current")
        current2 = d2.get("current")
        power1 = d1.get("power")
        power2 = d2.get("power")

        if current1 is not None and current2 is not None:
            total_current = float(current1) + float(current2)
            details.append(f"Банк: {total_current:+.2f} А")

        if power1 is not None and power2 is not None:
            total_power = float(power1) + float(power2)
            details.append(f"{total_power:+.1f} Вт")

        for name, delta in ((BATTERIES[0], delta1), (BATTERIES[1], delta2)):
            if delta is not None:
                if delta >= DELTA_BAD_MV:
                    serious.append(f"{name}: delta {delta:.0f} мВ")
                elif delta >= DELTA_WARNING_MV:
                    warnings.append(f"{name}: delta {delta:.0f} мВ")

        all_temps = t1 + t2
        if all_temps:
            max_temp = max(all_temps)
            details.append(f"Tmax: {max_temp:.1f} °C")
            if max_temp >= TEMP_BAD:
                serious.append(f"температура {max_temp:.1f} °C")
            elif max_temp >= TEMP_WARNING:
                warnings.append(f"температура {max_temp:.1f} °C")

        for name, data in ((BATTERIES[0], d1), (BATTERIES[1], d2)):
            if data.get("problem"):
                serious.append(
                    f"{name}: ошибка BMS, код {data.get('problem_code')}"
                )

            if data.get("chrg_mosfet") is False:
                soc = data.get("battery_level")
                normal_full = False
                try:
                    normal_full = (
                        not data.get("problem")
                        and soc is not None
                        and float(soc) >= 98.0
                    )
                except Exception:
                    normal_full = False

                if not normal_full:
                    warnings.append(f"{name}: Charge MOS OFF")

            if data.get("dischrg_mosfet") is False:
                warnings.append(f"{name}: Discharge MOS OFF")

        if serious:
            text = " • ".join(details)
            text += "\nТребует внимания: " + "; ".join(serious + warnings)
            self._set_status("ТРЕБУЕТ ВНИМАНИЯ", text, level="bad")
        elif warnings:
            text = " • ".join(details)
            text += "\nПредупреждения: " + "; ".join(warnings)
            self._set_status("ЕСТЬ ПРЕДУПРЕЖДЕНИЯ", text, level="warn")
        else:
            text = " • ".join(details)
            self._set_status("НОРМА", text, level="ok")

    def _set_status(self, title, detail, level="ok"):
        if level == "bad":
            bg = "#3f1218"
            border = "#ef4444"
            fg1 = "#fee2e2"
            fg2 = "#fecaca"
        elif level == "warn":
            bg = "#3a2b08"
            border = "#f59e0b"
            fg1 = "#fef3c7"
            fg2 = "#fde68a"
        else:
            bg = "#16351f"
            border = "#22c55e"
            fg1 = "#dcfce7"
            fg2 = "#bbf7d0"

        self.status_box.config(
            bg=bg,
            highlightbackground=border,
        )
        self.status_title.config(
            text=f"СОСТОЯНИЕ БАНКА: {title}",
            bg=bg,
            fg=fg1,
        )
        self.status_detail.config(
            text=detail,
            bg=bg,
            fg=fg2,
        )


if __name__ == "__main__":
    app = BatteryMonitorApp()
    app.mainloop()
