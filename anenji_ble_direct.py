"""Direct, read-only Saihang BLE transport for the ANENJI monitor.

Uses the existing aiobmsble Saihang parser but intentionally bypasses its
connection manager, which could not enable notifications on the user's BMS.
Never invokes BMS configuration commands; only Modbus function 03 read query.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable

from bleak import BleakClient
from aiobmsble.bms.saihang_bms import BMS

Log = Callable[[str], None]


class TransportError(RuntimeError):
    pass


async def _polling_update(client, bms, rx, tx, log: Log):
    """Try reading RX directly if the CCCD notification subscription fails.

    This is a *best-effort* workaround. Some GATT devices only expose fresh
    responses through notifications. Validate each response with the official
    Saihang decoder; never fabricate sample data from an advertisement.
    """
    async def query_and_poll(query: bytes, *args, **kwargs):
        for request_no in range(1, 3):
            bms._msg_event.clear()
            # This packet is a read-register query (function code 03).
            await client.write_gatt_char(tx, query, response=False)
            log(f"Прямое чтение FFFC: запрос {request_no}/2 отправлен")
            for read_no in range(8):
                try:
                    raw = bytes(await asyncio.wait_for(
                        client.read_gatt_char(rx, use_cached=False), timeout=2.5
                    ))
                    bms._notification_handler(rx, bytearray(raw))
                    if bms._msg_event.is_set():
                        log(f"Прямое чтение FFFC: получен корректный пакет ({len(raw)} байт)")
                        return
                    if read_no == 0:
                        log(f"Прямое чтение FFFC: ответ не является пакетом BMS "
                            f"({len(raw)} байт; заголовок {raw[:6].hex(' ')})")
                except Exception as exc:
                    # A read error can be transient; use the next scheduled poll.
                    if read_no == 0:
                        log(f"Прямое чтение FFFC: {type(exc).__name__}: {exc}")
                await asyncio.sleep(0.35)
        raise TransportError("FFFC не отдаёт корректный ответ при прямом чтении")

    # Saihang._async_update uses _await_msg, which normally waits for notifications.
    # Replace only this *instance's* receive routine, keeping official parsing.
    bms._await_msg = query_and_poll
    return await bms._async_update()


async def read_saihang_direct(device, mode: str, log: Log) -> dict:
    """Connect, query, decode, disconnect using Bleak directly.

    Mode changes only the Windows service discovery cache policy. The scan
    supplied BLEDevice is reused so Bleak won't scan again while connecting.
    """
    if mode not in ("uncached", "default", "cached"):
        raise ValueError(f"Unsupported BLE mode {mode}")
    opts = {"timeout": 18.0}
    if sys.platform == "win32" and mode != "default":
        opts["winrt"] = {"use_cached_services": mode == "cached"}

    client = BleakClient(device, **opts)  # no restrictive service UUID filter
    bms = BMS(ble_device=device)  # use original official Saihang parser
    bms._client = client  # bind the already-connected direct transport to the parser
    log(f"Прямое подключение [{mode}], без фильтра услуг BLE")

    async with client:
        available = [f"{c.uuid}@{c.handle:04X}" for c in client.services.characteristics.values()]
        log(f"GATT [{mode}]: {', '.join(available[:40])}")
        rx = client.services.get_characteristic("fffc")
        tx = client.services.get_characteristic("fffb")
        if rx is None or tx is None:
            raise TransportError(f"Нет обязательных характеристик FFFB/FFFC "
                                 f"(FFFB={tx is not None}, FFFC={rx is not None})")
        log(f"Канал BMS: FFFB@{tx.handle:04X} -> FFFC@{rx.handle:04X}")
        try:
            await client.start_notify(rx, bms._notification_handler)
        except Exception as exc:
            log(f"Подписка FFFC не удалась: {type(exc).__name__}: {exc}; "
                "пробую чтение FFFC без уведомлений")
            data = await _polling_update(client, bms, rx, tx, log)
        else:
            log("Подписка FFFC успешна; отправка запроса чтения")
            data = await asyncio.wait_for(bms._async_update(), timeout=20.0)

        if not isinstance(data, dict) or data.get("voltage") is None:
            raise TransportError("Ответ BMS не содержит напряжение")
        BMS._add_missing_values(data, BMS._raw_values())
        data["_address"] = device.address
        return data
