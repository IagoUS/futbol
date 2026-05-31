// Pestaña Cerebro IA — sincronización, consejos, análisis individual
import React, { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { api } from "../api";

interface SyncProgress {
  scraper: string;
  estado: string;
  mensaje: string;
  timestamp: string;
}

interface SyncStatus {
  running: boolean;
  progress: SyncProgress[];
  last_sync: string | null;
  error: string | null;
}

interface Consejo {
  contenido: string;
  creado: string;
}

interface JugadorPlantilla {
  id: number;
  nombre: string;
  posicion: string;
  precio_actual: number;
}

interface AnalisisData {
  titularidad?: {
    condicion?: string;
    competencia?: string;
    probabilidad_titular_proximo_partido?: string;
    fuentes?: Record<string, { recomendacion: string | null; probabilidad_titular: string | null; url: string | null }>;
  };
  forma?: {
    ultimos_3_partidos?: Array<{ rival: string; rating_sofascore: number | null; minutos: number | null; fecha: string; goles: number | null; asistencias: number | null }>;
    tendencia_rating?: string;
    tendencia_minutos?: string;
    fuente_sofascore?: string | null;
  };
  proximo_rival_mundial?: { nombre: string; fecha: string; nivel: string; ranking_fifa_rival: number | null; analisis: string };
  grupo_mundial?: { nombre_grupo: string; equipos: string[]; probabilidad_clasificacion: string; analisis: string };
  lesiones_sanciones?: { estado: string; detalle: string | null; fuente: string | null };
  apuestas?: { cuota_marcar_gol: number | null; cuota_asistencia: number | null; fuente_url: string | null };
  fantasy_especialistas?: Record<string, { recomendacion: string | null; puntuacion_esperada: number | null; url: string | null }>;
  veredicto?: { decision: string; justificacion: string; confianza: string; precio_minimo_venta_recomendado: number | null; riesgo_principal: string };
  raw?: string;
  error?: string;
}

interface AnalisisResult {
  ok: boolean;
  desde_cache: boolean;
  fecha_analisis: string;
  data: AnalisisData;
  jugador_nombre?: string;
  jugador_id?: number;
}

interface ChatMessage {
  role: "user" | "ia";
  texto: string;
  timestamp: string;
}

const CHAT_STORAGE_KEY = "cerebro-ia-chat";

interface HistorialEntry {
  id: number;
  jugador_id: number;
  jugador_nombre: string;
  fecha: string;
  veredicto_decision: string | null;
  veredicto_confianza: string | null;
  tipo_consulta: string;
  json_respuesta: string | null;
}

const CONSEJOS_META: Record<string, { emoji: string; titulo: string; color: string }> = {
  COMPRAR: { emoji: "🟢", titulo: "FICHAR AHORA", color: "#00ff88" },
  VENDER: { emoji: "🔴", titulo: "VENDER ANTES DE QUE BAJE", color: "#e74c3c" },
  "11_IDEAL": { emoji: "⚽", titulo: "11 IDEAL PRÓXIMA JORNADA", color: "#4a90e2" },
  ESPECULACION: { emoji: "📈", titulo: "CHOLLOS DE ESPECULACIÓN", color: "#f39c12" },
  ALERTA_RIVALES: { emoji: "🕵️", titulo: "ALERTA DE RIVALES", color: "#9b59b6" },
};

const VEREDICTO_COLOR: Record<string, string> = {
  "FICHAR": "#00ff88",
  "RETIRAR VENTA": "#00ff88",
  "MANTENER EN VENTA": "#f39c12",
  "NO FICHAR": "#f39c12",
  "VENDER URGENTE": "#e74c3c",
};

const NIVEL_COLOR: Record<string, string> = { débil: "#00ff88", medio: "#f39c12", fuerte: "#e74c3c" };
const PROB_COLOR: Record<string, string> = { alta: "#00ff88", media: "#f39c12", baja: "#e74c3c" };
const ESTADO_COLOR: Record<string, string> = { disponible: "#00ff88", duda: "#f39c12", lesionado: "#e74c3c", sancionado: "#e74c3c" };

const fmt = (n: number) =>
  n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}M€` : n >= 1000 ? `${(n / 1000).toFixed(0)}K€` : `${n}€`;

const posColor: Record<string, string> = {
  Portero: "#4a90e2", Defensa: "#27ae60", Centrocampista: "#f39c12", Delantero: "#e74c3c",
};
const posLetter: Record<string, string> = {
  Portero: "P", Defensa: "D", Centrocampista: "C", Delantero: "DL",
};

function Block({ title, color, children }: { title: string; color: string; children: React.ReactNode }) {
  return (
    <div style={{ background: "#111a14", border: `1px solid ${color}33`, borderRadius: "8px", marginBottom: "1rem", overflow: "hidden" }}>
      <div style={{ background: `${color}18`, borderBottom: `1px solid ${color}33`, padding: "0.6rem 1rem", color, fontWeight: 700, fontFamily: "monospace", fontSize: "0.8rem", letterSpacing: "0.05em" }}>
        {title}
      </div>
      <div style={{ padding: "1rem" }}>{children}</div>
    </div>
  );
}

function Pill({ label, color }: { label: string; color: string }) {
  return (
    <span style={{ background: `${color}22`, color, border: `1px solid ${color}44`, padding: "2px 10px", borderRadius: "4px", fontSize: "0.75rem", fontWeight: 700 }}>
      {label}
    </span>
  );
}

interface HistorialTabProps {
  historial: HistorialEntry[];
  historialLoading: boolean;
  veredictoColor: (d: string) => string;
  onOpenAnalisis: (id: number, nombre: string) => void;
}

function HistorialTab({ historial, historialLoading, veredictoColor, onOpenAnalisis }: HistorialTabProps) {
  const [expandedConsejos, setExpandedConsejos] = useState<Set<number>>(new Set());
  const [expandedSecciones, setExpandedSecciones] = useState<Set<string>>(new Set());

  if (historialLoading) return <div style={{ textAlign: "center", color: "#00ff88", padding: "3rem", fontFamily: "monospace" }}>Cargando historial...</div>;
  if (historial.length === 0) return <div style={{ textAlign: "center", color: "#555", padding: "3rem" }}>Sin historial — genera consejos o analiza un jugador</div>;

  const consejos = historial.filter((h) => h.tipo_consulta === "consejos_generales");
  const chats = historial.filter((h) => h.tipo_consulta === "chat");
  const analisis = historial.filter((h) => !["consejos_generales", "chat"].includes(h.tipo_consulta || ""));

  const SectionHeader = ({ label, count, color }: { label: string; count: number; color: string }) => (
    <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", margin: "1.25rem 0 0.5rem" }}>
      <div style={{ flex: 1, height: 1, background: "#1a2e1f" }} />
      <span style={{ color, fontFamily: "monospace", fontSize: "0.78rem", fontWeight: 700 }}>{label} ({count})</span>
      <div style={{ flex: 1, height: 1, background: "#1a2e1f" }} />
    </div>
  );

  return (
    <div>
      {/* ── Consejos Generales ── */}
      {consejos.length > 0 && (
        <>
          <SectionHeader label="🧠 CONSEJOS GENERALES" count={consejos.length} color="#9b59b6" />
          {consejos.map((h) => {
            const isOpen = expandedConsejos.has(h.id);
            let parsed: Record<string, string> = {};
            try { parsed = JSON.parse(h.json_respuesta || "{}"); } catch {}
            return (
              <div key={h.id} style={{ background: "#111a14", border: "1px solid #9b59b644", borderRadius: "8px", marginBottom: "0.5rem" }}>
                <button
                  onClick={() => setExpandedConsejos((prev) => { const n = new Set(prev); isOpen ? n.delete(h.id) : n.add(h.id); return n; })}
                  style={{ width: "100%", background: "#9b59b618", border: "none", padding: "0.65rem 1rem", display: "flex", alignItems: "center", gap: "0.75rem", cursor: "pointer" }}
                >
                  <span style={{ color: "#9b59b6", fontSize: "1rem" }}>📋</span>
                  <span style={{ color: "#9b59b6", fontWeight: 700, fontFamily: "monospace", fontSize: "0.82rem", flex: 1, textAlign: "left" }}>
                    {h.jugador_nombre.replace("CONSEJOS_GENERALES_", "")}
                  </span>
                  <span style={{ color: "#555", fontSize: "0.7rem" }}>{new Date(h.fecha).toLocaleString("es-ES")}</span>
                  <span style={{ color: "#9b59b6", fontSize: "0.75rem", transform: isOpen ? "rotate(180deg)" : "rotate(0)", transition: "transform 0.2s" }}>▼</span>
                </button>
                {isOpen && (
                  <div style={{ padding: "0.75rem" }}>
                    {Object.entries(CONSEJOS_META).map(([tipo, meta]) => {
                      const secKey = `${h.id}-${tipo}`;
                      const secOpen = expandedSecciones.has(secKey);
                      const texto = parsed[tipo];
                      if (!texto) return null;
                      return (
                        <div key={tipo} style={{ background: "#0a0f0d", border: `1px solid ${meta.color}33`, borderRadius: "6px", marginBottom: "0.4rem" }}>
                          <button
                            onClick={() => setExpandedSecciones((prev) => { const n = new Set(prev); secOpen ? n.delete(secKey) : n.add(secKey); return n; })}
                            style={{ width: "100%", background: "transparent", border: "none", padding: "0.4rem 0.75rem", display: "flex", alignItems: "center", gap: "0.5rem", cursor: "pointer" }}
                          >
                            <span>{meta.emoji}</span>
                            <span style={{ color: meta.color, fontFamily: "monospace", fontSize: "0.75rem", fontWeight: 700, flex: 1, textAlign: "left" }}>{meta.titulo}</span>
                            <span style={{ color: meta.color, fontSize: "0.7rem", transform: secOpen ? "rotate(180deg)" : "rotate(0)", transition: "transform 0.2s" }}>▼</span>
                          </button>
                          {secOpen && (
                            <div style={{ padding: "0.5rem 0.75rem 0.75rem", color: "#ccc", fontSize: "0.85rem", lineHeight: 1.55 }}>
                              <ReactMarkdown>{texto}</ReactMarkdown>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </>
      )}

      {/* ── Chat ── */}
      {chats.length > 0 && (
        <>
          <SectionHeader label="💬 CHAT" count={chats.length} color="#4a90e2" />
          {chats.map((h) => (
            <div key={h.id} style={{ background: "#111a14", border: "1px solid #4a90e244", borderRadius: "8px", padding: "0.65rem 1rem", marginBottom: "0.4rem", display: "flex", gap: "1rem", alignItems: "center", flexWrap: "wrap" }}>
              <span style={{ color: "#4a90e2", fontSize: "0.95rem" }}>💬</span>
              <span style={{ color: "#ccc", fontSize: "0.85rem", flex: 1, fontStyle: "italic" }}>"{h.jugador_nombre}"</span>
              <span style={{ color: "#555", fontSize: "0.7rem" }}>{new Date(h.fecha).toLocaleString("es-ES")}</span>
            </div>
          ))}
        </>
      )}

      {/* ── Análisis Individual ── */}
      {analisis.length > 0 && (
        <>
          <SectionHeader label="🔍 ANÁLISIS INDIVIDUAL" count={analisis.length} color="#00ff88" />
          {analisis.map((h) => {
            const horasAtras = (Date.now() - new Date(h.fecha).getTime()) / 3_600_000;
            const esReciente = horasAtras < 24;
            const rawDecision = h.veredicto_decision?.replace(/^"|"$/g, "") || "";
            const col = veredictoColor(rawDecision);
            return (
              <div
                key={h.id}
                onClick={() => onOpenAnalisis(h.jugador_id, h.jugador_nombre)}
                style={{ background: "#111a14", border: "1px solid #1a2e1f", borderRadius: "8px", padding: "0.75rem 1rem", marginBottom: "0.4rem", display: "flex", alignItems: "center", gap: "1rem", flexWrap: "wrap", cursor: "pointer" }}
              >
                <span style={{ fontWeight: 600, color: "#ddd", minWidth: 150 }}>{h.jugador_nombre}</span>
                {rawDecision && <Pill label={rawDecision} color={col} />}
                {h.veredicto_confianza && <Pill label={`Confianza: ${h.veredicto_confianza?.replace(/^"|"$/g, "")}`} color={PROB_COLOR[h.veredicto_confianza?.replace(/^"|"$/g, "")] || "#aaa"} />}
                <span style={{ marginLeft: "auto", fontSize: "0.75rem", color: esReciente ? "#00ff88" : "#f39c12", fontWeight: 600 }}>
                  {esReciente ? "✓ Caché válida" : "⚠️ Actualizar"}
                </span>
                <span style={{ color: "#555", fontSize: "0.72rem" }}>{new Date(h.fecha).toLocaleString("es-ES")}</span>
              </div>
            );
          })}
        </>
      )}
    </div>
  );
}

export default function CerebroIA() {
  const [syncStatus, setSyncStatus] = useState<SyncStatus>({
    running: false,
    progress: [],
    last_sync: null,
    error: null,
  });
  const [consejos, setConsejos] = useState<Record<string, Consejo>>({});
  const [loadingConsejos, setLoadingConsejos] = useState(false);
  const [iaError, setIaError] = useState<string | null>(null);
  const pollingRef = useRef<NodeJS.Timeout | null>(null);

  const [activeSection, setActiveSection] = useState<"consejos" | "analisis" | "historial">("consejos");
  const [plantilla, setPlantilla] = useState<JugadorPlantilla[]>([]);
  const [analizando, setAnalizando] = useState<number | null>(null);
  const [analisisActivo, setAnalisisActivo] = useState<(AnalisisResult & { jugador_nombre: string; jugador_id: number }) | null>(null);
  const [analisisError, setAnalisisError] = useState<string | null>(null);
  const [historial, setHistorial] = useState<HistorialEntry[]>([]);
  const [historialLoading, setHistorialLoading] = useState(false);
  const [expandedConsejos, setExpandedConsejos] = useState<Set<string>>(new Set());

  const [chatMensajes, setChatMensajes] = useState<ChatMessage[]>(() => {
    try {
      const saved = localStorage.getItem(CHAT_STORAGE_KEY);
      return saved ? JSON.parse(saved) : [];
    } catch { return []; }
  });
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const chatEndRef = useRef<HTMLDivElement>(null);

  const saveChatToStorage = (msgs: ChatMessage[]) => {
    try { localStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(msgs)); } catch {}
  };

  const handleChatSend = async () => {
    const texto = chatInput.trim();
    if (!texto || chatLoading) return;
    const userMsg: ChatMessage = { role: "user", texto, timestamp: new Date().toISOString() };
    const updated = [...chatMensajes, userMsg];
    setChatMensajes(updated);
    saveChatToStorage(updated);
    setChatInput("");
    setChatLoading(true);
    try {
      const r = await api.chat(texto);
      const iaMsg: ChatMessage = { role: "ia", texto: r.respuesta, timestamp: r.timestamp };
      const withIa = [...updated, iaMsg];
      setChatMensajes(withIa);
      saveChatToStorage(withIa);
    } catch (e: unknown) {
      const errMsg: ChatMessage = { role: "ia", texto: `⚠️ Error: ${e instanceof Error ? e.message : String(e)}`, timestamp: new Date().toISOString() };
      const withErr = [...updated, errMsg];
      setChatMensajes(withErr);
      saveChatToStorage(withErr);
    } finally {
      setChatLoading(false);
    }
  };

  const handleClearChat = () => {
    setChatMensajes([]);
    try { localStorage.removeItem(CHAT_STORAGE_KEY); } catch {}
  };

  const toggleConsejo = (tipo: string) =>
    setExpandedConsejos((prev) => {
      const next = new Set(prev);
      next.has(tipo) ? next.delete(tipo) : next.add(tipo);
      return next;
    });

  // Polling del estado de sincronización
  const startPolling = useCallback(() => {
    pollingRef.current = setInterval(async () => {
      try {
        const status: SyncStatus = await api.syncStatus();
        setSyncStatus(status);
        if (!status.running) {
          clearInterval(pollingRef.current!);
          pollingRef.current = null;
        }
      } catch (_) {}
    }, 2000);
  }, []);

  useEffect(() => {
    api.syncStatus().then(setSyncStatus).catch(() => {});
    api.getConsejos().then((d) => setConsejos(d.data || {})).catch(() => {});
    api.plantilla().then((d) => setPlantilla(d.data || [])).catch(() => {});
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
    };
  }, []);

  useEffect(() => {
    if (chatEndRef.current) {
      chatEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [chatMensajes, chatLoading]);

  const handleAnalizar = async (jugador: JugadorPlantilla) => {
    setAnalizando(jugador.id);
    setAnalisisError(null);
    setActiveSection("analisis");
    try {
      const r = await api.analizarJugador(jugador.id);
      setAnalisisActivo({ ...r, jugador_nombre: jugador.nombre, jugador_id: jugador.id });
    } catch (e: unknown) {
      setAnalisisError(e instanceof Error ? e.message : String(e));
      setAnalisisActivo(null);
    } finally {
      setAnalizando(null);
    }
  };

  const loadHistorial = async () => {
    setHistorialLoading(true);
    try {
      const r = await api.historialAnalisis();
      setHistorial(r.data || []);
    } catch (_) {}
    finally { setHistorialLoading(false); }
  };

  const handleVerHistorial = () => {
    setActiveSection("historial");
    loadHistorial();
  };

  const handleSync = async () => {
    try {
      await api.sync();
      startPolling();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setSyncStatus((s) => ({ ...s, error: msg }));
    }
  };

  const handleGenerarConsejos = async () => {
    setLoadingConsejos(true);
    setIaError(null);
    try {
      await api.analizar();
      const r = await api.generarConsejos();
      if (r.ok) {
        const d = await api.getConsejos();
        setConsejos(d.data || {});
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setIaError(msg);
    } finally {
      setLoadingConsejos(false);
    }
  };

  const scraperLabels: Record<string, string> = {
    jugadores_mundo: "Catálogo Mundial CF",
    mi_plantilla: "Mi Plantilla",
    mercado: "Mercado de Fichajes",
    finanzas: "Saldo y Finanzas",
    movimientos_rivales: "Movimientos de Rivales",
    clasificacion: "Clasificación",
    plantillas_rivales: "Plantillas de Rivales",
    calendario: "Calendario",
    prob_titularidad: "Probabilidad de Titularidad",
    proyecciones: "Proyecciones de Rendimiento",
    historial_precios: "Historial de Precios",
    noticias: "Noticias y Alertas",
  };

  const totalScrapers = 12;
  const completedScrapers = syncStatus.progress.length;
  const progressPct = (completedScrapers / totalScrapers) * 100;

  const veredictoColor = (dec: string) => {
    for (const k of Object.keys(VEREDICTO_COLOR)) {
      if (dec?.toUpperCase().includes(k)) return VEREDICTO_COLOR[k];
    }
    return "#aaa";
  };

  const tabBtn = (id: "consejos" | "analisis" | "historial", label: string) => (
    <button
      onClick={() => id === "historial" ? handleVerHistorial() : setActiveSection(id)}
      style={{
        background: "transparent",
        border: "none",
        borderBottom: activeSection === id ? "2px solid #00ff88" : "2px solid transparent",
        color: activeSection === id ? "#00ff88" : "#666",
        padding: "10px 18px",
        cursor: "pointer",
        fontWeight: activeSection === id ? 700 : 400,
        fontSize: "0.9rem",
        transition: "all 0.15s",
      }}
    >{label}</button>
  );

  return (
    <div style={{ padding: "1rem", maxWidth: "960px", margin: "0 auto" }}>

      {/* ── Sync + nav bar ── */}
      <div style={{ background: "#111a14", border: "2px solid #00ff88", borderRadius: "12px", padding: "1.5rem 2rem", marginBottom: "1.5rem", display: "flex", flexWrap: "wrap", alignItems: "center", gap: "1rem", justifyContent: "space-between" }}>
        <div>
          <button
            onClick={handleSync}
            disabled={syncStatus.running}
            style={{ background: syncStatus.running ? "#1a2e1f" : "#00ff88", color: syncStatus.running ? "#00ff88" : "#0a0f0d", border: syncStatus.running ? "2px solid #00ff88" : "none", padding: "12px 32px", borderRadius: "8px", fontSize: "1rem", fontWeight: 700, cursor: syncStatus.running ? "not-allowed" : "pointer" }}
          >
            {syncStatus.running ? "⏳ SINCRONIZANDO..." : "🔄 SINCRONIZAR TODO"}
          </button>
          {syncStatus.last_sync && (
            <div style={{ color: "#555", fontSize: "0.75rem", marginTop: "4px" }}>
              Última sync: {new Date(syncStatus.last_sync).toLocaleString("es-ES")}
            </div>
          )}
        </div>
        <button
          onClick={handleGenerarConsejos}
          disabled={loadingConsejos}
          style={{ background: loadingConsejos ? "#1a1a2e" : "linear-gradient(135deg, #9b59b6, #6c3483)", color: "#fff", border: "none", padding: "12px 28px", borderRadius: "8px", fontSize: "0.95rem", fontWeight: 700, cursor: loadingConsejos ? "not-allowed" : "pointer", opacity: loadingConsejos ? 0.7 : 1 }}
        >
          {loadingConsejos ? "🧠 Consultando..." : "🧠 GENERAR CONSEJOS"}
        </button>
      </div>

      {syncStatus.error && (
        <div style={{ background: "#2d0a0a", border: "1px solid #e74c3c", borderRadius: "6px", padding: "0.75rem 1rem", color: "#e74c3c", marginBottom: "1rem", fontSize: "0.9rem" }}>
          ⚠️ {syncStatus.error}
        </div>
      )}
      {iaError && (
        <div style={{ color: "#e74c3c", marginBottom: "0.75rem", fontSize: "0.85rem" }}>⚠️ {iaError}</div>
      )}

      {/* Progress */}
      {(syncStatus.running || syncStatus.progress.length > 0) && (
        <div style={{ background: "#111a14", border: "1px solid #1a2e1f", borderRadius: "10px", padding: "1.25rem", marginBottom: "1.5rem" }}>
          <div style={{ display: "flex", justifyContent: "space-between", color: "#00ff88", fontWeight: 700, fontFamily: "monospace", marginBottom: "0.5rem" }}>
            <span>PROGRESO</span><span>{completedScrapers}/{totalScrapers}</span>
          </div>
          <div style={{ height: "6px", background: "#1a2e1f", borderRadius: "3px", overflow: "hidden", marginBottom: "0.75rem" }}>
            <div style={{ width: `${progressPct}%`, height: "100%", background: "#00ff88", transition: "width 0.5s ease" }} />
          </div>
          <div style={{ fontFamily: "monospace", fontSize: "0.82rem" }}>
            {Object.keys(scraperLabels).map((key, i) => {
              const log = syncStatus.progress.find((p) => p.scraper === key);
              return (
                <div key={key} style={{ display: "flex", gap: "0.6rem", padding: "3px 0", color: log ? (log.estado === "✓" ? "#00ff88" : "#e74c3c") : "#444" }}>
                  <span style={{ width: "18px", textAlign: "center" }}>{log ? log.estado : syncStatus.running && i === completedScrapers ? "⏳" : "○"}</span>
                  <span>{scraperLabels[key]}</span>
                  {log && log.mensaje !== "OK" && <span style={{ color: "#666", fontSize: "0.72rem" }}>— {log.mensaje}</span>}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ── Section tabs ── */}
      <div style={{ borderBottom: "1px solid #1a2e1f", marginBottom: "1.5rem", display: "flex" }}>
        {tabBtn("consejos", "🧠 Consejos IA")}
        {tabBtn("analisis", "🔍 Análisis Individual")}
        {tabBtn("historial", "📋 Historial")}
      </div>

      {/* ══════════ CONSEJOS ══════════ */}
      {activeSection === "consejos" && (
        <>
          {Object.keys(CONSEJOS_META).map((tipo) => {
            const meta = CONSEJOS_META[tipo];
            const consejo = consejos[tipo];
            const isOpen = expandedConsejos.has(tipo);
            return (
              <div key={tipo} style={{ background: "#111a14", border: `1px solid ${meta.color}33`, borderRadius: "10px", marginBottom: "1rem" }}>
                <button
                  onClick={() => toggleConsejo(tipo)}
                  style={{ width: "100%", background: `${meta.color}18`, borderBottom: isOpen ? `1px solid ${meta.color}33` : "none", border: "none", padding: "0.75rem 1.25rem", display: "flex", alignItems: "center", gap: "0.5rem", cursor: "pointer", textAlign: "left" }}
                >
                  <span style={{ fontSize: "1.1rem" }}>{meta.emoji}</span>
                  <span style={{ color: meta.color, fontWeight: 700, fontFamily: "monospace", fontSize: "0.85rem", letterSpacing: "0.05em", flex: 1 }}>{meta.titulo}</span>
                  {consejo && <span style={{ color: "#555", fontSize: "0.7rem", whiteSpace: "nowrap" }}>{new Date(consejo.creado).toLocaleString("es-ES")}</span>}
                  <span style={{ color: meta.color, fontSize: "0.8rem", marginLeft: "0.5rem", transform: isOpen ? "rotate(180deg)" : "rotate(0)", transition: "transform 0.2s", flexShrink: 0 }}>▼</span>
                </button>
                {isOpen && (
                  <div style={{ padding: "1.25rem", overflow: "visible" }}>
                    {consejo ? (
                      <div style={{ color: "#ddd", lineHeight: 1.6, fontSize: "0.95rem", overflow: "visible", whiteSpace: "normal" }}>
                        <ReactMarkdown>{consejo.contenido}</ReactMarkdown>
                      </div>
                    ) : (
                      <div style={{ color: "#555", fontStyle: "italic", textAlign: "center", padding: "1rem" }}>Sin consejos todavía — pulsa "Generar Consejos"</div>
                    )}
                  </div>
                )}
              </div>
            );
          })}

          {/* ── SEPARADOR + CHAT ── */}
          <div style={{ display: "flex", alignItems: "center", gap: "1rem", margin: "2rem 0 1.5rem" }}>
            <div style={{ flex: 1, height: 1, background: "#1a2e1f" }} />
            <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
              <span style={{ fontSize: "1.2rem" }}>💬</span>
              <span style={{ color: "#00ff88", fontWeight: 700, fontFamily: "monospace", fontSize: "0.9rem", letterSpacing: "0.05em" }}>CHAT CON TU ANALISTA</span>
            </div>
            <div style={{ flex: 1, height: 1, background: "#1a2e1f" }} />
            {chatMensajes.length > 0 && (
              <button
                onClick={handleClearChat}
                style={{ background: "transparent", border: "1px solid #333", color: "#666", padding: "4px 10px", borderRadius: "4px", cursor: "pointer", fontSize: "0.72rem", whiteSpace: "nowrap" }}
              >Limpiar chat</button>
            )}
          </div>

          {/* Área de mensajes */}
          <div style={{ background: "#0a0f0d", border: "1px solid #1a2e1f", borderRadius: "10px", overflow: "hidden", marginBottom: "1rem" }}>
            <div style={{ height: 400, overflowY: "auto", padding: "1rem", display: "flex", flexDirection: "column", gap: "0.75rem" }}>
              {chatMensajes.length === 0 && !chatLoading && (
                <div style={{ margin: "auto", textAlign: "center", color: "#333", fontSize: "0.85rem", lineHeight: 1.8 }}>
                  <div style={{ fontSize: "2rem", marginBottom: "0.5rem" }}>🧠</div>
                  <div>Pregúntame sobre tu plantilla, rivales o el mercado</div>
                  <div style={{ fontSize: "0.75rem", marginTop: "0.5rem", color: "#2a4a30" }}>ej: ¿Debería vender a Kanté? · ¿Cuál es el mejor portero del mercado? · ¿Qué están haciendo mis rivales?</div>
                </div>
              )}
              {chatMensajes.map((m, i) => (
                <div key={i} style={{ display: "flex", justifyContent: m.role === "user" ? "flex-end" : "flex-start" }}>
                  <div style={{
                    maxWidth: "80%",
                    background: m.role === "user" ? "#00ff8820" : "#111a14",
                    border: m.role === "user" ? "1px solid #00ff8844" : "1px solid #1a2e1f",
                    borderRadius: m.role === "user" ? "12px 12px 2px 12px" : "12px 12px 12px 2px",
                    padding: "0.65rem 1rem",
                    fontSize: "0.88rem",
                    lineHeight: 1.55,
                  }}>
                    {m.role === "ia" ? (
                      <div style={{ color: "#ddd" }}><ReactMarkdown>{m.texto}</ReactMarkdown></div>
                    ) : (
                      <div style={{ color: "#00ff88" }}>{m.texto}</div>
                    )}
                    <div style={{ color: "#333", fontSize: "0.65rem", marginTop: "0.3rem", textAlign: m.role === "user" ? "right" : "left" }}>
                      {new Date(m.timestamp).toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" })}
                    </div>
                  </div>
                </div>
              ))}
              {chatLoading && (
                <div style={{ display: "flex", justifyContent: "flex-start" }}>
                  <div style={{ background: "#111a14", border: "1px solid #1a2e1f", borderRadius: "12px 12px 12px 2px", padding: "0.65rem 1rem", fontSize: "0.85rem", color: "#00ff88", display: "flex", alignItems: "center", gap: "0.5rem" }}>
                    <span style={{ animation: "pulse 1.5s infinite" }}>⏳</span> Analizando...
                  </div>
                </div>
              )}
              <div ref={chatEndRef} />
            </div>

            {/* Input */}
            <div style={{ borderTop: "1px solid #1a2e1f", padding: "0.75rem", display: "flex", gap: "0.5rem" }}>
              <input
                type="text"
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && handleChatSend()}
                placeholder="Pregúntame algo sobre tu liga... (ej: ¿debería vender a Kanté?)"
                disabled={chatLoading}
                style={{
                  flex: 1,
                  background: "#0d150f",
                  border: "1px solid #1a2e1f",
                  borderRadius: "6px",
                  color: "#e0ffe8",
                  padding: "10px 14px",
                  fontSize: "0.9rem",
                  outline: "none",
                  opacity: chatLoading ? 0.6 : 1,
                }}
              />
              <button
                onClick={handleChatSend}
                disabled={chatLoading || !chatInput.trim()}
                style={{
                  background: chatLoading || !chatInput.trim() ? "#1a2e1f" : "#00ff88",
                  color: chatLoading || !chatInput.trim() ? "#00ff8844" : "#0a0f0d",
                  border: "none",
                  borderRadius: "6px",
                  padding: "10px 20px",
                  fontWeight: 700,
                  cursor: chatLoading || !chatInput.trim() ? "not-allowed" : "pointer",
                  fontSize: "0.9rem",
                  transition: "all 0.15s",
                  whiteSpace: "nowrap",
                }}
              >Enviar ↵</button>
            </div>
          </div>
        </>
      )}

      {/* ══════════ ANÁLISIS INDIVIDUAL ══════════ */}
      {activeSection === "analisis" && (
        <>
          {/* Plantilla cards */}
          {plantilla.length > 0 && (
            <div style={{ marginBottom: "1.5rem" }}>
              <div style={{ color: "#555", fontSize: "0.75rem", fontWeight: 700, letterSpacing: "0.05em", marginBottom: "0.75rem" }}>MI PLANTILLA — Selecciona un jugador para analizar</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem" }}>
                {plantilla.map((j) => (
                  <button
                    key={j.id}
                    onClick={() => handleAnalizar(j)}
                    disabled={analizando !== null}
                    style={{
                      background: analizando === j.id ? "#1a2e1f" : "#111a14",
                      border: `1px solid ${posColor[j.posicion] || "#333"}44`,
                      borderRadius: "6px",
                      padding: "6px 12px",
                      cursor: analizando !== null ? "wait" : "pointer",
                      display: "flex",
                      alignItems: "center",
                      gap: "6px",
                      transition: "border-color 0.15s",
                    }}
                  >
                    <span style={{ width: 22, height: 22, borderRadius: "50%", background: posColor[j.posicion] || "#333", display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: "0.6rem", fontWeight: 700, color: "#fff", flexShrink: 0 }}>
                      {posLetter[j.posicion] || "?"}
                    </span>
                    <span style={{ color: "#ddd", fontSize: "0.85rem" }}>{j.nombre}</span>
                    <span style={{ color: "#555", fontSize: "0.7rem" }}>{fmt(j.precio_actual || 0)}</span>
                    {analizando === j.id && <span style={{ color: "#00ff88", fontSize: "0.7rem" }}>⏳</span>}
                    {analizando !== j.id && <span style={{ color: "#4a90e2", fontSize: "0.65rem" }}>🔍</span>}
                  </button>
                ))}
              </div>
            </div>
          )}

          {analisisError && (
            <div style={{ background: "#2d0a0a", border: "1px solid #e74c3c", borderRadius: "6px", padding: "1rem", color: "#e74c3c", marginBottom: "1rem" }}>
              ⚠️ {analisisError}
            </div>
          )}

          {analizando !== null && !analisisActivo && (
            <div style={{ textAlign: "center", color: "#00ff88", padding: "3rem", fontFamily: "monospace" }}>
              🔍 Consultando Gemini con Google Search Grounding...
            </div>
          )}

          {/* Analysis result */}
          {analisisActivo && (
            <div>
              {/* Header */}
              <div style={{ background: "#111a14", border: "1px solid #1a2e1f", borderRadius: "10px", padding: "1rem 1.25rem", marginBottom: "1rem", display: "flex", alignItems: "center", gap: "1rem", flexWrap: "wrap" }}>
                <div style={{ fontWeight: 700, fontSize: "1.1rem" }}>{analisisActivo.jugador_nombre}</div>
                {analisisActivo.desde_cache ? (
                  <span style={{ color: "#00ff88", fontSize: "0.75rem", fontWeight: 600 }}>✓ Desde caché</span>
                ) : (
                  <span style={{ color: "#f39c12", fontSize: "0.75rem", fontWeight: 600 }}>✦ Análisis nuevo</span>
                )}
                <span style={{ color: "#555", fontSize: "0.72rem", marginLeft: "auto" }}>
                  {new Date(analisisActivo.fecha_analisis).toLocaleString("es-ES")}
                </span>
              </div>

              {analisisActivo.data.error && (
                <div style={{ background: "#2d0a0a", border: "1px solid #e74c3c", borderRadius: "6px", padding: "1rem", color: "#e74c3c", marginBottom: "1rem", fontFamily: "monospace", fontSize: "0.8rem", whiteSpace: "pre-wrap" }}>
                  {analisisActivo.data.raw || analisisActivo.data.error}
                </div>
              )}

              {/* VEREDICTO — siempre primero */}
              {analisisActivo.data.veredicto && (() => {
                const v = analisisActivo.data.veredicto;
                const col = veredictoColor(v.decision || "");
                return (
                  <div style={{ background: `${col}12`, border: `2px solid ${col}`, borderRadius: "10px", padding: "1.25rem", marginBottom: "1rem" }}>
                    <div style={{ color: col, fontWeight: 800, fontFamily: "monospace", fontSize: "1.1rem", letterSpacing: "0.05em", marginBottom: "0.5rem" }}>
                      {v.decision}
                    </div>
                    <div style={{ color: "#ddd", fontSize: "0.9rem", marginBottom: "0.5rem" }}>{v.justificacion}</div>
                    <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                      <Pill label={`Confianza: ${v.confianza}`} color={PROB_COLOR[v.confianza] || "#aaa"} />
                      {v.precio_minimo_venta_recomendado && <Pill label={`Mín. venta: ${fmt(v.precio_minimo_venta_recomendado)}`} color="#f39c12" />}
                      {v.riesgo_principal && <Pill label={`⚠ ${v.riesgo_principal}`} color="#e74c3c" />}
                    </div>
                  </div>
                );
              })()}

              {/* ESTADO FÍSICO */}
              {analisisActivo.data.lesiones_sanciones && (() => {
                const ls = analisisActivo.data.lesiones_sanciones;
                return (
                  <Block title="ESTADO FÍSICO" color={ESTADO_COLOR[ls.estado] || "#aaa"}>
                    <div style={{ display: "flex", gap: "0.75rem", alignItems: "center", flexWrap: "wrap" }}>
                      <Pill label={ls.estado?.toUpperCase() || "—"} color={ESTADO_COLOR[ls.estado] || "#aaa"} />
                      {ls.detalle && <span style={{ color: "#bbb", fontSize: "0.85rem" }}>{ls.detalle}</span>}
                      {ls.fuente && <a href={ls.fuente} target="_blank" rel="noreferrer" style={{ color: "#4a90e2", fontSize: "0.75rem" }}>{ls.fuente}</a>}
                    </div>
                  </Block>
                );
              })()}

              {/* TITULARIDAD */}
              {analisisActivo.data.titularidad && (() => {
                const t = analisisActivo.data.titularidad;
                return (
                  <Block title="TITULARIDAD" color="#4a90e2">
                    <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", marginBottom: "0.75rem" }}>
                      {t.condicion && <Pill label={t.condicion.toUpperCase()} color={t.condicion === "titular" ? "#00ff88" : t.condicion === "rotación" ? "#f39c12" : "#e74c3c"} />}
                      {t.probabilidad_titular_proximo_partido && <Pill label={`Próx. partido: ${t.probabilidad_titular_proximo_partido}`} color={PROB_COLOR[t.probabilidad_titular_proximo_partido] || "#aaa"} />}
                    </div>
                    {t.competencia && <div style={{ color: "#888", fontSize: "0.82rem", marginBottom: "0.5rem" }}>Competencia: {t.competencia}</div>}
                    {t.fuentes && (
                      <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                        {Object.entries(t.fuentes).map(([src, f]) => f.url ? (
                          <a key={src} href={f.url} target="_blank" rel="noreferrer" style={{ color: "#4a90e2", fontSize: "0.75rem", textDecoration: "none", border: "1px solid #4a90e244", borderRadius: "4px", padding: "2px 8px" }}>
                            {src} {f.recomendacion ? `— ${f.recomendacion}` : ""}
                          </a>
                        ) : null)}
                      </div>
                    )}
                  </Block>
                );
              })()}

              {/* FORMA */}
              {analisisActivo.data.forma && (() => {
                const f = analisisActivo.data.forma;
                return (
                  <Block title="FORMA RECIENTE" color="#f39c12">
                    <div style={{ display: "flex", gap: "0.75rem", marginBottom: "0.75rem", flexWrap: "wrap" }}>
                      {f.tendencia_rating && <Pill label={`Rating: ${f.tendencia_rating}`} color={f.tendencia_rating === "subiendo" ? "#00ff88" : f.tendencia_rating === "bajando" ? "#e74c3c" : "#aaa"} />}
                      {f.tendencia_minutos && <Pill label={`Minutos: ${f.tendencia_minutos}`} color={f.tendencia_minutos === "subiendo" ? "#00ff88" : f.tendencia_minutos === "bajando" ? "#e74c3c" : "#aaa"} />}
                    </div>
                    {f.ultimos_3_partidos && f.ultimos_3_partidos.length > 0 && (
                      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.82rem" }}>
                        <thead>
                          <tr style={{ borderBottom: "1px solid #1a2e1f" }}>
                            {["Rival", "Fecha", "Min", "Rating", "G", "A"].map(h => (
                              <th key={h} style={{ padding: "4px 8px", textAlign: "left", color: "#555", fontFamily: "monospace", fontSize: "0.72rem" }}>{h}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {f.ultimos_3_partidos.map((p, i) => (
                            <tr key={i} style={{ borderBottom: "1px solid #0d150f" }}>
                              <td style={{ padding: "4px 8px", color: "#ddd" }}>{p.rival || "—"}</td>
                              <td style={{ padding: "4px 8px", color: "#777" }}>{p.fecha || "—"}</td>
                              <td style={{ padding: "4px 8px", fontFamily: "monospace" }}>{p.minutos ?? "—"}</td>
                              <td style={{ padding: "4px 8px", fontFamily: "monospace", color: p.rating_sofascore && p.rating_sofascore >= 7 ? "#00ff88" : p.rating_sofascore && p.rating_sofascore < 6 ? "#e74c3c" : "#ddd" }}>{p.rating_sofascore ?? "—"}</td>
                              <td style={{ padding: "4px 8px", fontFamily: "monospace" }}>{p.goles ?? "—"}</td>
                              <td style={{ padding: "4px 8px", fontFamily: "monospace" }}>{p.asistencias ?? "—"}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                    {f.fuente_sofascore && <a href={f.fuente_sofascore} target="_blank" rel="noreferrer" style={{ color: "#4a90e2", fontSize: "0.75rem", display: "block", marginTop: "0.5rem" }}>→ SofaScore</a>}
                  </Block>
                );
              })()}

              {/* PRÓXIMO RIVAL */}
              {analisisActivo.data.proximo_rival_mundial && (() => {
                const r = analisisActivo.data.proximo_rival_mundial;
                return (
                  <Block title="PRÓXIMO RIVAL (MUNDIAL)" color={NIVEL_COLOR[r.nivel] || "#aaa"}>
                    <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", marginBottom: "0.5rem" }}>
                      <span style={{ fontWeight: 700, color: "#ddd" }}>{r.nombre}</span>
                      <Pill label={r.nivel?.toUpperCase() || "—"} color={NIVEL_COLOR[r.nivel] || "#aaa"} />
                      {r.ranking_fifa_rival && <Pill label={`FIFA #${r.ranking_fifa_rival}`} color="#aaa" />}
                      <span style={{ color: "#666", fontSize: "0.8rem" }}>{r.fecha}</span>
                    </div>
                    {r.analisis && <div style={{ color: "#bbb", fontSize: "0.85rem" }}>{r.analisis}</div>}
                  </Block>
                );
              })()}

              {/* GRUPO MUNDIAL */}
              {analisisActivo.data.grupo_mundial && (() => {
                const g = analisisActivo.data.grupo_mundial;
                return (
                  <Block title="GRUPO MUNDIAL" color="#9b59b6">
                    <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", marginBottom: "0.5rem" }}>
                      <span style={{ fontWeight: 700, color: "#9b59b6" }}>{g.nombre_grupo}</span>
                      <Pill label={`Clasificación: ${g.probabilidad_clasificacion}`} color={PROB_COLOR[g.probabilidad_clasificacion] || "#aaa"} />
                    </div>
                    {g.equipos?.length > 0 && <div style={{ color: "#888", fontSize: "0.82rem", marginBottom: "0.5rem" }}>{g.equipos.join(" · ")}</div>}
                    {g.analisis && <div style={{ color: "#bbb", fontSize: "0.85rem" }}>{g.analisis}</div>}
                  </Block>
                );
              })()}

              {/* ESPECIALISTAS FANTASY */}
              {analisisActivo.data.fantasy_especialistas && (() => {
                const esp = analisisActivo.data.fantasy_especialistas;
                const entries = Object.entries(esp).filter(([, v]) => v.recomendacion || v.url);
                if (!entries.length) return null;
                return (
                  <Block title="ESPECIALISTAS FANTASY" color="#1abc9c">
                    {entries.map(([src, v]) => (
                      <div key={src} style={{ display: "flex", gap: "0.75rem", alignItems: "center", padding: "4px 0", flexWrap: "wrap" }}>
                        <span style={{ color: "#1abc9c", fontWeight: 700, fontSize: "0.8rem", minWidth: 140 }}>{src}</span>
                        {v.recomendacion && <span style={{ color: "#ddd", fontSize: "0.85rem" }}>{v.recomendacion}</span>}
                        {v.puntuacion_esperada && <Pill label={`${v.puntuacion_esperada} pts`} color="#1abc9c" />}
                        {v.url && <a href={v.url} target="_blank" rel="noreferrer" style={{ color: "#4a90e2", fontSize: "0.75rem" }}>→ ver</a>}
                      </div>
                    ))}
                  </Block>
                );
              })()}

              {/* APUESTAS */}
              {analisisActivo.data.apuestas && (() => {
                const a = analisisActivo.data.apuestas;
                if (!a.cuota_marcar_gol && !a.cuota_asistencia) return null;
                return (
                  <Block title="CUOTAS DE APUESTAS" color="#666">
                    <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
                      {a.cuota_marcar_gol && <span style={{ color: "#bbb", fontSize: "0.85rem" }}>Marcar gol: <strong style={{ color: "#ddd" }}>{a.cuota_marcar_gol}</strong></span>}
                      {a.cuota_asistencia && <span style={{ color: "#bbb", fontSize: "0.85rem" }}>Asistencia: <strong style={{ color: "#ddd" }}>{a.cuota_asistencia}</strong></span>}
                      {a.fuente_url && <a href={a.fuente_url} target="_blank" rel="noreferrer" style={{ color: "#4a90e2", fontSize: "0.75rem" }}>→ fuente</a>}
                    </div>
                  </Block>
                );
              })()}
            </div>
          )}
        </>
      )}

      {/* ══════════ HISTORIAL ══════════ */}
      {activeSection === "historial" && (
        <HistorialTab
          historial={historial}
          historialLoading={historialLoading}
          veredictoColor={veredictoColor}
          onOpenAnalisis={(jugador_id, jugador_nombre) => {
            api.analizarJugador(jugador_id).then((r) => {
              setAnalisisActivo({ ...r, jugador_nombre, jugador_id });
              setActiveSection("analisis");
            }).catch(() => {});
          }}
        />
      )}
    </div>
  );
}
