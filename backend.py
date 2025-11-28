import psycopg2
from psycopg2.extras import RealDictCursor
import streamlit as st

# gestore db
#classe per parlare con Supabase 
class DatabaseManager:
    def __init__(self):
        # lettura ps da file segreto
        try:
            self.db_url = st.secrets["SUPABASE_URL"]
        except:
            st.error("Manca il link SUPABASE_URL nei secrets! Controlla.")
            st.stop()

    # esegue comandi sql 
    def execute(self, sql, params=()):
        conn = None
        try:
            # connesione al cloud
            conn = psycopg2.connect(self.db_url)
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute(sql, params)
            
            # Se la richiesta inizia con SELECT vuol dire che voglio leggere dati
            if sql.strip().upper().startswith("SELECT"):
                return cursor.fetchall()
            # Altrimenti (INSERT, UPDATE) sto modificando, quindi salvo (commit)
            else:
                conn.commit()
                return True
        except Exception as e:
            st.error(f"Ahi, errore nel database: {e}")
            return []
        finally:
            # chiusura in uscita
            if conn: conn.close()

# gestore linee produttive
class LineaManager:
    def __init__(self, db_manager):
        self.db = db_manager
        self.init_lines()

    def init_lines(self):
        # creazione tabella linee se non gia presente
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS linee_produttive (
                id INTEGER PRIMARY KEY,
                nome TEXT,
                vincoli TEXT,
                stato TEXT DEFAULT 'Attiva',
                motivo_fermo TEXT DEFAULT '',
                pezzi_fatti INTEGER DEFAULT 0,
                pezzi_scarti INTEGER DEFAULT 0,
                target_assegnato TEXT DEFAULT ''
            );
        """)
        # se è vuota creo le 5 linee 
        if not self.db.execute("SELECT * FROM linee_produttive"):
            lines_setup = [
                (1, "Linea 1 (Porsche/Merc)", "SOLO Porsche, Mercedes"),
                (2, "Linea 2 (Ferrari/Audi)", "SOLO Ferrari, Audi"),
                (3, "Linea 3 (Ferrari/Audi)", "SOLO Ferrari, Audi"),
                (4, "Linea 4 (Jolly)", "TUTTI"),
                (5, "Linea 5 (Jolly)", "TUTTI")
            ]
            for l in lines_setup:
                self.db.execute("INSERT INTO linee_produttive (id, nome, vincoli) VALUES (%s, %s, %s)", (l[0], l[1], l[2]))

    # legge lo stato di tutte le linee
    def get_status(self):
        return self.db.execute("SELECT * FROM linee_produttive ORDER BY id")

    # Aggiunge pezzi (buoni o scarti) a una linea specifica
    def update_counts(self, linea_id, buoni=0, scarti=0):
        self.db.execute("UPDATE linee_produttive SET pezzi_fatti = pezzi_fatti + %s, pezzi_scarti = pezzi_scarti + %s WHERE id = %s", (buoni, scarti, linea_id))

    # Ferma o fa ripartire una linea
    def set_stato(self, linea_id, stato, motivo=""):
        self.db.execute("UPDATE linee_produttive SET stato = %s, motivo_fermo = %s WHERE id = %s", (stato, motivo, linea_id))
    
    # Assegna un ordine a una linea (Cosa deve produrre)
    def assegna_commessa(self, linea_id, codice_commessa):
        self.db.execute("UPDATE linee_produttive SET target_assegnato = %s WHERE id = %s", (codice_commessa, linea_id))

    # --- FUNZIONE NUOVA IMPORTANTE ---
    # Questa fa la somma di TUTTI i pezzi prodotti per ogni ordine, 
    # sommando il lavoro di tutte le linee insieme.
    def get_produzione_per_ordine(self):
        sql = "SELECT target_assegnato, SUM(pezzi_fatti) as tot FROM linee_produttive WHERE target_assegnato != '' GROUP BY target_assegnato"
        res = self.db.execute(sql)
        # trasformo in un dizionario facile da usare: {'ORD-01': 500, 'ORD-02': 150}
        return {r['target_assegnato']: r['tot'] for r in res}

    # Calcola il totale assoluto di pezzi fatti oggi (per la dashboard in alto)
    def get_totale_produzione(self):
        res = self.db.execute("SELECT SUM(pezzi_fatti) as tot FROM linee_produttive")
        return res[0]['tot'] if res[0]['tot'] else 0

# gestione oridni
class OrdineManager:
    def __init__(self, db_manager):
        self.db = db_manager
        self.init_orders()

    def init_orders(self):
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS ordini_produzione (
                codice TEXT PRIMARY KEY,
                modello TEXT,
                quantita INTEGER,
                deadline TEXT
            );
        """)

    # inserisce un nuovo ordine nel database
    def add_ordine(self, codice, modello, quantita, deadline):
        self.db.execute("INSERT INTO ordini_produzione (codice, modello, quantita, deadline) VALUES (%s, %s, %s, %s)", (codice, modello, quantita, deadline))

    # recupera la lista ordini
    def get_ordini(self):
        return self.db.execute("SELECT * FROM ordini_produzione")

    # prepara un testo leggibile per AI
    def get_ordini_text(self):
        data = self.get_ordini()
        if not data: return "Nessun ordine attivo."
        return "\n".join([f"- {o['codice']}: {o['quantita']}x {o['modello']} (Deadline: {o['deadline']})" for o in data])

    # reset fine giornata
    def reset_giornata(self):
        self.db.execute("DELETE FROM ordini_produzione")
        self.db.execute("UPDATE linee_produttive SET pezzi_fatti=0, pezzi_scarti=0, stato='Attiva', motivo_fermo='', target_assegnato=''")

    # somma quanti pezzi dobbiamo fare in totale oggi
    def get_totale_target(self):
        res = self.db.execute("SELECT SUM(quantita) as tot FROM ordini_produzione")
        return res[0]['tot'] if res[0]['tot'] else 0
