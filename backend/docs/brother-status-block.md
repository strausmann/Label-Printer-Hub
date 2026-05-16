# Brother PT-Series status block (ESC i S)

Source: Brother Raster Command Reference, PT-Series.

## Request

3 bytes sent on TCP port 9100:

```
0x1B 0x69 0x53
```

(ASCII: ESC, 'i', 'S')

## Reply

32 bytes received. Offsets are 0-based, little-endian where applicable:

| Offset | Length | Field |
|---|---|---|
| 0 | 1 | Print head mark (0x80) |
| 1 | 1 | Size of reply (0x20 = 32) |
| 2 | 1 | Brother code (0x42 'B') |
| 3 | 1 | Series code |
| 4 | 1 | Model code |
| 5 | 1 | Country (0x30 = '0') |
| 6 | 1 | Reserved |
| 7 | 1 | Reserved |
| 8 | 1 | Error information 1 (bit 0=no media, 1=end of media, 2=cutter jam, 3=printer in use, 4=printer turned off) |
| 9 | 1 | Error information 2 (bit 0=replace media, 4=cover open, 5=overheating) |
| 10 | 1 | Media width (mm) |
| 11 | 1 | Media type (0x00 none, 0x01 laminated, 0x03 non-laminated, 0x11 heat-shrink-2:1, ...) |
| 12 | 1 | Number of colors (always 1 for PT-Series) |
| 13 | 1 | Fonts |
| 14 | 1 | Japanese fonts |
| 15 | 1 | Mode |
| 16 | 1 | Density |
| 17 | 1 | Media length (mm; 0 for tape) |
| 18 | 1 | Status type (0x00 reply-to-status, 0x01 phase-change, 0x02 error, 0x05 notification, 0x06 phase-change-notification) |
| 19 | 1 | Phase type (0x00 receiving / 0x01 printing) |
| 20 | 2 | Phase number high/low |
| 22 | 1 | Notification number |
| 23 | 1 | Expansion area length |
| 24 | 1 | Tape colour information |
| 25 | 1 | Text colour information |
| 26 | 4 | Hardware settings |
| 30 | 2 | Reserved |

## Error decoding

`tape_empty` ← bit 0 OR bit 1 of byte 8 set
`cover_open` ← bit 4 of byte 9 set
`error_flags` ← raw value of (byte8, byte9) packed
`loaded_tape_mm` ← byte 10 (0 → no tape inserted)
