// AP-76: comparison sheet (original pose 05, corrected pose 05, canon, v3) + close-ups. Sources are only read, never altered; enlargements use nearest-neighbour so no detail is invented.
const path=require('path');
const sharp=require('module').createRequire(path.resolve(__dirname,'../../../skills/directing-stickman-videos/package.json'))('sharp');
const D=path.resolve(__dirname,'../lookdev-richenv')+'/',O=D+'ap76-pose05-test/';
const ORIG=D+'extracted/canonical-character-01_05-pleading.png',COR=O+'character-01_pose-05-pleading_skin-only_test.png';
const lab=(t,w)=>Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="30"><rect width="100%" height="100%" fill="#1d2433"/><text x="8" y="21" font-family="Arial" font-size="16" fill="#fff">${t}</text></svg>`);
const BG={r:209,g:209,b:209};
async function onGrey(f,box,scale){let i=sharp(f).flatten({background:BG});if(box)i=i.extract(box);return i.resize({width:Math.round((box?box.width:274)*scale),kernel:'nearest'}).toBuffer()}
(async()=>{
 // sheet 1: four full figures at a common height (nearest/lanczos only to fit; labelled)
 const H=560,tiles=[];
 const fig=async(buf)=>sharp(buf).resize({height:H,kernel:'lanczos3'}).toBuffer();
 tiles.push(['1 Original pose 05 (sheet, AP-58 extract)',await fig(await sharp(ORIG).flatten({background:BG}).toBuffer())]);
 tiles.push(['2 Corrected pose 05 (skin only)',await fig(await sharp(COR).flatten({background:BG}).toBuffer())]);
 tiles.push(['3 Canon (scene crop)',await fig(await sharp(D+'lookdev-scene-01.png').extract({left:430,top:780,width:250,height:555}).toBuffer())]);
 tiles.push(['4 Approved v3 (1024x1536, downscaled)',await fig(await sharp(D+'production-candidates/corrected/candidate-04_corrected-v3.png').extract({left:230,top:100,width:570,height:1320}).toBuffer())]);
 const ws=[];for(const [,b] of tiles)ws.push((await sharp(b).metadata()).width);
 const TW=Math.max(...ws)+20,SW=tiles.length*TW+10;const comp=[];
 tiles.forEach(([t,b],i)=>{comp.push({input:lab(t,TW-4),left:5+i*TW,top:5});comp.push({input:b,left:5+i*TW+Math.round((TW-ws[i])/2),top:40})});
 await sharp({create:{width:SW,height:H+50,channels:3,background:'#ffffff'}}).composite(comp).png().toFile(O+'compare-sheet-1-full-figures.png');
 // sheet 2: close-ups original vs corrected (6x nearest), 4 regions
 const regs=[['face + skin',{left:20,top:5,width:235,height:215},3],['wavy mouth + chin',{left:70,top:130,width:120,height:75},6],['clasped hands + arms',{left:50,top:200,width:170,height:120},5],['bent knees + shoes',{left:20,top:400,width:230,height:169},3]];
 const rows=[];let y=0;
 for(const [n,box,sc] of regs){const a=await onGrey(ORIG,box,sc),b=await onGrey(COR,box,sc),w=box.width*sc,h=box.height*sc;rows.push({input:lab('ORIGINAL: '+n,w),left:0,top:y},{input:lab('CORRECTED: '+n,w),left:w+10,top:y},{input:a,left:0,top:y+30},{input:b,left:w+10,top:y+30});y+=h+40;}
 const W2=Math.max(...regs.map(r=>r[1].width*r[2]))*2+10;
 await sharp({create:{width:W2,height:y,channels:3,background:'#ffffff'}}).composite(rows).png().toFile(O+'compare-sheet-2-closeups.png');
})();
