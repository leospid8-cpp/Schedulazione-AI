// mappatura pin
const int NUM_LINEE = 5;

// input (sensore nastro su pin 24, pulsanti su 2,3,4,5,6)
const int PIN_BTN[] = {2, 3, 4, 5, 6};
const int PIN_SENS_NASTRO = 24; 

// output (luci e relè)
const int PIN_LED[] = {8, 9, 10, 11, 12};
const int PIN_RELE = 7;

// memoria
int ultimiStatiBtn[NUM_LINEE] = {HIGH, HIGH, HIGH, HIGH, HIGH};
int ultimoStatoSensore = LOW; 
unsigned long ultimoTempoClick[NUM_LINEE] = {0,0,0,0,0};

// preparo tutto
void setup() {
  Serial.begin(9600);
  
  // configuro le linee manuali
  for(int i=0; i<NUM_LINEE; i++) {
    pinMode(PIN_BTN[i], INPUT_PULLUP);
    pinMode(PIN_LED[i], OUTPUT);
    digitalWrite(PIN_LED[i], HIGH); // accendo per prova
  }

  // configuro la linea 1 reale
  pinMode(PIN_SENS_NASTRO, INPUT); // input normale perche ho la resistenza
  
  // configuro il relè
  pinMode(PIN_RELE, OUTPUT);
  digitalWrite(PIN_RELE, HIGH); // parto fermo
  
  delay(1000); // aspetto un secondo
  
  // spengo tutto e sono pronto
  for(int i=0; i<NUM_LINEE; i++) digitalWrite(PIN_LED[i], LOW);
}

// controllo continuo
void loop() {
  // --- controllo il nastro (linea 1) ---
  int letturaSens = digitalRead(PIN_SENS_NASTRO);
  
  // se vedo che il pezzo è arrivato (da 0 passa a 1)
  if (letturaSens == HIGH && ultimoStatoSensore == LOW) {
     
     // aspetto un attimo per essere sicuro
     if (millis() - ultimoTempoClick[0] > 300) { 
        Serial.println("BTN:1"); // dico al pc che ho fatto un pezzo
        ultimoTempoClick[0] = millis();
     }
  }
  ultimoStatoSensore = letturaSens;

  // --- controllo i pulsanti manuali ---
  for(int i=0; i<NUM_LINEE; i++) {
    int lettura = digitalRead(PIN_BTN[i]);
    
    // se premo il pulsante
    if(lettura == LOW && ultimiStatiBtn[i] == HIGH) {
      if (millis() - ultimoTempoClick[i] > 300) { 
        Serial.print("BTN:");
        Serial.println(i + 1); // lo dico al pc
        ultimoTempoClick[i] = millis();
      }
    }
    ultimiStatiBtn[i] = lettura;
  }

  // --- ascolto il pc per accendere le luci ---
  if(Serial.available() > 0) {
    String comando = Serial.readStringUntil('\n');
    comando.trim();
    
    // se il messaggio è giusto
    if(comando.length() == NUM_LINEE) {
      
      // gestisco linea 1 (speciale con relè)
      if(comando[0] == '1') {
        digitalWrite(PIN_LED[0], HIGH); // accendo luce
        digitalWrite(PIN_RELE, LOW);    // attivo relè (parte nastro)
      } else {
        digitalWrite(PIN_LED[0], LOW);  // spengo luce
        digitalWrite(PIN_RELE, HIGH);   // stacco relè (fermo nastro)
      }

      // gestisco le altre linee (solo luci)
      for(int i=1; i<NUM_LINEE; i++) {
        if(comando[i] == '1') digitalWrite(PIN_LED[i], HIGH);
        else digitalWrite(PIN_LED[i], LOW);
      }
    }
  }
}
