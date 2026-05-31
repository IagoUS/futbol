// Módulo de comunicación con el backend FastAPI
import { API_URL } from "./config";
const BASE = API_URL;

async function call(path: string, method = "GET", body?: unknown) {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`HTTP ${res.status}: ${text}`);
  }
  return res.json();
}

export const api = {
  login: (email: string, password: string) =>
    call("/auth/login", "POST", { email, password }),
  logout: () => call("/auth/logout", "POST"),
  authStatus: () => call("/auth/status"),
  sync: () => call("/sync", "POST"),
  syncStatus: () => call("/sync/status"),
  mercado: () => call("/mercado"),
  plantilla: () => call("/plantilla"),
  finanzas: () => call("/finanzas"),
  clasificacion: () => call("/clasificacion"),
  transfers: () => call("/transfers"),
  noticias: () => call("/noticias"),
  historialPrecios: () => call("/historial-precios"),
  analizar: () => call("/analizar", "POST"),
  generarConsejos: () => call("/consejos", "POST"),
  getConsejos: () => call("/consejos"),
  logs: () => call("/logs"),
  analizarJugador: (jugadorId: number) => call(`/analizar-jugador/${jugadorId}`),
  historialAnalisis: () => call("/historial-analisis"),
  chat: (mensaje: string) => call("/chat", "POST", { mensaje }),
};
