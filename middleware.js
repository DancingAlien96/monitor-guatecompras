// Login basico en el servidor (Vercel Edge Middleware).
// El usuario y la contrasena se definen como variables de entorno en Vercel
// (LOGIN_USER y LOGIN_PASS); NO van en el codigo, asi nadie las ve.
//
// Protege todo el sitio MENOS /api/notify (que lo llama el cron y se protege
// aparte con CRON_SECRET).

export const config = {
  matcher: ['/((?!api/notify).*)'],
};

export default function middleware(req) {
  const USER = process.env.LOGIN_USER;
  const PASS = process.env.LOGIN_PASS;

  // Si no se han configurado credenciales, no se bloquea nada (evita dejar
  // el sitio inaccesible por error antes de poner las variables en Vercel).
  if (!USER || !PASS) return;

  const auth = req.headers.get('authorization') || '';
  const [scheme, encoded] = auth.split(' ');
  if (scheme === 'Basic' && encoded) {
    let decoded = '';
    try { decoded = atob(encoded); } catch (e) {}
    const i = decoded.indexOf(':');
    const u = decoded.slice(0, i);
    const p = decoded.slice(i + 1);
    if (u === USER && p === PASS) return; // credenciales correctas -> deja pasar
  }

  return new Response('Acceso restringido. Inicia sesión.', {
    status: 401,
    headers: {
      'WWW-Authenticate': 'Basic realm="Concursos Guatecompras", charset="UTF-8"',
      'Content-Type': 'text/plain; charset=utf-8',
    },
  });
}
