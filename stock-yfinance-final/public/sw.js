const C='sv10';
self.addEventListener('install',e=>{e.waitUntil(caches.open(C).then(c=>c.addAll(['./index.html','./manifest.json'])));self.skipWaiting()});
self.addEventListener('activate',e=>{e.waitUntil(caches.keys().then(ks=>Promise.all(ks.filter(k=>k!==C).map(k=>caches.delete(k)))));self.clients.claim()});
self.addEventListener('fetch',e=>{if(e.request.url.includes('.netlify/functions')||e.request.url.includes('fonts.'))return;e.respondWith(caches.match(e.request).then(c=>c||fetch(e.request).catch(()=>c)))});
