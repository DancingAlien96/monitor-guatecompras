// Login basico en el servidor (Vercel Edge Middleware) con VARIOS usuarios.
//
// Las credenciales se definen en una variable de entorno en Vercel llamada
// LOGIN_USERS, con la lista de "usuario:contrasena" separados por coma o por
// salto de linea. Ejemplo:
//    ana:clave1,luis:clave2,maria:clave3,jose:clave4
// (Las contrasenas pueden contener ":" pero NO comas ni saltos de linea.)
//
// NO van en el codigo, asi nadie las ve. Protege todo el sitio MENOS
// /api/notify (que lo llama el cron y se protege aparte con CRON_SECRET).

export const config = {
  matcher: ['/((?!api/notify).*)'],
};

function credenciales() {
  const map = new Map();
  (process.env.LOGIN_USERS || '').split(/[\n,]/).forEach((par) => {
    const s = par.trim();
    if (!s) return;
    const i = s.indexOf(':');
    if (i > 0) map.set(s.slice(0, i).trim(), s.slice(i + 1));
  });
  // Compatibilidad: tambien admite un usuario suelto si se definio asi.
  if (process.env.LOGIN_USER && process.env.LOGIN_PASS) {
    map.set(process.env.LOGIN_USER, process.env.LOGIN_PASS);
  }
  return map;
}

export default function middleware(req) {
  const creds = credenciales();
  // Si no hay credenciales configuradas, no se bloquea nada (evita dejar el
  // sitio inaccesible por error antes de poner la variable en Vercel).
  if (creds.size === 0) return;

  const auth = req.headers.get('authorization') || '';
  const [scheme, encoded] = auth.split(' ');
  if (scheme === 'Basic' && encoded) {
    let decoded = '';
    try { decoded = atob(encoded); } catch (e) {}
    const i = decoded.indexOf(':');
    const u = decoded.slice(0, i);
    const p = decoded.slice(i + 1);
    if (creds.has(u) && creds.get(u) === p) return; // usuario y clave correctos
  }

  return new Response('Acceso restringido. Inicia sesión.', {
    status: 401,
    headers: {
      'WWW-Authenticate': 'Basic realm="Concursos Guatecompras", charset="UTF-8"',
      'Content-Type': 'text/plain; charset=utf-8',
    },
  });
}
