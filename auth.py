# MVP autenticazione: utenti hardcoded, password in plaintext.
# In produzione: migrazione a Supabase Auth con hash bcrypt e Row Level Security.
# Vedi roadmap Fase 2 in CLAUDE.md.
from __future__ import annotations

USERS: dict[str, dict] = {
    "admin":     {"password": "admin",  "name": "Admin",     "role": "admin"},
    "operatore": {"password": "op123",  "name": "Operatore", "role": "operatore"},
    "viewer":    {"password": "v123",   "name": "Viewer",    "role": "viewer"},
}


def authenticate(username: str, password: str) -> dict | None:
    """Verifica le credenziali e ritorna il profilo utente, o None se non valide."""
    user = USERS.get(username)
    if user and user["password"] == password:
        return {"username": username, "name": user["name"], "role": user["role"]}
    return None


def can_write(role: str) -> bool:
    """Ritorna True se il ruolo può eseguire azioni di scrittura."""
    return role in ("admin", "operatore")
