-- Smart Factory MES v6.1 - Migrazione "Storico Produzione + Obiettivi"

-- 1) (Opzionale) verifica tabella linee esistente
-- Se già esiste, lascia così.

-- 2) Storico eventi produzione (OK/KO/START/STOP)
CREATE TABLE IF NOT EXISTS produzione_eventi (
  id BIGSERIAL PRIMARY KEY,
  ts TIMESTAMPTZ NOT NULL DEFAULT now(),
  linea_id INTEGER NOT NULL REFERENCES linee_produttive(id) ON DELETE CASCADE,
  ordine_codice TEXT DEFAULT '',
  tipo TEXT NOT NULL CHECK (tipo IN ('OK','KO','START','STOP')),
  qta INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_prod_eventi_linea_ts
  ON produzione_eventi(linea_id, ts);

-- 3) Obiettivi giornalieri per linea (target OK)
CREATE TABLE IF NOT EXISTS obiettivi_linea_giorno (
  giorno DATE NOT NULL,
  linea_id INTEGER NOT NULL REFERENCES linee_produttive(id) ON DELETE CASCADE,
  target_ok INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (giorno, linea_id)
);
