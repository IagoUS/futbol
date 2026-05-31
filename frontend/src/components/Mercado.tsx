// Pestaña Mercado de Fichajes
import React, { useEffect, useState } from "react";
import { api } from "../api";

interface Jugador {
  id: number;
  nombre: string;
  posicion: string;
  equipo: string;
  team_name: string;
  precio: number;
  puntos_ultima_jornada: number;
  tendencia: number;
  score_oportunidad: number;
  status_cf: string;
  status_info: string | null;
  price_increment: number;
  next_match_date: number | null;
  next_match_rival: string | null;
}

const fmtDate = (ts: number | null) => {
  if (!ts) return null;
  return new Date(ts * 1000).toLocaleDateString("es-ES", { day: "2-digit", month: "2-digit" });
};

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

export default function Mercado() {
  const [jugadores, setJugadores] = useState<Jugador[]>([]);
  const [loading, setLoading] = useState(true);
  const [filtroPos, setFiltroPos] = useState("Todos");
  const [filtroMaxPrecio, setFiltroMaxPrecio] = useState(50_000_000);
  const [filtroMinScore, setFiltroMinScore] = useState(0);
  const [busqueda, setBusqueda] = useState("");

  useEffect(() => {
    api
      .mercado()
      .then((d) => setJugadores(d.data || []))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  const filtrados = jugadores
    .filter((j) => filtroPos === "Todos" || j.posicion === filtroPos)
    .filter((j) => j.precio <= filtroMaxPrecio)
    .filter((j) => j.score_oportunidad >= filtroMinScore)
    .filter((j) =>
      j.nombre.toLowerCase().includes(busqueda.toLowerCase()) ||
      j.equipo.toLowerCase().includes(busqueda.toLowerCase())
    );

  return (
    <div style={{ padding: "1rem" }}>
      {/* Filtros */}
      <div
        style={{
          display: "flex",
          gap: "1rem",
          flexWrap: "wrap",
          marginBottom: "1rem",
          background: "#111a14",
          padding: "1rem",
          borderRadius: "8px",
          border: "1px solid #1a2e1f",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
          <label style={{ color: "#00ff88", fontSize: "0.75rem", fontWeight: 600 }}>
            POSICIÓN
          </label>
          <select
            value={filtroPos}
            onChange={(e) => setFiltroPos(e.target.value)}
            style={{
              background: "#0a0f0d",
              border: "1px solid #00ff88",
              color: "#fff",
              padding: "6px 10px",
              borderRadius: "4px",
              cursor: "pointer",
            }}
          >
            {["Todos", "Portero", "Defensa", "Centrocampista", "Delantero"].map((p) => (
              <option key={p}>{p}</option>
            ))}
          </select>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
          <label style={{ color: "#00ff88", fontSize: "0.75rem", fontWeight: 600 }}>
            PRECIO MÁX: {fmt(filtroMaxPrecio)}
          </label>
          <input
            type="range"
            min={0}
            max={50_000_000}
            step={500_000}
            value={filtroMaxPrecio}
            onChange={(e) => setFiltroMaxPrecio(Number(e.target.value))}
            style={{ accentColor: "#00ff88", width: "180px" }}
          />
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
          <label style={{ color: "#00ff88", fontSize: "0.75rem", fontWeight: 600 }}>
            SCORE MÍN: {filtroMinScore}
          </label>
          <input
            type="range"
            min={0}
            max={100}
            value={filtroMinScore}
            onChange={(e) => setFiltroMinScore(Number(e.target.value))}
            style={{ accentColor: "#00ff88", width: "180px" }}
          />
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: "4px", flex: 1, minWidth: "200px" }}>
          <label style={{ color: "#00ff88", fontSize: "0.75rem", fontWeight: 600 }}>
            BUSCAR
          </label>
          <input
            type="text"
            placeholder="Nombre o equipo..."
            value={busqueda}
            onChange={(e) => setBusqueda(e.target.value)}
            style={{
              background: "#0a0f0d",
              border: "1px solid #333",
              color: "#fff",
              padding: "6px 10px",
              borderRadius: "4px",
              outline: "none",
            }}
          />
        </div>
      </div>

      {loading ? (
        <div style={{ textAlign: "center", color: "#00ff88", padding: "3rem" }}>
          Cargando mercado...
        </div>
      ) : filtrados.length === 0 ? (
        <div style={{ textAlign: "center", color: "#555", padding: "3rem" }}>
          No hay jugadores — pulsa "Sincronizar Todo" para obtener datos
        </div>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.9rem" }}>
            <thead>
              <tr style={{ borderBottom: "2px solid #00ff88" }}>
                {["POS", "JUGADOR", "EQUIPO", "PRECIO", "TENDENCIA", "ESTADO", "PRÓXIMO", "SCORE", ""].map((h) => (
                  <th
                    key={h}
                    style={{
                      padding: "10px 12px",
                      textAlign: "left",
                      color: "#00ff88",
                      fontFamily: "monospace",
                      fontSize: "0.75rem",
                      fontWeight: 700,
                      letterSpacing: "0.05em",
                    }}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtrados.map((j, i) => (
                <tr
                  key={j.id}
                  style={{
                    borderBottom: "1px solid #1a2e1f",
                    background: i % 2 === 0 ? "#0d150f" : "transparent",
                    transition: "background 0.15s",
                  }}
                  onMouseEnter={(e) =>
                    ((e.currentTarget as HTMLTableRowElement).style.background = "#152018")
                  }
                  onMouseLeave={(e) =>
                    ((e.currentTarget as HTMLTableRowElement).style.background =
                      i % 2 === 0 ? "#0d150f" : "transparent")
                  }
                >
                  <td style={{ padding: "10px 12px" }}>
                    <span
                      style={{
                        background: posColor[j.posicion] || "#666",
                        color: "#fff",
                        padding: "2px 7px",
                        borderRadius: "3px",
                        fontSize: "0.7rem",
                        fontWeight: 700,
                      }}
                    >
                      {j.posicion?.charAt(0) || "?"}
                    </span>
                  </td>
                  <td style={{ padding: "10px 12px", fontWeight: 600 }}>{j.nombre}</td>
                  <td style={{ padding: "10px 12px", color: "#aaa", fontSize: "0.85rem" }}>{j.team_name || j.equipo}</td>
                  <td style={{ padding: "10px 12px", fontFamily: "monospace" }}>{fmt(j.precio)}</td>
                  <td style={{ padding: "10px 12px", textAlign: "center", fontFamily: "monospace", fontSize: "0.82rem" }}>
                    {(() => {
                      const inc = j.price_increment || 0;
                      const color = inc > 0 ? "#00ff88" : inc < 0 ? "#e74c3c" : "#aaa";
                      const arrow = inc > 0 ? "↑" : inc < 0 ? "↓" : "→";
                      const text = inc !== 0 ? `${inc > 0 ? "+" : ""}${(inc / 1000).toFixed(0)}K€` : "estable";
                      return <span style={{ color }}>{arrow} {text}</span>;
                    })()}
                  </td>
                  <td style={{ padding: "8px 12px", fontSize: "0.78rem" }}>
                    {(() => {
                      const s = j.status_cf || "ok";
                      if (s === "ok") return <span style={{ color: "#00ff88" }}>✅</span>;
                      if (s === "doubt") return <span style={{ color: "#f39c12" }} title={j.status_info || ""}>⚠️ Duda</span>;
                      return <span style={{ color: "#e74c3c" }} title={j.status_info || ""}>🔴</span>;
                    })()}
                  </td>
                  <td style={{ padding: "8px 12px", color: "#888", fontSize: "0.78rem", whiteSpace: "nowrap" }}>
                    {j.next_match_rival
                      ? `vs ${j.next_match_rival}${fmtDate(j.next_match_date) ? ` (${fmtDate(j.next_match_date)})` : ""}`
                      : "—"}
                  </td>
                  <td style={{ padding: "10px 12px" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                      <div
                        style={{
                          width: "60px",
                          height: "8px",
                          background: "#1a2e1f",
                          borderRadius: "4px",
                          overflow: "hidden",
                        }}
                      >
                        <div
                          style={{
                            width: `${j.score_oportunidad}%`,
                            height: "100%",
                            background:
                              j.score_oportunidad >= 70
                                ? "#00ff88"
                                : j.score_oportunidad >= 40
                                ? "#f39c12"
                                : "#e74c3c",
                            borderRadius: "4px",
                          }}
                        />
                      </div>
                      <span
                        style={{
                          fontFamily: "monospace",
                          fontWeight: 700,
                          color:
                            j.score_oportunidad >= 70
                              ? "#00ff88"
                              : j.score_oportunidad >= 40
                              ? "#f39c12"
                              : "#e74c3c",
                        }}
                      >
                        {j.score_oportunidad}
                      </span>
                    </div>
                  </td>
                  <td style={{ padding: "10px 12px" }}>
                    <button
                      style={{
                        background: "transparent",
                        border: "1px solid #00ff88",
                        color: "#00ff88",
                        padding: "4px 12px",
                        borderRadius: "4px",
                        cursor: "pointer",
                        fontSize: "0.8rem",
                        fontWeight: 600,
                        transition: "all 0.15s",
                      }}
                      onMouseEnter={(e) => {
                        (e.currentTarget as HTMLButtonElement).style.background = "#00ff88";
                        (e.currentTarget as HTMLButtonElement).style.color = "#0a0f0d";
                      }}
                      onMouseLeave={(e) => {
                        (e.currentTarget as HTMLButtonElement).style.background = "transparent";
                        (e.currentTarget as HTMLButtonElement).style.color = "#00ff88";
                      }}
                    >
                      Fichar
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ color: "#555", fontSize: "0.8rem", padding: "0.5rem 0", textAlign: "right" }}>
            {filtrados.length} jugadores
          </div>
        </div>
      )}
    </div>
  );
}
