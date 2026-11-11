// AP-74 (derived from the AP-60 builder, which is left untouched): ONLY AP-60 Shot 2 (shocked, 2.5-4.5 s) as a stand-alone 2 s project; same camera, plate, shadow, scale and anchor; the only change is the character file (skin-corrected pose 03).
// AP-60 technical proof of concept (concept code): builds project.json for the UNMODIFIED renderer.
// Usage: node poc-build-vertical.cjs WORK_DIR   (assets/ and silent.wav must exist there)
// Plate, sprite and shadow share ONE camera transform (no parallax from a single flat plate).
const fs=require('fs'),path=require('path');
const dir=path.resolve(process.argv[2]);
const FPS=30,K=1280/941;                       // design units per plate pixel
const PH=1280*2275.56/1280;                    // design height of the 1080x1920 frame = 2275.56
const PLATE_H=1672*K;                          // 2274.6
const FEET_NATIVE={x:546.9,y:1317};            // measured canonical feet position in plate pixels (see composite/README)
const S=0.95*K;                                // sprite px -> design units at Z=1
const POSES={
  worried:{file:'pose-02-worried-phone.png',w:270,anchor:{x:102,y:560}},
  shocked:{file:'character-01_pose-03-shocked_skin-only_test.png',w:274,anchor:{x:139,y:585}},
  plead:{file:'pose-05-pleading.png',w:273,anchor:{x:130,y:558}},
  deadpan:{file:'pose-06-deadpan-arms-crossed.png',w:271,anchor:{x:134,y:580}},
};
const lerp=(a,b,t)=>a+(b-a)*t, cl=(v,a,b)=>Math.max(a,Math.min(b,v)), ease=t=>{t=cl(t,0,1);return t*t*(3-2*t)};
const r=v=>Math.round(v*100)/100;
const FEET={x:FEET_NATIVE.x*K,y:FEET_NATIVE.y*K};
const HEAD={x:FEET.x+10,y:FEET.y-260};         // look-at point near the face (design units)
const shots=[
  {start:0,end:2.5,pose:'worried',cam:t=>({z:lerp(1.0,1.55,ease(t/2.5)),cx:lerp(640,FEET.x,ease(t/2.5)),cy:lerp(PLATE_H/2,HEAD.y+120,ease(t/2.5))})},
  {start:2.5,end:4.5,pose:'shocked',cam:t=>{let z=1.55,cx=FEET.x,cy=HEAD.y+120;if(t>0.15)z=lerp(1.55,2.3,ease((t-0.15)/0.25));
    if(t>0.4&&t<1.2){const a=14*(1-(t-0.4)/0.8);cx+=Math.sin(t*70)*a;cy+=Math.cos(t*55)*a*0.6}return{z,cx,cy:z>1.6?HEAD.y+40:cy}}},
  {start:4.5,end:6.5,pose:'plead',cam:t=>({z:lerp(2.3,1.45,ease(t/2)),cx:FEET.x,cy:lerp(HEAD.y+40,HEAD.y+140,ease(t/2))})},
  {start:6.5,end:8,pose:'deadpan',cam:t=>({z:lerp(1.45,1.0,ease(t/1.5)),cx:lerp(FEET.x,640,ease(t/1.5)),cy:lerp(HEAD.y+140,PLATE_H/2,ease(t/1.5))})},
];
function clampCam({z,cx,cy}){return{z,cx:cl(cx,640/z,1280-640/z),cy:cl(cy,(PH/2)/z,PLATE_H-(PH/2)/z)}}
const shot2=shots[1];shot2.start=0;shot2.end=2;
const project={version:1,style:'B1',grid:false,width:1080,height:1920,fps:FPS,
  voice:{path:'silent.wav',lead:0,tail:0},
  captions:[{start:0.2,end:1.8,text:'Snap zoom and shake on the shock.'}],
  shots:[shot2].map(s=>{
    const P=POSES[s.pose],span=s.end-s.start,n=Math.round(span*FPS);
    const plate=[],spr=[],shd=[];
    for(let f=0;f<n;f++){
      const t=f/FPS,c=clampCam(s.cam(t)),Z=c.z;
      plate.push({t:r(t),x:r((0-c.cx)*Z+640),y:r((0-c.cy)*Z+PH/2),w:r(1280*Z)});
      const fx=(FEET.x-c.cx)*Z+640,fy=(FEET.y-c.cy)*Z+PH/2,k=S*Z;
      spr.push({t:r(t),x:r(fx-P.anchor.x*k),y:r(fy-P.anchor.y*k),w:r(P.w*k)});
      const sw=190*Z;shd.push({t:r(t),x:r(fx-sw/2),y:r(fy-0.105*sw),w:r(sw)});
    }
    return{start:s.start,end:s.end,layers:[
      {type:'image',path:'assets/plate.png',x:0,y:0,w:1280,keys:plate},
      {type:'image',path:'assets/shadow.png',x:0,y:0,w:190,keys:shd},
      {type:'image',path:'assets/'+P.file,x:0,y:0,w:P.w,keys:spr}]};
  }),sfx:[]};
fs.writeFileSync(path.join(dir,'project.json'),JSON.stringify(project));
console.log('project.json',fs.statSync(path.join(dir,'project.json')).size,'bytes; design height',PH.toFixed(1));
