// AP-72: evidence sheets AP-60 vs AP-72 (read-only on both MP4 frames).
const path=require('path'),fs=require('fs');
const sharp=require('module').createRequire(path.resolve(__dirname,'../../../skills/directing-stickman-videos/package.json'))('sharp');
const D=path.resolve(__dirname,'../lookdev-richenv/ap72-validation')+'/',T=['0.0','1.2','2.4','3.4','4.6','6.0','7.5'];
const lab=(t,w)=>Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="34"><rect width="100%" height="100%" fill="#1d2433"/><text x="10" y="23" font-family="Arial" font-size="18" fill="#fff">${t}</text></svg>`);
(async()=>{
  // 1) side-by-side: rows = times, cols = AP-60 | AP-72 (scaled to 270x480 each)
  const w=270,h=480,cells=[];
  for(let i=0;i<T.length;i++)for(const n of[60,72]){
    const img=await sharp(D+`frames/ap${n}-t${T[i]}.png`).resize(w,h).toBuffer();
    cells.push({input:img,left:(n===72?w+6:0)+ (i%4)*(2*w+24),top:40+Math.floor(i/4)*(h+40)});
  }
  const SW=4*(2*w+24),SH=40+2*(h+40);
  const heads=[];for(let i=0;i<T.length;i++)heads.push({input:lab(`t=${T[i]}s   AP-60 (left)  |  AP-72 (right)`,2*w+6),left:(i%4)*(2*w+24),top:Math.floor(i/4)*(h+40)+(i>=4?h+40:0)*0});
  await sharp({create:{width:SW,height:SH+ (0),channels:3,background:'#e8eaee'}}).composite([...cells,...heads.map((x,i)=>({...x,top:Math.floor(i/4)*(h+40)+ (Math.floor(i/4)?0:0)}))]).png().toFile(D+'compare-ap60-vs-ap72-sidebyside.png');
  // 2) contact sheet of AP-72
  const cs=[];for(let i=0;i<T.length;i++)cs.push({input:await sharp(D+`frames/ap72-t${T[i]}.png`).resize(w,h).toBuffer(),left:i*(w+8)+8,top:8});
  await sharp({create:{width:T.length*(w+8)+8,height:h+16,channels:3,background:'#1d2433'}}).composite(cs).png().toFile(D+'contact-sheet-ap72.png');
  // 3) close-ups (native 1080x1920 pixels, 2x nearest enlarge): face at t=3.4 (max zoom), hands + body at 1.2 and 6.0
  const crop=async(n,t,box,out)=>sharp(D+`frames/ap${n}-t${t}.png`).extract(box).resize({width:box.width*2,kernel:'nearest'}).toBuffer();
  const sets=[['face (t=3.4s, zoom 2.3)','3.4',{left:200,top:0,width:700,height:560}],['hands/torso (t=1.2s)','1.2',{left:200,top:960,width:680,height:520}],['hands/torso (t=6.0s)','6.0',{left:200,top:880,width:680,height:520}]];
  for(const [name,t,box] of sets){
    const a=await crop(60,t,box),b=await crop(72,t,box),W=box.width*2,H=box.height*2;
    await sharp({create:{width:W*2+12,height:H+34,channels:3,background:'#1d2433'}}).composite([{input:lab('AP-60 '+name,W),left:0,top:0},{input:lab('AP-72 '+name,W),left:W+12,top:0},{input:a,left:0,top:34},{input:b,left:W+12,top:34}]).png().toFile(D+`closeup-${name.split(' ')[0].replace('/','-')}-t${t}.png`);
  }
})();
