// usage: node cdp.mjs eval "<js>" | node cdp.mjs shot out.png
const [cmd,arg]=process.argv.slice(2);
const list=await (await fetch('http://127.0.0.1:9333/json')).json();
const pg=list.find(t=>t.type==='page');
const ws=new WebSocket(pg.webSocketDebuggerUrl);let id=0;const pend={};
ws.onmessage=e=>{const m=JSON.parse(e.data);if(pend[m.id]){pend[m.id](m);delete pend[m.id];}};
await new Promise(r=>ws.onopen=r);
const call=(method,params={})=>new Promise(r=>{pend[++id]=r;ws.send(JSON.stringify({id,method,params}));});
if(cmd==='eval'){const r=await call('Runtime.evaluate',{expression:arg,awaitPromise:true,returnByValue:true});console.log(JSON.stringify(r.result.result?.value ?? r.result));}
else{const r=await call('Page.captureScreenshot',{format:'png'});(await import('fs')).writeFileSync(arg,Buffer.from(r.result.data,'base64'));console.log('saved');}
ws.close();
