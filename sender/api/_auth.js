import { createHash, timingSafeEqual } from 'node:crypto';

const sha = (s) => createHash('sha256').update(String(s ?? '')).digest();

// Constant-time password comparison.
export function checkPassword(given) {
  const expected = process.env.SENDER_PASSWORD;
  if (!expected) return false; // fail closed if not configured
  return timingSafeEqual(sha(given), sha(expected));
}

// Optional shared key for receivers. If RECEIVER_KEY is not set, /api/latest is open.
export function checkReceiverKey(given) {
  const expected = process.env.RECEIVER_KEY;
  if (!expected) return true;
  return timingSafeEqual(sha(given), sha(expected));
}
