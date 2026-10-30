// Deixa o sistema instalável no celular e mostra os avisos. Não guarda dados: tudo vem sempre da internet.
self.addEventListener('install',()=>self.skipWaiting());
self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));
self.addEventListener('fetch',e=>{if(e.request.mode==='navigate')e.respondWith(fetch(e.request).catch(()=>new Response('<meta charset=utf-8><body style="background:#0e1014;color:#ddd;font:16px sans-serif;padding:40px">Sem internet. Conecte e abra de novo.</body>',{headers:{'Content-Type':'text/html'}})))});
self.addEventListener('notificationclick',e=>{e.notification.close();e.waitUntil(self.clients.matchAll({type:'window',includeUncontrolled:true}).then(cs=>{for(const c of cs){if('focus' in c)return c.focus()}return self.clients.openWindow('./')}))});
