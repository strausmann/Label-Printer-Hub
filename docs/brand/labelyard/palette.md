# Labelyard palette (blue-4, string L)

## Brand values

| Role | Light | Dark |
|---|---|---|
| Tile (navy) | `#0B1429` | `#22366A` |
| Tag (royal / sky blue) | `#3F73EC` | `#7FA3F5` |
| String L | `#FDFCF9` | `#101B38` |
| Eyelet (hole, = tile) | `#0B1429` | `#22366A` |
| Wordmark | `#1F1D1A` | `#F1EEE7` |
| Subtitle | `#6B655A` | `#958E81` |
| Social card ground | `#0B1429` | - |

Changed against blue-4 in the comparison: the light tile went from `#14213F` to `#0B1429` and the tag from `#3568E0` to `#3F73EC`.

## Contrast (WCAG 2.x)

| Pair | Foreground | Background | Ratio |
|---|---|---|---|
| Light: tag vs tile | #3F73EC | #0B1429 | 4.3:1 (was 3.2:1) |
| Light: L vs tag | #FDFCF9 | #3F73EC | 4.2:1 (was 4.9:1) |
| Light: tile vs page | #0B1429 | #F6F4EF | 16.7:1 |
| Dark: tag vs tile | #7FA3F5 | #22366A | 4.7:1 |
| Dark: L vs tag | #101B38 | #7FA3F5 | 6.8:1 |
| Dark: tile vs page | #22366A | #171614 | 1.6:1 |
| Wordmark light vs page | #1F1D1A | #F6F4EF | 15.3:1 |
| Wordmark dark vs page | #F1EEE7 | #171614 | 15.6:1 |
| Subtitle light vs page | #6B655A | #F6F4EF | 5.3:1 |
| Subtitle dark vs page | #958E81 | #171614 | 5.6:1 |

The two light-mode figures trade off against each other: a lighter tag helps against the tile and hurts against the L, so both sit just above 4:1. The dark tile against the dark page is only 1.6:1, so the dark mark leans on the tag (7.3:1 against the page) to carry the shape.

## Proposal: mapping to UI tokens if blue becomes the primary UI accent
Not decided by the maintainer. Today's tokens: `--accent` amber `#D4912A` / `#E2A445`, `--link` stamp `#2F4E8F` / `#8FAEE6`.

The logo tag blue `#3F73EC` is too light for white button text (4.3:1), so the UI would use a darker step of the same hue.

| Token | Light | Dark | Note |
|---|---|---|---|
| `--accent` | `#2D5BD0` | `#7FA3F5` | white on light accent 6.0:1; dark accent on page 7.3:1 |
| `--accent-ink` (text on accent) | `#FFFFFF` | `#0B1429` | 6.0:1 and 7.4:1 |
| `--accent-soft` | `#E3EBFB` | `#14203F` | selection and hover fills |
| `--link` | `#2D5BD0` | `#7FA3F5` | replaces stamp blue; 5.4:1 on `#F6F4EF`, 6.7:1 on `#201E1B` |
| `--focus-ring` | `#2D5BD0` | `#7FA3F5` | unchanged mechanism |
| amber (`#D4912A` / `#E2A445`) | keep | keep | demoted to warning and highlight; as text on paper it is only 2.4:1, so never as small text there |
| `--warn` | `#B5651B` | `#E39A4F` | unchanged |

If the maintainer keeps amber as the UI accent, the blue stays logo-only and none of this applies.
