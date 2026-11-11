// AP-74: AP-60 | AP-72 | AP-74 Shot 2 frame comparison (frames extracted from the MP4s; read-only).
const path=require('path');const sharp=require('module').createRequire(path.resolve(__dirname,'../../../skills/directing-stickman-videos/package.json'))('sharp');
const O=path.resolve(__dirname,'../lookdev-richenv/ap74-pose03-test')+'/',T=['0.2','0.5','1.0','1.7'];
const lab=(t,w)=>Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="30"><rect width="100%" height="100%" fill="#1d2433"/><text x="8" y="21" font-family="Arial" font-size="16" fill="#fff">${t}</text></svg>`);
(async()=>{const w=300,h=533,comp=[];
 for(let i=0;i<T.length;i++)for(const [j,n,nm] of [[0,60,'AP-60'],[1,72,'AP-72 (v3)'],[2,74,'AP-74 (pose 03)']]){const x=i*(3*w+30)+j*(w+4);comp.push({input:lab(`${nm} t=${T[i]}s`,w),left:x,top:0},{input:await sharp(O+`frames/ap${n}-t${T[i]}.png`).resize(w,h).toBuffer(),left:x,top:30});}
 await sharp({create:{width:T.length*(3*w+30),height:h+34,channels:3,background:'#e8eaee'}}).composite(comp).png().toFile(O+'compare-shot2-ap60-ap72-ap74.png');
 // native-pixel close-ups (2x nearest): face at t=1.7 (zoom 2.3) and lower body/hands
 const crops=[['face t=1.7s',{left:200,top:0,width:700,height:560}],['hands t=1.7s',{left:60,top:700,width:960,height:420}]];let y=0;const rows=[];
 for(const [name,box] of crops){const W=box.width*1.5|0,H=box.height*1.5|0;
  for(const [k,n,nm] of [[0,60,'AP-60'],[1,72,'AP-72'],[2,74,'AP-74']]){rows.push({input:lab(nm+' '+name,W),left:k*(W+8),top:y},{input:await sharp(O+`frames/ap${n}-t1.7.png`).extract(box).resize({width:W,kernel:'nearest'}).toBuffer(),left:k*(W+8),top:y+30});}
  y+=H+40;}
 const W=(700*1.5|0)>(880*1.5|0)?1:0;await sharp({create:{width:3*((880*1.5|0)+8),height:y,channels:3,background:'#ffffff'}}).composite(rows).png().toFile(O+'closeups-shot2-ap60-ap72-ap74.png');})();
