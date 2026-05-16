# ptouch library — entry points used by First-Print

Version: `ptouch>=1.1.0` (pinned in pyproject.toml).

## Classes we use

- `ptouch.ConnectionNetwork(host: str, port: int = 9100, timeout: float = 5.0)`
- `ptouch.PTP750W(connection, use_compression=None, high_resolution=None)` (subclass of `LabelPrinter`)
- `ptouch.Label(image: PIL.Image.Image, tape: type[Tape] | Tape)`
- Tape classes: `ptouch.LaminatedTape4mm` ... `ptouch.LaminatedTape24mm` (size suffix matches `tape_mm`).
- Print method: `LabelPrinter.print(label, margin_mm=None, high_resolution=None, feed=True, auto_cut=None, half_cut=None)`

## ptouch exception hierarchy (caught by PTouchBackend and rewrapped)

- `ptouch.PrinterConnectionError` — generic connection problem
- `ptouch.PrinterNetworkError` — network-layer failure (DNS, refused)
- `ptouch.PrinterTimeoutError` — TCP timeout
- `ptouch.PrinterWriteError` — write failure mid-print
- `ptouch.PrinterPermissionError` — USB-permission issue (n/a for network)
- `ptouch.PrinterNotFoundError` — host unreachable

## Status query — NOT exposed by ptouch

`LabelPrinter` has only `_cmd_print_information` (private, and a send command). There is no `get_status` / `query_status` method. We implement status query ourselves: ESC i S over a raw asyncio socket, see Brother Raster Command Reference (PT-Series).
