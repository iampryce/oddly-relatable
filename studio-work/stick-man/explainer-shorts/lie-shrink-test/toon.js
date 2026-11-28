export const INK = "#241726";
export const SKIN = "#ffe2c2";
const WHITE = "#ffffff";
const MOUTH = "#5a1e28";
const TONGUE = "#e86e78";
const SH_SKIN = [
    0.96,
    0.86,
    0.84
];
const SH_CLOTH = [
    0.64,
    0.66,
    0.74
];
const SH_FELT = [
    0.62,
    0.62,
    0.7
];
const rad = (d)=>d * Math.PI / 180;
const clamp = (x, a, b)=>Math.max(a, Math.min(b, x));
export const mul = (c, m)=>{
    const n = parseInt(c.slice(1), 16);
    const ch = (v, k)=>Math.min(255, Math.round(v * k)).toString(16).padStart(2, "0");
    return `#${ch(n >> 16 & 255, m[0])}${ch(n >> 8 & 255, m[1])}${ch(n & 255, m[2])}`;
};
export const shade = (c, k)=>mul(c, [
        k,
        k,
        k
    ]);
export const mix = (a, b, t)=>{
    const A = parseInt(a.slice(1), 16), B = parseInt(b.slice(1), 16);
    const ch = (s)=>Math.round((A >> s & 255) * (1 - t) + (B >> s & 255) * t).toString(16).padStart(2, "0");
    return `#${ch(16)}${ch(8)}${ch(0)}`;
};
const rnd = (seed, k)=>{
    const x = Math.sin(seed * 127.1 + k * 311.7) * 43758.5453;
    return x - Math.floor(x);
};
const rotPts = (pts, a, cx, cy)=>pts.map(([x, y])=>[
            cx + (x - cx) * Math.cos(a) - (y - cy) * Math.sin(a),
            cy + (x - cx) * Math.sin(a) + (y - cy) * Math.cos(a)
        ]);
const rotAbout = (q, a, c)=>rotPts([
        q
    ], a, c[0], c[1])[0];
const lerp2 = (a, b, t)=>[
        a[0] + (b[0] - a[0]) * t,
        a[1] + (b[1] - a[1]) * t
    ];
const curve = (a, k, b, n = 10)=>{
    const c = [
        2 * k[0] - (a[0] + b[0]) / 2,
        2 * k[1] - (a[1] + b[1]) / 2
    ], out = [];
    for(let i = 0; i <= n; i++){
        const t = i / n, s = 1 - t;
        out.push([
            s * s * a[0] + 2 * s * t * c[0] + t * t * b[0],
            s * s * a[1] + 2 * s * t * c[1] + t * t * b[1]
        ]);
    }
    return out;
};
export const RIFLEMAN = {
    jacket: "#357650",
    pants: "#3d4440",
    boots: INK,
    hat: "shako",
    belt: "#f1efe6",
    buttons: "#d9dde0",
    rifle: true
};
export const OFFICER = {
    ...RIFLEMAN,
    hat: "shako_tall",
    buttons: "#e8c45a",
    sash: "#c0353a",
    sword: true,
    moustache: "#4a3020",
    rifle: false,
    belt: null,
    build: "stout"
};
export const KID = {
    jacket: "#f08a2c",
    pants: "#3b5b9a",
    boots: "#f4f1ea",
    hat: "cap",
    cap: "#e2453c",
    build: "kid"
};
export const PARENT = {
    jacket: "#7b5ac9",
    pants: "#3b3f52",
    boots: "#5a3b2a",
    hat: "hair",
    hair: "#5a3b2a"
};
export const SKINS = [
    SKIN,
    "#f5c9a0",
    "#ecd0b6",
    "#c99067"
];
export const soldier = (v = 0, extra = {})=>{
    const o = {
        ...RIFLEMAN,
        skin: SKINS[v % 4]
    };
    if (v % 4 === 1) o.moustache = "#4a3426";
    if (v % 4 === 3) o.moustache = "#2a201a";
    return {
        ...o,
        ...extra
    };
};
export const townsfolk = (v = 0)=>{
    const coats = [
        "#3f6fb5",
        "#8c3b4a",
        "#5d7a3a",
        "#b5653f",
        "#2f5f6a",
        "#7b5ac9"
    ];
    const o = {
        jacket: coats[v % 6],
        pants: "#3b3f52",
        boots: "#4a3426",
        skin: SKINS[v % 4]
    };
    return v % 2 ? {
        ...o,
        hat: "bonnet",
        dress: [
            "#d9a441",
            "#c25a7a",
            "#5a8fc2"
        ][v % 3]
    } : {
        ...o,
        hat: "tophat"
    };
};
export class Pen {
    g;
    ol = 12;
    rot = null;
    constructor(g){
        this.g = g;
    }
    P(x, y) {
        if (!this.rot) return [
            x,
            y
        ];
        const r = this.rot, a = r[0], cx = r[1], cy = r[2], dx = r.length > 3 ? r[3] : 0, dy = r.length > 4 ? r[4] : 0, c = Math.cos(a), s = Math.sin(a);
        return [
            cx + (x - cx) * c - (y - cy) * s + dx,
            cy + (x - cx) * s + (y - cy) * c + dy
        ];
    }
    path(pts, close) {
        const g = this.g;
        g.beginPath();
        pts.forEach((p, i)=>{
            const [x, y] = this.P(p[0], p[1]);
            if (i) g.lineTo(x, y);
            else g.moveTo(x, y);
        });
        if (close) g.closePath();
    }
    poly(pts, fill, ol) {
        const g = this.g, w = ol ?? this.ol;
        this.path(pts, true);
        if (fill) {
            g.fillStyle = fill;
            g.fill();
        }
        if (w) {
            g.lineWidth = w;
            g.strokeStyle = INK;
            g.lineJoin = "round";
            g.stroke();
        }
    }
    ell(cx, cy, rx, ry, fill, ol, a0 = 0, a1 = 360, rot = 0) {
        this.poly(ellPts(cx, cy, rx, ry, a0, a1, rot), fill, ol);
    }
    line(pts, fill, w, ink = true) {
        const g = this.g;
        g.lineCap = "round";
        g.lineJoin = "round";
        if (ink) {
            this.path(pts, false);
            g.strokeStyle = INK;
            g.lineWidth = w + 2 * this.ol * 0.9;
            g.stroke();
        }
        this.path(pts, false);
        g.strokeStyle = fill;
        g.lineWidth = w;
        g.stroke();
    }
    stroke(pts, w, fill = INK) {
        const g = this.g;
        g.lineCap = "round";
        g.lineJoin = "round";
        this.path(pts, false);
        g.strokeStyle = fill;
        g.lineWidth = w;
        g.stroke();
    }
    arc(cx, cy, rx, ry, a0, a1, w, fill = INK) {
        const pts = [];
        for(let i = 0; i <= 24; i++)pts.push([
            cx + rx * Math.cos(rad(a0 + (a1 - a0) * i / 24)),
            cy + ry * Math.sin(rad(a0 + (a1 - a0) * i / 24))
        ]);
        this.stroke(pts, w, fill);
    }
    dot(cx, cy, r, fill = INK) {
        const [x, y] = this.P(cx, cy);
        this.g.beginPath();
        this.g.arc(x, y, r, 0, Math.PI * 2);
        this.g.fillStyle = fill;
        this.g.fill();
    }
    clip(pts, fn) {
        const g = this.g;
        g.save();
        this.path(pts, true);
        g.clip();
        fn();
        g.restore();
    }
    shadedFill(pts, base, shadow, light, R, shift = 0.45, r0 = 1.05, r1 = 1.25) {
        const g = this.g, n = pts.length;
        let cx = 0, cy = 0;
        for (const [x, y] of pts){
            cx += x / n;
            cy += y / n;
        }
        const [gx, gy] = this.P(cx + Math.cos(light) * shift * R, cy + Math.sin(light) * shift * R);
        const gr = g.createRadialGradient(gx, gy, 0, gx, gy, r1 * R);
        gr.addColorStop(0, base);
        gr.addColorStop(r0 / r1, base);
        gr.addColorStop(1, shadow);
        this.path(pts, true);
        g.fillStyle = gr;
        g.fill();
    }
    gradFill(pts, base, shadow, light, flat = 0.22) {
        const g = this.g, dx = Math.cos(light), dy = Math.sin(light), n = pts.length;
        let cx = 0, cy = 0, lo = Infinity, hi = -Infinity;
        for (const [x, y] of pts){
            cx += x / n;
            cy += y / n;
            const d = x * dx + y * dy;
            lo = Math.min(lo, d);
            hi = Math.max(hi, d);
        }
        const dc = cx * dx + cy * dy;
        const [ax, ay] = this.P(cx + dx * (hi - dc), cy + dy * (hi - dc)), [bx, by] = this.P(cx + dx * (lo - dc), cy + dy * (lo - dc));
        const gr = g.createLinearGradient(ax, ay, bx, by);
        gr.addColorStop(0, base);
        gr.addColorStop(flat, base);
        gr.addColorStop(1, shadow);
        this.path(pts, true);
        g.fillStyle = gr;
        g.fill();
    }
    inkRing(pts, w0, thick, k = 0.45, col = INK) {
        const n = pts.length;
        let cx = 0, cy = 0;
        for (const [x, y] of pts){
            cx += x / n;
            cy += y / n;
        }
        const out = [], inn = [];
        pts.forEach((q, i)=>{
            const a = pts[(i + n - 1) % n], b = pts[(i + 1) % n];
            let nx = b[1] - a[1], ny = a[0] - b[0];
            const l = Math.hypot(nx, ny) || 1;
            nx /= l;
            ny /= l;
            const h = 0.5 * w0 * (1 + k * Math.cos(Math.atan2(q[1] - cy, q[0] - cx) - thick));
            out.push([
                q[0] + nx * h,
                q[1] + ny * h
            ]);
            inn.push([
                q[0] - nx * h,
                q[1] - ny * h
            ]);
        });
        const g = this.g;
        const trace = (r)=>{
            r.forEach(([x0, y0], i)=>{
                const [x, y] = this.P(x0, y0);
                if (i) g.lineTo(x, y);
                else g.moveTo(x, y);
            });
            g.closePath();
        };
        g.beginPath();
        trace(out);
        trace(inn.reverse());
        g.fillStyle = col;
        g.fill("evenodd");
    }
    band(pts, fill, w, rim, cap = "butt") {
        const g = this.g;
        g.lineCap = cap;
        g.lineJoin = "round";
        this.path(pts, false);
        g.strokeStyle = INK;
        g.lineWidth = w + 2 * rim;
        g.stroke();
        this.path(pts, false);
        g.strokeStyle = fill;
        g.lineWidth = w;
        g.stroke();
        g.lineCap = "round";
    }
}
const ellPts = (cx, cy, rx, ry, a0 = 0, a1 = 360, rot = 0, n = 48)=>{
    const r = rad(rot), pts = [];
    for(let i = 0; i <= n; i++){
        const a = rad(a0 + (a1 - a0) * i / n), x = rx * Math.cos(a), y = ry * Math.sin(a);
        pts.push([
            cx + x * Math.cos(r) - y * Math.sin(r),
            cy + x * Math.sin(r) + y * Math.cos(r)
        ]);
    }
    return pts;
};
const rrect = (x0, y0, x1, y1, r, n = 8)=>{
    const pts = [];
    for (const [cx, cy, a] of [
        [
            x1 - r,
            y0 + r,
            -90
        ],
        [
            x1 - r,
            y1 - r,
            0
        ],
        [
            x0 + r,
            y1 - r,
            90
        ],
        [
            x0 + r,
            y0 + r,
            180
        ]
    ])for(let i = 0; i <= n; i++)pts.push([
        cx + r * Math.cos(rad(a + 90 * i / n)),
        cy + r * Math.sin(rad(a + 90 * i / n))
    ]);
    return pts;
};
const taper = (p, a, b, wa, wb, col = INK)=>{
    const dx = b[0] - a[0], dy = b[1] - a[1], l = Math.hypot(dx, dy) || 1, nx = -dy / l, ny = dx / l;
    p.poly([
        [
            a[0] + nx * wa / 2,
            a[1] + ny * wa / 2
        ],
        [
            b[0] + nx * wb / 2,
            b[1] + ny * wb / 2
        ],
        [
            b[0] - nx * wb / 2,
            b[1] - ny * wb / 2
        ],
        [
            a[0] - nx * wa / 2,
            a[1] - ny * wa / 2
        ]
    ], col, 0);
    p.dot(a[0], a[1], wa / 2, col);
    p.dot(b[0], b[1], wb / 2, col);
};
export const blobPts = (cx, cy, B, n = 72)=>{
    const ph = [
        rnd(B.seed, 11),
        rnd(B.seed, 12),
        rnd(B.seed, 13)
    ].map((v)=>v * Math.PI * 2);
    const pts = [];
    for(let i = 0; i < n; i++){
        const t = i / n * Math.PI * 2, c = Math.cos(t), s = Math.sin(t), e = 2 / (s < 0 ? B.nTop : B.nBot);
        let X = Math.sign(c) * Math.abs(c) ** e;
        const Y = Math.sign(s) * Math.abs(s) ** e;
        X *= (1 + B.egg * Y) * (1 + B.asym * Math.sign(X));
        const r = 1 + B.noise * (Math.cos(2 * t + ph[0]) + 0.7 * Math.cos(3 * t + ph[1]) + 0.5 * Math.cos(4 * t + ph[2]));
        const x = B.a * X * r, y = B.b * Y * r;
        pts.push([
            cx + x * Math.cos(B.rot) - y * Math.sin(B.rot),
            cy + x * Math.sin(B.rot) + y * Math.cos(B.rot)
        ]);
    }
    return pts;
};
export const headBlob = (seed, a = 118, facing = 0)=>({
        a,
        b: a * (0.94 + 0.08 * (rnd(seed, 1) - 0.5)),
        nTop: 1.75 + 0.3 * (rnd(seed, 2) - 0.5),
        nBot: 2.3 + 0.3 * (rnd(seed, 3) - 0.5),
        egg: -0.12 + 0.06 * (rnd(seed, 4) - 0.5),
        asym: (0.06 + 0.04 * rnd(seed, 5)) * (facing || (rnd(seed, 6) < 0.5 ? -1 : 1)),
        rot: rad(8 * (rnd(seed, 7) - 0.5)),
        noise: 0.008,
        seed
    });
export const thickAngle = (light)=>Math.atan2(-Math.sin(light) + 0.8, -Math.cos(light));
const DEF_LIGHT = rad(-120);
const FACE = {
    neutral: {
        eye: [
            "lid",
            "lid"
        ],
        brow: [
            0,
            -1
        ],
        mouth: "dash"
    },
    stern: {
        eye: [
            "lid",
            "lid"
        ],
        brow: [
            3,
            -2
        ],
        mouth: "frown"
    },
    grin: {
        eye: [
            "happy",
            "happy"
        ],
        brow: [
            -3,
            -3
        ],
        mouth: "grin"
    },
    laugh: {
        eye: [
            "squeeze",
            "squeeze"
        ],
        brow: [
            -4,
            -4
        ],
        mouth: "laugh"
    },
    whistle: {
        eye: [
            "dash",
            "dash"
        ],
        brow: [
            -2,
            -4
        ],
        mouth: "o"
    },
    nervous: {
        eye: [
            "small",
            "small"
        ],
        brow: [
            -3,
            2
        ],
        mouth: "wave"
    },
    shock: {
        eye: [
            "shock",
            "shock"
        ],
        brow: [
            -7,
            -6
        ],
        mouth: "O"
    },
    relief: {
        eye: [
            "happy",
            "happy"
        ],
        brow: [
            -2,
            1
        ],
        mouth: "smileWide"
    },
    relief_open: {
        eye: [
            "happy",
            "happy"
        ],
        brow: [
            -2,
            1
        ],
        mouth: "grin"
    },
    dazed: {
        eye: [
            "spiral",
            "spiral"
        ],
        brow: [
            -3,
            2
        ],
        mouth: "wave"
    },
    pained: {
        eye: [
            "squeeze",
            "lid"
        ],
        brow: [
            -3,
            2
        ],
        mouth: "teeth"
    },
    smile: {
        eye: [
            "dot",
            "dot"
        ],
        brow: [
            0,
            -1
        ],
        mouth: "smirk"
    },
    smile_closed: {
        eye: [
            "happy",
            "happy"
        ],
        brow: [
            0,
            -1
        ],
        mouth: "smile"
    },
    lick: {
        eye: [
            "dot",
            "dot"
        ],
        brow: [
            0,
            -1
        ],
        mouth: "lick"
    }
};
const halfLid = (k)=>k === "dot" || k === "small" ? "lid" : k === "lid" ? "slit" : k === "shock" ? "shockHalf" : k;
const eyeKind = (k, lid)=>lid >= 1 && k !== "happy" && k !== "squeeze" && k !== "spiral" ? "dash" : lid > 0 ? halfLid(k) : k;
const lidOf = (b)=>b === true ? 1 : Number(b) || 0;
const eye = (p, kind, x, ey, u, side, look, skin)=>{
    const lx = x + look * 3 * u, lw = 3.8 * u;
    switch(kind){
        case "dot":
            p.ell(lx, ey, 3.8 * u, 5.5 * u, INK, 0);
            break;
        case "small":
            p.ell(lx, ey, 3 * u, 4.4 * u, INK, 0);
            break;
        case "lid":
            p.ell(lx, ey - u, 7 * u, 6 * u, INK, 0, 0, 180);
            p.stroke([
                [
                    x - 9 * u,
                    ey - u
                ],
                [
                    x + 9 * u,
                    ey - u
                ]
            ], lw);
            break;
        case "slit":
            p.ell(lx, ey, 7 * u, 2.6 * u, INK, 0, 0, 180);
            p.stroke([
                [
                    x - 9 * u,
                    ey
                ],
                [
                    x + 9 * u,
                    ey
                ]
            ], lw);
            break;
        case "happy":
            p.arc(x, ey + 3 * u, 8 * u, 6 * u, 200, 340, lw);
            break;
        case "dash":
            p.stroke([
                [
                    x - 8.5 * u,
                    ey
                ],
                [
                    x + 8.5 * u,
                    ey
                ]
            ], lw);
            break;
        case "squeeze":
            p.stroke([
                [
                    x + 6 * u * side,
                    ey - 5 * u
                ],
                [
                    x - 6 * u * side,
                    ey
                ],
                [
                    x + 6 * u * side,
                    ey + 5 * u
                ]
            ], lw);
            break;
        case "shock":
        case "shockHalf":
            p.ell(x, ey, 11 * u, 11 * u, WHITE, 2.6 * u);
            p.dot(lx - side * 1.5 * u, ey + 1.5 * u, 3 * u);
            if (kind === "shockHalf") {
                p.ell(x, ey, 11 * u, 11 * u, skin, 0, 180, 360);
                p.stroke([
                    [
                        x - 11 * u,
                        ey
                    ],
                    [
                        x + 11 * u,
                        ey
                    ]
                ], 2.6 * u);
            }
            break;
        default:
            {
                const s = [];
                for(let t = 1; t < 15; t++)s.push([
                    x + Math.cos(t * 0.9) * t * 0.55 * u,
                    ey + Math.sin(t * 0.9) * t * 0.55 * u
                ]);
                p.stroke(s, 2.4 * u);
            }
    }
};
const dmouth = (p, mx, y, rx, ry, u, tongue = false)=>{
    p.ell(mx, y, rx, ry, MOUTH, 0, 0, 180);
    p.clip([
        [
            mx - rx,
            y
        ],
        [
            mx + rx,
            y
        ],
        [
            mx + rx,
            y + 3 * u
        ],
        [
            mx - rx,
            y + 3 * u
        ]
    ], ()=>p.ell(mx, y, rx, ry, WHITE, 0, 0, 180));
    if (tongue) p.ell(mx + 2 * u, y + 0.62 * ry, 0.4 * rx, 0.28 * ry, TONGUE, 0);
    p.ell(mx, y, rx, ry, null, 3 * u, 0, 180);
};
const mouth = (p, kind, mx, my, u, k = 1)=>{
    const mw = 4 * u;
    switch(kind){
        case "dash":
            p.stroke([
                [
                    mx - 5.5 * u * k,
                    my
                ],
                [
                    mx + 5.5 * u * k,
                    my - 0.8 * u
                ]
            ], mw);
            break;
        case "frown":
            p.arc(mx, my + 3 * u, 6.5 * u * k, 3.5 * u, 200, 340, mw);
            break;
        case "smirk":
            p.arc(mx + u, my - 3 * u, 7 * u * k, 4 * u, 10, 150, mw);
            break;
        case "smile":
            p.arc(mx, my - 3 * u, 8 * u * k, 4.5 * u, 20, 160, mw);
            break;
        case "smileWide":
            p.arc(mx, my - 4 * u, 11 * u * k, 6 * u, 15, 165, mw);
            break;
        case "grin":
            dmouth(p, mx, my - u, 12 * u * k, 8 * u, u);
            break;
        case "laugh":
            dmouth(p, mx, my, 16 * u * k, 11 * u, u, true);
            break;
        case "o":
            p.ell(mx + 4 * u, my, 3.5 * u, 4 * u, MOUTH, 2.8 * u);
            break;
        case "O":
            p.ell(mx, my + 2 * u, 9 * u * k, 11 * u, MOUTH, 3.2 * u);
            break;
        case "wave":
            {
                const s = [];
                for(let i = 0; i <= 12; i++)s.push([
                    mx - 9 * u * k + i * 1.5 * u * k,
                    my + 1.5 * u * Math.sin(i * 1.3)
                ]);
                p.stroke(s, 3 * u);
                break;
            }
        case "teeth":
            p.poly([
                [
                    mx - 12 * u * k,
                    my - 4 * u
                ],
                [
                    mx + 12 * u * k,
                    my - 4 * u
                ],
                [
                    mx + 11 * u * k,
                    my + 4 * u
                ],
                [
                    mx - 11 * u * k,
                    my + 4 * u
                ]
            ], WHITE, 3 * u);
            for (const j of [
                -1,
                0,
                1
            ])p.stroke([
                [
                    mx + j * 6 * u * k,
                    my - 4 * u
                ],
                [
                    mx + j * 6 * u * k,
                    my + 4 * u
                ]
            ], 1.5 * u);
            break;
        case "lick":
            p.arc(mx, my - 3 * u, 8 * u * k, 4.5 * u, 20, 160, mw);
            p.ell(mx + 6 * u * k, my + 3 * u, 3.6 * u, 4.6 * u, TONGUE, 2.4 * u);
            break;
    }
};
const faceFront = (p, cx, cy, W, expr, facing, look, lid, brim, skin, moustache, stout = false)=>{
    const u = W / 100, F = FACE[expr], fx = cx + 7 * u * facing;
    const ex = (F.eye[0] === "shock" ? 12 : 13) * u, ey = cy;
    for (const side of [
        -1,
        1
    ]){
        const x = fx + side * ex;
        const kind = eyeKind(F.eye[(facing ? side === facing : side > 0) ? 1 : 0], lid);
        eye(p, kind, x, ey, u, side, look, skin);
        const [dI, dO] = F.brow, by = ey - (brim ? 17 : 20) * u;
        if (kind === "shock" || kind === "shockHalf") p.arc(x, by - 6 * u, 9 * u, 3 * u, 200, 340, 4 * u);
        else taper(p, [
            x - side * 8.5 * u,
            by + dI * u
        ], [
            x + side * 8.5 * u,
            by + dO * u
        ], 5 * u, 2.5 * u);
    }
    const mx = cx + 8 * u * facing, my = cy + 20 * u;
    mouth(p, F.mouth, mx, my, u);
    if (moustache) for (const s of [
        -1,
        1
    ])taper(p, [
        mx + s * 1.5 * u,
        cy + 12.5 * u
    ], [
        mx + s * (stout ? 19 : 15) * u,
        cy + (stout ? 10.5 : 15) * u
    ], stout ? 5.5 * u : 4.5 * u, 1.6 * u, moustache);
    if (expr === "nervous") p.ell(cx + 40 * u * (facing || 1), cy - 22 * u, 3 * u, 5 * u, "#9fd4ff", 2 * u);
};
const faceSide = (p, hx, hy, W, expr, lid, brim, skin, moustache, stout = false)=>{
    const u = W / 100, F = FACE[expr], ex = hx + 27 * u, ey = hy;
    const kind = eyeKind(F.eye[1], lid);
    eye(p, kind, ex, ey, u, 1, 0.6, skin);
    const by = ey - (brim ? 17 : 20) * u, [dI, dO] = F.brow;
    if (kind === "shock" || kind === "shockHalf") p.arc(ex, by - 6 * u, 9 * u, 3 * u, 200, 340, 4 * u);
    else taper(p, [
        ex + 8 * u,
        by + dI * u
    ], [
        ex - 7 * u,
        by - u + dO * u
    ], 5 * u, 2.5 * u);
    p.stroke([
        [
            hx + 44 * u,
            hy + 4 * u
        ],
        [
            hx + 47.5 * u,
            hy + 9 * u
        ],
        [
            hx + 43 * u,
            hy + 10 * u
        ]
    ], 3 * u);
    mouth(p, F.mouth, hx + 33 * u, hy + 21 * u, u, 0.62);
    if (moustache) taper(p, [
        hx + 41 * u,
        hy + 13.5 * u
    ], [
        hx + 25 * u,
        hy + (stout ? 11.5 : 16) * u
    ], stout ? 5.5 * u : 4.5 * u, 1.6 * u, moustache);
    if (expr === "nervous") p.ell(hx - 30 * u, hy - 24 * u, 3 * u, 5 * u, "#9fd4ff", 2 * u);
};
const BONNET = "#e9cf8f", BONNET_BRIM = "#d6b46a";
const hatBehind = (p, o, H, cx, hc, light, thick, ow, side)=>{
    if (o.hat !== "bonnet") return;
    const bb = blobPts(cx - (side ? 12 : 0) * (H.a / 50), hc - 0.07 * 2 * H.b, {
        ...H,
        a: H.a * 1.17,
        b: H.b * 1.13,
        asym: 0,
        egg: 0.04,
        seed: H.seed + 3
    });
    p.shadedFill(bb, BONNET, mul(BONNET, SH_CLOTH), light, H.a * 1.17);
    p.inkRing(bb, ow * 0.85, thick);
};
const hatOn = (p, o, hp, H, cx, hc, light, seed, facing, side)=>{
    const W = 2 * H.a, HH = 2 * H.b, u = W / 100, crown = hc - H.b, ow = 0.85 * 5 * u;
    const a = H.rot + rad(4 * (rnd(seed, 20) - 0.5));
    const R = (pts)=>rotPts(pts, a, cx, hc);
    const sag = (yb, wb)=>{
        const base = [];
        for(let i = 0; i <= 12; i++){
            const t = i / 12;
            base.push([
                cx + wb * (2 * t - 1),
                yb + 3 * u * (1 - (2 * t - 1) ** 2)
            ]);
        }
        return base;
    };
    if (o.hat === "shako" || o.hat === "shako_tall") {
        const tall = o.hat === "shako_tall", yb = crown + 0.25 * HH, ht = (tall ? 0.66 : 0.56) * HH, wb = 46 * u, wt = 52 * u;
        const body = R([
            ...sag(yb, wb).reverse(),
            [
                cx - wt,
                yb - ht
            ],
            [
                cx + wt,
                yb - ht
            ]
        ]);
        p.shadedFill(body, "#3a3d47", "#24262d", light, wt, 0.4);
        if (tall) p.clip(body, ()=>p.band(R([
                [
                    cx - wt - 5 * u,
                    yb - ht + 0.07 * HH
                ],
                [
                    cx + wt + 5 * u,
                    yb - ht + 0.07 * HH
                ]
            ]), "#e8c45a", 0.06 * HH, 1.5 * u));
        p.poly(body, null, ow);
        const deg = a * 180 / Math.PI;
        if (side) {
            p.poly(R([
                [
                    cx + 36 * u,
                    yb - 1 * u
                ],
                [
                    cx + 60 * u,
                    yb + 8 * u
                ],
                [
                    cx + 34 * u,
                    yb + 6 * u
                ]
            ]), "#16171b", 2.5 * u);
            const [tx, ty] = R([
                [
                    cx + 24 * u,
                    yb - ht - 6 * u
                ]
            ])[0];
            p.ell(tx, ty, 7 * u, 7 * u, "#2b7a4b", 2.5 * u);
        } else {
            const [px, py] = R([
                [
                    cx + 3 * u * facing,
                    yb + 3 * u
                ]
            ])[0];
            p.ell(px, py, 34 * u, 0.045 * HH, "#16171b", 2.5 * u, 0, 180, deg);
            const [bx, by] = R([
                [
                    cx,
                    yb - 0.45 * ht
                ]
            ])[0];
            p.ell(bx, by, 7 * u, 6 * u, tall ? "#e8c45a" : "#c9ccd2", 2 * u, 0, 360, deg);
            p.arc(bx, by, 3.5 * u, 2.8 * u, 200, 500, 1.6 * u);
            const [tx, ty] = R([
                [
                    cx,
                    yb - ht - 6 * u
                ]
            ])[0];
            p.ell(tx, ty, 7 * u, 7 * u, "#2b7a4b", 2.5 * u);
        }
    } else if (o.hat === "cap" || o.hat === "hair") {
        const cut = crown + (o.hat === "cap" ? 0.3 : 0.42) * HH;
        const keep = (x, y)=>y < cut || side && o.hat === "hair" && x < cx - 6 * u && y < hc + 0.42 * H.b;
        const n = hp.length, startIdx = Math.max(0, hp.findIndex(([x, y], i)=>keep(x, y) && !keep(hp[(i + n - 1) % n][0], hp[(i + n - 1) % n][1])));
        const arc = [
            ...hp.slice(startIdx),
            ...hp.slice(0, startIdx)
        ].filter(([x, y])=>keep(x, y)).map(([x, y])=>[
                cx + (x - cx) * 1.03,
                hc + (y - hc) * 1.03
            ]);
        if (arc.length < 3) return;
        if (o.hat === "hair") {
            const [x0, y0] = arc[arc.length - 1], [x1, y1] = arc[0];
            for(let i = 1; i < 6; i++)arc.push([
                x0 + (x1 - x0) * i / 6,
                y0 + (y1 - y0) * i / 6 + (i % 2 ? 4 * u : 0)
            ]);
        }
        const col = o.hat === "cap" ? o.cap : o.hair;
        p.shadedFill(arc, col, mul(col, SH_FELT), light, H.a, 0.35);
        p.poly(arc, null, ow);
        if (o.hat === "hair") {
            const s = side ? -1 : facing || 1;
            p.stroke([
                [
                    cx + s * 10 * u,
                    cut - 30 * u
                ],
                [
                    cx + s * 2 * u,
                    cut - 12 * u
                ]
            ], 1.2 * u);
        }
        if (o.hat === "cap") {
            const deg = a * 180 / Math.PI;
            if (side) p.poly(R([
                [
                    cx + 40 * u,
                    cut - 2 * u
                ],
                [
                    cx + 74 * u,
                    cut + 4 * u
                ],
                [
                    cx + 40 * u,
                    cut + 6 * u
                ]
            ]), shade(col, 0.8), ow);
            else {
                const s = facing || (rnd(seed, 21) < 0.5 ? -1 : 1), [px, py] = R([
                    [
                        cx + s * 4 * u,
                        cut + 1.5 * u
                    ]
                ])[0];
                p.ell(px, py, 32 * u, 0.06 * HH, shade(col, 0.8), ow, 0, 180, deg);
            }
        }
    } else if (o.hat === "tophat") {
        const yb = crown + 0.22 * HH, ht = 0.8 * HH, wb = 0.31 * W, wt = 0.33 * W, col = "#2e2a36";
        const body = R([
            ...sag(yb, wb).reverse(),
            [
                cx - wt,
                yb - ht
            ],
            [
                cx + wt,
                yb - ht
            ]
        ]);
        p.shadedFill(body, col, mul(col, SH_FELT), light, wt, 0.4);
        p.clip(body, ()=>p.band(R([
                [
                    cx - wt - 4 * u,
                    yb - 0.13 * HH
                ],
                [
                    cx + wt + 4 * u,
                    yb - 0.13 * HH
                ]
            ]), shade(o.jacket, 0.9), 0.14 * HH, 0.8 * u));
        p.poly(body, null, ow);
        const [bx, by] = R([
            [
                cx,
                yb + 1 * u
            ]
        ])[0];
        p.ell(bx, by, 0.45 * W, 0.05 * HH, "#1d1b22", ow, 0, 360, a * 180 / Math.PI);
    } else if (o.hat === "bonnet") {
        const [bx, by] = R([
            [
                cx + (side ? 6 * u : 0),
                crown + 0.16 * HH
            ]
        ])[0];
        p.arc(bx, by, 0.5 * W, 0.2 * HH, 200, 340, 7 * u, BONNET_BRIM);
        p.arc(bx, by, 0.5 * W + 3.5 * u, 0.2 * HH + 3.5 * u, 200, 340, 1.2 * u);
        const cy = hc + H.b * 0.98;
        p.stroke([
            [
                cx - 14 * u,
                cy - 4 * u
            ],
            [
                cx,
                cy + 2 * u
            ],
            [
                cx + 14 * u,
                cy - 4 * u
            ]
        ], 2 * u, BONNET_BRIM);
    }
};
const BUILD = {
    adult: {
        a: 118,
        torso: 1.1,
        legs: 1.4,
        tw: 0.8
    },
    stout: {
        a: 118,
        torso: 1.15,
        legs: 1.32,
        tw: 0.92
    },
    kid: {
        a: 112,
        torso: 0.85,
        legs: 1.0,
        tw: 0.72
    }
};
const footStroke = (p, a, b, w, col)=>{
    if (col !== INK) p.stroke([
        a,
        b
    ], w + 3, INK);
    p.stroke([
        a,
        b
    ], w, col);
};
export const bodyFront = (p, o, opts)=>{
    const { phase = 0, expr = "neutral", mode = "march", look = 0, blink = false, lift = 60, prop = null, tilt = 0, headTilt = 0, wave, light = DEF_LIGHT, facing = 0, seed = 1 } = opts;
    const Bd = BUILD[o.build ?? "adult"], skin = o.skin ?? SKIN, two = Math.PI * 2, lid = lidOf(blink);
    const H = headBlob(seed, Bd.a, facing), W = 2 * H.a, HH = 2 * H.b, u = W / 100;
    const tall = (1 + Bd.torso + Bd.legs) * HH, sole = 975;
    const bob = mode === "march" ? 0.025 * tall * Math.cos(2 * two * phase) : mode === "stroll" ? 0.015 * tall * Math.cos(2 * two * phase) : 0;
    const torsoBot = mode === "sit" ? sole - 0.2 * HH : sole - Bd.legs * HH + bob;
    const chin = torsoBot - Bd.torso * HH, hc = chin - H.b, crown = hc - H.b, hipY = torsoBot - 0.12 * HH;
    const thick = thickAngle(light), ow = 5 * u;
    const legCol = mix(o.pants, INK, 0.55), armCol = mix(o.jacket, INK, 0.5), footCol = o.boots;
    const legW = 5.8 * u, footW = 7.5 * u;
    p.rot = null;
    if (mode === "sit") {
        for (const side of [
            -1,
            1
        ]){
            const h = [
                300 + side * 15 * u,
                hipY
            ], k = [
                300 + side * 36 * u,
                hipY + 0.2 * HH
            ], f = [
                300 + side * 44 * u,
                sole - 8 * u
            ];
            p.stroke(curve(h, k, f), legW, legCol);
            footStroke(p, [
                f[0] - side * 2 * u,
                f[1]
            ], [
                f[0] + side * 12 * u,
                f[1] - 5 * u
            ], footW, footCol);
        }
    } else if (mode === "fall") {
        const legs = [
            [
                [
                    300 - 15 * u,
                    hipY
                ],
                [
                    300 - 46 * u,
                    hipY + 0.5 * HH
                ],
                [
                    300 - 70 * u,
                    hipY + 0.72 * HH
                ]
            ],
            [
                [
                    300 + 15 * u,
                    hipY
                ],
                [
                    300 + 50 * u,
                    hipY + 0.45 * HH
                ],
                [
                    300 + 76 * u,
                    hipY + 0.22 * HH
                ]
            ]
        ];
        legs.forEach(([h, k, f], i)=>{
            p.stroke(curve(h, k, f), legW, legCol);
            footStroke(p, f, [
                f[0] + (i ? 14 : -14) * u,
                f[1] + (i ? -6 : 4) * u
            ], footW, footCol);
        });
    } else if (o.dress) {
        for (const side of [
            -1,
            1
        ]){
            const fx = 300 + side * 12 * u, fy = sole - 4 * u;
            p.stroke([
                [
                    fx,
                    sole - 0.4 * HH
                ],
                [
                    fx + side * u,
                    fy
                ]
            ], legW, legCol);
            footStroke(p, [
                fx - side * 3 * u,
                fy
            ], [
                fx + side * 12 * u,
                fy + u
            ], footW, footCol);
        }
    } else {
        const L = mode === "march" ? lift * 1.25 : mode === "stroll" ? lift * 0.55 : 0;
        for (const [side, ph] of [
            [
                -1,
                0
            ],
            [
                1,
                0.5
            ]
        ]){
            const up = Math.max(0, Math.sin(two * (phase + ph))) * L;
            const hx = 300 + side * 15 * u, fx = 300 + side * 22 * u, fy = sole - 4 * u - up;
            const k = [
                (hx + fx) / 2 + side * (1.5 * u + up * 0.16),
                (hipY + fy) / 2 - up * 0.08
            ];
            p.stroke(curve([
                hx,
                hipY
            ], k, [
                fx,
                fy
            ]), legW, legCol);
            footStroke(p, [
                fx - side * 3 * u,
                fy
            ], [
                fx + side * 13 * u,
                fy + 0.5 * u
            ], footW, footCol);
        }
    }
    const sway = mode === "march" ? 1.6 * Math.sin(two * phase) : mode === "stroll" ? 1.0 * Math.sin(two * phase) : 0;
    const A = tilt + sway;
    p.rot = A ? [
        rad(A),
        300,
        hipY
    ] : null;
    const dress = !!o.dress && mode !== "sit" && mode !== "fall";
    const T = {
        a: Bd.tw / 2 * W / 1.06,
        b: 0.5 * (torsoBot - (chin - 0.25 * HH)),
        nTop: 2.2,
        nBot: 2.6,
        egg: o.build === "stout" ? 0.17 : 0.12,
        asym: 0.04 * facing,
        rot: 0,
        noise: 0.006,
        seed: seed + 7
    };
    const tcx = 300 + 3 * u * facing, tcy = torsoBot - T.b, tp = blobPts(tcx, tcy, T);
    const sh = (side)=>[
            tcx + side * 0.85 * T.a,
            chin + 0.12 * HH
        ];
    const hang = (side, fwd)=>{
        const S = sh(side), ex = tcx + side * (1.12 * T.a + 4 * u);
        const hx = ex + side * 3 * u - side * 6 * u * Math.max(0, fwd) + side * 4 * u * Math.max(0, -fwd);
        return [
            S,
            [
                ex,
                S[1] + 0.48 * HH
            ],
            [
                hx,
                chin + 1.04 * HH - Math.abs(fwd) * 9 * u
            ]
        ];
    };
    const sw = mode === "march" || mode === "stroll" ? Math.sin(two * phase) : 0;
    const R0 = [
        300 + 47 * u,
        torsoBot + 0.12 * HH
    ], R1 = [
        300 + 64 * u,
        crown - 0.32 * HH
    ];
    const rifle = !!o.rifle && (mode === "march" || mode === "stand" || mode === "stroll");
    const arms = [];
    if (mode === "sit") for (const side of [
        -1,
        1
    ])arms.push({
        pts: [
            sh(side),
            [
                tcx + side * (1.1 * T.a + 6 * u),
                sh(side)[1] + 0.4 * HH
            ],
            [
                tcx + side * (1.2 * T.a + 10 * u),
                torsoBot + 0.04 * HH
            ]
        ],
        front: false
    });
    else if (mode === "fall") for (const side of [
        -1,
        1
    ])arms.push({
        pts: [
            sh(side),
            [
                tcx + side * (1.15 * T.a + 12 * u),
                sh(side)[1] - 0.25 * HH
            ],
            [
                tcx + side * (1.3 * T.a + 24 * u),
                sh(side)[1] - 0.68 * HH
            ]
        ],
        front: false
    });
    else {
        arms.push({
            pts: prop === "shako" ? hang(-1, 0) : hang(-1, -sw),
            front: false
        });
        if (rifle) {
            const G = lerp2(R0, R1, 0.1);
            arms.push({
                pts: [
                    sh(1),
                    [
                        tcx + 1.12 * T.a + 5 * u,
                        sh(1)[1] + 0.45 * HH
                    ],
                    G
                ],
                front: false
            });
        } else if (wave !== undefined) {
            const S = sh(1);
            arms.push({
                pts: [
                    S,
                    [
                        tcx + 1.1 * T.a + 10 * u + 3 * u * wave,
                        S[1] - 0.22 * HH
                    ],
                    [
                        tcx + 1.18 * T.a + 16 * u + 12 * u * wave,
                        S[1] - 0.6 * HH
                    ]
                ],
                front: false
            });
        } else if (prop === "icecream") {
            const S = sh(1);
            arms.push({
                pts: [
                    S,
                    [
                        tcx + 1.05 * T.a + 4 * u,
                        S[1] + 0.45 * HH
                    ],
                    [
                        tcx + 0.5 * T.a,
                        S[1] + 0.4 * HH
                    ]
                ],
                front: true
            });
        } else if (Array.isArray(prop)) {
            const S = sh(1), k = clamp(prop[1], 0, 1);
            const E = lerp2([
                tcx + 1.1 * T.a + 10 * u,
                S[1] - 0.15 * HH
            ], [
                tcx + 1.2 * T.a + 10 * u,
                S[1] + 0.3 * HH
            ], k);
            const Hd = lerp2([
                tcx + 1.15 * T.a + 14 * u,
                S[1] - 0.55 * HH
            ], [
                tcx + 1.45 * T.a + 22 * u,
                S[1] + 0.35 * HH
            ], k);
            arms.push({
                pts: [
                    S,
                    E,
                    Hd
                ],
                front: true
            });
        } else arms.push({
            pts: hang(1, sw),
            front: false
        });
    }
    const drawArm = (a)=>{
        p.stroke(curve(a.pts[0], a.pts[1], a.pts[2]), 5.2 * u, armCol);
        p.dot(a.pts[2][0], a.pts[2][1], 5.5 * u);
    };
    if (rifle) {
        p.band([
            R0,
            R1
        ], "#7a4b2a", 5 * u, 1.5 * u, "round");
        p.band([
            lerp2(R0, R1, 0.6),
            R1
        ], "#8d949c", 2.4 * u, 1.2 * u, "round");
    }
    if (o.sword && mode !== "sit") {
        const s0 = [
            tcx - 0.75 * T.a,
            torsoBot - 0.2 * HH
        ];
        p.band([
            s0,
            [
                s0[0] - Math.sin(rad(25)) * 0.8 * HH,
                s0[1] + Math.cos(rad(25)) * 0.8 * HH
            ]
        ], "#c9ccd2", 3 * u, 1.2 * u, "round");
    }
    for (const a of arms)if (!a.front) drawArm(a);
    if (dress) {
        const D = {
            a: 0.5 * W * 0.98,
            b: 0.5 * (sole - 0.35 * HH - (chin - 0.2 * HH)),
            nTop: 2.0,
            nBot: 3.0,
            egg: 0.35,
            asym: 0.03 * facing,
            rot: 0,
            noise: 0.006,
            seed: seed + 9
        };
        const dp = blobPts(300, sole - 0.35 * HH - D.b, D);
        p.gradFill(dp, o.dress, mul(o.dress, SH_CLOTH), light);
        p.inkRing(dp, ow, thick);
        const Sw = {
            a: 0.37 * W,
            b: 0.3 * HH,
            nTop: 2.2,
            nBot: 2.4,
            egg: 0.1,
            asym: 0,
            rot: 0,
            noise: 0.006,
            seed: seed + 8
        };
        const sp = blobPts(300, chin + 0.12 * HH, Sw);
        p.gradFill(sp, o.jacket, mul(o.jacket, SH_CLOTH), light);
        p.inkRing(sp, ow * 0.9, thick);
    } else {
        p.gradFill(tp, o.jacket, mul(o.jacket, SH_CLOTH), light);
        p.clip(tp, ()=>{
            if (o.belt) {
                for (const s of [
                    -1,
                    1
                ])p.band([
                    [
                        tcx - s * 0.75 * T.a,
                        chin - 0.05 * HH
                    ],
                    [
                        tcx + s * 0.8 * T.a,
                        torsoBot - 0.1 * HH
                    ]
                ], o.belt, 5.5 * u, 1.8 * u);
                const xc = tcx + 0.025 * T.a, yc = chin - 0.05 * HH + (torsoBot - 0.1 * HH - (chin - 0.05 * HH)) * (0.75 / 1.55);
                p.poly([
                    [
                        xc - 3.5 * u,
                        yc - 3.5 * u
                    ],
                    [
                        xc + 3.5 * u,
                        yc - 3.5 * u
                    ],
                    [
                        xc + 3.5 * u,
                        yc + 3.5 * u
                    ],
                    [
                        xc - 3.5 * u,
                        yc + 3.5 * u
                    ]
                ], "#d9dde0", 1.5 * u);
            }
            if (o.sash) p.band([
                [
                    tcx - 1.3 * T.a,
                    torsoBot - 0.32 * HH
                ],
                [
                    tcx + 1.3 * T.a,
                    torsoBot - 0.32 * HH
                ]
            ], o.sash, 0.13 * HH, 1.8 * u);
            for(let i = 0; i < 4; i++){
                const y = chin + 0.12 * HH + i * 0.2 * HH;
                if (o.sash && Math.abs(y - (torsoBot - 0.32 * HH)) < 0.08 * HH) continue;
                p.dot(tcx + 2 * u * facing, y, 2.2 * u + 0.8 * u, INK);
                p.dot(tcx + 2 * u * facing, y, 2.2 * u, o.buttons ?? shade(o.jacket, 0.7));
            }
        });
        if (o.sash) {
            const s = facing || 1;
            p.poly([
                [
                    tcx + s * 0.55 * T.a,
                    torsoBot - 0.3 * HH
                ],
                [
                    tcx + s * 0.75 * T.a,
                    torsoBot + 0.05 * HH
                ],
                [
                    tcx + s * 0.45 * T.a,
                    torsoBot + 0.02 * HH
                ]
            ], o.sash, 1.6 * u);
        }
        p.inkRing(tp, ow, thick);
    }
    for (const a of arms)if (a.front) {
        drawArm(a);
        const [hx, hy] = a.pts[2];
        if (prop === "icecream") {
            p.poly([
                [
                    hx - 8 * u,
                    hy - 12 * u
                ],
                [
                    hx + 8 * u,
                    hy - 12 * u
                ],
                [
                    hx,
                    hy + 7 * u
                ]
            ], "#e0a35a", 1.8 * u);
            p.ell(hx, hy - 19 * u, 11 * u, 10 * u, "#f7c6d9", 2.2 * u);
            p.dot(hx, hy, 5.5 * u);
        } else if (Array.isArray(prop)) {
            const ang = rad(-70 + 105 * clamp(prop[1], 0, 1));
            const Rh = (pts)=>rotPts(pts, ang, hx, hy);
            p.band(Rh([
                [
                    hx,
                    hy + 12 * u
                ],
                [
                    hx,
                    hy - 44 * u
                ]
            ]), "#8a5a34", 5 * u, 1.5 * u, "round");
            p.poly(Rh([
                [
                    hx - 12 * u,
                    hy - 58 * u
                ],
                [
                    hx + 20 * u,
                    hy - 58 * u
                ],
                [
                    hx + 20 * u,
                    hy - 42 * u
                ],
                [
                    hx - 12 * u,
                    hy - 42 * u
                ]
            ]), "#7d848c", 2.2 * u);
            p.dot(hx, hy, 5.5 * u);
        }
    }
    if (prop === "shako") {
        const [hx, hy] = arms[0].pts[2];
        p.poly([
            [
                hx - 14 * u,
                hy + 3 * u
            ],
            [
                hx + 14 * u,
                hy + 3 * u
            ],
            [
                hx + 16 * u,
                hy + 30 * u
            ],
            [
                hx - 16 * u,
                hy + 30 * u
            ]
        ], "#3a3d47", 2.2 * u);
        p.ell(hx, hy + 31 * u, 3.5 * u, 3.5 * u, "#2b7a4b", 1.5 * u);
        p.dot(hx, hy, 5.5 * u);
    }
    const Ah = A + headTilt, [cpx, cpy] = rotAbout([
        300,
        chin
    ], rad(A), [
        300,
        hipY
    ]);
    p.rot = Ah ? [
        rad(Ah),
        300,
        chin,
        cpx - 300,
        cpy - chin
    ] : null;
    hatBehind(p, o, H, 300, hc, light, thick, ow, false);
    const hp = blobPts(300, hc, H);
    p.shadedFill(hp, skin, mul(skin, SH_SKIN), light, H.a);
    p.inkRing(hp, ow, thick);
    hatOn(p, o, hp, H, 300, hc, light, seed, facing, false);
    const brim = !!o.hat && o.hat !== "hair" && o.hat !== "bonnet" && o.hat !== "cap";
    faceFront(p, 300, hc, W, expr, facing, look, lid, brim, skin, o.moustache, o.build === "stout");
    p.rot = null;
};
const ik = (hip, ank, l1, l2)=>{
    const dx = ank[0] - hip[0], dy = ank[1] - hip[1], d = clamp(Math.hypot(dx, dy), 1, l1 + l2 - 0.01);
    const A = Math.acos(clamp((l1 * l1 + d * d - l2 * l2) / (2 * l1 * d), -1, 1)), k = Math.atan2(dy, dx) - A;
    return [
        hip[0] + l1 * Math.cos(k),
        hip[1] + l1 * Math.sin(k)
    ];
};
const SWING_HIP = 733;
export const bodySide = (p, o, opts)=>{
    const { phase = 0, expr = "neutral", mode = "march", blink = false, stomp = 1, pose = 0, stride = 1, light = DEF_LIGHT, seed = 1 } = opts;
    const Bd = BUILD[o.build ?? "adult"], skin = o.skin ?? SKIN, two = Math.PI * 2, lid = lidOf(blink);
    const H = {
        ...headBlob(seed, Bd.a, 1),
        asym: 0.12,
        rot: rad(3 + 3 * (rnd(seed, 7) - 0.5))
    };
    const W = 2 * H.a, HH = 2 * H.b, u = W / 100, sole = 975, ankY = sole - 4 * u;
    const thick = thickAngle(light), ow = 5 * u;
    const legLen = (Bd.legs + 0.12) * HH - 4 * u, l1 = legLen / 2, l2 = legLen / 2;
    const nearCol = mix(o.pants, INK, 0.55), farCol = mix(o.pants, INK, 0.75), footCol = o.boots;
    const legs = [];
    let hipY = ankY - legLen * 0.995, lean = 0, nearFwd = 0;
    if (mode === "march") {
        const S = 370 * stride, liftH = Math.max(22, 40 + 70 * (stomp - 1));
        const st = (ph)=>{
            const c = ((phase + ph) % 1 + 1) % 1;
            if (c < 0.5) {
                const s = c / 0.5;
                return {
                    x: S / 2 - S * s,
                    h: 0,
                    stance: true,
                    s
                };
            }
            const s = (c - 0.5) / 0.5;
            return {
                x: -S / 2 + S * s - S / Math.PI * Math.sin(2 * Math.PI * s),
                h: liftH * Math.sin(Math.PI * s),
                stance: false,
                s
            };
        };
        const nL = st(0), fL = st(0.5), stance = nL.stance ? nL : fL;
        const Leff = legLen * (1 - 0.035 * Math.sin(Math.PI * stance.s));
        hipY = ankY - Math.sqrt(Math.max(1, Leff * Leff - stance.x * stance.x));
        for (const [L, near] of [
            [
                fL,
                false
            ],
            [
                nL,
                true
            ]
        ])legs.push({
            ank: [
                300 + L.x,
                ankY - L.h
            ],
            pitch: L.stance ? 0 : rad(35 * Math.sin(Math.PI * L.s) * (1 - 1.6 * L.s)),
            near
        });
        lean = 4 + 3 * Math.cos(2 * two * phase);
        nearFwd = nL.x / (S / 2);
    } else if (mode === "push") {
        hipY = ankY - 0.87 * legLen;
        legs.push({
            ank: [
                300 - 0.5 * legLen,
                ankY
            ],
            pitch: rad(-8),
            near: false
        }, {
            ank: [
                300 + 0.32 * legLen,
                ankY
            ],
            pitch: 0,
            near: true
        });
        lean = 14 * pose;
    } else if (mode === "swing") {
        hipY = SWING_HIP;
        const a = rad(60 * pose);
        for (const [dx, near] of [
            [
                -6,
                false
            ],
            [
                0,
                true
            ]
        ]){
            const knee = [
                300 + l1 * 0.98 + dx * u,
                hipY + 6 * u
            ];
            legs.push({
                ank: [
                    knee[0] + l2 * Math.sin(a),
                    knee[1] + l2 * Math.cos(a)
                ],
                pitch: -a * 0.5,
                near
            });
        }
    } else {
        legs.push({
            ank: [
                300 - 4 * u,
                ankY
            ],
            pitch: 0,
            near: false
        }, {
            ank: [
                300 + 4 * u,
                ankY
            ],
            pitch: 0,
            near: true
        });
    }
    const torsoBot = hipY + 0.12 * HH, chin = torsoBot - Bd.torso * HH, hc = chin - H.b, crown = hc - H.b, hip = [
        300,
        hipY
    ];
    p.rot = null;
    for (const L of legs){
        const knee = mode === "swing" ? [
            300 + l1 * 0.98 + (L.near ? 0 : -6 * u),
            hipY + 6 * u
        ] : ik(hip, L.ank, l1, l2);
        const hp0 = [
            300 + (L.near ? 0 : -5 * u),
            hipY
        ];
        p.stroke([
            hp0,
            knee,
            L.ank
        ], 5.8 * u, L.near ? nearCol : farCol);
        const c = Math.cos(L.pitch), s = Math.sin(L.pitch);
        footStroke(p, [
            L.ank[0] - 3 * u * c,
            L.ank[1] - 3 * u * s
        ], [
            L.ank[0] + 13 * u * c,
            L.ank[1] + 13 * u * s + 0.5 * u
        ], 7.5 * u, L.near ? footCol : footCol === INK ? INK : shade(footCol, 0.82));
    }
    p.rot = lean ? [
        rad(lean),
        300,
        hipY
    ] : null;
    const T = {
        a: (o.build === "stout" ? 0.36 : 0.31) * W,
        b: 0.5 * (torsoBot - (chin - 0.25 * HH)),
        nTop: 2.2,
        nBot: 2.5,
        egg: 0.1,
        asym: 0.06,
        rot: 0,
        noise: 0.006,
        seed: seed + 7
    };
    const tcx = 300 + 2 * u, tcy = torsoBot - T.b, tp = blobPts(tcx, tcy, T);
    const armCol = mix(o.jacket, INK, 0.5), farArm = mix(o.jacket, INK, 0.68);
    const S = [
        tcx + 0.05 * T.a,
        chin + 0.14 * HH
    ], aLen = 0.95 * HH;
    const swingArm = (ang)=>{
        const e = [
            S[0] + Math.sin(ang) * aLen * 0.5,
            S[1] + Math.cos(ang) * aLen * 0.5
        ], a2 = ang + rad(16) * Math.sign(ang || 1);
        return [
            S,
            e,
            [
                e[0] + Math.sin(a2) * aLen * 0.5,
                e[1] + Math.cos(a2) * aLen * 0.5
            ]
        ];
    };
    const rifle = !!o.rifle && (mode === "march" || mode === "stand");
    const B0 = [
        tcx + 0.72 * T.a,
        chin + 0.58 * HH
    ], B1 = [
        tcx - 0.95 * T.a - 22 * u,
        crown - 0.4 * HH
    ];
    let near, far;
    if (mode === "swing") {
        near = [
            S,
            [
                S[0] + 12 * u,
                S[1] - 0.16 * HH
            ],
            [
                300 + 6 * u,
                chin - 0.3 * HH
            ]
        ];
        far = [
            S,
            [
                S[0] + 8 * u,
                S[1] - 0.18 * HH
            ],
            [
                300 + 2 * u,
                chin - 0.36 * HH
            ]
        ];
    } else if (mode === "push") {
        const reach = 0.55 * HH + 0.45 * HH * pose;
        let hN = [
            S[0] + reach,
            S[1] + 0.06 * HH
        ];
        if (opts.hand) {
            const th = -rad(lean), dx = opts.hand[0] - 300, dy = opts.hand[1] - hipY;
            const tg = [
                300 + dx * Math.cos(th) - dy * Math.sin(th),
                hipY + dx * Math.sin(th) + dy * Math.cos(th)
            ];
            hN = [
                hN[0] + (tg[0] - hN[0]) * pose,
                hN[1] + (tg[1] - hN[1]) * pose
            ];
        }
        near = [
            S,
            [
                (S[0] + hN[0]) / 2,
                (S[1] + hN[1]) / 2 + 0.06 * HH
            ],
            hN
        ];
        far = [
            S,
            [
                (S[0] + hN[0]) / 2 - 4 * u,
                (S[1] + hN[1]) / 2 - 0.02 * HH
            ],
            [
                hN[0] - 6 * u,
                hN[1] - 0.08 * HH
            ]
        ];
    } else if (rifle) {
        near = [
            S,
            [
                S[0] - 4 * u,
                S[1] + 0.42 * HH
            ],
            B0
        ];
        far = mode === "march" ? swingArm(rad(30) * nearFwd) : swingArm(0);
    } else {
        near = swingArm(rad(-30) * nearFwd);
        far = mode === "march" ? swingArm(rad(30) * nearFwd) : null;
    }
    if (far) {
        p.stroke(curve(far[0], far[1], far[2]), 5.2 * u, farArm);
        p.dot(far[2][0], far[2][1], 5.5 * u);
    }
    p.gradFill(tp, o.jacket, mul(o.jacket, SH_CLOTH), light);
    p.clip(tp, ()=>{
        if (o.belt) p.band([
            [
                tcx - 0.65 * T.a,
                chin - 0.05 * HH
            ],
            [
                tcx + 0.75 * T.a,
                torsoBot - 0.1 * HH
            ]
        ], o.belt, 5.5 * u, 1.8 * u);
        if (o.sash) p.band([
            [
                tcx - 1.3 * T.a,
                torsoBot - 0.32 * HH
            ],
            [
                tcx + 1.3 * T.a,
                torsoBot - 0.32 * HH
            ]
        ], o.sash, 0.13 * HH, 1.8 * u);
        if (!o.dress) for(let i = 0; i < 3; i++){
            const y = chin + 0.16 * HH + i * 0.24 * HH;
            p.dot(tcx + 0.8 * T.a, y, 3 * u, INK);
            p.dot(tcx + 0.8 * T.a, y, 2.2 * u, o.buttons ?? shade(o.jacket, 0.7));
        }
    });
    p.inkRing(tp, ow, thick);
    if (rifle) {
        p.band([
            B0,
            B1
        ], "#7a4b2a", 5 * u, 1.5 * u, "round");
        p.band([
            lerp2(B0, B1, 0.6),
            B1
        ], "#8d949c", 2.4 * u, 1.2 * u, "round");
    }
    p.stroke(curve(near[0], near[1], near[2]), 5.2 * u, armCol);
    p.dot(near[2][0], near[2][1], 5.5 * u);
    const hx = 300 + 4 * u;
    hatBehind(p, o, H, hx, hc, light, thick, ow, true);
    const hp = blobPts(hx, hc, H);
    p.shadedFill(hp, skin, mul(skin, SH_SKIN), light, H.a);
    p.inkRing(hp, ow, thick);
    hatOn(p, o, hp, H, hx, hc, light, seed, 1, true);
    const brim = !!o.hat && o.hat !== "hair" && o.hat !== "bonnet" && o.hat !== "cap";
    faceSide(p, hx, hc, W, expr, lid, brim, skin, o.moustache, o.build === "stout");
    p.rot = null;
};
export const swingKid = (p, o, kick, expr, light = DEF_LIGHT, blink = 0)=>{
    const rope = 1830, k = 1.1, HH = 2 * headBlob(5, BUILD[o.build ?? "adult"].a, 1).b;
    const seat = rope + 18, x0 = 150, x1 = 550;
    p.line([
        [
            350,
            20
        ],
        [
            x0 + 16,
            seat + 4
        ]
    ], "#a07a4c", 10);
    p.poly(rrect(x0, seat, x1, seat + 36, 10), "#b5653f", 9);
    const g = p.g;
    g.save();
    g.translate(350 - 300 * k, rope + 18 - (SWING_HIP + 0.12 * HH) * k);
    g.scale(k, k);
    bodySide(new Pen(g), o, {
        expr,
        mode: "swing",
        pose: kick,
        light,
        seed: 5,
        blink
    });
    g.restore();
    p.line([
        [
            350,
            20
        ],
        [
            x1 - 16,
            seat + 4
        ]
    ], "#a07a4c", 10);
};
export const fxNote = (p, kind, col = "#1f2a44")=>{
    p.ell(70, 200, 46, 34, col, 8, 0, 360, -20);
    p.stroke([
        [
            110,
            190
        ],
        [
            110,
            40
        ]
    ], 14);
    if (kind === 0) p.poly([
        [
            110,
            40
        ],
        [
            170,
            70
        ],
        [
            170,
            110
        ],
        [
            110,
            82
        ]
    ], col, 8);
    else {
        p.ell(150, 170, 40, 30, col, 8, 0, 360, -20);
        p.stroke([
            [
                186,
                160
            ],
            [
                186,
                20
            ]
        ], 14);
        p.poly([
            [
                110,
                40
            ],
            [
                186,
                20
            ],
            [
                186,
                50
            ],
            [
                110,
                70
            ]
        ], col, 8);
    }
};
export const fxBurst = (p, t, col = "#fff3b0", rays = 10, r0 = 40, r1 = 230)=>{
    const c = 250, e = 1 - (1 - t) ** 3;
    for(let i = 0; i < rays; i++){
        const a = rad(i * 360 / rays + 7 * (i % 2)), ra = r0 + (r1 - r0) * e * (0.75 + 0.25 * (i % 2));
        p.poly([
            [
                c + r0 * 0.5 * Math.cos(a + 0.18),
                c + r0 * 0.5 * Math.sin(a + 0.18)
            ],
            [
                c + ra * Math.cos(a),
                c + ra * Math.sin(a)
            ],
            [
                c + r0 * 0.5 * Math.cos(a - 0.18),
                c + r0 * 0.5 * Math.sin(a - 0.18)
            ]
        ], col, Math.max(3, 8 * (1 - t)));
    }
    if (t < 0.5) p.ell(c, c, r0 * (1.4 - t), r0 * (1.4 - t), WHITE, 8);
};
export const fxSplash = (p, t)=>{
    const c = 400, size = 800, rise = Math.sin(Math.min(1, t * 1.3) * Math.PI);
    const blue = "#bfe8ff", deep = "#6cc0f0";
    if (rise > 0.02) {
        const pts = [];
        for(let i = 0; i < 19; i++){
            const h = (i % 2 ? 260 : 130) * rise * (0.7 + 0.3 * Math.sin(i * 1.7));
            pts.push([
                c - 330 + 660 * i / 18,
                size - 120 - h
            ]);
        }
        p.poly([
            ...pts,
            [
                c + 330,
                size - 90
            ],
            [
                c - 330,
                size - 90
            ]
        ], blue, 10);
        p.ell(c, size - 100, 360, 46, deep, 10);
    }
    for(let i = 0; i < 8; i++){
        const a = rad(200 + i * 18), d = 120 + 380 * t, y = size - 160 + d * Math.sin(a) + 520 * t * t, r = 26 * (1 - t) + 6;
        if (t > 0.08 && y < size - 40) p.ell(c + d * Math.cos(a), y, r, r * 1.25, blue, 7);
    }
};
export const fxPuff = (p, t)=>{
    for(let i = 0; i < 5; i++){
        const a = rad(160 + i * 55), d = 40 + 70 * t, r = (34 + 20 * (i % 2)) * (1 - 0.6 * t);
        p.ell(150 + d * Math.cos(a), 180 + d * 0.45 * Math.sin(a), r, r * 0.8, `rgba(238,225,205,${(1 - t).toFixed(3)})`, 0);
    }
};
export const fxStars = (p, t)=>{
    for(let i = 0; i < 4; i++){
        const a = t * Math.PI * 2 + i * Math.PI / 2, x = 210 + 150 * Math.cos(a), y = 110 + 40 * Math.sin(a), pts = [];
        for(let k = 0; k < 10; k++){
            const r = k % 2 ? 14 : 34, b = rad(k * 36 - 90);
            pts.push([
                x + r * Math.cos(b),
                y + r * Math.sin(b)
            ]);
        }
        p.poly(pts, "#ffd84a", 6);
    }
};
export const fxCreak = (p, t)=>{
    const j = 6 * Math.sin(t * 40);
    for (const a of [
        -30,
        0,
        30
    ]){
        const b = rad(a - 90);
        p.stroke([
            [
                150 + 70 * Math.cos(b) + j,
                230 + 70 * Math.sin(b)
            ],
            [
                150 + 100 * Math.cos(b) + 10 + j,
                230 + 100 * Math.sin(b)
            ],
            [
                150 + 130 * Math.cos(b) + j,
                230 + 130 * Math.sin(b)
            ]
        ], 10);
    }
};
export const fxRing = (p, t)=>{
    const g = p.g;
    for(let k = 0; k < 3; k++){
        const u = t - k * 0.22;
        if (u <= 0 || u >= 1) continue;
        g.beginPath();
        g.ellipse(300, 300, 60 + 230 * u, 60 + 230 * u, 0, 0, Math.PI * 2);
        g.strokeStyle = k === 0 ? "#f6fcff" : "#cfe8fa";
        g.lineWidth = 9 * (1 - u) + 3;
        g.stroke();
    }
};
export const fxSign = (p)=>{
    const g = p.g, RED = "#d42f2f";
    p.poly(rrect(14, 14, 686, 506, 40), "#f6ecd2", 0);
    p.poly(rrect(14, 14, 686, 506, 40), null, 14);
    p.poly(rrect(70, 352, 630, 384, 8), "#8a5a3a", 9);
    g.beginPath();
    g.moveTo(112, 470);
    g.quadraticCurveTo(350, 300, 588, 470);
    g.strokeStyle = INK;
    g.lineWidth = 16;
    g.lineCap = "round";
    g.stroke();
    for (const x of [
        88,
        612
    ])p.poly(rrect(x - 16, 384, x + 16, 470, 4), "#8a5a3a", 9);
    for (const x of [
        150,
        278,
        406,
        534
    ]){
        p.poly(rrect(x - 30, 150, x + 30, 214, 14), "#357650", 9);
        p.stroke([
            [
                x - 8,
                210
            ],
            [
                x + 34,
                262
            ],
            [
                x + 46,
                338
            ]
        ], 15, INK);
        p.stroke([
            [
                x + 6,
                210
            ],
            [
                x - 12,
                274
            ],
            [
                x - 36,
                336
            ]
        ], 15, INK);
        p.poly(rrect(x + 30, 330, x + 74, 350, 9), INK, 0);
        p.poly(rrect(x - 52, 328, x - 8, 348, 9), INK, 0);
    }
    for (const [a, b] of [
        [
            [
                96,
                70
            ],
            [
                604,
                452
            ]
        ],
        [
            [
                604,
                70
            ],
            [
                96,
                452
            ]
        ]
    ]){
        p.stroke([
            a,
            b
        ], 58, "#ffffff");
        p.stroke([
            a,
            b
        ], 42, RED);
    }
};
export const fxCloud = (p, seed)=>{
    const blobs = [
        [
            150,
            190,
            80
        ],
        [
            250,
            150,
            105
        ],
        [
            360,
            160,
            95
        ],
        [
            450,
            195,
            70
        ],
        [
            300,
            210,
            90
        ]
    ];
    for (const [x, y, r] of blobs)p.ell(x + seed * 37 % 20 - 10, y, r, r * 0.8, "#ffffff", 0);
    p.ell(300, 235, 230, 40, "#ffffff", 0);
};
export const fxShadow = (p, col)=>{
    const g = p.g;
    g.fillStyle = WHITE;
    g.fillRect(0, 0, 128, 256);
    g.save();
    g.filter = "blur(9px)";
    const lg = g.createLinearGradient(0, 205, 0, 22);
    lg.addColorStop(0, mix(col, WHITE, 0.08));
    lg.addColorStop(0.55, mix(col, WHITE, 0.3));
    lg.addColorStop(1, mix(col, WHITE, 0.85));
    g.fillStyle = lg;
    g.beginPath();
    g.moveTo(40, 205);
    g.bezierCurveTo(36, 120, 46, 50, 64, 30);
    g.bezierCurveTo(82, 50, 92, 120, 88, 205);
    g.closePath();
    g.fill();
    g.fillStyle = col;
    g.beginPath();
    g.ellipse(64, 205, 30, 17, 0, 0, Math.PI * 2);
    g.fill();
    g.restore();
};
export const fxContact = (p, col)=>{
    const g = p.g;
    g.fillStyle = WHITE;
    g.fillRect(0, 0, 128, 128);
    const gr = g.createRadialGradient(64, 64, 0, 64, 64, 64);
    for (const [r, k] of [
        [
            0,
            0
        ],
        [
            0.32,
            0.02
        ],
        [
            0.5,
            0.22
        ],
        [
            0.66,
            0.58
        ],
        [
            0.82,
            0.88
        ],
        [
            1,
            1
        ]
    ])gr.addColorStop(r, mix(col, WHITE, k));
    g.fillStyle = gr;
    g.fillRect(0, 0, 128, 128);
};
export const fxPlank = (p)=>{
    p.poly(rrect(14, 30, 306, 78, 10), "#a8744a", 9);
    p.line([
        [
            40,
            46
        ],
        [
            150,
            44
        ],
        [
            270,
            50
        ]
    ], "#7d5234", 4);
    p.line([
        [
            60,
            62
        ],
        [
            200,
            64
        ],
        [
            284,
            60
        ]
    ], "#7d5234", 4);
    p.dot(36, 54, 5, INK);
    p.dot(284, 54, 5, INK);
};
export const fxDrum = (p)=>{
    p.poly(rrect(40, 70, 220, 190, 16), "#f1ece0", 9);
    p.poly(rrect(32, 58, 228, 86, 12), "#c9373a", 8);
    p.poly(rrect(32, 176, 228, 204, 12), "#c9373a", 8);
    p.line([
        [
            52,
            88
        ],
        [
            82,
            172
        ],
        [
            112,
            88
        ],
        [
            142,
            172
        ],
        [
            172,
            88
        ],
        [
            202,
            172
        ]
    ], INK, 6);
    p.ell(130, 58, 98, 18, "#f7f3ea", 8);
};
export const fxBlob = (p, col)=>{
    const g = p.g;
    g.fillStyle = WHITE;
    g.fillRect(0, 0, 128, 128);
    const gr = g.createRadialGradient(64, 64, 0, 64, 64, 64);
    for (const [r, k] of [
        [
            0,
            0
        ],
        [
            0.5,
            0.04
        ],
        [
            0.64,
            0.18
        ],
        [
            0.76,
            0.42
        ],
        [
            0.87,
            0.72
        ],
        [
            0.95,
            0.92
        ],
        [
            1,
            1
        ]
    ])gr.addColorStop(r, mix(col, WHITE, k));
    g.fillStyle = gr;
    g.fillRect(0, 0, 128, 128);
};
FACE.snore = { eye: ["dash", "dash"], brow: [0, -1], mouth: "o" };
FACE.stubborn = { eye: ["lid", "lid"], brow: [4, -3], mouth: "frown" };
FACE.squint = { eye: ["slit", "slit"], brow: [3, -2], mouth: "dash" };

// ---------------- Roman-era cast (our own designs), built on the Pen / blob / face helpers above ----------------
const STEEL = "#aeb6bf", BRASS = "#d9a845", LEATHER = "#7a4a2a";
export const OUTFITS = {
  legion: { tunic: "#b8322f", cape: "#8f2228", skin: SKIN, helmet: true, armor: true, spear: true, shield: true },
  old: { tunic: "#9c4a3c", cape: "#6e3330", skin: "#f3d6bb", helmet: "old", armor: true, spear: true, shield: false, beard: "#f4f1ea", brows: "#f4f1ea" },
  toga: { tunic: "#f1ead8", skin: "#f5c9a0", toga: "#6b3c8f", hair: "#3b2a20", stout: true },
  civA: { tunic: "#4f7fb8", skin: "#f5c9a0", hair: "#5a3b2a" },
  civB: { tunic: "#d9a441", skin: SKIN, hair: "#2b211c", dress: "#c25a7a" },
  civC: { tunic: "#5d8a3a", skin: "#c99067", hair: "#1e1714", stout: true },
  workA: { tunic: "#8a5d3b", skin: "#f5c9a0", cap: "#c2733a", apron: "#d8c9a6" },
  workB: { tunic: "#3f6a6f", skin: "#ecd0b6", cap: "#5b4a8a", moustache: "#4a3020" },
};

/** galea: iron bowl, brass brow band, cheek guards, transverse red crest */
const galea = (p, H, cx, hc, light, thick, ow, old, u) => {
  const crest = old ? "#8d4b3f" : "#d2372f", bowl = old ? "#8f8a7e" : STEEL;
  // crest (behind the bowl top)
  const cy0 = hc - H.b * 0.98;
  const cr = ellPts(cx, cy0, 0.66 * 2 * H.a, 0.42 * 2 * H.b, 180, 360, 0, 40);
  cr.push([cx + 0.66 * 2 * H.a * 0.98, cy0 + 4 * u], [cx - 0.66 * 2 * H.a * 0.98, cy0 + 4 * u]);
  const crP = [...ellPts(cx, cy0 + 2 * u, 0.62 * 2 * H.a, 0.36 * 2 * H.b, 180, 360, 0, 40)];
  p.shadedFill(crP, crest, mul(crest, [0.7, 0.62, 0.7]), light, 0.62 * 2 * H.a, 0.3);
  p.clip(crP, () => { for (let i = -9; i <= 9; i++) p.stroke([[cx + i * 7.4 * u, cy0], [cx + i * 9.4 * u, cy0 - 0.62 * H.b * Math.cos(i / 11)]], 1.4 * u, mul(crest, [0.62, 0.55, 0.62])); });
  if (old) p.clip(crP, () => { for (let i = 0; i < 6; i++) p.ell(cx + (i - 3) * 22 * u, cy0 - 18 * u - (i % 2) * 10 * u, 9 * u, 5 * u, "#6f6a5e", 0); });
  p.inkRing(crP, ow * 0.85, thick);
  p.poly(rrect(cx - 10 * u, cy0 - 6 * u, cx + 10 * u, cy0 + 6 * u, 3 * u), BRASS, 2 * u);
  // bowl: upper head cap
  const bandY = hc - H.b * 0.42;
  const bp = ellPts(cx, bandY, H.a * 1.05, H.b * 0.66, 180, 360, 0, 48);
  p.shadedFill(bp, bowl, mul(bowl, [0.62, 0.64, 0.72]), light, H.a, 0.4);
  p.clip(bp, () => {
    p.stroke(ellPts(cx - 20 * u, bandY - 0.3 * H.b, 0.25 * H.a, 0.18 * H.b, 200, 300, 0, 16), 4 * u, "#ffffff55");
    if (old) for (let i = 0; i < 9; i++) p.ell(cx + Math.sin(i * 2.3) * 0.8 * H.a, bandY - (0.08 + 0.5 * ((i * 0.37) % 1)) * H.b, (3 + (i % 3) * 2) * u, (2 + (i % 2)) * u, "#8a4b22", 0);
  });
  p.inkRing(bp, ow * 0.9, thick);
  p.band([[cx - H.a * 1.04, bandY], [cx + H.a * 1.04, bandY]], old ? "#a88a4a" : BRASS, 7 * u, 1.8 * u, "round");
  for (const s of [-1, 1]) p.dot(cx + s * 0.55 * H.a, bandY, 2.2 * u, "#fff3c4");
};
const cheeks = (p, H, cx, hc, light, ow, old, u) => {
  const bowl = old ? "#8f8a7e" : STEEL;
  for (const s of [-1, 1]) {
    const x0 = cx + s * 0.78 * H.a, x1 = cx + s * 1.07 * H.a, y0 = hc - H.b * 0.42, y1 = hc + H.b * 0.48;
    const pts = [[x0, y0], [x1, y0], [x1 - s * 0.04 * H.a, y1 - 0.1 * H.b], [x0 + s * 0.06 * H.a, y1], [x0 - s * 0.05 * H.a, (y0 + y1) / 2]];
    p.shadedFill(pts, bowl, mul(bowl, [0.62, 0.64, 0.72]), light, 0.2 * H.a, 0.3);
    p.poly(pts, null, ow * 0.8);
    p.dot((x0 + x1) / 2, (y0 + y1) / 2 - 0.05 * H.b, 2.2 * u, BRASS);
  }
};
const cobweb = (p, cx, cy, r, u) => {
  const g = p.g; g.save(); g.globalAlpha = 0.8;
  for (let i = 0; i < 7; i++) { const a = -Math.PI * (0.05 + 0.9 * i / 6); p.stroke([[cx, cy], [cx + Math.cos(a) * r, cy + Math.sin(a) * r]], 1.1 * u, "#f2f2f2"); }
  for (let k = 1; k <= 4; k++) { const rr = r * k / 4.3, pts = []; for (let i = 0; i < 7; i++) { const a = -Math.PI * (0.05 + 0.9 * i / 6); pts.push([cx + Math.cos(a) * rr, cy + Math.sin(a) * rr]); } p.stroke(pts, 1 * u, "#f2f2f2"); }
  g.restore();
};

/** front-facing Roman-era character. opts: expr, blink, look, facing, seed, L/R arm poses, tilt, headTilt, bob, nohelmet, light */
export const romanFront = (p, key, opts = {}) => {
  const O = typeof key === "string" ? OUTFITS[key] : key;
  const { expr = "neutral", blink = 0, look = 0, facing = 0, seed = 3, L = "hang", R = O.spear ? "spear" : "hang", tilt = 0, headTilt = 0,
    bob = 0, nohelmet = false, light = rad(-120), web = false, step = 0 } = opts;
  const lid = lidOf(blink), skin = O.skin ?? SKIN;
  const H = headBlob(seed, 118, facing), W = 2 * H.a, HH = 2 * H.b, u = W / 100;
  const torsoL = O.stout ? 1.12 : 1.08, legsL = 1.38, sole = 975;
  const torsoBot = sole - legsL * HH - bob * HH, chin = torsoBot - torsoL * HH, hc = chin - H.b, hipY = torsoBot - 0.12 * HH;
  const thick = thickAngle(light), ow = 5 * u, cx = 300;
  const legCol = mix(O.tunic, INK, 0.62), armCol = mix(O.tunic, INK, 0.5);
  const helmet = !!O.helmet && !nohelmet, old = O.helmet === "old";
  p.rot = null;
  // ---- cape behind everything ----
  if (O.cape) {
    const cp = [[cx - 0.48 * W, chin + 0.08 * HH], [cx + 0.48 * W, chin + 0.08 * HH], [cx + 0.62 * W, sole - 0.55 * HH], [cx + 0.2 * W, sole - 0.45 * HH], [cx - 0.2 * W, sole - 0.5 * HH], [cx - 0.62 * W, sole - 0.55 * HH]];
    p.gradFill(cp, O.cape, mul(O.cape, [0.6, 0.6, 0.7]), light); p.inkRing(cp, ow * 0.8, thick);
  }
  // ---- legs ----
  const dress = !!O.dress;
  for (const side of [-1, 1]) {
    const up = Math.max(0, Math.sin(Math.PI * 2 * (step + (side > 0 ? 0.5 : 0)))) * 30 * (step ? 1 : 0);
    const hx = cx + side * 16 * u, fx = cx + side * 22 * u, fy = sole - 4 * u - up;
    p.stroke(curve([hx, hipY], [(hx + fx) / 2 + side * 2 * u, (hipY + fy) / 2], [fx, fy]), 5.8 * u, legCol);
    const sandal = O.helmet ? LEATHER : "#5a3b2a";
    p.stroke([[fx - side * 3 * u, fy], [fx + side * 13 * u, fy + 0.5 * u]], 7.5 * u + 3, INK);
    p.stroke([[fx - side * 3 * u, fy], [fx + side * 13 * u, fy + 0.5 * u]], 7.5 * u, sandal);
    if (O.helmet) for (let k = 1; k <= 3; k++) p.stroke([[fx - 4 * u, fy - k * 0.07 * HH], [fx + 4 * u, fy - k * 0.07 * HH - 2 * u]], 2 * u, LEATHER);
  }
  // ---- upper body ----
  p.rot = tilt ? [rad(tilt), cx, hipY] : null;
  const T = { a: (0.4 * W) / 1.06 * (O.stout ? 1.12 : 1), b: 0.5 * (torsoBot - (chin - 0.25 * HH)), nTop: 2.2, nBot: 2.6, egg: O.stout ? 0.17 : 0.12, asym: 0.04 * facing, rot: 0, noise: 0.006, seed: seed + 7 };
  const tcx = cx + 3 * u * facing, tcy = torsoBot - T.b, tp = blobPts(tcx, tcy, T);
  const S = (side) => [tcx + side * 0.85 * T.a, chin + 0.12 * HH];
  const arm = (side, pose) => {
    const s = S(side), X = (k) => tcx + side * (T.a * 1.1 + k * u);
    switch (pose) {
      case "spear": return { pts: [s, [X(6), s[1] + 0.42 * HH], [X(10), s[1] + 0.2 * HH]], front: false };
      case "point": return { pts: [s, [X(28), s[1] - 0.02 * HH], [X(62), s[1] - 0.1 * HH]], front: false, finger: true };
      case "up": return { pts: [s, [X(14), s[1] - 0.3 * HH], [X(22), s[1] - 0.75 * HH]], front: false };
      case "wave": return { pts: [s, [X(16), s[1] - 0.2 * HH], [X(30 + 10 * Math.sin(opts.wv || 0)), s[1] - 0.62 * HH]], front: false };
      case "hip": return { pts: [s, [X(22), s[1] + 0.3 * HH], [tcx + side * T.a * 0.95, torsoBot - 0.3 * HH]], front: false };
      case "belly": return { pts: [s, [X(8), s[1] + 0.45 * HH], [tcx + side * 0.25 * T.a, torsoBot - 0.35 * HH]], front: true };
      case "temple": return { pts: [s, [X(26), s[1] + 0.05 * HH], [cx + side * (H.a + 16 * u), hc - 0.1 * HH]], front: false, swirl: true };
      case "lift": return { pts: [s, [X(20), s[1] - 0.25 * HH], [X(4), s[1] - 0.82 * HH]], front: false };
      case "shield": return { pts: [s, [X(4), s[1] + 0.4 * HH], [tcx + side * 0.6 * T.a, torsoBot - 0.1 * HH]], front: true };
      case "cross": return { pts: [s, [X(2), s[1] + 0.38 * HH], [tcx - side * 0.45 * T.a, s[1] + 0.32 * HH]], front: true };
      case "reach": { const lf = (opts.lift || 0) * 0.62 * HH; return { pts: [s, [X(42), s[1] - 0.12 * HH - lf * 0.6], [X(82), s[1] - 0.5 * HH - lf]], front: false }; }
      case "cheek": return { pts: [s, [X(16), s[1] + 0.05 * HH], [cx + side * (H.a + 2 * u), hc + 0.25 * H.b]], front: false };
      case "thumb": return { pts: [s, [X(20), s[1] + 0.12 * HH], [X(44), s[1] - 0.12 * HH]], front: false, thumb: true };
      default: return { pts: [s, [X(4), s[1] + 0.48 * HH], [X(3), chin + 1.04 * HH]], front: false };
    }
  };
  const arms = [arm(-1, L), arm(1, R)];
  const drawArm = (a) => {
    p.stroke(curve(a.pts[0], a.pts[1], a.pts[2]), 5.2 * u, armCol);
    const [hx, hy] = a.pts[2];
    p.dot(hx, hy, 5.5 * u);
    if (a.finger) { const dx = a.pts[2][0] - a.pts[1][0], dy = a.pts[2][1] - a.pts[1][1], l = Math.hypot(dx, dy); p.stroke([[hx, hy], [hx + dx / l * 14 * u, hy + dy / l * 14 * u]], 2.6 * u); }
    if (a.thumb) p.stroke([[hx, hy], [hx + Math.sign(hx - cx) * 6 * u, hy - 12 * u]], 2.6 * u);
  };
  // spear behind
  if (O.spear && R === "spear") {
    const [hx, hy] = arms[1].pts[2], s0 = [hx + 2 * u, sole - 2 * u], s1 = [hx - 3 * u, 70];
    p.band([s0, s1], old ? "#6d5236" : "#8a5a34", 4.2 * u, 1.4 * u, "round");
    const tip = [[s1[0] - 7 * u, s1[1] + 6 * u], [s1[0], s1[1] - 34 * u], [s1[0] + 7 * u, s1[1] + 6 * u], [s1[0], s1[1] + 14 * u]];
    p.poly(tip, old ? "#8b7c6a" : "#c9cfd6", 2 * u);
    if (web) cobweb(p, s1[0] - 2 * u, s1[1] + 60 * u, 70 * u, u);
  }
  for (const a of arms) if (!a.front) drawArm(a);
  // torso
  if (dress) {
    const D = { a: 0.5 * W * 0.98, b: 0.5 * ((sole - 0.35 * HH) - (chin - 0.2 * HH)), nTop: 2.0, nBot: 3.0, egg: 0.35, asym: 0, rot: 0, noise: 0.006, seed: seed + 9 };
    const dp = blobPts(cx, sole - 0.35 * HH - D.b, D);
    p.gradFill(dp, O.dress, mul(O.dress, SH_CLOTH), light); p.inkRing(dp, ow, thick);
  }
  // skirt / pteruges below the torso
  if (!dress) {
    const sk = [[tcx - 0.92 * T.a, torsoBot - 0.2 * HH], [tcx + 0.92 * T.a, torsoBot - 0.2 * HH], [tcx + 1.0 * T.a, torsoBot + 0.3 * HH], [tcx - 1.0 * T.a, torsoBot + 0.3 * HH]];
    p.gradFill(sk, O.tunic, mul(O.tunic, SH_CLOTH), light); p.poly(sk, null, ow * 0.8);
    if (O.armor) for (let i = -3; i <= 3; i++) { const x = tcx + i * 0.27 * T.a, st = [[x - 9 * u, torsoBot - 0.05 * HH], [x + 9 * u, torsoBot - 0.05 * HH], [x + 9 * u, torsoBot + 0.22 * HH], [x - 9 * u, torsoBot + 0.22 * HH]]; p.poly(st, old ? "#5e4632" : LEATHER, 1.6 * u); }
  }
  p.gradFill(tp, O.tunic, mul(O.tunic, SH_CLOTH), light);
  p.clip(tp, () => {
    if (O.armor) {
      const top = chin - 0.1 * HH, bot = torsoBot - 0.25 * HH, n = 5;
      for (let i = 0; i < n; i++) {
        const y0 = top + (bot - top) * i / n, y1 = top + (bot - top) * (i + 1) / n;
        const c = old ? (i % 2 ? "#8d8679" : "#9a9384") : (i % 2 ? "#a7b0ba" : "#bcc4cc");
        p.poly([[tcx - 1.5 * T.a, y0], [tcx + 1.5 * T.a, y0 + 3 * u], [tcx + 1.5 * T.a, y1 + 3 * u], [tcx - 1.5 * T.a, y1]], c, 1.8 * u);
      }
      p.band([[tcx - 1.4 * T.a, torsoBot - 0.2 * HH], [tcx + 1.4 * T.a, torsoBot - 0.2 * HH]], LEATHER, 0.08 * HH, 1.5 * u);
      for (let i = -2; i <= 2; i++) p.dot(tcx + i * 0.3 * T.a, torsoBot - 0.2 * HH, 2.4 * u, BRASS);
      if (old) for (let i = 0; i < 5; i++) p.ell(tcx + Math.sin(i * 1.7) * 0.7 * T.a, top + (bot - top) * ((i * 0.31) % 1), 6 * u, 3 * u, "#8a4b22", 0);
    } else {
      p.band([[tcx - 1.4 * T.a, torsoBot - 0.24 * HH], [tcx + 1.4 * T.a, torsoBot - 0.24 * HH]], O.apron ? "#5a3b2a" : "#e2c27a", 0.05 * HH, 1.2 * u);
      if (O.toga) p.band([[tcx - 1.0 * T.a, chin - 0.1 * HH], [tcx + 1.1 * T.a, torsoBot - 0.1 * HH]], O.toga, 0.16 * HH, 1.6 * u);
      if (O.apron) p.poly([[tcx - 0.55 * T.a, torsoBot - 0.2 * HH], [tcx + 0.55 * T.a, torsoBot - 0.2 * HH], [tcx + 0.6 * T.a, torsoBot + 0.2 * HH], [tcx - 0.6 * T.a, torsoBot + 0.2 * HH]], O.apron, 1.6 * u);
      p.stroke([[tcx - 0.2 * T.a, chin + 0.02 * HH], [tcx, chin + 0.16 * HH], [tcx + 0.2 * T.a, chin + 0.02 * HH]], 2 * u);
    }
  });
  p.inkRing(tp, ow, thick);
  if (O.armor) for (const s of [-1, 1]) { // shoulder plates
    const sp = ellPts(tcx + s * 0.72 * T.a, chin + 0.1 * HH, 0.42 * T.a, 0.13 * HH, 180, 360, s * 8, 20);
    p.poly(sp, old ? "#9a9384" : "#c5ccd3", 1.8 * u);
  }
  if (O.moss) {/* reserved */}
  for (const a of arms) if (a.front) drawArm(a);
  // shield in front, held by the left hand
  if (O.shield && L === "shield") {
    const sx = tcx - 0.55 * T.a, sy = torsoBot + 0.05 * HH, sw = 0.36 * W, sh = 0.78 * HH;
    const sp = rrect(sx - sw, sy - sh, sx + sw, sy + sh, 8 * u);
    p.gradFill(sp, "#c0302c", "#7d1d22", light);
    p.clip(sp, () => {
      p.band([[sx - sw, sy], [sx + sw, sy]], BRASS, 6 * u, 1.2 * u);
      p.band([[sx, sy - sh], [sx, sy + sh]], BRASS, 6 * u, 1.2 * u);
      for (const s of [-1, 1]) { p.stroke([[sx + s * 12 * u, sy - 14 * u], [sx + s * 34 * u, sy - 46 * u], [sx + s * 22 * u, sy - 44 * u], [sx + s * 46 * u, sy - 74 * u]], 3.5 * u, BRASS); p.stroke([[sx + s * 12 * u, sy + 14 * u], [sx + s * 34 * u, sy + 46 * u], [sx + s * 22 * u, sy + 44 * u], [sx + s * 46 * u, sy + 74 * u]], 3.5 * u, BRASS); }
      p.stroke(ellPts(sx - sw * 0.5, sy - sh * 0.7, sw * 0.3, sh * 0.1, 200, 320, 0, 10), 3 * u, "#ffffff44");
    });
    p.ell(sx, sy, 13 * u, 13 * u, "#e6c068", 2.2 * u);
    p.inkRing(sp, ow, thick);
  }
  // ---- head ----
  const [cpx, cpy] = rotAbout([cx, chin], rad(tilt), [cx, hipY]);
  const Ah = tilt + headTilt;
  p.rot = Ah ? [rad(Ah), cx, chin, cpx - cx, cpy - chin] : null;
  if (helmet) galea(p, H, cx, hc, light, thick, ow, old, u);
  const hp = blobPts(cx, hc, H);
  if (O.hair && !helmet) { const hb = blobPts(cx, hc - 0.03 * HH, { ...H, a: H.a * 1.04, b: H.b * 1.05 }); p.poly(hb, O.hair, 0); }
  p.shadedFill(hp, skin, mul(skin, SH_SKIN), light, H.a);
  p.inkRing(hp, ow, thick);
  if (helmet) {
    const bandY = hc - H.b * 0.42, bp = ellPts(cx, bandY, H.a * 1.05, H.b * 0.66, 180, 360, 0, 48);
    p.shadedFill(bp, old ? "#8f8a7e" : STEEL, mul(old ? "#8f8a7e" : STEEL, [0.62, 0.64, 0.72]), light, H.a, 0.4);
    p.clip(bp, () => { p.stroke(ellPts(cx - 20 * u, bandY - 0.3 * H.b, 0.25 * H.a, 0.18 * H.b, 200, 300, 0, 16), 5 * u, "#ffffff66");
      if (old) for (let i = 0; i < 9; i++) p.ell(cx + Math.sin(i * 2.3) * 0.8 * H.a, bandY - (0.08 + 0.5 * ((i * 0.37) % 1)) * H.b, (4 + (i % 3) * 2) * u, (2.5 + (i % 2)) * u, "#8a4b22", 0); });
    p.poly(bp, null, ow * 0.9);
    p.band([[cx - H.a * 1.05, bandY], [cx + H.a * 1.05, bandY]], old ? "#a88a4a" : BRASS, 7 * u, 1.8 * u, "round");
    p.poly(rrect(cx - 4 * u, bandY - 0.55 * H.b, cx + 4 * u, bandY - 3 * u, 2 * u), old ? "#a88a4a" : BRASS, 1.5 * u);
    cheeks(p, H, cx, hc, light, ow, old, u);
  } else if (O.cap) hatOn(p, { hat: "cap", cap: O.cap, jacket: O.tunic }, hp, H, cx, hc, light, seed, facing, false);
  else if (O.hair) hatOn(p, { hat: "hair", hair: O.hair, jacket: O.tunic }, hp, H, cx, hc, light, seed, facing, false);
  else if (O.helmet && nohelmet) { // bald old head with white side tufts
    for (const s of [-1, 1]) p.ell(cx + s * 0.9 * H.a, hc - 0.1 * H.b, 0.22 * H.a, 0.3 * H.b, "#f4f1ea", 3 * u);
  }
  if (O.beard) {
    const bd = blobPts(cx + 6 * u * facing, hc + 0.85 * H.b, { a: 0.62 * H.a, b: 0.75 * H.b, nTop: 2.4, nBot: 1.6, egg: -0.35, asym: 0, rot: 0, noise: 0.02, seed: seed + 4 });
    p.shadedFill(bd, O.beard, mul(O.beard, [0.86, 0.86, 0.92]), light, 0.6 * H.a, 0.3);
    p.clip(bd, () => { for (let i = -3; i <= 3; i++) p.stroke([[cx + i * 9 * u, hc + 0.45 * H.b], [cx + i * 7 * u, hc + 1.35 * H.b]], 1.2 * u, "#c9c4bb"); });
    p.inkRing(bd, ow * 0.8, thick);
  }
  faceFront(p, cx, hc, W, expr, facing, look, lid, helmet, skin, O.beard ? O.beard : O.moustache, !!O.stout);
  if (O.brows) for (const s of [-1, 1]) p.ell(cx + 7 * u * facing + s * 14 * u, hc - 20 * u, 11 * u, 5 * u, O.brows, 2 * u);
  if (O.beard) { // re-draw the mouth over the beard for open mouths
    if (expr === "shock" || expr === "snore") p.ell(cx + 8 * u * facing, hc + 22 * u, 6 * u, 7 * u, "#5a1e28", 2 * u);
  }
  p.rot = null;
  if (arms.some((a) => a.swirl)) { // cuckoo swirl next to the temple
    const a = arms.find((x) => x.swirl), [hx, hy] = a.pts[2], ph = opts.swirl || 0, pts = [];
    for (let i = 0; i < 40; i++) { const t = i / 40 * Math.PI * 4 + ph, r = (4 + i * 0.7) * u; pts.push([hx + Math.cos(t) * r, hy - 40 * u + Math.sin(t) * r]); }
    p.stroke(pts, 3 * u, "#ffffff"); p.stroke(pts, 1.4 * u, INK);
  }
};

/** loose helmet prop card (lifted off the old soldier) */
export const helmetCard = (p) => {
  const H = headBlob(3, 118, 0), u = 2 * H.a / 100, hc = 560, light = rad(-120), thick = thickAngle(light), ow = 5 * u;
  galea(p, H, 300, hc, light, thick, ow, true, u);
  const bandY = hc - H.b * 0.42, bp = ellPts(300, bandY, H.a * 1.05, H.b * 0.66, 180, 360, 0, 48);
  // dark inside visible from below
  p.ell(300, bandY, H.a * 1.05, 0.12 * H.b, "#2a221e", 0);
  p.shadedFill(bp, "#8f8a7e", mul("#8f8a7e", [0.62, 0.64, 0.72]), light, H.a, 0.4);
  p.clip(bp, () => { for (let i = 0; i < 9; i++) p.ell(300 + Math.sin(i * 2.3) * 0.8 * H.a, bandY - (0.08 + 0.5 * ((i * 0.37) % 1)) * H.b, (4 + (i % 3) * 2) * u, (2.5 + (i % 2)) * u, "#8a4b22", 0); });
  p.poly(bp, null, ow * 0.9);
  p.band([[300 - H.a * 1.05, bandY], [300 + H.a * 1.05, bandY]], "#a88a4a", 7 * u, 1.8 * u, "round");
  cheeks(p, H, 300, hc, light, ow, true, u);
};

/** ZZZ for the sleeping guard */
export const fxZ = (p, t) => {
  const g = p.g; g.save(); g.font = "900 120px Arial Black, Arial"; g.lineJoin = "round";
  for (let i = 0; i < 3; i++) {
    const k = (t + i / 3) % 1, x = 220 + i * 70 + Math.sin(k * 6) * 20, y = 700 - k * 500, s = 0.5 + k * 0.7;
    g.save(); g.translate(x, y); g.scale(s, s); g.globalAlpha = Math.min(1, (1 - k) * 2.5);
    g.lineWidth = 16; g.strokeStyle = INK; g.strokeText("Z", 0, 0); g.fillStyle = "#ffffff"; g.fillText("Z", 0, 0); g.restore();
  }
  g.restore();
};
/** falling leaf */
export const fxLeaf = (p, col) => { p.poly([[300, 380], [420, 470], [300, 620], [180, 470]], col, 14); p.stroke([[300, 400], [300, 600]], 8); };
/** dust cloud puff (k 0..1 growth) */
export const fxDust = (p, k, col = "#e8dcc4") => {
  const g = p.g; g.save(); g.globalAlpha = Math.max(0, 1 - k * k);
  for (let i = 0; i < 7; i++) { const a = i / 7 * Math.PI * 2, r = 90 + 150 * k; p.ell(300 + Math.cos(a) * r, 520 + Math.sin(a) * r * 0.6, 120 + 60 * k, 100 + 50 * k, col, 12); }
  p.ell(300, 520, 170 + 110 * k, 140 + 80 * k, col, 0);
  g.restore();
};
export const fxDrip = (p) => p.ell(300, 500, 40, 64, "#9fd4ff", 10);
export const fxWood = (p, seed) => { p.poly([[200, 420], [400, 400], [420, 560], [230, 600]], "#5b3d22", 14); p.stroke([[240, 450], [380, 440]], 6, "#3a2614"); p.ell(330, 520, 26, 18, "#4d7a32", 0); };

export const headCenter = (seed = 3) => { const H = headBlob(seed, 118, 0), HH = 2 * H.b; return 975 - 1.38 * HH - 1.08 * HH - H.b; };

// ---------------- Oddly Relatable stick cast (Episode 15), drawn on the Pen API above ----------------
// Same approach as roman.js: one function draws a whole character on the 600x1000 design canvas (soles at y=975).
// House style (approved masters): round white head, bold black outline, big white eyes + black pupils,
// simple brows, small mouth, NO nose, slim white body, thin black stick limbs, small solid black mitten hands.
const BLK = "#121212", PAPER = "#f6f1e2", SHADE = "#d5d8e0", SHADE2 = "#e6e8ee", MOUTHC = "#4a1a1f", TONG = "#d9707a";
const lerpN = (a, b, t) => a + (b - a) * t;
const lerpP = (a, b, t) => [lerpN(a[0], b[0], t), lerpN(a[1], b[1], t)];
// filled shape with a black outline
const fo = (p, pts, fill, w) => { const g = p.g; p.path(pts, true); if (fill) { g.fillStyle = fill; g.fill(); } if (w) { g.lineWidth = w; g.strokeStyle = BLK; g.lineJoin = "round"; g.stroke(); } };
const ln = (p, pts, w, col = BLK) => p.stroke(pts, w, col);
// thick coloured stroke with a black rim (white brows, wires)
const rimLine = (p, pts, fill, w, rim) => { p.stroke(pts, w + 2 * rim, BLK); p.stroke(pts, w, fill); };
// tapered stroke (brows, moustache halves)
const taperPts = (pts, w0, w1) => {
  const L = [], Rr = [], n = pts.length;
  for (let i = 0; i < n; i++) {
    const a = pts[Math.max(0, i - 1)], b = pts[Math.min(n - 1, i + 1)], dx = b[0] - a[0], dy = b[1] - a[1], l = Math.hypot(dx, dy) || 1;
    const w = lerpN(w0, w1, i / (n - 1)) / 2, nx = -dy / l * w, ny = dx / l * w;
    L.push([pts[i][0] + nx, pts[i][1] + ny]); Rr.push([pts[i][0] - nx, pts[i][1] - ny]);
  }
  return [...L, ...Rr.reverse()];
};
const qbez = (a, c, b, n = 16) => { const o = []; for (let i = 0; i <= n; i++) { const t = i / n, u = 1 - t; o.push([u * u * a[0] + 2 * u * t * c[0] + t * t * b[0], u * u * a[1] + 2 * u * t * c[1] + t * t * b[1]]); } return o; };

// ---------- expressions: numeric parameter sets (blendable) ----------
// browY: + raises (R units) | browAng: + = inner ends down (cross) | browArc: arch | browAsym: + raises the screen-right brow
// lid: upper lid 0..1 | lidAng: + = lid line slopes down toward the nose (angry) | lidBot: lower-lid squint
// eyeS/pupS: eye and pupil scale | curve: mouth corners up(+)/down(-) | skew: + lifts the screen-right corner
// mw: mouth width | jaw: forced opening (shock) | teeth: show upper teeth when open
export const EXPR = {
  neutral:   { browY: 0.00, browAng: 0, browArc: 0.5, browAsym: 0, lid: 0.12, lidAng: 0, lidBot: 0, eyeS: 1.0, pupS: 1.0, curve: 0.10, skew: 0, mw: 0.30, jaw: 0, teeth: 0 },
  reading:   { browY: -0.02, browAng: 0.05, browArc: 0.45, browAsym: 0, lid: 0.30, lidAng: 0, lidBot: 0, eyeS: 1.0, pupS: 1.0, curve: -0.05, skew: 0, mw: 0.22, jaw: 0, teeth: 0 },
  stern:     { browY: -0.04, browAng: 0.55, browArc: 0.25, browAsym: 0, lid: 0.16, lidAng: 0.35, lidBot: 0.06, eyeS: 0.97, pupS: 1.0, curve: -0.55, skew: 0, mw: 0.32, jaw: 0, teeth: 0 },
  smirk:     { browY: 0.00, browAng: 0.15, browArc: 0.4, browAsym: 0.14, lid: 0.38, lidAng: 0.1, lidBot: 0.08, eyeS: 1.0, pupS: 1.0, curve: 0.45, skew: 0.75, mw: 0.42, jaw: 0, teeth: 0 },
  smug:      { browY: 0.00, browAng: 0.45, browArc: 0.3, browAsym: 0.10, lid: 0.36, lidAng: 0.1, lidBot: 0.05, eyeS: 1.0, pupS: 1.0, curve: 0.40, skew: 0.65, mw: 0.40, jaw: 0, teeth: 0 },
  skeptical: { browY: 0.00, browAng: 0.25, browArc: 0.3, browAsym: 0.20, lid: 0.42, lidAng: 0.12, lidBot: 0.10, eyeS: 1.0, pupS: 1.0, curve: -0.20, skew: -0.45, mw: 0.28, jaw: 0, teeth: 0 },
  shocked:   { browY: 0.17, browAng: -0.55, browArc: 0.65, browAsym: 0, lid: 0.0, lidAng: 0, lidBot: 0, eyeS: 1.3, pupS: 0.55, curve: -0.9, skew: 0, mw: 0.25, jaw: 1.0, teeth: 1 },
  worried:   { browY: 0.10, browAng: -0.45, browArc: 0.55, browAsym: 0, lid: 0.0, lidAng: 0, lidBot: 0, eyeS: 1.12, pupS: 0.8, curve: -0.45, skew: 0.1, mw: 0.26, jaw: 0, teeth: 0 },
  indignant: { browY: -0.08, browAng: 0.75, browArc: 0.15, browAsym: -0.04, lid: 0.42, lidAng: 0.45, lidBot: 0.14, eyeS: 1.0, pupS: 0.95, curve: -0.75, skew: -0.15, mw: 0.34, jaw: 0, teeth: 0 },
};
export const blendExpr = (a, b, t) => { const A = typeof a === "string" ? EXPR[a] : a, B = typeof b === "string" ? EXPR[b] : b, o = {}; for (const k in A) o[k] = lerpN(A[k], B[k] ?? A[k], t); return o; };

// talking mouth shapes: [width scale, opening (R units), roundness 0..1]
export const MOUTHS = { closed: [1, 0, 0], small: [0.85, 0.07, 0.1], mid: [0.95, 0.14, 0.1], round: [0.55, 0.15, 1], wide: [1.1, 0.22, 0], rest: [1, 0, 0] };

// ---------- characters ----------
export const CAST = {
  mortimer: { tufts: true, glasses: true, browStyle: "white", baseFacing: 0 },
  sidney: { combover: true, moustache: true, browStyle: "dark", heavyLid: 0.06, lidShade: true },
  winifred: { bun: "#a84a2a", browStyle: "dark" },
  ronald: { cap: "#7a6a4e", rosy: true, browStyle: "dark" },
  // narrator of the narrated shorts (draft, awaiting owner approval): plain stick man, teal cap, dark brows
  narrator: { cap: "#2f7f86", browStyle: "dark" },
  // narrator design options (drafts): same body and face system, different head details
  optA: { cap: "#2f7f86", browStyle: "dark" },                                    // A: teal cap
  optB: { spiky: "#1b1816", rosy: true, browStyle: "dark" },                      // B: spiky black hair, rosy cheeks
  optC: { beanie: "#e8892b", cuff: "#c96d17", browStyle: "dark" },                // C: orange beanie with a pom
  optD: { hairCap: "#4a3322", glasses: true, browStyle: "dark" },                 // D: brown hair and round glasses
  optE: { bun: "#7a3fa0", rosy: true, browStyle: "dark" },                        // E: purple top bun, rosy cheeks
  // arm / leg style options on Sam (drafts)
  samLine: { hairCap: "#5a3b26", tie: "#c23b3b", browStyle: "dark", body: { R: 172, hip: 688, torso: 228, limb: 1.1, torsoW: 1.3, hand: 1.1, foot: 1.05 } },
  samThick: { hairCap: "#5a3b26", tie: "#c23b3b", browStyle: "dark", limbStyle: "thick", body: { R: 172, hip: 688, torso: 228, limb: 1.1, torsoW: 1.3, hand: 1.1, foot: 1.05 } },
  samPipeArms: { hairCap: "#5a3b26", tie: "#c23b3b", browStyle: "dark", armStyle: "pipe", body: { R: 172, hip: 688, torso: 228, limb: 1.1, torsoW: 1.3, hand: 1.1, foot: 1.05 } },
  samPipeAll: { hairCap: "#5a3b26", tie: "#c23b3b", browStyle: "dark", limbStyle: "pipe", body: { R: 172, hip: 688, torso: 228, limb: 1.1, torsoW: 1.3, hand: 1.1, foot: 1.05 } },
  // body options (drafts), all on the beanie head
  bodyA: { beanie: "#e8892b", cuff: "#c96d17", browStyle: "dark" },
  bodyB: { beanie: "#e8892b", cuff: "#c96d17", browStyle: "dark", body: { R: 180, hip: 700, torso: 205, limb: 1.25, torsoW: 1.35, hand: 1.15, foot: 1.1 } },
  bodyC: { beanie: "#e8892b", cuff: "#c96d17", browStyle: "dark", body: { R: 172, hip: 690, torso: 225, limb: 1.1, torsoW: 1.65, hand: 1.1, foot: 1.05 } },
  bodyD: { beanie: "#e8892b", cuff: "#c96d17", browStyle: "dark", body: { R: 150, hip: 640, torso: 270, limb: 0.9, torsoW: 0.85 } },
  bodyE: { beanie: "#e8892b", cuff: "#c96d17", browStyle: "dark", body: { R: 205, hip: 722, torso: 170, limb: 1.2, torsoW: 1.1, hand: 1.2, foot: 1.15 } },
  bodyF: { beanie: "#e8892b", cuff: "#c96d17", browStyle: "dark", body: { R: 168, hip: 665, torso: 250, limb: 1.35, torsoW: 1.15, hand: 1.3, foot: 1.1 } },
  // new characters for the narrated shorts (drafts): an everyman who tells small lies
  samN: { hairCap: "#5a3b26", tie: "#c23b3b", browStyle: "dark", body: { R: 172, hip: 688, torso: 228, limb: 1.1, torsoW: 1.3, hand: 1.1, foot: 1.05 } },
  devN: { spiky: "#1b1816", glasses: true, tie: "#2f5fb0", browStyle: "dark", body: { R: 180, hip: 700, torso: 205, limb: 1.25, torsoW: 1.35, hand: 1.15, foot: 1.1 } },
  moN: { beanie: "#e8892b", cuff: "#c96d17", rosy: true, browStyle: "dark", body: { R: 172, hip: 690, torso: 225, limb: 1.1, torsoW: 1.65, hand: 1.1, foot: 1.05 } },
  kitN: { bun: "#7a3fa0", rosy: true, tie: "#e0b030", browStyle: "dark", body: { R: 160, hip: 650, torso: 262, limb: 0.95, torsoW: 0.95, hand: 1.05 } },
  optF: { headband: "#d23a3a", spiky: "#2b211c", browStyle: "dark", heavyLid: 0.04 }, // F: red headband, short dark hair, relaxed lids
};

// ---------- head parts ----------
const eyeDraw = (p, ex, ey, rx, ry, E, look, lidK, side, C, R) => {
  const ow = 0.038 * R, pts = ellPts(ex, ey, rx, ry, 0, 360, 0, 40);
  fo(p, pts, "#ffffff", 0);
  p.clip(pts, () => {
    p.ell(ex - 0.45 * rx, ey + 0.55 * ry, rx * 0.9, ry * 0.65, SHADE2, 0);
    // pupil
    const pr = 0.4 * Math.min(rx, ry) * E.pupS, mx = rx - pr * 0.95, my = ry - pr * 0.95;
    const px = ex + look[0] * mx * 0.85, py = ey + look[1] * my * 0.8;
    p.dot(px, py, pr, BLK);
    p.dot(px - pr * 0.38, py - pr * 0.4, pr * 0.3, "#ffffff");
    // upper lid (white skin + line), slope toward the nose for anger
    const lid = Math.min(1, lidK);
    if (lid > 0.01) {
      const yl = ey - ry + 2 * ry * lid, sl = E.lidAng * ry * 0.5 * side; // side=-1 left eye: inner corner is +x
      const a = [ex - rx * 1.2, yl - sl * 1.2], b = [ex + rx * 1.2, yl + sl * 1.2];
      fo(p, [[ex - rx * 1.3, ey - ry * 1.4], [ex + rx * 1.3, ey - ry * 1.4], b, a], "#ffffff", 0);
      if (lid < 0.97) { p.stroke([a, b], 0.05 * ry, SHADE); p.stroke([[a[0], a[1] + ry * 0.07], [b[0], b[1] + ry * 0.07]], ry * 0.12, "rgba(170,175,190,.35)"); }
      if (C.lidShade) fo(p, [[ex - rx * 1.3, ey - ry * 1.4], [ex + rx * 1.3, ey - ry * 1.4], [b[0], b[1] - ry * 0.02], [a[0], a[1] - ry * 0.02]], "rgba(190,194,206,.55)", 0);
      ln(p, [a, b], ow * 0.95);
    }
    if (E.lidBot > 0.01 && lid < 0.97) {
      const yb = ey + ry - 2 * ry * E.lidBot;
      fo(p, [[ex - rx * 1.3, ey + ry * 1.4], [ex + rx * 1.3, ey + ry * 1.4], [ex + rx * 1.2, yb], [ex - rx * 1.2, yb]], "#ffffff", 0);
      ln(p, [[ex - rx * 1.1, yb + ry * 0.05], [ex, yb - ry * 0.03], [ex + rx * 1.1, yb + ry * 0.05]], ow * 0.7);
    }
  });
  fo(p, pts, null, ow);
  if (lidK >= 0.97) ln(p, qbez([ex - rx, ey + ry * 0.1], [ex, ey + ry * 0.45], [ex + rx, ey + ry * 0.1]), ow * 1.1); // closed: lash line
};

const browDraw = (p, bx, by, w, E, side, C, R) => {
  // side: -1 = screen-left brow, +1 = screen-right brow. inner end is toward the face centre.
  const inner = -side, ang = E.browAng * 0.22 * R, asym = E.browAsym * R * (side > 0 ? 1 : -0.4);
  const yIn = by + ang - asym, yOut = by - ang * 0.25 - asym;
  const xIn = bx + inner * w * 0.5, xOut = bx - inner * w * 0.5;
  const mid = [(xIn + xOut) / 2, (yIn + yOut) / 2 - E.browArc * 0.16 * R];
  const pts = qbez([xOut, yOut], mid, [xIn, yIn], 14);
  if (C.browStyle === "white") { // Mortimer: bushy white brows with a black rim
    const sh = taperPts(pts, 0.06 * R, 0.1 * R);
    fo(p, sh, "#ffffff", 0.035 * R);
    ln(p, qbez([xOut + inner * w * 0.15, yOut + 0.01 * R], [mid[0], mid[1] + 0.035 * R], [xIn - inner * w * 0.12, yIn + 0.02 * R], 10), 0.012 * R, "#b9bcc6");
  } else {
    fo(p, taperPts(pts, 0.055 * R, 0.1 * R), "#221d1a", 0);
  }
};

// mouth: base line through (mx,my), width W, corners curve c, skew s, opening H, roundness rd
const mouthDraw = (p, mx, my, W, c, s, H, rd, teeth, R, C) => {
  const n = 22, base = (t) => [mx + t * W / 2, my - c * 0.11 * R * t * t + c * 0.03 * R - s * 0.07 * R * t];
  if (H < 0.012 * R) {
    const pts = []; for (let i = 0; i <= n; i++) pts.push(base(-1 + 2 * i / n));
    ln(p, pts, 0.042 * R);
    // little cheek tick on the lifted corner (master smile)
    if (c > 0.3) { const sd = s >= 0 ? 1 : -1, q = base(sd); ln(p, [[q[0] - sd * 0.02 * R, q[1] - 0.05 * R], [q[0] + sd * 0.05 * R, q[1] + 0.03 * R]], 0.026 * R); }
    if (c < -0.5) { for (const sd of [-1, 1]) { const q = base(sd); ln(p, [[q[0] + sd * 0.01 * R, q[1] - 0.01 * R], [q[0] + sd * 0.05 * R, q[1] + 0.05 * R]], 0.024 * R); } }
    return;
  }
  const up = [], lo = [];
  for (let i = 0; i <= n; i++) {
    const t = -1 + 2 * i / n, [x, y] = base(t), k = Math.pow(Math.max(0, 1 - t * t), rd > 0.5 ? 0.5 : 0.75);
    up.push([x, y - H * 0.28 * k]); lo.push([x, y + H * 0.72 * k]);
  }
  const shape = [...up, ...lo.reverse()];
  fo(p, shape, MOUTHC, 0);
  p.clip(shape, () => {
    if (H > 0.09 * R) p.ell(mx + s * 0.03 * R, my + H * 0.62, W * 0.32, H * 0.38, TONG, 0);
    if (teeth && H > 0.1 * R) { const tp = up.map(([x, y]) => [x, y + 0.045 * R]); fo(p, [...up, ...tp.reverse()], "#ffffff", 0); }
  });
  fo(p, shape, null, 0.04 * R);
};

/** a whole head. Returns nothing; draws at (hx,hy) radius R. o: E (expr params), mouth, look, blink, facing, pitch */
export const stickHead = (p, C, hx, hy, R, o) => {
  const E = o.E, f = o.facing || 0, pitch = o.pitch || 0;
  const ow = 0.048 * R;
  if (!o.faceOnly) {
  // hair behind the head
  if (C.bun) { fo(p, ellPts(hx + 0.05 * R, hy - 1.0 * R, 0.42 * R, 0.34 * R), C.bun, ow * 0.9); }
  // Mortimer tufts (behind the head outline so the head rim overlaps them)
  const tuft = (sd) => {
    const x0 = hx + sd * 0.86 * R, y0 = hy - 0.28 * R, pts = [];
    const lobes = [[0.0, -0.46], [0.22, -0.44], [0.3, -0.3], [0.44, -0.24], [0.32, -0.1], [0.46, -0.02], [0.3, 0.06], [0.36, 0.2], [0.16, 0.16], [0.12, 0.3], [0.0, 0.26]];
    for (const [dx, dy] of lobes) pts.push([x0 + sd * dx * R, y0 + dy * R]);
    pts.push([x0 - sd * 0.12 * R, y0 + 0.1 * R], [x0 - sd * 0.12 * R, y0 - 0.25 * R]);
    fo(p, pts, "#f2f3f6", ow * 0.8);
    p.clip(pts, () => { p.ell(x0 + sd * 0.05 * R, y0 + 0.06 * R, 0.16 * R, 0.12 * R, "#d4d7de", 0); });
    ln(p, [[x0 + sd * 0.1 * R, y0 - 0.12 * R], [x0 + sd * 0.22 * R, y0 - 0.04 * R]], 0.018 * R, "#9aa0ab");
    ln(p, [[x0 + sd * 0.08 * R, y0 + 0.04 * R], [x0 + sd * 0.2 * R, y0 + 0.12 * R]], 0.018 * R, "#9aa0ab");
  };
  if (C.tufts) { tuft(-1); tuft(1); }
  // head: white with a soft grey crescent on the lower-left (light from upper right)
  const hp = ellPts(hx, hy, R, R, 0, 360, 0, 72);
  fo(p, hp, "#ffffff", 0);
  p.clip(hp, () => {
    const g = p.g, [gx, gy] = p.P(hx + 0.24 * R, hy - 0.2 * R), gr = g.createRadialGradient(gx, gy, 0, gx, gy, 1.2 * R);
    gr.addColorStop(0, "#ffffff"); gr.addColorStop(0.74, "#ffffff"); gr.addColorStop(0.86, "#e4e6ec"); gr.addColorStop(1, "#c3c7d2");
    p.path(hp, true); g.fillStyle = gr; g.fill();
    if (C.rosy) for (const sd of [-1, 1]) p.ell(hx + f * 0.3 * R + sd * 0.42 * R, hy + 0.25 * R, 0.13 * R, 0.08 * R, "rgba(232,120,120,.45)", 0);
  });
  fo(p, hp, null, ow);
  }
  // features
  const fx = hx + f * 0.3 * R, fy = hy + pitch * 0.14 * R;
  const eyeY = fy - 0.09 * R - Math.max(0, E.eyeS - 1) * 0.12 * R, sep = 0.35 * R * Math.max(1, 0.25 + 0.8 * E.eyeS);
  const rx = 0.28 * R * E.eyeS, ry = 0.31 * R * E.eyeS;
  const lidK = Math.max(E.lid + (C.heavyLid || 0) * (1 - Math.min(1, E.jaw)), o.blink || 0);
  const look = o.look || [0, 0];
  const exs = [fx - sep * (1 - f * 0.12), fx + sep * (1 + f * 0.12)];
  const sc = [1 - Math.max(0, f) * 0.14, 1 + Math.min(0, f) * 0.14]; // far eye slightly narrower
  exs.forEach((ex, i) => eyeDraw(p, ex, eyeY, rx * sc[i], ry, E, look, lidK, i ? 1 : -1, C, R));
  const browBase = eyeY - ry - 0.1 * R + E.browY * R;
  exs.forEach((ex, i) => browDraw(p, ex + (i ? 0.02 : -0.02) * R, browBase, 0.34 * R * sc[i], E, i ? 1 : -1, C, R));
  if (!o.faceOnly) {
  // comb-over strands across the top
  if (C.combover) {
    const strands = [[-0.62, -0.62, 0.0, -1.2, 0.72, -0.84], [-0.48, -0.8, 0.1, -1.26, 0.56, -0.98], [-0.72, -0.46, -0.1, -1.06, 0.66, -0.68], [-0.3, -0.92, 0.18, -1.18, 0.4, -1.04]];
    strands.forEach(([a, b, c, d, e2, f2], i) => ln(p, qbez([hx + a * R, hy + b * R], [hx + c * R, hy + d * R], [hx + e2 * R, hy + f2 * R]), (i === 3 ? 0.02 : 0.028) * R, "#2a2420"));
  }
  if (C.hairCap) { // short hair: a dome hugging the top of the head, with a side-swept edge
    const hc = [...ellPts(hx, hy - 0.08 * R, 1.0 * R, 0.98 * R, 195, 345, 0, 30), [hx + 0.62 * R, hy - 0.5 * R], [hx + 0.1 * R, hy - 0.66 * R], [hx - 0.55 * R, hy - 0.58 * R]];
    fo(p, hc, C.hairCap, ow * 0.9);
    ln(p, qbez([hx - 0.7 * R, hy - 0.62 * R], [hx - 0.1 * R, hy - 0.98 * R], [hx + 0.62 * R, hy - 0.52 * R], 12), 0.022 * R, "rgba(255,255,255,.28)");
  }
  if (C.spiky) { // five spikes on the crown
    const sp = [];
    const n = 5;
    for (let i = 0; i < n; i++) { const a0 = Math.PI * (1.12 + 0.76 * i / n), a1 = Math.PI * (1.12 + 0.76 * (i + 0.5) / n), a2 = Math.PI * (1.12 + 0.76 * (i + 1) / n), h = (i % 2 ? 1.28 : 1.42) * R;
      sp.push([hx + Math.cos(a0) * 0.98 * R, hy + Math.sin(a0) * 0.98 * R], [hx + Math.cos(a1) * h, hy + Math.sin(a1) * h], [hx + Math.cos(a2) * 0.98 * R, hy + Math.sin(a2) * 0.98 * R]); }
    fo(p, sp, C.spiky, ow * 0.9);
  }
  if (C.beanie) { // knitted beanie: dome, folded cuff, pom
    const dome = [...ellPts(hx, hy - 0.3 * R, 1.0 * R, 0.95 * R, 180, 360, 0, 36)];
    fo(p, dome, C.beanie, ow * 0.9);
    for (let i = -3; i <= 3; i++) ln(p, [[hx + i * 0.26 * R, hy - 0.4 * R], [hx + i * 0.2 * R, hy - 1.18 * R]], 0.014 * R, "rgba(0,0,0,.18)");
    const cuff = rrect(hx - 1.02 * R, hy - 0.52 * R, hx + 1.02 * R, hy - 0.2 * R, 0.07 * R);
    fo(p, cuff, C.cuff, ow * 0.9);
    p.dot(hx, hy - 1.3 * R, 0.17 * R, C.cuff); p.path(ellPts(hx, hy - 1.3 * R, 0.17 * R, 0.17 * R), true); p.g.lineWidth = ow * 0.8; p.g.strokeStyle = BLK; p.g.stroke();
  }
  if (C.headband) ln(p, qbez([hx - 0.99 * R, hy - 0.3 * R], [hx, hy - 0.5 * R], [hx + 0.99 * R, hy - 0.3 * R], 20), 0.15 * R, C.headband), ln(p, qbez([hx - 0.99 * R, hy - 0.3 * R], [hx, hy - 0.5 * R], [hx + 0.99 * R, hy - 0.3 * R], 20), 0.012 * R, BLK);
  if (C.cap) {
    const cp = [...ellPts(hx, hy - 0.5 * R, 0.98 * R, 0.55 * R, 180, 360, 0, 30), [hx + 1.25 * R, hy - 0.42 * R], [hx + 0.9 * R, hy - 0.36 * R]];
    fo(p, cp, C.cap, ow * 0.9);
    ln(p, [[hx - 0.9 * R, hy - 0.48 * R], [hx + 0.9 * R, hy - 0.44 * R]], 0.03 * R);
  }
  }
  // mouth
  const M = o.mouthM || MOUTHS[o.mouth || "closed"] || MOUTHS.closed;   // mouthM: [width scale, opening, roundness] already blended by the caller
  const talkOpen = M[1] * R * (o.talkAmp ?? 1);
  const jawOpen = E.jaw * 0.46 * R;
  const H = Math.max(talkOpen, jawOpen);
  const rd = jawOpen > talkOpen ? 0.6 : M[2];
  const W = E.mw * R * 2 * (jawOpen > talkOpen ? 0.95 : M[0]);
  const mx = fx + 0.02 * R, my = fy + 0.43 * R;
  const curve = H > 0.05 * R ? (jawOpen > talkOpen ? E.curve : E.curve * 0.5) : E.curve;
  mouthDraw(p, mx, my, W, curve, E.skew, H, rd, E.teeth, R, C);
  if (C.moustache) { // pencil moustache: two thin tapered halves, lifted with the upper lip
    const yy = my - 0.12 * R - H * 0.22 - E.skew * 0.02 * R;
    for (const sd of [-1, 1]) {
      const sk = sd * E.skew * 0.035 * R;
      const pts = qbez([mx + sd * 0.03 * R, yy - sk * 0.3], [mx + sd * 0.17 * R, yy - 0.05 * R - sk], [mx + sd * 0.3 * R, yy + 0.02 * R - sk * 1.4], 10);
      fo(p, taperPts(pts, 0.07 * R, 0.03 * R), "#57504a", 0.012 * R);
      for (let k = 1; k < 4; k++) { const q = pts[k * 2 + 1]; ln(p, [[q[0], q[1] - 0.015 * R], [q[0] + sd * 0.01 * R, q[1] + 0.02 * R]], 0.008 * R, "#3a3430"); }
    }
  }
  // Mortimer's small round wire glasses, sitting low on the eyes
  if (C.glasses) {
    const gy = eyeY + 0.24 * R + (o.glassesDrop || 0) * R, gr = 0.155 * R;
    const gxs = [exs[0] + 0.06 * R, exs[1] - 0.06 * R];
    gxs.forEach((gx) => {
      const rp = ellPts(gx, gy, gr, gr * 0.95, 0, 360, 0, 32);
      const g = p.g; g.save(); g.globalAlpha = 0.35; fo(p, rp, "#cfe2ee", 0); g.restore();
      p.clip(rp, () => ln(p, [[gx - gr * 0.5, gy + gr * 0.1], [gx + gr * 0.1, gy - gr * 0.55]], 0.03 * R, "rgba(255,255,255,.9)"));
      fo(p, rp, null, 0.026 * R);
    });
    ln(p, qbez([gxs[0] + gr, gy - 0.02 * R], [(gxs[0] + gxs[1]) / 2, gy - 0.09 * R], [gxs[1] - gr, gy - 0.02 * R], 8), 0.022 * R);
    // temple wires out to the sides of the head
    const yT = gy - 0.06 * R;
    ln(p, [[gxs[0] - gr, gy - 0.02 * R], [hx - Math.sqrt(Math.max(0, R * R - (yT - hy) ** 2)) * 0.99, yT - 0.06 * R]], 0.02 * R);
    ln(p, [[gxs[1] + gr, gy - 0.02 * R], [hx + Math.sqrt(Math.max(0, R * R - (yT - hy) ** 2)) * 0.99, yT - 0.06 * R]], 0.02 * R);
  }
};

// mitten hand: solid black oval with a thumb, pointing along `dir` (radians)
const hand = (p, x, y, dir, R, thumbSide = 1) => {
  // (x, y) is the wrist: the mitten starts there and extends along `dir`, so the arm line ends inside its base
  const ca = Math.cos(dir), sa = Math.sin(dir), L = 0.2 * R, W = 0.125 * R;
  const cx = x + ca * L * 0.72, cy = y + sa * L * 0.72, deg = dir * 180 / Math.PI - 90;
  // thumb first (behind), then the palm over its root, so the two read as one mitten
  const tx = cx + Math.cos(dir + thumbSide * 1.35) * W * 0.95 - ca * L * 0.15, ty = cy + Math.sin(dir + thumbSide * 1.35) * W * 0.95 - sa * L * 0.15;
  fo(p, ellPts(tx, ty, 0.055 * R, 0.1 * R, 0, 360, (dir + thumbSide * 0.8) * 180 / Math.PI - 90, 14), BLK, 0);
  fo(p, ellPts(cx, cy, W, L, 0, 360, deg, 28), BLK, 0);
  // wrist: a short black collar so the line flows into the hand
  ln(p, [[x - ca * 0.05 * R, y - sa * 0.05 * R], [cx, cy]], 0.11 * R, BLK);
};


// ---------- held props (drawn under the mitten so the hand grips them). (x,y)=grip point, a=angle of the prop's long axis (radians, 0 = pointing right, +y down) ----------
const PROPS = {
  hammer: (p, x, y, a, R, o = {}) => { const c = Math.cos(a), s = Math.sin(a), L = 0.7 * R, W = 0.07 * R, P = (u, v) => [x + c * u - s * v, y + s * u + c * v];
    fo(p, [P(-0.18 * R, -W), P(L, -W), P(L, W), P(-0.18 * R, W)], "#a8693a", 5);
    fo(p, [P(L - 0.04 * R, -0.2 * R), P(L + 0.2 * R, -0.2 * R), P(L + 0.2 * R, 0.1 * R), P(L - 0.04 * R, 0.1 * R)], "#8d96a3", 6);
    fo(p, [P(L + 0.2 * R, -0.12 * R), P(L + 0.3 * R, -0.08 * R), P(L + 0.3 * R, 0.02 * R), P(L + 0.2 * R, 0.0 * R)], "#8d96a3", 5); },
  tape: (p, x, y, a, R, o = {}) => { const c = Math.cos(a), s = Math.sin(a), P = (u, v) => [x + c * u - s * v, y + s * u + c * v];
    // yellow case; the blade runs out of it along +u for o.len (design units)
    if (o.len) { const L = o.len; fo(p, [P(0.1 * R, -0.03 * R), P(0.1 * R + L, -0.03 * R), P(0.1 * R + L, 0.03 * R), P(0.1 * R, 0.03 * R)], "#f3c623", 3.5);
      for (let k = 1; k * 0.1 * R < L; k++) { const u = 0.1 * R + k * 0.1 * R; p.stroke([P(u, -0.03 * R), P(u, k % 5 === 0 ? 0.0 : -0.012 * R)], 2, "#121212"); } }
    fo(p, [P(-0.2 * R, -0.17 * R), P(0.12 * R, -0.17 * R), P(0.12 * R, 0.17 * R), P(-0.2 * R, 0.17 * R)], "#f3c623", 6); p.ell(...P(-0.05 * R, 0), 0.07 * R, 0.07 * R, "#3a3a3a", 0); },
  plank: (p, x, y, a, R, o = {}) => { const c = Math.cos(a), s = Math.sin(a), L = o.len || 2.2 * R, W = 0.1 * R, P = (u, v) => [x + c * u - s * v, y + s * u + c * v];
    fo(p, [P(-L * 0.5, -W), P(L * 0.5, -W), P(L * 0.5, W), P(-L * 0.5, W)], "#d9a366", 6);
    for (let k = -2; k <= 2; k++) p.stroke([P(k * L * 0.2, -W * 0.7), P(k * L * 0.2 + L * 0.08, W * 0.4)], 2.5, "#a8763f"); },
  pencil: (p, x, y, a, R, o = {}) => { const c = Math.cos(a), s = Math.sin(a), L = 0.45 * R, W = 0.035 * R, P = (u, v) => [x + c * u - s * v, y + s * u + c * v];
    fo(p, [P(-0.1 * R, -W), P(L, -W), P(L + 0.1 * R, 0), P(L, W), P(-0.1 * R, W)], "#f0c040", 3.5); },
};
// two-bone arm: from shoulder s toward hand target t, elbow bends outward/down (bend: +1/-1 flips)
const ik2 = (s, t, L1, L2, sd, bend = 1) => {
  let dx = t[0] - s[0], dy = t[1] - s[1], d = Math.hypot(dx, dy) || 1; const dm = L1 + L2 - 1;
  if (d > dm) { dx *= dm / d; dy *= dm / d; d = dm; }
  const a = (d * d + L1 * L1 - L2 * L2) / (2 * d), h = Math.sqrt(Math.max(0, L1 * L1 - a * a)), ux = dx / d, uy = dy / d;
  const c1 = [s[0] + ux * a - uy * h, s[1] + uy * a + ux * h], c2 = [s[0] + ux * a + uy * h, s[1] + uy * a - ux * h];
  const sc1 = c1[1] * 0.6 + sd * c1[0], sc2 = c2[1] * 0.6 + sd * c2[0];                      // default: elbow lower and outward
  const pick = (sc1 > sc2 ? c1 : c2), other = pick === c1 ? c2 : c1;
  const e = bend > 0 ? pick : other; return { e, h: [s[0] + dx, s[1] + dy] };
};

/** stickFront(p, who, opts)
 * opts: expr (name | params) | exprB + exprT (blend), mouth, talkAmp, look [x,y], blink, facing, pitch, headRoll (deg), bodyLean (deg),
 *       pose: "hang" | "read" | "lap" | "recoil" | "cross" (or poseB + poseT blend), paperY 0 (reading) .. 1 (lowered), paperTilt,
 *       seated (bool), headDX/headDY (design units, head recoil), squash (0..), glassesDrop */
export const stickFront = (p, who, opts = {}) => {
  const C = CAST[who] || {};
  let E = typeof opts.expr === "object" ? opts.expr : EXPR[opts.expr || "neutral"];
  if (opts.exprB) E = blendExpr(E, opts.exprB, opts.exprT || 0);
  // body proportions (per character, C.body): head radius, hip height (smaller = shorter legs), torso length, limb weight, torso width, hand and foot scale
  const B = { R: 165, hip: 672, torso: 240, limb: 1, torsoW: 1, hand: 1, foot: 1, ...(C.body || {}) };
  const R = B.R, cx = 300, sole = 975, seated = !!opts.seated;
  const hipY = seated ? B.hip + 48 : B.hip, torsoLen = B.torso, neckLen = 22;
  // limb style per character: "line" (thin black, default) | "thick" (heavier black) | "pipe" (white tube with a black outline)
  const armStyle = C.armStyle || C.limbStyle || "line", legStyle = C.legStyle || C.limbStyle || "line";
  const limbLine = (style, pts, w) => style === "pipe" ? rimLine(p, pts, "#ffffff", w * 1.9, 4.2) : style === "thick" ? ln(p, pts, w * 1.7) : ln(p, pts, w);
  const armLine = (pts, w) => limbLine(armStyle, pts, w), legLine = (pts, w) => limbLine(legStyle, pts, w);
  const squash = opts.squash || 0;
  const torsoTop = hipY - torsoLen * (1 - squash * 0.5);
  const lean = (opts.bodyLean || 0) * Math.PI / 180;
  // body lean pivots at the hips
  const rotP = (x, y) => { const dx = x - cx, dy = y - hipY; return [cx + dx * Math.cos(lean) - dy * Math.sin(lean), hipY + dx * Math.sin(lean) + dy * Math.cos(lean)]; };
  const neck = rotP(cx + 4, torsoTop);
  const hx = neck[0] + (opts.headDX || 0), hy = neck[1] - neckLen - R + (opts.headDY || 0) + squash * 20;
  // ---- legs + feet ----
  if (seated) {
    for (const sd of [-1, 1]) {
      const hip = [cx + sd * 18, hipY - 6], knee = [cx + sd * 46, hipY + 40], foot = [cx + sd * 52, sole - 12];
      legLine([hip, knee, foot], 9 * B.limb);
      fo(p, ellPts(foot[0] + sd * 14, sole - 8, 34 * B.foot, 14 * B.foot, 0, 360, 0, 20), BLK, 0);
    }
  } else {
    for (const sd of [-1, 1]) {
      const hip = [cx + sd * 16, hipY - 4], foot = [cx + sd * 40, sole - 14];
      legLine([hip, [cx + sd * 24, (hipY + sole) / 2], foot], 9 * B.limb);
      fo(p, ellPts(foot[0] + sd * 14, sole - 9, 42 * B.foot, 17 * B.foot, 0, 360, 0, 20), BLK, 0);
    }
  }
  // ---- arm poses (per side): elbow + hand ----
  const sh = (sd) => rotP(cx + sd * 26, torsoTop + 14);
  const paperY = opts.paperY || 0;
  const pw = 1.1 * R, ph = 1.35 * R, pTop = torsoTop - 0.02 * R + paperY * 1.15 * R, pcx = cx + 6;
  const poses = {
    hang: (sd) => ({ e: [cx + sd * 74, torsoTop + 130], h: [cx + sd * 92, hipY + 30] }),
    read: (sd) => ({ e: [pcx + sd * (pw / 2 + 0.42 * R), pTop + ph * 0.95], h: [pcx + sd * (pw / 2 - 0.02 * R), pTop + ph * 0.72] }),
    lap: (sd) => ({ e: [cx + sd * 78, hipY - 40], h: [cx + sd * 52, hipY + 30] }),
    recoil: (sd) => ({ e: [cx + sd * 96, torsoTop + 120], h: [cx + sd * 92, torsoTop + 10] }),
    cross: (sd) => ({ e: [cx + sd * 66, torsoTop + 128], h: [cx - sd * 34, torsoTop + 96 + sd * 8] }),
  };
  const armAt = (sd) => {
    const ca = opts.arms && opts.arms[sd < 0 ? "L" : "R"]; if (ca) { const s0 = sh(sd); return ik2(s0, [s0[0] + ca.hx, s0[1] + ca.hy], 125, 130, sd, ca.bend ?? 1); }
    const A = poses[opts.pose || "hang"](sd);
    if (opts.poseB) { const B = poses[opts.poseB](sd), t = opts.poseT || 0; return { e: lerpP(A.e, B.e, t), h: lerpP(A.h, B.h, t) }; }
    return A;
  };
  const arms = [-1, 1].map((sd) => ({ sd, s: sh(sd), ...armAt(sd) }));
  const crossed = (opts.pose === "cross" && !opts.poseB) || (opts.poseB === "cross" && (opts.poseT || 0) > 0.5);
  // ---- torso: slim white tapered pill ----
  const tw0 = 30 * B.torsoW, tw1 = 42 * B.torsoW, tb = hipY + 8;
  const tpts = [];
  for (let i = 0; i <= 12; i++) { const t = i / 12, y = lerpN(torsoTop, tb - tw1, t), w = lerpN(tw0, tw1, t * t); tpts.push(rotP(cx + 4 + w, y)); }
  for (let i = 0; i <= 16; i++) { const a = Math.PI * i / 16; tpts.push(rotP(cx + 4 + Math.cos(a) * tw1, tb - tw1 + Math.sin(a) * tw1 * 1.0)); }
  for (let i = 12; i >= 0; i--) { const t = i / 12, y = lerpN(torsoTop, tb - tw1, t), w = lerpN(tw0, tw1, t * t); tpts.push(rotP(cx + 4 - w, y)); }
  for (let i = 1; i < 14; i++) { const a2 = Math.PI + Math.PI * i / 14; tpts.push(rotP(cx + 4 + Math.cos(a2) * tw0, torsoTop + Math.sin(a2) * tw0 * 0.5)); }   // rounded shoulders
  // arms behind the paper are drawn before it; hands on top
  const drawArm = (a) => { armLine([a.s, a.e, a.h], 8.5 * B.limb); };
  fo(p, tpts, "#ffffff", 0);
  p.clip(tpts, () => { p.ell(cx - 40, (torsoTop + tb) / 2 + 30, 34, torsoLen * 0.62, SHADE2, 0); });
  if (C.tie) p.clip(tpts, () => { // knot + blade, hanging from the neck
    const k = rotP(cx + 4, torsoTop + 8), b = [rotP(cx + 4 - 13, torsoTop + 150), rotP(cx + 4, torsoTop + 178), rotP(cx + 4 + 13, torsoTop + 150)];
    fo(p, [rotP(cx + 4 - 12, torsoTop + 2), rotP(cx + 4 + 12, torsoTop + 2), rotP(cx + 4 + 8, torsoTop + 22), rotP(cx + 4 - 8, torsoTop + 22)], C.tie, 3);
    fo(p, [rotP(cx + 4 - 8, torsoTop + 22), rotP(cx + 4 + 8, torsoTop + 22), rotP(cx + 4 + 16, torsoTop + 150), rotP(cx + 4, torsoTop + 182), rotP(cx + 4 - 16, torsoTop + 150)], C.tie, 3);
    ln(p, [rotP(cx + 4 - 5, torsoTop + 60), rotP(cx + 4 + 6, torsoTop + 52)], 4, "rgba(255,255,255,.35)");
  });
  fo(p, tpts, null, 7);
  // neck: thick black stick from the torso top into the head
  const neckTop = [hx - (opts.facing || 0) * 4, hy + R * 0.9];
  ln(p, [rotP(cx + 4, torsoTop + 6), neckTop], 13);
  if (opts.arms) { // free arms (IK) with held props
    for (const a of arms) {
      const ca = opts.arms[a.sd < 0 ? "L" : "R"]; drawArm(a);
      const dir = Math.atan2(a.h[1] - a.e[1], a.h[0] - a.e[0]);
      if (ca && ca.prop) PROPS[ca.prop](p, a.h[0], a.h[1], ca.a ?? dir, R, ca);
      hand(p, a.h[0], a.h[1], dir, R * B.hand, -a.sd);
    }
  } else   if (crossed) { // crossed arms: upper arms first, then forearms across the chest
    for (const a of arms) armLine([a.s, a.e], 8.5 * B.limb);
    for (const a of arms) { armLine([a.e, a.h], 8.5 * B.limb); hand(p, a.h[0], a.h[1], Math.atan2(a.h[1] - a.e[1], a.h[0] - a.e[0]), R * B.hand, -a.sd); }
  } else if ((opts.pose || "hang") === "read") {
    for (const a of arms) drawArm(a);
    // the will: cream sheet with grey ruled lines (no readable text)
    const tilt = (opts.paperTilt || 0) * Math.PI / 180, pc = [pcx, pTop + ph / 2];
    const rot = (x, y) => [pc[0] + (x - pc[0]) * Math.cos(tilt) - (y - pc[1]) * Math.sin(tilt), pc[1] + (x - pc[0]) * Math.sin(tilt) + (y - pc[1]) * Math.cos(tilt)];
    const sheet = [rot(pcx - pw / 2, pTop), rot(pcx + pw / 2, pTop + 4), rot(pcx + pw / 2 + 3, pTop + ph), rot(pcx - pw / 2 - 2, pTop + ph - 3)];
    fo(p, sheet, PAPER, 0);
    p.clip(sheet, () => {
      p.ell(pcx - pw * 0.55, pTop + ph * 0.7, pw * 0.3, ph * 0.6, "#e7e0cc", 0);
      for (let i = 0; i < 9; i++) { const y = pTop + 0.16 * R + i * 0.11 * R, x0 = pcx - pw * 0.36, x1 = pcx + pw * (i % 3 === 2 ? 0.05 : 0.34); ln(p, [rot(x0, y), rot(x1, y + 1)], 3.2, "#b9b2a0"); }
    });
    fo(p, sheet, null, 6);
    for (const a of arms) hand(p, a.h[0], a.h[1], Math.atan2(a.h[1] - a.e[1], a.h[0] - a.e[0]), R * B.hand, -a.sd);
  } else {
    for (const a of arms) { drawArm(a); hand(p, a.h[0], a.h[1], Math.atan2(a.h[1] - a.e[1], a.h[0] - a.e[0]), R * B.hand, -a.sd); }
  }
  // ---- head (roll about the neck) ----
  const roll = (opts.headRoll || 0) + (opts.bodyLean || 0);
  p.rot = roll ? [roll * Math.PI / 180, neckTop[0], neckTop[1]] : null;
  stickHead(p, C, hx, hy, R, { E, mouth: opts.mouth, talkAmp: opts.talkAmp, look: opts.look, blink: opts.blink, facing: opts.facing, pitch: opts.pitch, glassesDrop: opts.glassesDrop });
  p.rot = null;
};
/** head centre in design units for a given pose (for aligning cameras / focus) */
export const stickHeadY = (seated) => (seated ? 720 : 672) - 240 - 22 - 165;
