import serial
import time
import psycopg2
from psycopg2.extras import RealDictCursor

# configurazione
# controllo su quale porta ho attaccato arduino
ARDUINO_PORT = 'COM3' 
BAUD_RATE = 9600

# qui metto la stringa di supabase con la password
DB_URL = "postgresql://postgres.topizuytggdbpgpawgdw:LA_TUA_PASSWORD@aws-0-eu-central-1.pooler.supabase.com:6543/postgres"

# provo a connettermi al database
def connect_db():
    try:
        return psycopg2.connect(DB_URL)
    except Exception as e:
        print(f"non riesco a connettermi al db: {e}")
        return None

# avvio tutto
def main():
    print(f"cerco arduino sulla porta {ARDUINO_PORT}...")
    try:
        ser = serial.Serial(ARDUINO_PORT, BAUD_RATE, timeout=1)
        time.sleep(2) # aspetto che si svegli
        print("fatto! sono connesso ad arduino.")
    except:
        print("errore: non trovo arduino. controlla il cavo.")
        return

    conn = connect_db()
    
    # ciclo infinito
    while True:
        # 1. ascolto arduino
        if ser.in_waiting > 0:
            try:
                line = ser.readline().decode('utf-8').strip()
                
                # se arduino mi dice che ha fatto un pezzo
                if line.startswith("BTN:"):
                    linea_id = int(line.split(":")[1])
                    print(f"ho ricevuto un segnale dalla linea {linea_id}! lo dico al cloud...")
                    
                    # aggiorno il database
                    if conn.closed: conn = connect_db()
                    cur = conn.cursor()
                    cur.execute("UPDATE linee_produttive SET pezzi_fatti = pezzi_fatti + 1 WHERE id = %s", (linea_id,))
                    conn.commit()
                    print(f"fatto. database aggiornato per linea {linea_id}")
            except Exception as e:
                print(f"ho avuto un problema a scrivere: {e}")

        # 2. leggo dal cloud per accendere le luci
        try:
            if conn.closed: conn = connect_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            # chiedo quali linee sono attive
            cur.execute("SELECT id, stato FROM linee_produttive ORDER BY id ASC")
            rows = cur.fetchall()
            
            # creo la stringa tipo "11011"
            stato_stringa = ""
            for r in rows:
                if r['stato'] == 'Attiva':
                    stato_stringa += "1"
                else:
                    stato_stringa += "0"
            
            # spedisco ad arduino se ho tutti i dati
            if len(stato_stringa) == 5:
                ser.write((stato_stringa + "\n").encode())
                
        except Exception as e:
            pass # se fallisco riprovo dopo

        time.sleep(0.2) # riposo un attimo

if __name__ == "__main__":
    main()
