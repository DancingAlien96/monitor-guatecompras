// Protege el sitio con una pantalla de login (web/login.html).
// Si no hay una sesion valida (cookie firmada), redirige a /login.html.
//
// Configuracion (variables de entorno en Vercel):
//   LOGIN_USERS  -> "usuario1:clave1,usuario2:clave2,..." (la lista de usuarios)
//   AUTH_SECRET  -> una cadena larga y aleatoria (firma las sesiones)
//
// Si falta alguna, NO bloquea (para no dejar el sitio inaccesible por error).

export const config = {
  matcher: ['/((?!_next).*)'],
};

// Rutas que se sirven SIN sesion: la pantalla de login, su API, y el cron.
const ABIERTAS = ['/login.html', '/api/login', '/api/notify'];

function hayCredenciales() {
  return !!(process.env.LOGIN_USERS || (process.env.LOGIN_USER && process.env.LOGIN_PASS));
}

function leerCookie(req, nombre) {
  const c = req.headers.get('cookie') || '';
  const m = c.match(new RegExp('(?:^|;\\s*)' + nombre + '=([^;]+)'));
  return m ? m[1] : null;
}

async function hmac(secret, data) {
  const key = await crypto.subtle.importKey('raw', new TextEncoder().encode(secret),
    { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const sig = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(data));
  let bin = '';
  const bytes = new Uint8Array(sig);
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

async function sesionValida(token, secret) {
  const p = token.split('.');
  if (p.length !== 2) return false;
  if (p[1] !== (await hmac(secret, p[0]))) return false; // firma incorrecta
  let payload = '';
  try { payload = atob(p[0].replace(/-/g, '+').replace(/_/g, '/')); } catch (e) { return false; }
  const exp = parseInt(payload.split('|')[1] || '0', 10);
  return Date.now() < exp; // no vencida
}

export default async function middleware(req) {
  const pathname = new URL(req.url).pathname;
  if (ABIERTAS.some(function (r) { return pathname === r || pathname.indexOf(r) === 0; })) return;

  // Sin credenciales o sin secreto configurados -> no bloquear.
  if (!hayCredenciales() || !process.env.AUTH_SECRET) return;

  const token = leerCookie(req, 'sesion');
  if (token && (await sesionValida(token, process.env.AUTH_SECRET))) return;

  const url = new URL(req.url);
  url.pathname = '/login.html';
  url.search = '';
  return Response.redirect(url, 302);
}
