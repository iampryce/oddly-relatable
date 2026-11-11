// Silent PCM WAV writer. The renderer requires an audio track whose length defines the video length;
// a text-only conversation short has no narration, so we supply exact-length silence.
import fs from 'node:fs';

export function silentWav(file, seconds, rate = 48000) {
  if (!Number.isFinite(seconds) || seconds <= 0) throw new Error('silentWav: positive duration required');
  const n = Math.round(seconds * rate);
  const bytes = Buffer.alloc(44 + n * 2);
  bytes.write('RIFF', 0); bytes.writeUInt32LE(bytes.length - 8, 4); bytes.write('WAVEfmt ', 8);
  bytes.writeUInt32LE(16, 16); bytes.writeUInt16LE(1, 20); bytes.writeUInt16LE(1, 22);
  bytes.writeUInt32LE(rate, 24); bytes.writeUInt32LE(rate * 2, 28); bytes.writeUInt16LE(2, 32); bytes.writeUInt16LE(16, 34);
  bytes.write('data', 36); bytes.writeUInt32LE(n * 2, 40);
  fs.writeFileSync(file, bytes);
  return {file, samples: n, seconds: n / rate};
}
