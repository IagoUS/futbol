// URL base del backend. Se sobrescribe en producción vía REACT_APP_API_URL
// (definida en render.yaml para el deploy estático). En local cae a localhost.
export const API_URL = process.env.REACT_APP_API_URL || "http://localhost:8000";
