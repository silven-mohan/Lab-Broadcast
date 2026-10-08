import { createHash, timingSafeEqual } from 'node:crypto';

const sha = (s) => createHash('sha256').update(String(s ?? '')).digest();

// Constant-time password comparison.
export function checkPassword(given) {
  const expected = process.env.SENDER_PASSWORD;
  if (!expected) return false; // fail closed if not configured
  return timingSafeEqual(sha(given), sha(expected));
}
