This repository contains the experiments and datasets from Jude Béthinger-Busquet's and Julian Haverkamp's bachelor research theses.

Jude's abstract:
Wireless communication protocols are largely used for remote IoT deployments, where energy-efficiency is a key concern. WiFi, BLE and LoRa are commonly used for wireless transmission in IoT. This thesis experimentally measures and models the energy consumption of WiFi, BLE and LoRa across different operational phases. The Seeed Studio XIAO ESP32C3, Seeed Studio XIAO nRF52840, and LoRa RN2903 Mote transceiver modules were used for WiFi, BLE and LoRa testing respectively. The experimental measurements were conducted in two experiments, one transmission experiment, measuring idle and transmission energies across varying data payload sizes, and one boot experiment, measuring power draw during module startup, each repeated 30 times per module. Data processing was performed, characterizing module current consumption behaviours and computing energy costs. Comparison to theoretical values presented similarities, validating experimental methodology. Results revealed BLE to be the most energy-efficient for every tested transmission payload size as well as idle and boot operational phases. Additionally, this work provides detailed analysis of the module's behaviour through the boot, idle and transmission operational phases.




Julian's abstract: 


The continuing growth of Internet of Things (IoT) deployments has placed the energy consumption of wireless modules at the center of efforts to extend device lifetimes. While individual energy efficiency gains may be minor, the billions of IoT devices in use means that such improvements could carry significant cumulative energy and environmental implications. Existing energy models treat radio operation as the dominant energy drain, while the method by which a host microcontroller delivers data to the module has remained largely unexamined. This study empirically characterises the energy consumption of three wireless modules (Seeed Studio XIAO ESP32-C3 (Wi-Fi), Seeed Studio XIAO nRF52840 (BLE), and RN2903 LoRa Mote) across three host-to- module payload delivery strategies: full payload, chunked, and byte-by-byte. Module current demand was measured across payload sizes from 1 byte up to 512 KiB. Across all payload sizes and methods, BLE was the most energy-efficient module per byte. The chunked strategy was the most efficient delivery method at smaller payloads, with the full-payload strategy overtaking it at larger sizes due to firmware-level scheduling effects. The byte-by-byte strategy was consistently the worst performer. These findings suggest that host-side delivery strategy could meaningfully shape IoT module energy consumption alongside the choice of protocol.





Julian's read me


# BTR: Empirical Energy Characterisation of Wireless IoT Modules

This repository contains the source code, raw measurement data, processing scripts, and figures from a bachelor thesis at the Maastricht Science Programme, conducted in collaboration with the EU-funded MISO project (Grant No. 101086541) and the Arctic Green Computing group at UiT (The Arctic University of Norway).

The study compares the energy consumption of three wireless IoT modules (Wi-Fi, BLE, and LoRa) across three host-to-module data delivery strategies (full payload, chunked, byte-by-byte) at payload sizes from 1 byte to 512 KiB. The full thesis is included in the repository for context.

If you want to reproduce the experiments, extend the analysis, or just borrow parts of the pipeline for your own work, this README walks through how everything fits together.

## TL;DR findings

- BLE (nRF52840) was the most energy-efficient module per byte across every payload size and delivery method tested.
- The chunked delivery method was most efficient at smaller payloads, with the full-payload method overtaking it at larger sizes (the crossover point depends on the protocol and is driven by firmware-level scheduling, not the protocol itself).
- The byte-by-byte method was consistently the worst performer, with energy scaling roughly linearly with payload due to cumulative per-byte UART and radio overhead.

## Hardware required to reproduce

| Component | Model | Notes |
|---|---|---|
| Host computer | Any | macOS was used; Linux should work with minor path changes |
| Microcontroller | Raspberry Pi Pico (RP2040) | Powers and controls the Wi-Fi/BLE modules over UART |
| Wi-Fi module | Seeed Studio XIAO ESP32-C3 | |
| BLE module | Seeed Studio XIAO nRF52840 | |
| LoRa module | RN2903 LoRa Mote (×2) | Second mote acts as receive node |
| Multimeter | Rohde & Schwarz HMC8012 | Used in DC V mode, 200 SPS, 4¾ digit |
| Shunt resistor | 1.1 Ω, ±5% tolerance | Measured value used in analysis was 1.1346 Ω |
| Breadboard, jumper wires, modified USB cable for LoRa | | |

The LoRa setup needs a USB cable with the VBUS line exposed so the shunt can be spliced in. The RN2903 cannot be powered through the Pico because its USB-to-UART bridge needs USB power to enumerate.

Wiring diagrams for all three setups are in the thesis (Figures 1, 2, 3) and reproduced in `docs/wiring/`.

## Software requirements

- Python 3.10 or newer
- Arduino IDE (or `arduino-cli`) with these board packages:
  - `esp32` by Espressif Systems (for the ESP32-C3)
  - `Adafruit nRF52` by Adafruit (for the nRF52840)
- The Python packages listed in `requirements.txt` (mainly `pandas`, `numpy`, `matplotlib`, `seaborn`, `pyvisa`, `pyserial`)

Install Python dependencies with:

```bash
pip install -r requirements.txt
```

For the multimeter you also need a VISA backend. On macOS and Linux, `pyvisa-py` works out of the box and is included in `requirements.txt`. On Windows you may want NI-VISA from National Instruments.

## Repository layout

```
BTR/
├── firmware/                  # Arduino .ino files for the Pico and each module
│   ├── pico/                  # Pico firmware variants (one per experiment)
│   │   ├── pico_full.ino
│   │   ├── pico_chunk.ino
│   │   └── pico_byte.ino
│   ├── esp32c3/               # Wi-Fi module firmware
│   ├── nrf52840/              # BLE module firmware
│   └── rn2903/                # LoRa command sequences (host-driven)
│
├── host/                      # Host-side Python control scripts
│   ├── run_experiment.py      # Main experiment runner
│   ├── meter.py               # HMC8012 multimeter interface (PyVISA)
│   ├── pico_io.py             # Serial interface to the Pico
│   ├── ble_receiver.py        # BLE client for receiving and verifying payloads
│   ├── wifi_receiver.py       # TCP client for receiving and verifying payloads
│   ├── lora_receiver.py       # Second-mote receive script (validation only)
│   └── att_mtu_ble.py         # Standalone script to confirm BLE ATT MTU
│
├── data/
│   ├── raw/                   # Raw CSVs straight from the experiment runs
│   │   ├── wifi/{full,chunk,byte}/
│   │   ├── ble/{full,chunk,byte}/
│   │   └── lora/{full,chunk,byte}/
│   ├── processed/             # Cleaned and consolidated CSVs
│   ├── calibration/           # Shunt, supply voltage, and zero-offset characterisation
│   └── boot/                  # Module boot-up runs (separate from main experiments)
│
├── analysis/                  # Data processing and plotting scripts
│   ├── Data_processing.py     # Cleans raw CSVs, consolidates rows, trims trailing idle
│   ├── build_summary.py       # Aggregates per-run statistics into summary tables
│   ├── plot_tx_violins.py     # Section 3.2 distribution plots
│   ├── plot_overlays.py       # Section 3.1 overlaid current profiles
│   ├── plot_means.py          # Section 3.4 mean consumption profiles with 95% CI
│   ├── plot_efficiency.py     # Sections 3.5–3.8 per-byte efficiency plots
│   ├── plot_skewness.py       # Section 3.3 unified vs isolated skewness plots
│   ├── plot_boot.py           # Section 3.9 boot-up profiles
│   ├── uncertainty.py         # GUM-framework uncertainty propagation
│   └── sample_Rate.py         # Diagnostic for the 5 Hz sample rate issue
│
├── figures/                   # High-resolution outputs (PNG and SVG)
│
├── docs/
│   ├── wiring/                # Wiring diagrams (matching Figures 1–3 in the thesis)
│   └── thesis.pdf             # Full thesis PDF
│
├── requirements.txt
└── README.md
```

## Reproducing an experiment from scratch

The full pipeline goes from flashing firmware to producing the final figures. Here is the order:

### 1. Flash the firmware

Open the Arduino IDE and flash:

- The relevant Pico firmware (`firmware/pico/pico_<method>.ino`) to the Raspberry Pi Pico
- The relevant module firmware (`firmware/<module>/<module>_<method>.ino`) to the wireless module

For the LoRa experiments there is no module firmware to flash. The RN2903 is controlled directly from the host using its built-in command set, so `host/run_experiment.py` issues the `radio tx` commands itself.

### 2. Calibrate

Before any data collection, run the calibration scripts to characterise your specific setup:

```bash
python host/calibrate_shunt.py       # 10-minute resistance baseline
python host/calibrate_supply.py      # 10-minute USB supply voltage baseline
python host/calibrate_offset.py      # Short-circuit zero-offset test
```

These write to `data/calibration/`. The values are read by `analysis/uncertainty.py` and propagated through every downstream calculation, so do not skip this step if you swap any hardware. Note also that the HMC8012 datasheet specifies a 90-minute warm-up for rated accuracy. The original runs used 30 minutes, which appeared sufficient based on baseline stability tests, but if you want full datasheet accuracy give it the full 90.

### 3. Run an experiment

```bash
python host/run_experiment.py --module ble --method chunk --runs 30
```

Flags:
- `--module {wifi,ble,lora}` selects which module is connected
- `--method {full,chunk,byte}` selects the host-to-module delivery strategy
- `--runs N` sets the number of runs (default 30 to match the thesis)
- `--output PATH` overrides the default `data/raw/<module>/<method>/` location

Each run produces one CSV containing the timestamp, shunt voltage, and phase label (`Baseline`, `Tx`, or `Idle`) for every measurement. Failed runs (where memory allocation fails) are marked with a `<module>_malloc_fail` row at the end of the Tx phase and excluded automatically during processing.

A single run is capped at roughly 15 minutes. With 30 runs, the byte-by-byte experiments take several hours, so plan accordingly.

### 4. Process the raw data

```bash
python analysis/Data_processing.py --input data/raw/ble/chunk/ --output data/processed/ble/chunk/
```

This script:
- Filters out failed runs
- Moves erroneous voltage values into a separate `# OVERVIEW` block
- Adds a `# RESULTS` section summarising each phase
- Consolidates sequential rows with identical voltage and phase into single entries with start and end timestamps (this is a lossless compression that significantly speeds up downstream analysis)
- Trims trailing idle phases following the final successful transmission

### 5. Generate figures

Each plot script reads from `data/processed/` and writes to `figures/`:

```bash
python analysis/plot_overlays.py        # Section 3.1
python analysis/plot_tx_violins.py      # Section 3.2
python analysis/plot_skewness.py        # Section 3.3
python analysis/plot_means.py           # Section 3.4
python analysis/plot_efficiency.py      # Sections 3.5–3.8
python analysis/plot_boot.py            # Section 3.9
python analysis/build_summary.py        # Tables 3, 8, 9, 10
```

Or run all of them:

```bash
python analysis/run_all_plots.py
```

## Understanding the data format

Each raw CSV looks roughly like this:

```
# METER
timestamp,V_shunt,phase
2025-08-14T13:42:01.124,0.0921,Baseline
2025-08-14T13:42:01.328,0.0921,Baseline
...
2025-08-14T13:42:06.140,0.1043,Tx_1
2025-08-14T13:42:06.345,0.1052,Tx_1
...
2025-08-14T13:42:07.140,0.0935,Idle
...
```

After processing, consolidated rows have both a `t_start` and `t_end`:

```
t_start,t_end,V_shunt,phase
2025-08-14T13:42:01.124,2025-08-14T13:42:06.135,0.0921,Baseline
2025-08-14T13:42:06.140,2025-08-14T13:42:07.135,0.1043,Tx_1
...
```

Phase labels follow the pattern `Tx_<payload_size_bytes>` for transmission phases. The baseline phase is always the first 5 seconds of a run, and `Idle` is the 1-second gap between transmissions.

### Converting voltage to current and power

The conversion uses Ohm's law with the calibrated shunt resistance, supply voltage, and zero-offset:

```
I = (V_shunt - V_offset) / R_mean
P = I × V_supply
```

The calibration values from the original runs (in `data/calibration/`) were:

| Metric | Mean | Std. Dev. | Spread |
|---|---|---|---|
| Shunt resistance | 1.134584 Ω | 1.45 × 10⁻³ | 8.67 × 10⁻³ |
| Supply voltage | 5.020379 V | 3.56 × 10⁻⁴ | 1.67 × 10⁻³ |
| Voltage offset | −2.18 × 10⁻⁶ V | 1.70 × 10⁻⁶ | 8.70 × 10⁻⁶ |

Uncertainty propagation follows the GUM framework (Type A + Type B + zero-offset). See `analysis/uncertainty.py` for the implementation and Section 2.6 of the thesis for the derivation.

## Known limitations and caveats

A few things worth knowing if you build on this work:

- **Effective sample rate is ~5 Hz, not 200 Hz.** The HMC8012 was nominally configured at 200 SPS, but the way the Python script issues `READ?` commands resets the meter's internal state on every poll, effectively capping the loop at roughly 5 Hz. Short transmissions at small payloads are therefore undersampled. The `sample_Rate.py` script confirms this across all runs. If you reproduce the work, either use an oscilloscope or reconfigure the meter to stream into its internal buffer instead of using blocking per-sample queries. See Section 4.4 of the thesis for the full discussion.
- **Wi-Fi full-payload caps at 64 KiB**, not the 256 KiB tested, due to heap fragmentation across successive transfers. The chunk method reached 512 KiB without this issue.
- **LoRa full-payload caps at 220 bytes** based on an initial misreading of the RN2903 datasheet. The actual per-packet maximum is 255 bytes. Noticed too late to re-run.
- **Transmission distance is not controlled.** Wi-Fi and BLE were ~30 cm from the host, LoRa modules were ~2 m apart. Distance was not treated as an independent variable.
- **No reception (Rx) measurements.** Only transmission energy is characterised. Real IoT applications typically involve bidirectional traffic.
- **Single device per module.** Findings may not generalise to other ESP32, nRF, or LoRa hardware. Hardware variability between identical units is also not characterised.

## Citing this work

If you use the data, code, or methodology from this repository, please cite the thesis.

## Acknowledgements

This research was conducted in collaboration with the EU-funded MISO project (Grant No. 101086541) and the Arctic Green Computing group at UiT (The Arctic University of Norway).

This README was drafted with the assistance of an AI language model (Claude by Anthropic), using the contents of the thesis as input. The draft was then reviewed and edited before publication.

## License

Code is released under the MIT License (see `LICENSE`). Data is released under CC-BY 4.0, meaning you are free to use it with attribution.
