// AP-63: close-up comparison sheets (new files only, in production-candidates/upscale-tests/).
const path=require('path'),fs=require('fs');
const sharp=require('module').createRequire(path.resolve(__dirname,'../../../skills/directing-stickman-videos/package.json'))('sharp');
const D=path.resolve(__dirname,'../lookdev-richenv')+'/',P=D+'production-candidates/',O=P+'upscale-tests/';
const label=async(buf,text)=>{const m=await sharp(buf).metadata();const svg=`<svg xmlns="http://www.w3.org/2000/svg" width="${m.width}" height="34"><rect width="100%" height="34" fill="#111"/><text x="8" y="23" font-family="Arial" font-size="16" fill="#fff">${text}</text></svg>`;
  return sharp({create:{width:m.width,height:m.height+34,channels:3,background:'#111'}}).composite([{input:Buffer.from(svg),left:0,top:0},{input:buf,left:0,top:34}]).png().toBuffer()};
const row=async(panels,gap=12)=>{const ms=await Promise.all(panels.map(p=>sharp(p).metadata()));const W=ms.reduce((a,m)=>a+m.width,0)+gap*(panels.length-1),H=Math.max(...ms.map(m=>m.height));let x=0;
  return sharp({create:{width:W,height:H,channels:3,background:'#333'}}).composite(panels.map((p,i)=>{const o={input:p,left:x,top:0};x+=ms[i].width+gap;return o})).png().toBuffer()};
(async()=>{
  const C4=P+'production-candidate-04-character-master.png';
  // nohalo 2x of the character (new file)
  const c4=await sharp(C4).removeAlpha().png().toBuffer();
  await sharp(c4).affine([2,0,0,2],{interpolator:'nohalo',idx:0.25,idy:0.25}).png().toFile(O+'char04_2x_nohalo.png');
  // ---- Sheet 1: head close-up at 1080x1920 viewing scale (head ~700 px wide on screen)
  const W=700;
  const sheetHead=await sharp(D+'extracted/canonical-character-01_01-neutral.png').flatten({background:'#c8c8c8'}).extract({left:40,top:5,width:195,height:215}).resize(W,Math.round(215*W/195),{kernel:'lanczos3'}).png().toBuffer();
  const c4Head=await sharp(C4).extract({left:240,top:110,width:540,height:440}).resize(W,Math.round(440*W/540),{kernel:'lanczos3'}).png().toBuffer();
  const c4Up=await sharp(O+'char04_2x_nohalo.png').extract({left:480,top:220,width:1080,height:880}).resize(W,Math.round(880*W/1080),{kernel:'lanczos3'}).png().toBuffer();
  await sharp(await row([await label(sheetHead,'Current sheet pose 01 (270px wide), enlarged to screen'),await label(c4Head,'Candidate 04 native (1024x1536)'),await label(c4Up,'Candidate 04 x2 nohalo (2048x3072)')])).toFile(O+'compare-head-closeup.png');
  // ---- Sheet 1b: hands (the flagged deviation) vs canon hand
  const hand=await sharp(C4).extract({left:290,top:850,width:140,height:130}).resize(420,390,{kernel:'lanczos3'}).png().toBuffer();
  const canonHand=await sharp(D+'lookdev-scene-01.png').extract({left:500,top:1010,width:80,height:70}).resize(420,368,{kernel:'lanczos3'}).png().toBuffer();
  const sheetHand=await sharp(D+'extracted/canonical-character-01_01-neutral.png').flatten({background:'#c8c8c8'}).extract({left:5,top:395,width:90,height:90}).resize(420,420,{kernel:'lanczos3'}).png().toBuffer();
  await sharp(await row([await label(sheetHand,'Approved sheet pose 01 hand (rounded mitt)'),await label(hand,'Candidate 04 hand (curled hook, notched)'),await label(canonHand,'Canon (phone hand region, for reference)')])).toFile(O+'compare-hands.png');
  // ---- Sheet 2: plate close-up at Z~2.3 (470 px of source -> 1080 px on screen), crop 2x2 grid region bookshelf+armchair edge
  const reg={left:360,top:1040,width:470,height:470};const S=700;
  const canon=await sharp(D+'lookdev-scene-01.png').extract(reg).resize(S,S,{kernel:'lanczos3'}).png().toBuffer();
  const c5n=await sharp(P+'production-candidate-05-environment-master.png').extract(reg).resize(S,S,{kernel:'lanczos3'}).png().toBuffer();
  const c5u=await sharp(O+'room05_2x_nohalo.png').extract({left:reg.left*2,top:reg.top*2,width:reg.width*2,height:reg.height*2}).resize(S,S,{kernel:'lanczos3'}).png().toBuffer();
  await sharp(await row([await label(canon,'Canon (character present, same region)'),await label(c5n,'Candidate 05 native 941x1672'),await label(c5u,'Candidate 05 x2 nohalo 1882x3344')])).toFile(O+'compare-plate-closeup.png');
  console.log('ok');
})();
