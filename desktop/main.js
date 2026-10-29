// Gestor de Tarefas — programa para Windows.
// Abre o sistema hospedado, então toda melhoria publicada chega sozinha.
const { app, BrowserWindow, shell, Menu, Tray, nativeImage } = require('electron');
const path = require('path');
const URL_SISTEMA = 'https://pazzolline-ai.github.io/gestor-tarefas/';
const HOST = new URL(URL_SISTEMA).host;
const PERMITIDOS = [HOST, 'nhrbbsgmipkwqeqqkgjj.supabase.co', 'cdn.jsdelivr.net', 'cdnjs.cloudflare.com', 'fonts.googleapis.com', 'fonts.gstatic.com'];

if (!app.requestSingleInstanceLock()) { app.quit(); }
app.userAgentFallback = app.userAgentFallback + ' GestorPC/' + app.getVersion();
let win, tray, saindo = false;
const ICONE = () => nativeImage.createFromPath(path.join(__dirname, 'build', 'icon.png'));
function criar() {
  win = new BrowserWindow({
    width: 1400, height: 900, minWidth: 380, minHeight: 500,
    title: 'Gestor de Tarefas', backgroundColor: '#0e1014', autoHideMenuBar: true,
    icon: path.join(__dirname, 'build', 'icon.png'),
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true, spellcheck: true }
  });
  Menu.setApplicationMenu(null);
  win.loadURL(URL_SISTEMA);
  // Links externos (WhatsApp, mapas, e-mail) abrem no navegador padrão
  win.webContents.setWindowOpenHandler(({ url }) => { if (/^(https?:|mailto:|webcal:)/.test(url)) shell.openExternal(url); return { action: 'deny' }; });
  win.webContents.on('will-navigate', (e, url) => {
    try { const h = new URL(url).host; if (h && h !== HOST) { e.preventDefault(); if (/^(https?:|mailto:|webcal:)/.test(url)) shell.openExternal(url); } } catch (_) {}
  });
  // Fechar no X deixa o programa na bandeja (perto do relógio) para os avisos continuarem chegando
  win.on('close', (e) => { if (!saindo) { e.preventDefault(); win.hide(); } });
  // Nome e logo escolhidos no sistema viram o título e o ícone da janela
  win.webContents.on('page-favicon-updated', (_e, urls) => {
    const u = (urls || [])[0]; if (!u || !u.startsWith('data:image/')) { win.setIcon(ICONE()); if (tray) tray.setImage(ICONE().resize({ width: 16, height: 16 })); return; }
    const img = nativeImage.createFromDataURL(u); if (img.isEmpty()) return;
    win.setIcon(img); if (tray) tray.setImage(img.resize({ width: 16, height: 16 }));
  });
  win.on('page-title-updated', (_e, t) => { if (tray) tray.setToolTip(t); });
  win.webContents.on('did-fail-load', (_e, code) => { if (code !== -3) win.loadFile(path.join(__dirname, 'offline.html')); });
  win.webContents.session.setPermissionRequestHandler((wc, perm, cb) => cb(['notifications', 'clipboard-sanitized-write'].includes(perm)));
  win.webContents.on('before-input-event', (e, i) => {
    if ((i.control && i.key.toLowerCase() === 'r') || i.key === 'F5') { win.webContents.reloadIgnoringCache(); e.preventDefault(); }
    if (i.control && i.shift && i.key.toLowerCase() === 'i') e.preventDefault();
  });
}
app.on('second-instance', mostrar);
app.setAppUserModelId('br.com.londerodrigues.gestor');
function mostrar() { if (!win) return; if (win.isMinimized()) win.restore(); win.show(); win.focus(); }
function criarBandeja() {
  tray = new Tray(ICONE().resize({ width: 16, height: 16 }));
  tray.setToolTip('Gestor de Tarefas');
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: 'Abrir', click: mostrar },
    { label: 'Iniciar junto com o Windows', type: 'checkbox', checked: app.getLoginItemSettings().openAtLogin,
      click: (it) => app.setLoginItemSettings({ openAtLogin: it.checked, args: ['--oculto'] }) },
    { type: 'separator' },
    { label: 'Sair', click: () => { saindo = true; app.quit(); } }
  ]));
  tray.on('click', mostrar);
}
app.whenReady().then(() => {
  if (!app.getLoginItemSettings().openAtLogin && !process.argv.includes('--sem-auto')) app.setLoginItemSettings({ openAtLogin: true, args: ['--oculto'] });
  criar(); criarBandeja();
  if (process.argv.includes('--oculto')) win.hide();
});
app.on('before-quit', () => { saindo = true; });
app.on('window-all-closed', () => {});
