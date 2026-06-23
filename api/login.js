// Verifica usuario/contrasena (variable LOGIN_USERS) y, si son correctos,
// crea una cookie de sesion FIRMADA (HMAC con AUTH_SECRET). El middleware
// valida esa cookie en cada visita.
const subtle = (globalThis.crypto && globalThis.crypto.subtle) || require('crypto').webcrypto.subtle;

function credenciales() {
  const map = new Map();
  (process.env.LOGIN_USERS || '').split(/[\n,]/).forEach((par) => {
    const s = par.trim();
    if (!s) return;
    const i = s.indexOf(':');
    if (i > 0) map.set(s.slice(0, i).trim(), s.slice(i + 1));
  });
  if (process.env.LOGIN_USER && process.env.LOGIN_PASS) {
    map.set(process.env.LOGIN_USER, process.env.LOGIN_PASS);
  }
  return map;
}

async function hmac(secret, data) {
  const key = await subtle.importKey('raw', new TextEncoder().encode(secret),
    { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const sig = await subtle.sign('HMAC', key, new TextEncoder().encode(data));
  return Buffer.from(new Uint8Array(sig)).toString('base64url');
}

const DIAS = 30;

module.exports = async (req, res) => {
  if (req.method !== 'POST') { res.status(405).json({ error: 'Usa POST' }); return; }
  let body = req.body;
  if (typeof body === 'string') { try { body = JSON.parse(body); } catch (e) { body = {}; } }
  const usuario = (body && body.usuario) || '';
  const clave = (body && body.clave) || '';

  const creds = credenciales();
  if (!creds.size) { res.status(500).json({ error: 'No hay usuarios configurados (LOGIN_USERS)' }); return; }
  if (!creds.has(usuario) || creds.get(usuario) !== clave) {
    res.status(401).json({ error: 'Usuario o contraseña incorrectos' }); return;
  }
  const secret = process.env.AUTH_SECRET;
  if (!secret) { res.status(500).json({ error: 'Falta configurar AUTH_SECRET' }); return; }

  const expira = Date.now() + DIAS * 24 * 60 * 60 * 1000;
  const payloadB64 = Buffer.from(usuario + '|' + expira, 'utf8').toString('base64url');
  const token = payloadB64 + '.' + (await hmac(secret, payloadB64));

  res.setHeader('Set-Cookie',
    'sesion=' + token + '; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=' + (DIAS * 24 * 60 * 60));
  res.status(200).json({ ok: true });
};
