/**
 * Genera y persiste un user_id unico por tab del navegador.
 * Usa sessionStorage (unico por tab) para que multiples tabs
 * generen IDs diferentes, soportando concurrencia de usuarios.
 */

const SESSION_KEY = 'axxon_user_id';

export function getUserId() {
  let userId = sessionStorage.getItem(SESSION_KEY);
  if (!userId) {
    userId = `user_${crypto.randomUUID()}`;
    sessionStorage.setItem(SESSION_KEY, userId);
  }
  return userId;
}
