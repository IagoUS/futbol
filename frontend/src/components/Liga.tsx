// Pestaña Liga — clasificación, transferencias y gráfico de precios
import React, { useEffect, useState } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import { api } from "../api";

interface ClasificacionEntry {
  id: number;
  posicion: number;
  nombre: string;
  puntos_totales: number;
  puntos_ultima_jornada: number;
  valor_plantilla: number;
  // Calculado backend en /clasificacion:
  //   50_000_000 − valor_plantilla + Σventas − Σcompras
  // Para el usuario logueado (id == miUserId) viene reemplazado por finanzas.saldo.
  saldo_estimado?: number;
  es_estimado?: boolean;
}

interface Transfer {
  id: number;
  usuario_nombre: string;
  tipo: string;
  jugador_nombre: string;
  precio: number;
  fecha: string;
}

interface PrecioEntry {
  jugador_id: number;
  jugador_nombre: string;
  fecha: string;
  precio: number;
}

interface MercadoPuja {
  id: number;
  nombre: string;
  posicion: string;
  precio: number;
  score_oportunidad: number;
}

interface PlantillaPuja {
  id: number;
  nombre: string;
  posicion: string;
  precio_actual: number;
}

const parseFecha = (fecha: string): Date => {
  const n = Number(fecha);
  return new Date(isNaN(n) ? fecha : n * 1000);
};

const fmt = (n: number) =>
  n >= 1_000_000
    ? `${(n / 1_000_000).toFixed(1)}M€`
    : n >= 1000
    ? `${(n / 1000).toFixed(0)}K€`
    : `${n}€`;

const COLORS = [
  "#00ff88", "#4a90e2", "#f39c12", "#e74c3c", "#9b59b6",
  "#1abc9c", "#e67e22", "#3498db", "#e91e63", "#ff5722",
];

interface LigaProps {
  miUserId: number;
}

export default function Liga({ miUserId }: LigaProps) {
  const [clasificacion, setClasificacion] = useState<ClasificacionEntry[]>([]);
  const [transfers, setTransfers] = useState<Transfer[]>([]);
  const [precios, setPrecios] = useState<PrecioEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<"clasificacion" | "transfers" | "precios" | "pujas">("clasificacion");
  const [busquedaTransfer, setBusquedaTransfer] = useState("");
  const [mercadoPujas, setMercadoPujas] = useState<MercadoPuja[]>([]);
  const [plantillaPujas, setPlantillaPujas] = useState<PlantillaPuja[]>([]);
  const [saldoActual, setSaldoActual] = useState(0);
  // Puja máxima reportada por Biwenger (data.status.maximumBid del endpoint /market?status=sold).
  // Es el tope real que Biwenger usa para validar pujas. Distinto del saldo bruto.
  const [maximumBid, setMaximumBid] = useState<number | null>(null);
  const [objetivos, setObjetivos] = useState<Set<number>>(new Set());
  const [ventas, setVentas] = useState<Set<number>>(new Set());
  const [pujasResultados, setPujasResultados] = useState<Record<number, string>>({});
  const [pujandoId, setPujandoId] = useState<number | null>(null);

  useEffect(() => {
    Promise.allSettled([
      api.clasificacion(), api.transfers(), api.historialPrecios(),
      api.mercado(), api.plantilla(), api.finanzas(),
    ]).then(([c, t, p, m, pl, f]) => {
        setClasificacion(c.status === "fulfilled" ? c.value.data || [] : []);
        setTransfers(t.status === "fulfilled" ? t.value.data || [] : []);
        setPrecios(p.status === "fulfilled" ? p.value.data || [] : []);
        setMercadoPujas(m.status === "fulfilled" ? m.value.data || [] : []);
        setPlantillaPujas(pl.status === "fulfilled" ? pl.value.data || [] : []);
        if (f.status === "fulfilled") {
          // saldoActual y maximumBid provienen EXCLUSIVAMENTE de la tabla `finanzas`
          // (sincronizada desde la API de Biwenger). No son cálculos derivados.
          // /finanzas → {ok: true, data: {saldo, valor_plantilla, maximum_bid, ...}}.
          const fin = f.value?.data || {};
          setSaldoActual(fin.saldo || 0);
          setMaximumBid(fin.maximum_bid ?? null);
        }
        if (c.status === "rejected") console.error("clasificacion:", c.reason);
        if (t.status === "rejected") console.error("transfers:", t.reason);
        if (p.status === "rejected") console.error("historial-precios:", p.reason);
      })
      .finally(() => setLoading(false));
  }, []);

  // Base del "saldo disponible":
  //   - Si Biwenger devuelve maximumBid, usamos ese valor (es el tope real que
  //     Biwenger usa para validar pujas: descuenta pujas pendientes y respeta
  //     el valor mínimo de plantilla).
  //   - Fallback a saldoActual si maximumBid no está disponible aún.
  const saldoBase = maximumBid !== null ? maximumBid : saldoActual;
  const saldoDisponible = saldoBase + plantillaPujas
    .filter((p) => ventas.has(p.id))
    .reduce((sum, p) => sum + (p.precio_actual || 0), 0);

  const calcularPuja = async (jugador: MercadoPuja) => {
    const ventasNombres = plantillaPujas.filter((p) => ventas.has(p.id)).map((p) => p.nombre).join(", ");
    const mensaje = `Tengo ${saldoDisponible.toLocaleString("es-ES")}€ disponibles${
      ventasNombres ? ` (incluyendo la venta de ${ventasNombres})` : ""
    }. ¿Cuánto debería pujar por ${jugador.nombre} que vale ${jugador.precio.toLocaleString("es-ES")}€? Ten en cuenta el saldo estimado de mis rivales y el historial de pujas de la liga`;
    setPujandoId(jugador.id);
    try {
      const r = await api.chat(mensaje);
      setPujasResultados((prev) => ({ ...prev, [jugador.id]: r.respuesta || "" }));
    } catch (e) {
      setPujasResultados((prev) => ({ ...prev, [jugador.id]: "Error al calcular" }));
    } finally {
      setPujandoId(null);
    }
  };

  // Transformar historial de precios a formato para Recharts
  const jugadoresUnicos: string[] = (Array.from(new Set(precios.map((p) => p.jugador_nombre))) as string[]).slice(0, 8);
  const fechasUnicas: string[] = (Array.from(new Set(precios.map((p) => p.fecha.slice(0, 10)))) as string[]).sort();
  const chartData = fechasUnicas.map((fecha: string) => {
    const entry: Record<string, string | number> = { fecha };
    jugadoresUnicos.forEach((nombre: string) => {
      const match = precios.find(
        (p) => p.jugador_nombre === nombre && p.fecha.slice(0, 10) === fecha
      );
      if (match) entry[nombre] = match.precio;
    });
    return entry;
  });

  if (loading) {
    return (
      <div style={{ textAlign: "center", color: "#00ff88", padding: "3rem" }}>
        Cargando liga...
      </div>
    );
  }

  return (
    <div style={{ padding: "1rem" }}>
      {/* Sub-tabs */}
      <div
        style={{
          display: "flex",
          gap: "0.5rem",
          marginBottom: "1.5rem",
          borderBottom: "1px solid #1a2e1f",
          paddingBottom: "0.5rem",
        }}
      >
        {(["clasificacion", "transfers", "precios", "pujas"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            style={{
              background: tab === t ? "#00ff8822" : "transparent",
              border: tab === t ? "1px solid #00ff88" : "1px solid #333",
              color: tab === t ? "#00ff88" : "#666",
              padding: "6px 18px",
              borderRadius: "4px",
              cursor: "pointer",
              fontSize: "0.85rem",
              fontWeight: 600,
              transition: "all 0.15s",
            }}
          >
            {t === "clasificacion" ? "🏆 Clasificación" : t === "transfers" ? "🔄 Transferencias" : t === "precios" ? "📈 Precios" : "🎯 Pujas"}
          </button>
        ))}
      </div>

      {/* ── CLASIFICACIÓN ── */}
      {tab === "clasificacion" && (
        <div>
          {clasificacion.length === 0 ? (
            <div style={{ textAlign: "center", color: "#555", padding: "3rem" }}>
              Sin datos — pulsa "Sincronizar Todo"
            </div>
          ) : (
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ borderBottom: "2px solid #00ff88" }}>
                  {["#", "MANAGER", "PUNTOS", "ÚLT. JORNADA", "VALOR PLANTILLA", "SALDO EST."].map((h) => (
                    <th
                      key={h}
                      style={{
                        padding: "10px 12px",
                        textAlign: "left",
                        color: "#00ff88",
                        fontFamily: "monospace",
                        fontSize: "0.75rem",
                        fontWeight: 700,
                      }}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {clasificacion.map((entry, i) => (
                  <tr
                    key={entry.id}
                    style={{
                      borderBottom: "1px solid #1a2e1f",
                      background: i % 2 === 0 ? "#0d150f" : "transparent",
                    }}
                  >
                    <td style={{ padding: "10px 12px" }}>
                      <span
                        style={{
                          fontFamily: "monospace",
                          fontWeight: 700,
                          color:
                            entry.posicion === 1
                              ? "#f39c12"
                              : entry.posicion === 2
                              ? "#aaa"
                              : entry.posicion === 3
                              ? "#cd7f32"
                              : "#555",
                        }}
                      >
                        {entry.posicion === 1 ? "🥇" : entry.posicion === 2 ? "🥈" : entry.posicion === 3 ? "🥉" : `${entry.posicion}º`}
                      </span>
                    </td>
                    <td style={{ padding: "10px 12px", fontWeight: 600 }}>{entry.nombre}</td>
                    <td style={{ padding: "10px 12px", fontFamily: "monospace", fontWeight: 700, color: "#00ff88" }}>
                      {entry.puntos_totales}
                    </td>
                    <td style={{ padding: "10px 12px", fontFamily: "monospace" }}>
                      {entry.puntos_ultima_jornada}
                    </td>
                    <td style={{ padding: "10px 12px", fontFamily: "monospace" }}>
                      {fmt(entry.valor_plantilla || 0)}
                    </td>
                    {(() => {
                      // saldo_estimado lo calcula el backend en /clasificacion:
                      //   - Rival: 50M − valor_plantilla + Σventas − Σcompras (es_estimado=true)
                      //   - Usuario logueado: saldo real de finanzas (es_estimado=false)
                      // Fallback al cálculo legacy si el backend no lo devuelve.
                      const esYo = entry.id === miUserId;
                      const saldo = entry.saldo_estimado
                        ?? (esYo ? saldoActual : (50_000_000 - (entry.valor_plantilla || 0)));
                      const esEstimado = entry.es_estimado ?? !esYo;
                      const color = saldo >= 0 ? "#00ff88" : "#e74c3c";
                      return (
                        <td style={{ padding: "10px 12px", fontFamily: "monospace", color }}>
                          {fmt(saldo)}
                          {esEstimado && <span style={{ color: "#555", fontSize: "0.7rem", marginLeft: "4px" }}>~est.</span>}
                        </td>
                      );
                    })()}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* ── TRANSFERENCIAS ── */}
      {tab === "transfers" && (
        <div>
          <input
            type="text"
            placeholder="Buscar jugador..."
            value={busquedaTransfer}
            onChange={(e) => setBusquedaTransfer(e.target.value)}
            style={{
              width: "100%",
              marginBottom: "0.75rem",
              padding: "8px 12px",
              background: "#111a14",
              border: "1px solid #1a2e1f",
              borderRadius: "6px",
              color: "#e0ffe8",
              fontSize: "0.9rem",
              outline: "none",
              boxSizing: "border-box",
            }}
          />
          {transfers.length === 0 ? (
            <div style={{ textAlign: "center", color: "#555", padding: "3rem" }}>
              Sin transferencias — pulsa "Sincronizar Todo"
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
              {transfers
                .filter((t) => !busquedaTransfer || t.jugador_nombre.toLowerCase().includes(busquedaTransfer.toLowerCase()))
                .map((t) => (
                <div
                  key={t.id}
                  style={{
                    background: "#111a14",
                    border: "1px solid #1a2e1f",
                    borderRadius: "6px",
                    padding: "0.75rem 1rem",
                    display: "flex",
                    alignItems: "center",
                    gap: "0.75rem",
                    flexWrap: "wrap",
                  }}
                >
                  <span
                    style={{
                      background: t.tipo === "market" ? "#00ff8822" : "#e74c3c22",
                      color: t.tipo === "market" ? "#00ff88" : "#e74c3c",
                      border: `1px solid ${t.tipo === "market" ? "#00ff8844" : "#e74c3c44"}`,
                      padding: "2px 8px",
                      borderRadius: "3px",
                      fontSize: "0.7rem",
                      fontWeight: 700,
                    }}
                  >
                    {t.tipo === "market" ? "COMPRA" : "VENTA"}
                  </span>
                  <span style={{ fontWeight: 600 }}>{t.usuario_nombre}</span>
                  <span style={{ color: "#aaa" }}>
                    {t.tipo === "market" ? "compró a" : "vendió"}
                  </span>
                  <span style={{ color: "#00ff88", fontWeight: 600 }}>{t.jugador_nombre}</span>
                  <span style={{ color: "#aaa" }}>por</span>
                  <span style={{ fontFamily: "monospace", fontWeight: 700 }}>{fmt(t.precio || 0)}</span>
                  <span style={{ marginLeft: "auto", color: "#555", fontSize: "0.75rem" }}>
                    {t.fecha ? parseFecha(t.fecha).toLocaleDateString("es-ES") : ""}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── GRÁFICO DE PRECIOS ── */}
      {tab === "precios" && (
        <div>
          {chartData.length === 0 ? (
            <div style={{ textAlign: "center", color: "#555", padding: "3rem" }}>
              Sin historial de precios — pulsa "Sincronizar Todo"
            </div>
          ) : (
            <div
              style={{
                background: "#111a14",
                border: "1px solid #1a2e1f",
                borderRadius: "10px",
                padding: "1.5rem",
              }}
            >
              <div style={{ color: "#00ff88", fontWeight: 700, marginBottom: "1rem" }}>
                Evolución de precios — últimos 30 días
              </div>
              <ResponsiveContainer width="100%" height={380}>
                <LineChart data={chartData} margin={{ top: 5, right: 20, left: 10, bottom: 5 }}>
                  <XAxis
                    dataKey="fecha"
                    tick={{ fill: "#555", fontSize: 11 }}
                    tickFormatter={(v: string) => v.slice(5)}
                  />
                  <YAxis
                    tick={{ fill: "#555", fontSize: 11 }}
                    tickFormatter={(v: number) => fmt(v)}
                  />
                  <Tooltip
                    contentStyle={{
                      background: "#111a14",
                      border: "1px solid #1a2e1f",
                      borderRadius: "6px",
                    }}
                    labelStyle={{ color: "#aaa" }}
                    formatter={(value: number) => [fmt(value), ""]}
                  />
                  <Legend wrapperStyle={{ color: "#aaa", fontSize: "0.8rem" }} />
                  {jugadoresUnicos.map((nombre, i) => (
                    <Line
                      key={nombre}
                      type="monotone"
                      dataKey={nombre}
                      stroke={COLORS[i % COLORS.length]}
                      strokeWidth={2}
                      dot={false}
                      connectNulls
                    />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      )}
      {/* ── CALCULADOR DE PUJAS ── */}
      {tab === "pujas" && (
        <div>
          {/* Saldo disponible */}
          <div style={{ background: "#111a14", border: "1px solid #00ff8844", borderRadius: "8px", padding: "1rem", marginBottom: "1.25rem", display: "flex", alignItems: "center", gap: "1.5rem", flexWrap: "wrap" }}>
            <div>
              <div style={{ color: "#555", fontSize: "0.65rem", fontWeight: 700, letterSpacing: "0.05em" }}>SALDO BRUTO</div>
              <div style={{ fontFamily: "monospace", fontSize: "1.0rem", fontWeight: 700, color: "#aaa" }}>{fmt(saldoActual)}</div>
            </div>
            {maximumBid !== null && (
              <div title="Puja máxima reportada por Biwenger (descuenta pujas pendientes y respeta el valor mínimo de plantilla)">
                <div style={{ color: "#555", fontSize: "0.65rem", fontWeight: 700, letterSpacing: "0.05em" }}>PUJA MÁXIMA BIWENGER</div>
                <div style={{ fontFamily: "monospace", fontSize: "1.1rem", fontWeight: 700, color: "#00ff88" }}>{fmt(maximumBid)}</div>
              </div>
            )}
            {ventas.size > 0 && (
              <div>
                <div style={{ color: "#555", fontSize: "0.65rem", fontWeight: 700, letterSpacing: "0.05em" }}>+ VENTAS MARCADAS</div>
                <div style={{ fontFamily: "monospace", fontSize: "1.1rem", fontWeight: 700, color: "#f39c12" }}>
                  +{fmt(plantillaPujas.filter((p) => ventas.has(p.id)).reduce((s, p) => s + (p.precio_actual || 0), 0))}
                </div>
              </div>
            )}
            <div style={{ borderLeft: "1px solid #1a2e1f", paddingLeft: "1.5rem" }} title={maximumBid !== null ? "Puja máxima Biwenger + ventas marcadas" : "Saldo bruto + ventas marcadas (puja máxima Biwenger no disponible)"}>
              <div style={{ color: "#555", fontSize: "0.65rem", fontWeight: 700, letterSpacing: "0.05em" }}>SALDO DISPONIBLE PARA PUJAR</div>
              <div style={{ fontFamily: "monospace", fontSize: "1.3rem", fontWeight: 700, color: "#00ff88" }}>{fmt(saldoDisponible)}</div>
            </div>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1.5rem" }}>
            {/* Jugadores a vender (mi plantilla) */}
            <div>
              <div style={{ color: "#e74c3c", fontFamily: "monospace", fontSize: "0.75rem", fontWeight: 700, marginBottom: "0.5rem", letterSpacing: "0.05em" }}>🔴 MARCO COMO VENDO</div>
              {plantillaPujas.length === 0 ? (
                <div style={{ color: "#555", fontSize: "0.8rem" }}>Sin jugadores — sincroniza primero</div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: "4px", maxHeight: "340px", overflowY: "auto" }}>
                  {plantillaPujas.map((p) => (
                    <label key={p.id} style={{ display: "flex", alignItems: "center", gap: "8px", background: ventas.has(p.id) ? "#e74c3c18" : "#111a14", border: `1px solid ${ventas.has(p.id) ? "#e74c3c44" : "#1a2e1f"}`, borderRadius: "5px", padding: "6px 10px", cursor: "pointer" }}>
                      <input
                        type="checkbox"
                        checked={ventas.has(p.id)}
                        onChange={() => setVentas((prev) => { const n = new Set(prev); n.has(p.id) ? n.delete(p.id) : n.add(p.id); return n; })}
                        style={{ accentColor: "#e74c3c" }}
                      />
                      <span style={{ flex: 1, fontSize: "0.82rem", fontWeight: 600 }}>{p.nombre}</span>
                      <span style={{ fontFamily: "monospace", fontSize: "0.78rem", color: "#e74c3c" }}>{fmt(p.precio_actual || 0)}</span>
                    </label>
                  ))}
                </div>
              )}
            </div>

            {/* Objetivos del mercado */}
            <div>
              <div style={{ color: "#4a90e2", fontFamily: "monospace", fontSize: "0.75rem", fontWeight: 700, marginBottom: "0.5rem", letterSpacing: "0.05em" }}>🎯 OBJETIVOS DEL MERCADO</div>
              {mercadoPujas.length === 0 ? (
                <div style={{ color: "#555", fontSize: "0.8rem" }}>Mercado vacío — sincroniza primero</div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: "4px", maxHeight: "340px", overflowY: "auto" }}>
                  {mercadoPujas.map((m) => (
                    <label key={m.id} style={{ display: "flex", alignItems: "center", gap: "8px", background: objetivos.has(m.id) ? "#4a90e218" : "#111a14", border: `1px solid ${objetivos.has(m.id) ? "#4a90e244" : "#1a2e1f"}`, borderRadius: "5px", padding: "6px 10px", cursor: "pointer" }}>
                      <input
                        type="checkbox"
                        checked={objetivos.has(m.id)}
                        onChange={() => setObjetivos((prev) => { const n = new Set(prev); n.has(m.id) ? n.delete(m.id) : n.add(m.id); return n; })}
                        style={{ accentColor: "#4a90e2" }}
                      />
                      <span style={{ flex: 1, fontSize: "0.82rem", fontWeight: 600 }}>{m.nombre}</span>
                      <span style={{ fontFamily: "monospace", fontSize: "0.78rem", color: "#4a90e2" }}>{fmt(m.precio || 0)}</span>
                    </label>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Calcular puja por objetivos marcados */}
          {objetivos.size > 0 && (
            <div style={{ marginTop: "1.5rem" }}>
              <div style={{ color: "#00ff88", fontFamily: "monospace", fontSize: "0.75rem", fontWeight: 700, marginBottom: "0.75rem", letterSpacing: "0.05em" }}>💡 CÁLCULO DE PUJA ÓPTIMA</div>
              {mercadoPujas.filter((m) => objetivos.has(m.id)).map((m) => (
                <div key={m.id} style={{ background: "#111a14", border: "1px solid #4a90e244", borderRadius: "8px", padding: "0.75rem 1rem", marginBottom: "0.5rem" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "1rem", flexWrap: "wrap" }}>
                    <span style={{ fontWeight: 700, flex: 1 }}>{m.nombre}</span>
                    <span style={{ fontFamily: "monospace", color: "#4a90e2", fontSize: "0.85rem" }}>{fmt(m.precio)}</span>
                    <button
                      onClick={() => calcularPuja(m)}
                      disabled={pujandoId !== null}
                      style={{ background: pujandoId === m.id ? "#1a2e1f" : "#4a90e222", border: "1px solid #4a90e244", color: "#4a90e2", padding: "4px 14px", borderRadius: "4px", cursor: pujandoId !== null ? "not-allowed" : "pointer", fontSize: "0.8rem", fontWeight: 700 }}
                    >
                      {pujandoId === m.id ? "Calculando..." : "Calcular puja"}
                    </button>
                  </div>
                  {pujasResultados[m.id] && (
                    <div style={{ marginTop: "0.5rem", color: "#ccc", fontSize: "0.85rem", lineHeight: 1.5, borderTop: "1px solid #1a2e1f", paddingTop: "0.5rem" }}>
                      {pujasResultados[m.id]}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
