// App principal — barra superior + 4 pestañas
import React, { useEffect, useState } from "react";
import Mercado from "./components/Mercado";
import MiPlantilla from "./components/MiPlantilla";
import CerebroIA from "./components/CerebroIA";
import Liga from "./components/Liga";
import Login from "./components/Login";
import { api } from "./api";

type Tab = "mercado" | "plantilla" | "cerebro" | "liga";

interface AuthState {
  loggedIn: boolean;
  userName: string;
  userId: number;
  checked: boolean;
}

interface Finanzas {
  saldo: number;
  valor_plantilla: number;
}

interface ClasificacionEntry {
  id: number;
  nombre: string;
  puntos_totales: number;
  posicion: number;
}

const TABS: { id: Tab; label: string }[] = [
  { id: "mercado", label: "🏪 Mercado" },
  { id: "plantilla", label: "👥 Mi Plantilla" },
  { id: "cerebro", label: "🧠 Cerebro IA" },
  { id: "liga", label: "📊 Liga" },
];

const fmt = (n: number) =>
  n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}M€` : n >= 1000 ? `${(n / 1000).toFixed(0)}K€` : `${n}€`;

export default function App() {
  const [tab, setTab] = useState<Tab>("cerebro");
  const [finanzas, setFinanzas] = useState<Finanzas | null>(null);
  const [miPosicion, setMiPosicion] = useState<number | null>(null);
  const [auth, setAuth] = useState<AuthState>({ loggedIn: false, userName: "", userId: 0, checked: false });

  // Comprobar sesión al arrancar
  useEffect(() => {
    api
      .authStatus()
      .then((d) => {
        setAuth({ loggedIn: d.logged_in, userName: d.user_name || "", userId: d.user_id || 0, checked: true });
      })
      .catch(() => {
        setAuth({ loggedIn: false, userName: "", userId: 0, checked: true });
      });
  }, []);

  // Cargar datos del dashboard cuando hay sesión
  useEffect(() => {
    if (!auth.loggedIn) return;
    api.finanzas().then((d) => setFinanzas(d.data || null)).catch(() => {});
    api.clasificacion().then((d) => {
      const tabla: ClasificacionEntry[] = d.data || [];
      const miRow = tabla.find((e) => e.id === auth.userId) ?? tabla[0];
      if (miRow) setMiPosicion(miRow.posicion);
    }).catch(() => {});
  }, [auth.loggedIn]);

  const handleLogin = (userName: string, userId: number) => {
    setAuth({ loggedIn: true, userName, userId, checked: true });
  };

  const handleLogout = async () => {
    await api.logout().catch(() => {});
    setAuth({ loggedIn: false, userName: "", userId: 0, checked: true });
    setFinanzas(null);
    setMiPosicion(null);
  };

  // Mientras comprueba el estado de sesión — spinner mínimo
  if (!auth.checked) {
    return (
      <div style={{ minHeight: "100vh", background: "#0a0f0d", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <div style={{ color: "#00ff88", fontFamily: "monospace", fontSize: "1.1rem" }}>⏳ Cargando...</div>
      </div>
    );
  }

  // Sin sesión — mostrar pantalla de login
  if (!auth.loggedIn) {
    return <Login onLogin={handleLogin} />;
  }

  return (
    <div style={{ minHeight: "100vh", background: "#0a0f0d", color: "#e0e0e0" }}>
      {/* ── Barra superior ── */}
      <header
        style={{
          background: "#0d150f",
          borderBottom: "1px solid #1a2e1f",
          padding: "0 1.5rem",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          height: "60px",
          position: "sticky",
          top: 0,
          zIndex: 100,
        }}
      >
        {/* Logo */}
        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
          <span style={{ fontSize: "1.4rem" }}>⚽</span>
          <span
            style={{
              fontWeight: 800,
              fontSize: "1.1rem",
              color: "#00ff88",
              fontFamily: "monospace",
              letterSpacing: "0.1em",
            }}
          >
            BIWENGER AGENT
          </span>
          <span
            style={{
              background: "#00ff8822",
              color: "#00ff88",
              border: "1px solid #00ff8444",
              padding: "1px 7px",
              borderRadius: "3px",
              fontSize: "0.65rem",
              fontWeight: 700,
            }}
          >
            MUNDIAL 2026
          </span>
        </div>

        {/* Stats */}
        <div style={{ display: "flex", gap: "1.5rem", alignItems: "center" }}>
          {/* Usuario logueado */}
          <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
            <span style={{ color: "#aaa", fontSize: "0.85rem" }}>
              👤 <span style={{ color: "#00ff88", fontWeight: 600 }}>{auth.userName}</span>
            </span>
            <button
              onClick={handleLogout}
              style={{
                background: "transparent",
                border: "1px solid #333",
                color: "#666",
                padding: "4px 10px",
                borderRadius: "4px",
                cursor: "pointer",
                fontSize: "0.75rem",
                transition: "all 0.15s",
              }}
              onMouseEnter={(e) => {
                (e.currentTarget as HTMLButtonElement).style.borderColor = "#e74c3c";
                (e.currentTarget as HTMLButtonElement).style.color = "#e74c3c";
              }}
              onMouseLeave={(e) => {
                (e.currentTarget as HTMLButtonElement).style.borderColor = "#333";
                (e.currentTarget as HTMLButtonElement).style.color = "#666";
              }}
            >
              Cerrar sesión
            </button>
          </div>

          {finanzas && (
            <>
              <div style={{ textAlign: "center" }}>
                <div style={{ color: "#555", fontSize: "0.6rem", fontWeight: 700 }}>SALDO</div>
                <div style={{ color: "#00ff88", fontFamily: "monospace", fontWeight: 700, fontSize: "0.9rem" }}>
                  {fmt(finanzas.saldo || 0)}
                </div>
              </div>
              <div style={{ textAlign: "center" }}>
                <div style={{ color: "#555", fontSize: "0.6rem", fontWeight: 700 }}>PLANTILLA</div>
                <div style={{ color: "#4a90e2", fontFamily: "monospace", fontWeight: 700, fontSize: "0.9rem" }}>
                  {fmt(finanzas.valor_plantilla || 0)}
                </div>
              </div>
            </>
          )}

          {miPosicion && (
            <div style={{ textAlign: "center" }}>
              <div style={{ color: "#555", fontSize: "0.6rem", fontWeight: 700 }}>POSICIÓN</div>
              <div style={{ color: "#f39c12", fontFamily: "monospace", fontWeight: 700, fontSize: "0.9rem" }}>
                {miPosicion}º
              </div>
            </div>
          )}
        </div>
      </header>

      {/* ── Tabs de navegación ── */}
      <nav
        style={{
          background: "#0d150f",
          borderBottom: "1px solid #1a2e1f",
          display: "flex",
          padding: "0 1rem",
        }}
      >
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            style={{
              background: "transparent",
              border: "none",
              borderBottom: tab === t.id ? "2px solid #00ff88" : "2px solid transparent",
              color: tab === t.id ? "#00ff88" : "#666",
              padding: "12px 20px",
              cursor: "pointer",
              fontSize: "0.9rem",
              fontWeight: tab === t.id ? 700 : 400,
              transition: "all 0.15s",
              letterSpacing: "0.02em",
            }}
            onMouseEnter={(e) => {
              if (tab !== t.id)
                (e.currentTarget as HTMLButtonElement).style.color = "#aaa";
            }}
            onMouseLeave={(e) => {
              if (tab !== t.id)
                (e.currentTarget as HTMLButtonElement).style.color = "#666";
            }}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {/* ── Contenido principal ── */}
      <main style={{ maxWidth: "1400px", margin: "0 auto" }}>
        {tab === "mercado" && <Mercado />}
        {tab === "plantilla" && <MiPlantilla />}
        {tab === "cerebro" && <CerebroIA />}
        {tab === "liga" && <Liga miUserId={auth.userId} />}
      </main>
    </div>
  );
}
