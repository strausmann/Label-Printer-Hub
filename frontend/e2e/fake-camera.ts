import { mkdirSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import { inflateSync } from "node:zlib";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { prepareZXingModule, writeBarcode } from "zxing-wasm/writer";

/**
 * Test pictures for Chromium's fake camera (`--use-file-for-fake-video-capture`): a code on a
 * white sheet, written as a YUV4MPEG2 file the browser loops. Nothing here is a real label:
 * the texts use the reserved host `hub.example.invalid`.
 */

// The library would fetch its WebAssembly from a CDN by default; read it from node_modules instead.
const wasmBinary = readFileSync(createRequire(import.meta.url).resolve("zxing-wasm/writer/zxing_writer.wasm"));
const writerReady = prepareZXingModule({ overrides: { wasmBinary }, fireImmediately: true });

const WIDTH = 640;
const HEIGHT = 480;
const FRAMES = 15;

interface Gray {
  width: number;
  height: number;
  pixels: Uint8Array;
}

/** Reads the 8-bit grey PNG the barcode writer produces (no interlacing, filters 0 to 4). */
function decodeGrayPng(png: Uint8Array): Gray {
  const view = Buffer.from(png);
  let offset = 8;
  let width = 0;
  let height = 0;
  const parts: Buffer[] = [];
  while (offset < view.length) {
    const length = view.readUInt32BE(offset);
    const type = view.toString("ascii", offset + 4, offset + 8);
    const data = view.subarray(offset + 8, offset + 8 + length);
    if (type === "IHDR") {
      width = data.readUInt32BE(0);
      height = data.readUInt32BE(4);
      if (data[8] !== 8 || data[9] !== 0 || data[12] !== 0) throw new Error(`unexpected PNG: depth ${data[8]}, colour type ${data[9]}`);
    } else if (type === "IDAT") parts.push(Buffer.from(data));
    offset += 12 + length;
  }
  const raw = inflateSync(Buffer.concat(parts));
  const pixels = new Uint8Array(width * height);
  for (let y = 0; y < height; y++) {
    const filter = raw[y * (width + 1)]!;
    for (let x = 0; x < width; x++) {
      const byte = raw[y * (width + 1) + 1 + x]!;
      const left = x > 0 ? pixels[y * width + x - 1]! : 0;
      const up = y > 0 ? pixels[(y - 1) * width + x]! : 0;
      const upLeft = x > 0 && y > 0 ? pixels[(y - 1) * width + x - 1]! : 0;
      let predictor = 0;
      if (filter === 1) predictor = left;
      else if (filter === 2) predictor = up;
      else if (filter === 3) predictor = (left + up) >> 1;
      else if (filter === 4) {
        const p = left + up - upLeft;
        const [pa, pb, pc] = [Math.abs(p - left), Math.abs(p - up), Math.abs(p - upLeft)];
        predictor = pa <= pb && pa <= pc ? left : pb <= pc ? up : upLeft;
      }
      pixels[y * width + x] = (byte + predictor) & 255;
    }
  }
  return { width, height, pixels };
}

/** Writes `text` as a code of `format`, scaled to fill most of a 640x480 white frame, to `file`. */
export async function writeFakeCameraFile(file: string, text: string, format: "QRCode" | "DataMatrix"): Promise<void> {
  await writerReady;
  const result = await writeBarcode(text, { format, scale: 4, withQuietZones: true });
  if (result.error || !result.image) throw new Error(`could not draw ${format}: ${result.error}`);
  const code = decodeGrayPng(new Uint8Array(await result.image.arrayBuffer()));

  const target = Math.floor(HEIGHT * 0.9);
  const side = Math.floor(target / Math.max(code.width, code.height)) * Math.max(code.width, code.height);
  const zoom = side / Math.max(code.width, code.height);
  const left = Math.floor((WIDTH - code.width * zoom) / 2);
  const top = Math.floor((HEIGHT - code.height * zoom) / 2);

  const luma = new Uint8Array(WIDTH * HEIGHT).fill(255);
  for (let y = 0; y < code.height * zoom; y++) {
    for (let x = 0; x < code.width * zoom; x++) {
      luma[(top + y) * WIDTH + left + x] = code.pixels[Math.floor(y / zoom) * code.width + Math.floor(x / zoom)]!;
    }
  }
  const chroma = new Uint8Array((WIDTH / 2) * (HEIGHT / 2)).fill(128);
  const header = Buffer.from(`YUV4MPEG2 W${WIDTH} H${HEIGHT} F30:1 Ip A1:1 C420jpeg\n`, "ascii");
  const frame = Buffer.concat([Buffer.from("FRAME\n", "ascii"), luma, chroma, chroma]);
  mkdirSync(dirname(file), { recursive: true });
  writeFileSync(file, Buffer.concat([header, ...Array.from({ length: FRAMES }, () => frame)]));
}
