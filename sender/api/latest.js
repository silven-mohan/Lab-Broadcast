// Receivers poll this. Returns the newest broadcast event, or 204 if there is none.
// The response is cached at Vercel's edge for 2 seconds so many receivers share one Redis read.
import { checkReceiverKey } from './_auth.js';
import { redis, LATEST_KEY } from './_store.js';

export default async function handler(req, res) {
  if (req.method !== 'GET') return res.status(405).json({ error: 'Method not allowed' });
  if (!checkReceiverKey(req.query?.k)) return res.status(401).json({ error: 'Unauthorized' });

  let raw;
  try {
    raw = await redis(['GET', LATEST_KEY]);
  } catch (err) {
    res.setHeader('Cache-Control', 'no-store');
    return res.status(502).json({ error: 'Store unavailable', detail: err.message });
  }

  res.setHeader('Cache-Control', 'public, s-maxage=2');
  if (!raw) return res.status(204).end();
  res.setHeader('Content-Type', 'application/json');
  return res.status(200).send(raw);
}
