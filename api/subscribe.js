// Recibe la suscripcion push del navegador y la guarda (Upstash Redis).
const { Redis } = require('@upstash/redis');

const redis = new Redis({
  url: process.env.UPSTASH_REDIS_REST_URL || process.env.KV_REST_API_URL,
  token: process.env.UPSTASH_REDIS_REST_TOKEN || process.env.KV_REST_API_TOKEN,
});

module.exports = async (req, res) => {
  if (req.method !== 'POST') { res.status(405).json({ error: 'Usa POST' }); return; }
  try {
    let sub = req.body;
    if (typeof sub === 'string') sub = JSON.parse(sub);
    if (!sub || !sub.endpoint) { res.status(400).json({ error: 'Suscripcion invalida' }); return; }
    // Se indexa por endpoint para no duplicar el mismo dispositivo.
    await redis.hset('subs', { [sub.endpoint]: sub });
    res.status(200).json({ ok: true });
  } catch (e) {
    res.status(500).json({ error: String((e && e.message) || e) });
  }
};
