// Gestor de Tarefas — programa para Windows.
// Abre o sistema hospedado, então toda melhoria publicada chega sozinha.
const { app, BrowserWindow, shell, Menu, Notification } = require('electron');
const path = require('path');
const URL_SISTEMA = 'https://pazzolline-ai.github.io/gestor-tarefas/';
const HOST = new URL(URL_SISTEMA).host;
const PERMITIDOS = [HOST, 'nhrbbsgmipkwqeqqkgjj.supabase.co', 'cdn.jsdelivr.net', 'cdnjs.cloudflare.com', 'fonts.googleapis.com', 'fonts.gstatic.com'];

if (!app.requestSingleInstanceLock()) { app.quit(); }
let win;
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
  win.webContents.on('did-fail-load', (_e, code) => { if (code !== -3) win.loadFile(path.join(__dirname, 'offline.html')); });
  win.webContents.session.setPermissionRequestHandler((wc, perm, cb) => cb(['notifications', 'clipboard-sanitized-write'].includes(perm)));
  win.webContents.on('before-input-event', (e, i) => {
    if ((i.control && i.key.toLowerCase() === 'r') || i.key === 'F5') { win.webContents.reloadIgnoringCache(); e.preventDefault(); }
    if (i.control && i.shift && i.key.toLowerCase() === 'i') e.preventDefault();
  });
}
app.on('second-instance', () => { if (win) { if (win.isMinimized()) win.restore(); win.focus(); } });
app.setAppUserModelId('br.com.londerodrigues.gestor');
app.whenReady().then(criar);
app.on('window-all-closed', () => app.quit());
