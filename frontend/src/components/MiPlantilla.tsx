// Pestaña Mi Plantilla
import React, { useEffect, useState } from "react";
import { api } from "../api";

interface Jugador {
  id: number;
  nombre: string;
  posicion: string;
  equipo: string;
  team_name: string;
  precio_actual: number;
  precio_compra: number;
  roi: number;
  puntos_totales: number;
  puntos_5j: string;
  estado: string;
  status_cf: string;
  status_info: string | null;
  price_increment: number;
  next_match_date: number | null;
  next_match_rival: string | null;
  slug: string;
  prob_titularidad: number;
  prob_analitica: number | null;
  prob_jornada: number | null;
  prob_futbol_fantasy: number | null;
  prob_media: number | null;
  rol_esperado: string | null;
  prob_gol: number | null;
  prob_asistencia: number | null;
  minutos_esperados: number | null;
  valoracion_mundial: string | null;
  proyeccion_recomendacion: string | null;
  proyeccion_justificacion: string | null;
}

interface Finanzas {
  saldo: number;
  valor_plantilla: number;
  dinero_gastado: number;
  dinero_ingresado: number;
}

const fmt = (n: number) =>
  n >= 1_000_000
    ? `${(n / 1_000_000).toFixed(1)}M€`
    : n >= 1000
    ? `${(n / 1000).toFixed(0)}K€`
    : `${n}€`;

const posColor: Record<string, string> = {
  Portero: "#4a90e2",
  Defensa: "#27ae60",
  Centrocampista: "#f39c12",
  Delantero: "#e74c3c",
};

const posLetter: Record<string, string> = {
  Portero: "P",
  Defensa: "D",
  Centrocampista: "C",
  Delantero: "DL",
};

const estadoLabel: Record<string, { label: string; color: string }> = {
  ok: { label: "✅ Disponible", color: "#00ff88" },
  injured: { label: "🔴 Lesionado", color: "#e74c3c" },
  doubt: { label: "⚠️ Duda", color: "#f39c12" },
  suspended: { label: "🚫 Sancionado", color: "#ff6b35" },
};

const fmtDate = (ts: number | null) => {
  if (!ts) return null;
  return new Date(ts * 1000).toLocaleDateString("es-ES", { day: "2-digit", month: "2-digit" });
};

const fmtInc = (inc: number) =>
  inc > 0
    ? { arrow: "↑", color: "#00ff88", text: `+${(inc / 1000).toFixed(0)}K€` }
    : inc < 0
    ? { arrow: "↓", color: "#e74c3c", text: `${(inc / 1000).toFixed(0)}K€` }
    : { arrow: "→", color: "#aaa", text: "estable" };

export default function MiPlantilla() {
  const [jugadores, setJugadores] = useState<Jugador[]>([]);
  const [finanzas, setFinanzas] = useState<Finanzas | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([api.plantilla(), api.finanzas()])
      .then(([p, f]) => {
        setJugadores(p.data || []);
        setFinanzas(f.data || null);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  const roiTotal = jugadores.reduce((acc, j) => acc + (j.roi || 0), 0);

  if (loading) {
    return (
      <div style={{ textAlign: "center", color: "#00ff88", padding: "3rem" }}>
        Cargando plantilla...
      </div>
    );
  }

  return (
    <div style={{ padding: "1rem" }}>
      {/* Resumen financiero */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
          gap: "1rem",
          marginBottom: "1.5rem",
        }}
      >
        {[
          { label: "SALDO", value: fmt(finanzas?.saldo || 0), color: "#00ff88" },
          { label: "VALOR PLANTILLA", value: fmt(finanzas?.valor_plantilla || 0), color: "#4a90e2" },
          {
            label: "ROI TOTAL",
            value: fmt(roiTotal),
            color: roiTotal >= 0 ? "#00ff88" : "#e74c3c",
          },
          { label: "JUGADORES", value: String(jugadores.length), color: "#f39c12" },
        ].map((s) => (
          <div
            key={s.label}
            style={{
              background: "#111a14",
              border: `1px solid ${s.color}33`,
              borderRadius: "8px",
              padding: "1rem",
              textAlign: "center",
            }}
          >
            <div style={{ color: "#666", fontSize: "0.7rem", fontWeight: 700, letterSpacing: "0.05em" }}>
              {s.label}
            </div>
            <div
              style={{ color: s.color, fontSize: "1.4rem", fontWeight: 700, fontFamily: "monospace" }}
            >
              {s.value}
            </div>
          </div>
        ))}
      </div>

      {jugadores.length === 0 ? (
        <div style={{ textAlign: "center", color: "#555", padding: "3rem" }}>
          Sin jugadores — pulsa "Sincronizar Todo"
        </div>
      ) : (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
            gap: "1rem",
          }}
        >
          {jugadores.map((j) => {
            const statusKey = j.status_cf || j.estado || "ok";
            const estado = estadoLabel[statusKey] || estadoLabel["ok"];
            const roiPos = (j.roi || 0) >= 0;
            const inc = fmtInc(j.price_increment || 0);
            const nextFecha = fmtDate(j.next_match_date);

            return (
              <div
                key={j.id}
                style={{
                  background: "#111a14",
                  border: "1px solid #1a2e1f",
                  borderRadius: "10px",
                  padding: "1rem",
                  position: "relative",
                  transition: "border-color 0.2s",
                }}
                onMouseEnter={(e) =>
                  ((e.currentTarget as HTMLDivElement).style.borderColor = "#00ff8855")
                }
                onMouseLeave={(e) =>
                  ((e.currentTarget as HTMLDivElement).style.borderColor = "#1a2e1f")
                }
              >
                {/* Posición badge */}
                <div
                  style={{
                    position: "absolute",
                    top: "10px",
                    right: "10px",
                    background: posColor[j.posicion] || "#666",
                    color: "#fff",
                    padding: "2px 8px",
                    borderRadius: "3px",
                    fontSize: "0.7rem",
                    fontWeight: 700,
                  }}
                >
                  {j.posicion?.charAt(0)}
                </div>

                {/* Cabecera con avatar + nombre */}
                <div style={{ display: "flex", gap: "0.75rem", alignItems: "center", marginBottom: "0.75rem" }}>
                  <div
                    style={{
                      width: 48,
                      height: 48,
                      borderRadius: "50%",
                      background: posColor[j.posicion] || "#333",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      fontWeight: 700,
                      fontSize: "0.85rem",
                      color: "#fff",
                      flexShrink: 0,
                      letterSpacing: "-0.03em",
                    }}
                  >
                    {posLetter[j.posicion] || "?"}
                  </div>
                  <div>
                    <div style={{ fontWeight: 700, fontSize: "1rem" }}>{j.nombre}</div>
                    <div style={{ color: "#aaa", fontSize: "0.8rem" }}>{j.team_name || j.equipo}</div>
                  </div>
                </div>

                {/* Estado físico */}
                <div style={{ marginBottom: "0.5rem" }}>
                  <span style={{ color: estado.color, fontSize: "0.75rem", fontWeight: 600 }}>
                    {estado.label}
                  </span>
                  {j.status_info && (
                    <span style={{ color: "#888", fontSize: "0.7rem", marginLeft: "0.4rem" }}>
                      — {j.status_info}
                    </span>
                  )}
                </div>

                {/* Tendencia precio + Próximo partido */}
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "0.5rem", fontSize: "0.75rem" }}>
                  <span style={{ color: inc.color, fontWeight: 700 }}>
                    {inc.arrow} {inc.text}
                  </span>
                  {j.next_match_rival && (
                    <span style={{ color: "#888" }}>
                      🆚 {j.next_match_rival}{nextFecha ? ` (${nextFecha})` : ""}
                    </span>
                  )}
                </div>

                {/* Datos financieros */}
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "1fr 1fr",
                    gap: "0.5rem",
                    marginBottom: "0.5rem",
                  }}
                >
                  <div>
                    <div style={{ color: "#555", fontSize: "0.65rem" }}>PRECIO ACTUAL</div>
                    <div style={{ fontFamily: "monospace", fontWeight: 600 }}>
                      {fmt(j.precio_actual || 0)}
                    </div>
                  </div>
                  <div>
                    <div style={{ color: "#555", fontSize: "0.65rem" }}>PRECIO COMPRA</div>
                    <div style={{ fontFamily: "monospace" }}>{fmt(j.precio_compra || 0)}</div>
                  </div>
                  <div>
                    <div style={{ color: "#555", fontSize: "0.65rem" }}>ROI</div>
                    <div
                      style={{
                        fontFamily: "monospace",
                        fontWeight: 700,
                        color: roiPos ? "#00ff88" : "#e74c3c",
                      }}
                    >
                      {roiPos ? "+" : ""}
                      {fmt(j.roi || 0)}
                    </div>
                  </div>
                  <div>
                    <div style={{ color: "#555", fontSize: "0.65rem" }}>PUNTOS</div>
                    <div style={{ fontFamily: "monospace", fontWeight: 600 }}>
                      {j.puntos_totales || 0}
                    </div>
                  </div>
                </div>

                {/* Probabilidad de titularidad — 4 fuentes */}
                <div style={{ marginBottom: "0.75rem" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "4px" }}>
                    <span style={{ color: "#555", fontSize: "0.65rem", fontWeight: 700, letterSpacing: "0.04em" }}>PROB. TITULAR</span>
                    {j.rol_esperado && (
                      <span style={{ fontSize: "0.65rem", background: j.rol_esperado === "titular" ? "#00ff8822" : j.rol_esperado === "suplente" ? "#e74c3c22" : "#f39c1222", color: j.rol_esperado === "titular" ? "#00ff88" : j.rol_esperado === "suplente" ? "#e74c3c" : "#f39c12", border: `1px solid ${j.rol_esperado === "titular" ? "#00ff8844" : j.rol_esperado === "suplente" ? "#e74c3c44" : "#f39c1244"}`, padding: "1px 6px", borderRadius: "3px", fontWeight: 700 }}>
                        {j.rol_esperado.toUpperCase()}
                      </span>
                    )}
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "3px", marginBottom: "4px" }}>
                    {([
                      ["Fuente 1", j.prob_analitica],
                      ["Fuente 2", j.prob_jornada],
                      [j.prob_futbol_fantasy != null ? "Fútbol F." : "Fuente 3", j.prob_futbol_fantasy],
                      ["Media", j.prob_media ?? j.prob_titularidad],
                    ] as [string, number | null][]).map(([label, val]) => (
                      <div
                        key={label}
                        title={val == null ? "Datos disponibles cuando empiece el torneo (11 junio)" : undefined}
                        style={{ background: "#0d150f", border: "1px solid #1a2e1f", borderRadius: "3px", padding: "2px 6px", display: "flex", justifyContent: "space-between", alignItems: "center", cursor: val == null ? "help" : "default" }}
                      >
                        <span style={{ color: "#555", fontSize: "0.6rem" }}>{label}</span>
                        <span style={{ fontFamily: "monospace", fontSize: "0.7rem", fontWeight: 700, color: val != null ? (val >= 70 ? "#00ff88" : val >= 40 ? "#f39c12" : "#e74c3c") : "#333" }}>
                          {val != null ? `${val}%` : "—"}
                        </span>
                      </div>
                    ))}
                  </div>
                  <div style={{ height: "3px", background: "#1a2e1f", borderRadius: "2px", overflow: "hidden" }}>
                    <div style={{ width: `${j.prob_media ?? j.prob_titularidad ?? 50}%`, height: "100%", background: "#00ff88", borderRadius: "2px" }} />
                  </div>
                </div>

                {/* Proyección Mundial */}
                {(j.prob_gol != null || j.valoracion_mundial) && (
                  <div style={{ background: "#0a0f0d", border: "1px solid #1a2e1f", borderRadius: "6px", padding: "0.5rem", marginBottom: "0.75rem" }}>
                    <div style={{ color: "#555", fontSize: "0.6rem", fontWeight: 700, letterSpacing: "0.04em", marginBottom: "4px" }}>PROYECCIÓN MUNDIAL</div>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: "4px", fontSize: "0.72rem", marginBottom: "4px" }}>
                      {j.prob_gol != null && <span style={{ color: "#f39c12" }}>⚽ Gol: <strong>{j.prob_gol}%</strong></span>}
                      {j.prob_asistencia != null && <span style={{ color: "#4a90e2" }}>🎯 Asist: <strong>{j.prob_asistencia}%</strong></span>}
                      {j.minutos_esperados != null && <span style={{ color: "#aaa" }}>⏱ <strong>{j.minutos_esperados}′</strong></span>}
                      {j.valoracion_mundial && (
                        <span style={{ color: j.valoracion_mundial === "alta" ? "#00ff88" : j.valoracion_mundial === "baja" ? "#e74c3c" : "#f39c12" }}>
                          📊 {j.valoracion_mundial.toUpperCase()}
                        </span>
                      )}
                    </div>
                    {j.proyeccion_recomendacion && (() => {
                      // Si el modelo recomienda COMPRAR un jugador que ya tengo, lo cambiamos a MANTENER
                      const reco = j.proyeccion_recomendacion === "comprar" ? "mantener" : j.proyeccion_recomendacion;
                      return (
                      <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                        <span style={{ fontSize: "0.65rem", background: reco === "vender" ? "#e74c3c22" : "#f39c1222", color: reco === "vender" ? "#e74c3c" : "#f39c12", border: `1px solid ${reco === "vender" ? "#e74c3c44" : "#f39c1244"}`, padding: "1px 7px", borderRadius: "3px", fontWeight: 700 }}>
                          💡 {reco.toUpperCase()}
                        </span>
                        {j.proyeccion_justificacion && (
                          <span style={{ color: "#777", fontSize: "0.65rem", flex: 1 }}>{j.proyeccion_justificacion}</span>
                        )}
                      </div>
                      );
                    })()}
                  </div>
                )}

                {/* Botón vender */}
                <button
                  style={{
                    width: "100%",
                    background: "transparent",
                    border: "1px solid #e74c3c",
                    color: "#e74c3c",
                    padding: "6px",
                    borderRadius: "4px",
                    cursor: "pointer",
                    fontSize: "0.8rem",
                    fontWeight: 600,
                    transition: "all 0.15s",
                  }}
                  onMouseEnter={(e) => {
                    (e.currentTarget as HTMLButtonElement).style.background = "#e74c3c";
                    (e.currentTarget as HTMLButtonElement).style.color = "#fff";
                  }}
                  onMouseLeave={(e) => {
                    (e.currentTarget as HTMLButtonElement).style.background = "transparent";
                    (e.currentTarget as HTMLButtonElement).style.color = "#e74c3c";
                  }}
                >
                  Poner en venta
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
