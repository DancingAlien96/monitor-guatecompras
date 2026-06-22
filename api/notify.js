// Envia el recordatorio push a todos los dispositivos suscritos.
// Lo dispara Vercel Cron a las horas configuradas (ver vercel.json).
// NO lee la API de Guatecompras (solo recuerda), por eso corre bien en la nube.
const { Redis } = require('@upstash/redis');
const webpush = require('web-push');

const redis = new Redis({
  url: process.env.UPSTASH_REDIS_REST_URL || process.env.KV_REST_API_URL,
  token: process.env.UPSTASH_REDIS_REST_TOKEN || process.env.KV_REST_API_TOKEN,
});

webpush.setVapidDetails(
  process.env.VAPID_SUBJECT || 'mailto:soporte@piums.io',
  process.env.VAPID_PUBLIC,
  process.env.VAPID_PRIVATE
);

module.exports = async (req, res) => {
  // Si defines CRON_SECRET, solo se acepta la llamada del cron de Vercel.
  if (process.env.CRON_SECRET && req.headers.authorization !== 'Bearer ' + process.env.CRON_SECRET) {
    res.status(401).json({ error: 'no autorizado' }); return;
  }
  try {
    const all = (await redis.hgetall('subs')) || {};
    const subs = Object.values(all);
    const payload = JSON.stringify({
      title: 'Recordatorio Guatecompras',
      body: 'Revisa los concursos nuevos de compra directa: abre la app y toca Buscar. 💧',
      url: './',
    });
    let enviadas = 0, eliminadas = 0;
    for (const sub of subs) {
      try { await webpush.sendNotification(sub, payload); enviadas++; }
      catch (e) {
        // 404/410 = suscripcion vencida -> se limpia
        if (e.statusCode === 404 || e.statusCode === 410) { await redis.hdel('subs', sub.endpoint); eliminadas++; }
      }
    }
    res.status(200).json({ enviadas: enviadas, eliminadas: eliminadas, total: subs.length });
  } catch (e) {
    res.status(500).json({ error: String((e && e.message) || e) });
  }
};
