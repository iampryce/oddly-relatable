// AP-59 compositing test (concept code). Reads ONLY the plate, canon and extracted sprite; writes into composite/.
// No generation, no redrawing: one extracted pose (02 worried-phone) is scaled/placed, optionally colour-matched,
// shadowed and occluded by a hand-traced foreground polygon taken from the plate itself.
const path=require('path');
const sharp=require('module').createRequire(path.resolve(__dirname,'../../../skills/directing-stickman-videos/package.json'))('sharp');
const D=path.resolve(__dirname,'../lookdev-richenv')+'/';
const OUT=D+'composite/';
const SPR=D+'extracted/canonical-character-01_02-worried-phone.png';
const PLATE=D+'lookdev-room-empty-03.png', CANON=D+'lookdev-scene-01.png';
const FEET_ANCHOR={x:102,y:560};            // from extracted/manifest.json
const FIT={s:0.95,ox:450,oy:785};            // measured best fit of the sprite onto the canon (see README)
const W=941,H=1672;
// hand-traced foreground (plant+table+books+mug), crop coords from plate y=1100
const FG=[[0,15],[40,40],[60,130],[120,140],[195,200],[200,260],[185,345],[215,352],[260,347],[350,345],[365,372],[365,385],[420,395],[470,430],[490,470],[490,520],[440,572],[0,572]].map(([x,y])=>[x,y+1100]);
async function spriteAt(scale,gain){
  const w=Math.round(270*scale),h=Math.round(571*scale);
  let img=sharp(SPR).resize(w,h,{kernel:'lanczos3'});
  const {data,info}=await img.ensureAlpha().raw().toBuffer({resolveWithObject:true});
  if(gain) for(let i=0;i<data.length;i+=4)for(let c=0;c<3;c++)data[i+c]=Math.min(255,Math.round(data[i+c]*gain[c]));
  return {buf:data,w:info.width,h:info.height};
}
async function shadow(cx,cy,rx,ry,a){
  const svg=`<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}"><defs><filter id="b"><feGaussianBlur stdDeviation="6"/></filter></defs><ellipse cx="${cx}" cy="${cy}" rx="${rx}" ry="${ry}" fill="rgb(35,18,8)" fill-opacity="${a}" filter="url(#b)"/></svg>`;
  return Buffer.from(svg);
}
async function compose({scale,feetX,feetY,gain,shadowA,fg,name}){
  const sp=await spriteAt(scale,gain);
  const left=Math.round(feetX-FEET_ANCHOR.x*scale), top=Math.round(feetY-FEET_ANCHOR.y*scale);
  const layers=[];
  if(shadowA) layers.push({input:await shadow(feetX,feetY-2,70*scale,11*scale,shadowA)});
  layers.push({input:sp.buf,raw:{width:sp.w,height:sp.h,channels:4},left,top});
  if(fg){
    const pts=FG.map(p=>p.join(',')).join(' ');
    const mask=Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}"><polygon points="${pts}" fill="white"/></svg>`);
    const fgBuf=await sharp(PLATE).ensureAlpha().composite([{input:await sharp(mask).png().toBuffer(),blend:'dest-in'}]).png().toBuffer();
    layers.push({input:fgBuf});
  }
  await sharp(PLATE).removeAlpha().composite(layers).png().toFile(OUT+name);
  return {left,top,w:sp.w,h:sp.h};
}
(async()=>{
  // colour gain: mean sprite vs canon over opaque interior pixels at the fitted placement
  const sp=await spriteAt(FIT.s);
  const C=await sharp(CANON).removeAlpha().raw().toBuffer();
  const sum=[0,0,0],cs=[0,0,0];let n=0;
  for(let y=0;y<sp.h;y+=2)for(let x=0;x<sp.w;x+=2){const o=(y*sp.w+x)*4;if(sp.buf[o+3]<250)continue;const co=((FIT.oy+y)*W+FIT.ox+x)*3;
    // restrict to the rust sweater/cream head (skip near-black outlines and mismatched edges)
    const lum=(sp.buf[o]+sp.buf[o+1]+sp.buf[o+2])/3; if(lum<70)continue;
    for(let c=0;c<3;c++){sum[c]+=sp.buf[o+c];cs[c]+=C[co+c]}n++}
  const gain=sum.map((s,c)=>cs[c]/s);
  console.log('colour gain (canon/sprite) R,G,B',gain.map(g=>g.toFixed(3)),'n',n);
  const A=await compose({scale:FIT.s,feetX:FIT.ox+FEET_ANCHOR.x*FIT.s,feetY:FIT.oy+FEET_ANCHOR.y*FIT.s,name:'composite-A-canonical-placement.png'});
  console.log('A',A);
  const B=await compose({scale:FIT.s,feetX:FIT.ox+FEET_ANCHOR.x*FIT.s,feetY:FIT.oy+FEET_ANCHOR.y*FIT.s,gain,shadowA:0.35,name:'composite-B-matched-shadow.png'});
  console.log('B',B);
  const Cc=await compose({scale:1.0,feetX:300,feetY:1488,gain,shadowA:0.3,fg:true,name:'composite-C-foreground-overlap.png'});
  console.log('C',Cc);
  // debug: foreground polygon outline over the plate
  const pts=FG.map(p=>p.join(',')).join(' ');
  const dbg=await sharp(PLATE).removeAlpha().composite([{input:Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}"><polygon points="${pts}" fill="rgba(255,0,255,0.25)" stroke="magenta" stroke-width="2"/></svg>`)}]).png().toBuffer();
  await sharp(dbg).extract({left:0,top:1100,width:W,height:572}).png().toFile(OUT+'debug-foreground-polygon.png');
  // A vs canon: side-by-side + diff heat (crop around character)
  const crop={left:340,top:740,width:420,height:640};
  const cA=await sharp(OUT+'composite-A-canonical-placement.png').extract(crop).png().toBuffer();
  const cC=await sharp(CANON).extract(crop).png().toBuffer();
  const a=await sharp(cA).raw().toBuffer(), c=await sharp(cC).raw().toBuffer();
  const d=Buffer.alloc(a.length);let tot=0;
  for(let i=0;i<a.length;i+=3){const v=Math.min(255,(Math.abs(a[i]-c[i])+Math.abs(a[i+1]-c[i+1])+Math.abs(a[i+2]-c[i+2]))*1.5);d[i]=v;d[i+1]=v;d[i+2]=v;tot+=v/1.5/3}
  console.log('mean abs diff per channel in crop (A vs canon):',(tot/(a.length/3)).toFixed(2));
  const cD=await sharp(d,{raw:{width:crop.width,height:crop.height,channels:3}}).png().toBuffer();
  await sharp({create:{width:crop.width*3+40,height:crop.height,channels:3,background:'#222'}}).composite([{input:cC,left:0,top:0},{input:cA,left:crop.width+20,top:0},{input:cD,left:crop.width*2+40,top:0}]).png().toFile(OUT+'comparison-canon-vs-A-vs-diff.png');
  // contact sheet of A,B,C (full frames, downscaled)
  const th=await Promise.all(['composite-A-canonical-placement.png','composite-B-matched-shadow.png','composite-C-foreground-overlap.png'].map(f=>sharp(OUT+f).resize({height:900}).png().toBuffer()));
  const tw=(await sharp(th[0]).metadata()).width;
  await sharp({create:{width:tw*3+40,height:900,channels:3,background:'#222'}}).composite(th.map((t,i)=>({input:t,left:i*(tw+20),top:0}))).png().toFile(OUT+'contact-sheet-composites.png');
})();
