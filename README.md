# ANENJI LiFePO4 BLE BMS Monitor — Windows, research notes

[Русская документация](README_RU.md) · Experiments from **November 6–12, 2026**.

This community research package contains a read-only Windows GUI for **two 12.8 V / 100 Ah ANENJI LiFePO4 packs** exposing `SH12100-H-*` BLE names, plus reproducible Bluetooth troubleshooting notes and field observations. Tested software stack: **Python 3.13.17, Bleak 3.0.2, aiobmsble 0.30.0**.

**Safety warning:** BMS telemetry may be unavailable or inaccurate. **Never use this software for safety-critical control, charging protection, or automatic disconnect decisions.** This is not manufacturer documentation.

## Install (Windows)

1. Install Python 3.13 and run `py -m pip install -r requirements.txt`.
2. Copy `batteries.example.json` to `batteries.json` and replace sample names with the **two exact BLE advertised names** of your batteries. Your `batteries.json` stays local and is ignored by git.
3. Run `py battery_gui_v8_13.py`; readings only happen when you press **Refresh**.
4. To build a Windows executable, run `py -m pip install -r requirements-build.txt`, then `BUILD_ANENJI_BMS_v8_13.bat`. Keep the configured `batteries.json` next to the resulting `.exe`.

The publicly shared source is generalized and intentionally **does not embed the owner's BLE identifiers**. We do not publish the owner's prebuilt, device-specific executable or raw identifying logs.

## Proven findings

- Advertisements were observed from two `SH12100-H-*` devices. In successful GATT sessions the `FFFB` characteristic was used for read requests and `FFFC` for responses/notifications (service `FFFA`).
- Windows intermittently produced `Could not start notify on 0019: Unreachable` and `Characteristic fffc was not found!` during November 12 debugging. Both devices later read successfully with a library-managed implementation (v8.12) and a direct Bleak implementation (v8.13). **The root cause is unknown.** The v8.13 fallback path was **not exercised** during those successes.
- In a PowMR charging experiment, current tapered to zero around 13.61 V pack voltage with inverter setting Float=13.7 V and Bulk settings of 14.2–14.4 V. BMS SOC was around 93%/90%. A cell-voltage spread of ~46–50 mV in one pack was observed near the end of charge and dropped to ~4–7 mV during discharge. **Actual bulk-stage voltage and charger stage were not captured; no definitive charger or balancer diagnosis is possible.**

## Research and diagnostics

- [Detailed measurements (Russian)](docs/OBSERVATIONS_RU.md)
- [Measurements and limits (English)](docs/OBSERVATIONS_EN.md)
- [Windows BLE troubleshooting (Russian)](docs/BLE_NOTES_RU.md)
- [Synthetic/anonymized example](examples/measurements_sample.csv)
- [Privacy policy for this release](PRIVACY.md)
- [Static HTML article for GitHub Pages](docs/index.html)
- [Forum announcement (English)](FORUM_POST_EN.md)

Built with third-party packages [`bleak`](https://github.com/hbldh/bleak) and [`aiobmsble`](https://github.com/patman15/aiobmsble). Not affiliated with ANENJI or PowMR. Tested only on one set of battery packs.
