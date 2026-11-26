// The guided generation page: the steps in order, in plain English, and small pure helpers (node --test).
// The API reports each step's status and cost; the words live here.

export type StepStatus = 'not_started' | 'running' | 'needs_approval' | 'done';

export type GuideStep = {
  key: string;
  title: string;
  what: string;       // what this step does
  why: string;
  before: string;     // what you need before starting
  help: string[];     // the help panel, one short instruction at a time
  available: boolean; // false: not in the dashboard yet (no buttons)
};

export const STEPS: GuideStep[] = [
  {key: 'upload', title: 'Upload your files', available: true,
    what: 'You add three files: the script, your voice recording and the reference video.',
    why: 'Everything after this is built from these files. The recording sets the timing of every shot.',
    before: 'The script, the voice recording (audio) and the reference video (MP4, MOV or WebM, up to 250 MB).',
    help: ['Open the episode page and add the script or the voice recording if they are missing.',
      'Come back here and choose the reference video with the button below.',
      'The reference video stays private. Only the acting analysis looks at it.',
      'When all three show a green tick, go to step 2.']},
  {key: 'acting', title: 'Acting analysis', available: true,
    what: 'Gemini watches the reference video and writes down how each person acts: faces, eyes, head, hands and timing.',
    why: 'Our characters copy the acting and the timing, not the look. These notes feed the prompts in step 3.',
    before: 'The reference video (step 1) and the Gemini key in Settings. A storyboard helps: its shots are used.',
    help: ['Check the price on the button. It is the most this can cost.',
      'Only tick "Use the free tier" if you accept that Google may use the video to improve its models.',
      'Click the button and confirm. It takes a few minutes.',
      'Read the notes and look at the key frames next to each shot.',
      'If they look right, click "These notes look right".']},
  {key: 'prompts', title: 'Prompt writing', available: true,
    what: 'ChatGPT writes each picture or video prompt from your notes, the character and the house style.',
    why: 'Every prompt is written first and checked by you before anything is drawn or animated.',
    before: 'Your notes for the shot. For a character prompt, the character. The OpenAI key in Settings.',
    help: ['Choose what you are making: a character master, a shot still, a face change or a movement.',
      'Pick the character and the shot if they apply. The acting notes for that shot are added for you.',
      'Write a few words about the shot, then check the price and click "Write prompt".',
      'Read the prompt. Change any words you like.',
      'Click "Use this prompt" when it is right.']},
  {key: 'masters', title: 'Character masters', available: true,
    what: 'Each character gets one approved master picture, drawn from the house style and the character description.',
    why: 'Every later picture of a character is made from its master, so the character never changes.',
    before: 'Each character has a written look (name, one accessory, expression) and a style reference in Settings.',
    help: ['Open the Characters page.',
      'On each character card, click "Generate master" and confirm the price.',
      'Look at the candidates and approve the one that is right.',
      'Come back here when every character has a master.']},
  {key: 'sets', title: 'Sets and seating masters', available: true,
    what: 'One straight-on picture for each wall of the room, then one seating picture for each side of the room with all its characters in place.',
    why: 'Every shot is then cut from these pictures, so the room and the seats stay the same in every shot.',
    before: 'Approved character masters (step 4) and the storyboard with its shots.',
    help: ['The image model cannot turn the camera around a room. Asking it to "rotate" a room gives a new, different room.',
      'So each wall is described and drawn straight-on, as if you stand facing it.',
      'Open the storyboard and make the seating still for each side of the room.',
      'Approve each picture when the room and the seats are right.']},
  {key: 'closeups', title: 'Close-ups', available: false,
    what: 'Close-ups are cut by zooming into the approved seating picture. No new background is drawn.',
    why: 'Zooming keeps the room, the light and the characters exactly the same as in the wide shot.',
    before: 'Approved seating pictures (step 5).',
    help: ['This step is coming next. For now, nothing to do here.']},
  {key: 'faces', title: 'Expressions, mouths and blinks', available: false,
    what: 'Only the face changes: eyes, eyebrows and mouth are redrawn inside a small mask on the rented GPU.',
    why: 'The rest of the picture stays exactly as approved, so the character cannot drift.',
    before: 'Approved stills and the approved face prompts (step 3).',
    help: ['This step is not in the dashboard yet.']},
  {key: 'movement', title: 'Movement', available: false,
    what: 'Characters move from one approved pose to the next, on the rented GPU.',
    why: 'Moving between two approved pictures keeps the start and the end of every move under your control.',
    before: 'Approved stills and the approved movement prompts (step 3).',
    help: ['This step is not in the dashboard yet.']},
  {key: 'talking', title: 'Talking shots', available: true,
    what: 'Wan 2.2 Speech-to-Video moves the speaker’s mouth to your recording, on a rented GPU, from the approved still.',
    why: 'Your recording is the voice. The picture has to match it, and the character must stay exactly as approved.',
    before: 'Approved stills (step 5), the transcript of your recording, Settings › GPU worker set to Rented with the RunPod key. The reference video (step 1) adds the actor’s head movement.',
    help: ['Each row is a shot where the person speaking is on screen. Check the red dot sits on the speaker’s head; click the still to move it.',
      'Play the voice-only audio: only the speaker’s words are heard. Laughs and other voices are muted so they do not move the mouth.',
      'Read the prompt. Click "Write with GPT" for a prompt from the acting notes, or keep the template. Edit it and click "Save prompt".',
      'The movement guide copies only the actor’s head movement as a stick skeleton. If the wrong person is followed, click "Which person is the actor?" and pick a frame that shows the actor.',
      'Click "Render all talking shots" (or one shot’s Render) and confirm the price. Uses Wan 2.2 Speech-to-Video; about 11 minutes per 5 seconds of shot, plus about 10 minutes to start the GPU.',
      'Watch each result. Click Approve on the one you want. Nothing is approved for you.']},
  {key: 'quality', title: 'Quality check', available: false,
    what: 'Gemini watches each finished clip and points out problems, such as a changed face or a wrong hand.',
    why: 'It catches problems before you spend time on the final review.',
    before: 'Finished clips.',
    help: ['This step is not in the dashboard yet.']},
  {key: 'assembly', title: 'Assembly and your review', available: false,
    what: 'The clips are joined on your recording, and you watch the whole episode.',
    why: 'Nothing is published without your approval.',
    before: 'Approved clips for every shot.',
    help: ['This step is not in the dashboard yet.']},
];

export const STATUS_TEXT: Record<StepStatus, string> = {
  not_started: 'Not started', running: 'Running', needs_approval: 'Needs your approval', done: 'Done',
};

export const STATUS_TONE: Record<StepStatus, string> = {
  not_started: '', running: 'busy', needs_approval: 'warn', done: 'good',
};

export function statusOf(api: any, key: string): StepStatus {
  const s = api?.steps?.[key]?.status;
  return s === 'running' || s === 'needs_approval' || s === 'done' ? s : 'not_started';
}

// The step to help with first: the first available step that is not done.
export function currentStep(api: any): number {
  const i = STEPS.findIndex(s => s.available && statusOf(api, s.key) !== 'done');
  return i < 0 ? STEPS.length - 1 : i;
}

// The help panel walks one instruction at a time across all steps: [step, line] -> the next or previous position.
export function moveHelp(pos: [number, number], dir: 1 | -1): [number, number] {
  const [s, l] = pos;
  if (dir === 1) {
    if (l + 1 < STEPS[s].help.length) return [s, l + 1];
    return s + 1 < STEPS.length ? [s + 1, 0] : pos;
  }
  if (l > 0) return [s, l - 1];
  return s > 0 ? [s - 1, STEPS[s - 1].help.length - 1] : pos;
}

// "about $0.21, at most $1.10" for any estimate with usd_typical / usd_max, or an image cost's own label
export function costText(c: any): string {
  if (!c) return '';
  if (typeof c.label === 'string' && c.usd_max == null) return c.label;
  const f = (x: number) => `$${x < 0.01 && x > 0 ? x.toFixed(4) : x.toFixed(2)}`;
  return `about ${f(c.usd_typical)}, at most ${f(c.usd_max)}`;
}

export const KIND_LABEL: Record<string, string> = {
  master: 'Character master', still: 'Shot still', face_edit: 'Face change (face only)', movement: 'Movement',
};
