// Scene format strategies (AP-79). Each storytelling format is an independent strategy with the same interface:
//   sequence(scene) -> timing;  compile(context) -> world layers, screen layers, sfx, checks.
// "text-chat" (AP-79) and "face-to-face" (AP-85 P1) are implemented. The others are registered as planned designs so stories can name them
// and get a clear "not implemented yet" error instead of silent fallback. Multi-scene stories are handled
// by the story compiler (one renderer shot per scene), not by a format.
import {textChat} from './text-chat.mjs';
import {faceToFace} from './face-to-face.mjs';

const planned = (id, description, inputs) => ({
  id, implemented: false, description, plannedInputs: inputs,
  sequence() { throw new Error(`Scene format "${id}" is designed but not implemented yet (AP-79 foundation only)`); },
  async compile() { throw new Error(`Scene format "${id}" is designed but not implemented yet (AP-79 foundation only)`); },
});

export const FORMATS = Object.freeze({
  'text-chat': textChat,
  'phone-call': planned('phone-call', 'Phone call: one or both callers on screen, two-sided dialogue, call UI.', ['cast (1–2)', 'lines with speaker and audio', 'call header']),
  'split-screen': planned('split-screen', 'Split screen: two locations visible at once, each with its own environment, cast and camera.', ['panels [{environment, cast, camera}]', 'lines']),
  'face-to-face': faceToFace,
  'solo': planned('solo', 'Solo scene: one character, monologue, reactions or physical comedy.', ['cast (1)', 'lines or captions', 'pose timeline']),
});

export function formatFor(id) {
  const f = FORMATS[id];
  if (!f) throw new Error(`Unknown scene format "${id}" (known: ${Object.keys(FORMATS).join(', ')})`);
  return f;
}
