// AP-67: comparison sheets (new files in production-candidates/corrected/). Original candidate | corrected | canon reference.
const path=require('path');
const sharp=require('module').createRequire(path.resolve(__dirname,'../../../skills/directing-stickman-videos/package.json'))('sharp');
const D=path.resolve(__dirname,'../lookdev-richenv')+'/',P=D+'production-candidates/',O=P+'corrected/';
const ORIG=P+'production-candidate-04-character-master.png',FIX=O+'candidate-04_corrected-v2.png',CANON=D+'lookdev-scene-01.png';
const lab=async(buf,text)=>{const m=await sharp(buf).metadata();const svg=`<svg xmlns="http://www.w3.org/2000/svg" width="${m.width}" height="36"><rect width="100%" height="36" fill="#111"/><text x="8" y="24" font-family="Arial" font-size="16" fill="#fff">${text}</text></svg>`;
 return sharp({create:{width:m.width,height:m.height+36,channels:3,background:'#111'}}).composite([{input:Buffer.from(svg),left:0,top:0},{input:buf,left:0,top:36}]).png().toBuffer()};
const row=async(ps,gap=12)=>{const ms=await Promise.all(ps.map(p=>sharp(p).metadata()));const W=ms.reduce((a,m)=>a+m.width,0)+gap*(ps.length-1),H=Math.max(...ms.map(m=>m.height));let x=0;
 return sharp({create:{width:W,height:H,channels:3,background:'#333'}}).composite(ps.map((p,i)=>{const o={input:p,left:x,top:0};x+=ms[i].width+gap;return o})).png().toBuffer()};
const crop=(f,box,w,h)=>sharp(f).extract(box).resize(w,h,{kernel:'lanczos3'}).png().toBuffer();
(async()=>{
 // 1 full body
 const a=await sharp(ORIG).resize({height:900}).png().toBuffer(),b=await sharp(FIX).resize({height:900}).png().toBuffer();
 await sharp(await row([await lab(a,'Candidate 04 ORIGINAL (unchanged)'),await lab(b,'Candidate 04 CORRECTED v2 (skin + hands)')])).toFile(O+'compare-full-body.png');
 // 2 face + swatches
 const fb={left:240,top:110,width:540,height:450};
 const fa=await crop(ORIG,fb,540,450),fc=await crop(FIX,fb,540,450),fk=await crop(CANON,{left:470,top:760,width:250,height:208},540,450);
 const sw=(rgb,t)=>`<svg xmlns="http://www.w3.org/2000/svg" width="176" height="70"><rect width="176" height="70" fill="rgb(${rgb})"/><text x="6" y="40" font-family="Arial" font-size="14" fill="#000">${t} ${rgb.join(',')}</text></svg>`;
 const r=require(O+'correction-report.json').skin_interior_mean;
 const strip=await sharp({create:{width:540,height:70,channels:3,background:'#333'}}).composite([{input:Buffer.from(sw(r.before,'orig')),left:0,top:0},{input:Buffer.from(sw(r.after,'fixed')),left:182,top:0},{input:Buffer.from(sw(r.canon,'canon')),left:364,top:0}]).png().toBuffer();
 const col=async(img)=>sharp({create:{width:540,height:520,channels:3,background:'#333'}}).composite([{input:img,left:0,top:0},{input:strip,left:0,top:450}]).png().toBuffer();
 await sharp(await row([await lab(await col(fa),'Original'),await lab(await col(fc),'Corrected v2'),await lab(await col(fk),'Canon (reference, lit painted scene)')])).toFile(O+'compare-face-closeup.png');
 // 3 hands
 const hb={left:270,top:830,width:480,height:150};
 const ha=await crop(ORIG,hb,720,225),hc=await crop(FIX,hb,720,225);
 const kcanon=await crop(CANON,{left:500,top:1000,width:90,height:80},360,320),kpose=await sharp(D+'extracted/canonical-character-01_02-worried-phone.png').flatten({background:'#c8c8c8'}).extract({left:70,top:250,width:80,height:60}).resize(360,270,{kernel:'lanczos3'}).png().toBuffer();
 const k=await sharp({create:{width:732,height:320,channels:3,background:'#333'}}).composite([{input:kcanon,left:0,top:0},{input:kpose,left:372,top:0}]).png().toBuffer();
 await sharp(await row([await lab(ha,'Original hands (curled hooks)'),await lab(hc,'Corrected: vector mitts (native res)'),await lab(k,'Canon mitt (left) and approved pose 02 mitt (right)')])).toFile(O+'compare-hands-closeup.png');
 // 4 viewing size: head at 1080x1920 close-up scale
 const vb={left:230,top:100,width:560,height:520};
 await sharp(await row([await lab(await crop(ORIG,vb,700,650),'Original at close-up viewing size'),await lab(await crop(FIX,vb,700,650),'Corrected at close-up viewing size')])).toFile(O+'compare-viewing-size.png');
 console.log('ok');
})();
