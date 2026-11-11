// Measures production candidates vs the canon (read-only). Usage: node assess-candidates.cjs
const path=require('path'),crypto=require('crypto'),fs=require('fs');
const sharp=require('module').createRequire(path.resolve(__dirname,'../../../skills/directing-stickman-videos/package.json'))('sharp');
const D=path.resolve(__dirname,'../lookdev-richenv')+'/', P=D+'production-candidates/';
const sha=f=>crypto.createHash('sha256').update(fs.readFileSync(f)).digest('hex');
(async()=>{
  console.log('sha empty-room test',sha(D+'lookdev-room-empty-03.png').slice(0,16),'| candidate 05',sha(P+'production-candidate-05-environment-master.png').slice(0,16));
  const raw=async f=>sharp(f).removeAlpha().raw().toBuffer({resolveWithObject:true});
  const T=await raw(D+'lookdev-room-empty-03.png'),E=await raw(P+'production-candidate-05-environment-master.png'),C=await raw(D+'lookdev-scene-01.png');
  const zones={window:[0,430,190,960],bookshelf:[340,560,690,1230],armchair:[0,950,420,1300],credenza:[665,900,941,1240],rug:[100,1300,941,1560],ceiling:[0,0,941,300],'fg table/plant':[0,1440,490,1672]};
  for(const [n,[x0,y0,x1,y1]] of Object.entries(zones)){let a=0,b=0,k=0,m=[0,0,0],m2=[0,0,0];
    for(let y=y0;y<y1;y+=2)for(let x=x0;x<x1;x+=2){const o=(y*941+x)*3;for(let c=0;c<3;c++){a+=Math.abs(E.data[o+c]-C.data[o+c]);b+=Math.abs(E.data[o+c]-T.data[o+c]);m[c]+=E.data[o+c];m2[c]+=C.data[o+c]}k+=3}
    console.log(n.padEnd(15),'cand vs canon',(a/k).toFixed(1),'| cand vs earlier empty test',(b/k).toFixed(1),'| mean RGB cand',m.map(v=>Math.round(v/(k/3))),'canon',m2.map(v=>Math.round(v/(k/3))));}
  // character: colours and outline
  const ch=await raw(P+'production-candidate-04-character-master.png');
  const W=ch.info.width,H=ch.info.height;let bg=[0,0,0],n=0;for(let i=0;i<40;i++)for(let j=0;j<40;j++){const o=((i)*W+j)*3;for(let c=0;c<3;c++)bg[c]+=ch.data[o+c];n++}
  console.log('char bg RGB',bg.map(v=>Math.round(v/n)),'size',W,H);
  let x0=W,y0=H,x1=0,y1=0;const bgm=bg.map(v=>v/n);
  for(let y=0;y<H;y++)for(let x=0;x<W;x++){const o=(y*W+x)*3;const d=Math.abs(ch.data[o]-bgm[0])+Math.abs(ch.data[o+1]-bgm[1])+Math.abs(ch.data[o+2]-bgm[2]);if(d>60){if(x<x0)x0=x;if(x>x1)x1=x;if(y<y0)y0=y;if(y>y1)y1=y}}
  console.log('figure bbox',x0,y0,x1,y1,'height',y1-y0,'margins L/R/T/B',x0,W-1-x1,y0,H-1-y1);
  const px=(x,y)=>{const o=(y*W+x)*3;return[ch.data[o],ch.data[o+1],ch.data[o+2]]};
  console.log('skin',px(512,420),'sweater',px(512,720),'shoe',px(400,1360),'bg corners',px(5,5),px(1018,1530),px(5,1530));
  const S=await raw(D+'lookdev-scene-01.png');const q=(x,y)=>{const o=(y*941+x)*3;return[S.data[o],S.data[o+1],S.data[o+2]]};
  console.log('canon: skin',q(600,830),'sweater',q(550,980),'shoe',q(520,1310));
})();
