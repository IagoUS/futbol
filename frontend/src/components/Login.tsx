// Pantalla de login — autenticación con credenciales de Biwenger
import React, { FormEvent, useState } from "react";
import { api } from "../api";

interface LoginProps {
  onLogin: (userName: string, userId: number) => void;
}

export default function Login({ onLogin }: LoginProps) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!email || !password) {
      setError("Introduce tu email y contraseña de Biwenger");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const result = await api.login(email, password);
      if (result.ok) {
        onLogin(result.user_name || "Usuario", result.user_id || 0);
      } else {
        setError(result.detail || "Error de autenticación");
      }
    } catch (e: unknown) {
      const raw = e instanceof Error ? e.message : String(e);
      // Parsear el detalle del error HTTP
      if (raw.includes("401")) {
        setError("Email o contraseña incorrectos");
      } else if (raw.includes("500")) {
        setError("No se puede conectar con Biwenger — comprueba tu conexión");
      } else {
        setError(raw);
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        background: "#0a0f0d",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "1rem",
      }}
    >
      <div
        style={{
          width: "100%",
          maxWidth: "420px",
        }}
      >
        {/* Logo */}
        <div style={{ textAlign: "center", marginBottom: "2.5rem" }}>
          <div style={{ fontSize: "3rem", marginBottom: "0.5rem" }}>⚽</div>
          <div
            style={{
              fontFamily: "monospace",
              fontWeight: 800,
              fontSize: "1.8rem",
              color: "#00ff88",
              letterSpacing: "0.1em",
            }}
          >
            BIWENGER AGENT
          </div>
          <div style={{ color: "#555", fontSize: "0.9rem", marginTop: "0.25rem" }}>
            Introduce tus credenciales de Biwenger para comenzar
          </div>
        </div>

        {/* Formulario */}
        <form onSubmit={handleSubmit}>
          <div
            style={{
              background: "#111a14",
              border: "1px solid #1a2e1f",
              borderRadius: "12px",
              padding: "2rem",
            }}
          >
            {/* Email */}
            <div style={{ marginBottom: "1.25rem" }}>
              <label
                style={{
                  display: "block",
                  color: "#00ff88",
                  fontSize: "0.75rem",
                  fontWeight: 700,
                  letterSpacing: "0.05em",
                  marginBottom: "6px",
                }}
              >
                EMAIL DE BIWENGER
              </label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="tu@email.com"
                autoComplete="email"
                style={{
                  width: "100%",
                  background: "#0a0f0d",
                  border: "1px solid #2a3e2f",
                  borderRadius: "6px",
                  color: "#fff",
                  padding: "10px 14px",
                  fontSize: "1rem",
                  outline: "none",
                  boxSizing: "border-box",
                  transition: "border-color 0.15s",
                }}
                onFocus={(e) =>
                  ((e.currentTarget as HTMLInputElement).style.borderColor = "#00ff88")
                }
                onBlur={(e) =>
                  ((e.currentTarget as HTMLInputElement).style.borderColor = "#2a3e2f")
                }
              />
            </div>

            {/* Contraseña */}
            <div style={{ marginBottom: "1.5rem" }}>
              <label
                style={{
                  display: "block",
                  color: "#00ff88",
                  fontSize: "0.75rem",
                  fontWeight: 700,
                  letterSpacing: "0.05em",
                  marginBottom: "6px",
                }}
              >
                CONTRASEÑA DE BIWENGER
              </label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                autoComplete="current-password"
                style={{
                  width: "100%",
                  background: "#0a0f0d",
                  border: "1px solid #2a3e2f",
                  borderRadius: "6px",
                  color: "#fff",
                  padding: "10px 14px",
                  fontSize: "1rem",
                  outline: "none",
                  boxSizing: "border-box",
                  transition: "border-color 0.15s",
                }}
                onFocus={(e) =>
                  ((e.currentTarget as HTMLInputElement).style.borderColor = "#00ff88")
                }
                onBlur={(e) =>
                  ((e.currentTarget as HTMLInputElement).style.borderColor = "#2a3e2f")
                }
              />
            </div>

            {/* Error */}
            {error && (
              <div
                style={{
                  background: "#2d0a0a",
                  border: "1px solid #e74c3c55",
                  borderRadius: "6px",
                  padding: "10px 14px",
                  color: "#e74c3c",
                  fontSize: "0.875rem",
                  marginBottom: "1.25rem",
                  lineHeight: 1.4,
                }}
              >
                ⚠️ {error}
              </div>
            )}

            {/* Botón */}
            <button
              type="submit"
              disabled={loading}
              style={{
                width: "100%",
                background: loading ? "#1a2e1f" : "#00ff88",
                color: loading ? "#00ff88" : "#0a0f0d",
                border: loading ? "1px solid #00ff88" : "none",
                borderRadius: "8px",
                padding: "13px",
                fontSize: "1rem",
                fontWeight: 700,
                cursor: loading ? "not-allowed" : "pointer",
                letterSpacing: "0.05em",
                transition: "all 0.2s",
              }}
            >
              {loading ? "⏳ Conectando con Biwenger..." : "🔐 INICIAR SESIÓN"}
            </button>
          </div>
        </form>

        {/* Aviso de privacidad */}
        <div
          style={{
            textAlign: "center",
            color: "#333",
            fontSize: "0.75rem",
            marginTop: "1.25rem",
            lineHeight: 1.5,
          }}
        >
          Tus credenciales se guardan localmente en SQLite.
          <br />
          Nunca se envían a terceros.
        </div>
      </div>
    </div>
  );
}
