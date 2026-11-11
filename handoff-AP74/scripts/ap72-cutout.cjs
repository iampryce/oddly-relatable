// AP-72: derive a TRANSPARENT cut-out of corrected v3 (read-only on v3). Pixels are only made transparent/cropped; no redrawing.
// Method: flat-grey background removed by border flood fill (+ small enclosed slivers), then an edge "unmix" turns
// black-to-grey anti-aliasing into black with partial alpha (no grey halo). Eye whites (>=240 luminance) are protected.
const path=require('path'),fs=require('fs'),crypto=require('crypto');
const sharp=require('module').createRequire(path.resolve(__dirname,'../../../skills/directing-stickman-videos/package.json'))('sharp');
const D=path.resolve(__dirname,'../lookdev-richenv')+'/';
const SRC=D+'production-candidates/corrected/candidate-04_corrected-v3.png', OUT=D+'ap72-validation/';
const sha=f=>crypto.createHash('sha256').update(fs.readFileSync(f)).digest('hex');
(async()=>{
  const before=sha(SRC);
  const {data,info}=await sharp(SRC).removeAlpha().raw().toBuffer({resolveWithObject:true});
  const W=info.width,H=info.height,N=W*H;
  const lum=i=>0.299*data[i*3]+0.587*data[i*3+1]+0.114*data[i*3+2];
  const sat=i=>Math.max(data[i*3],data[i*3+1],data[i*3+2])-Math.min(data[i*3],data[i*3+1],data[i*3+2]);
  // background estimate: median luminance of the 8px border
  const bl=[];for(let x=0;x<W;x++)for(const y of[0,4,H-1,H-5])bl.push(lum(y*W+x));bl.sort((a,b)=>a-b);
  const BG=bl[bl.length>>1],lo=bl[Math.floor(bl.length*0.01)],hi=bl[Math.floor(bl.length*0.99)];
  console.log('bg lum',BG,'p1',lo,'p99',hi);
  const isBg=i=>sat(i)<=14&&lum(i)>=BG-28&&lum(i)<=BG+22;   // grey, near the bg level, below eye-white brightness
  const isTight=i=>sat(i)<=8&&Math.abs(lum(i)-BG)<=7;  // pockets: only true background grey, not the black-to-white anti-aliasing ramp of eye whites
  const rm=new Uint8Array(N),q=[];
  const push=i=>{if(!rm[i]&&isBg(i)){rm[i]=1;q.push(i)}};
  for(let x=0;x<W;x++){push(x);push((H-1)*W+x)}for(let y=0;y<H;y++){push(y*W);push(y*W+W-1)}
  while(q.length){const i=q.pop(),x=i%W,y=(i/W)|0;if(x>0)push(i-1);if(x<W-1)push(i+1);if(y>0)push(i-W);if(y<H-1)push(i+W)}
  // enclosed bg-like pockets (e.g. between arm and torso), area <= 4000 and not bright
  const seen=new Uint8Array(N);let pockets=0;
  for(let s=0;s<N;s++){if(rm[s]||seen[s]||!isTight(s))continue;const comp=[s];seen[s]=1;for(let k=0;k<comp.length;k++){const i=comp[k],x=i%W,y=(i/W)|0;for(const j of[x>0?i-1:-1,x<W-1?i+1:-1,y>0?i-W:-1,y<H-1?i+W:-1])if(j>=0&&!seen[j]&&!rm[j]&&isTight(j)){seen[j]=1;comp.push(j)}}
    if(comp.length>=60&&comp.length<=4000){pockets++;for(const i of comp)rm[i]=1}}
  // alpha: removed=0; edge band (within 3px of removed, low saturation, darker than bg) -> black with alpha=1-lum/BG
  const dist=new Uint8Array(N).fill(9);
  for(let i=0;i<N;i++)if(rm[i])dist[i]=0;
  for(let pass=1;pass<=3;pass++)for(let y=1;y<H-1;y++)for(let x=1;x<W-1;x++){const i=y*W+x;if(dist[i]<=pass)continue;if(dist[i-1]<pass||dist[i+1]<pass||dist[i-W]<pass||dist[i+W]<pass)dist[i]=pass}
  const out=Buffer.alloc(N*4);
  for(let i=0;i<N;i++){let r=data[i*3],g=data[i*3+1],b=data[i*3+2],a=255;
    if(rm[i])a=0;else if(dist[i]<=3&&sat(i)<=40){const L=lum(i);a=Math.max(0,Math.min(255,Math.round((1-L/BG)*255*1.0)));if(a>0){r=g=b=0}}  // black-over-grey unmix
    out[i*4]=r;out[i*4+1]=g;out[i*4+2]=b;out[i*4+3]=a}
  // trim to bounding box (+10px pad)
  let x0=W,x1=0,y0=H,y1=0;for(let i=0;i<N;i++)if(out[i*4+3]>8){const x=i%W,y=(i/W)|0;x0=Math.min(x0,x);x1=Math.max(x1,x);y0=Math.min(y0,y);y1=Math.max(y1,y)}
  const pad=10;x0=Math.max(0,x0-pad);y0=Math.max(0,y0-pad);x1=Math.min(W-1,x1+pad);y1=Math.min(H-1,y1+pad);
  const full=await sharp(out,{raw:{width:W,height:H,channels:4}}).png().toBuffer();
  const file=OUT+'character-01_master-v3_cutout_test.png';
  await sharp(full).extract({left:x0,top:y0,width:x1-x0+1,height:y1-y0+1}).png().toFile(file);
  // feet anchor: bottom of the shoes, midway between the two shoe centres (computed in cropped coords)
  const rows=[];for(let y=y1-pad-30;y<=y1-pad;y++){let mn=W,mx=0;for(let x=0;x<W;x++)if(out[(y*W+x)*4+3]>128){mn=Math.min(mn,x);mx=Math.max(mx,x)}rows.push([mn,mx])}
  const feetX=((Math.min(...rows.map(r=>r[0]))+Math.max(...rows.map(r=>r[1])))/2)-x0, feetY=(y1-pad)-y0;
  const meta={source:path.relative(D,SRC),source_sha256_before:before,source_sha256_after:sha(SRC),source_unchanged:before===sha(SRC),
    output:path.relative(D,file),output_sha256:sha(file),crop:{x0,y0,w:x1-x0+1,h:y1-y0+1},feet_anchor:{x:+feetX.toFixed(1),y:feetY},bg_lum:BG,
    enclosed_pockets_removed:pockets,method:'border flood fill + enclosed pocket removal + black-over-grey edge unmix; no redrawing'};
  fs.writeFileSync(OUT+'character-01_master-v3_cutout_test.json',JSON.stringify(meta,null,1));console.log(JSON.stringify(meta,null,1));
})();
