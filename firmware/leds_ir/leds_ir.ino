// leds_ir.ino — LEDs IR con brillo PWM independiente para cada LED (ESP32)
//
// REQUISITOS: placa ESP32 con el core "esp32" de Arduino v3.x
//   (usa ledcAttach(pin, freq, res) / ledcWrite(pin, valor) por pin;
//    en el core v2.x esas funciones no existen con esta forma).
//
// Monitor Serie a 115200, con "New Line". Comandos:
//   120        -> todos los LEDs a brillo 120
//   2 80       -> solo el LED 2 a brillo 80
//   0          -> apaga todos (igual que "off")
//   off        -> apaga todos
//   id         -> modo identificación: enciende UN LED a la vez (1, 2, ... NUM_LEDS) cada segundo
//   estado     -> muestra el brillo de cada LED
//
// Seguridad: al arrancar TODOS los pines quedan en LOW antes que cualquier otra cosa,
// y los LEDs inician apagados (brillo 0).

// ---------------------------------------------------------------------------
// CÓMO CAMBIAR LA CANTIDAD DE LEDS O LOS PINES:
//   1) Cambia NUM_LEDS al número de LEDs que tengas.
//   2) Escribe en PINES exactamente NUM_LEDS números de pin GPIO, en orden
//      (el primero es el LED 1, el segundo el LED 2, etc.).
//   Ejemplo con 3 LEDs:  NUM_LEDS = 3;  PINES[NUM_LEDS] = {25, 21, 32};
//   Usa pines que sirvan como salida (evita 34-39, que en el ESP32 solo son entrada).
// ---------------------------------------------------------------------------
const int NUM_LEDS = 5;
const int PINES[NUM_LEDS] = {25, 21, 32, 33, 22};  // LED 1, LED 2, LED 3, LED 4, LED 5

// Frecuencia PWM: 200 kHz. Una frecuencia alta hace que la cámara vea un brillo
// estable (sin parpadeo ni bandas) con cualquier tiempo de exposición, incluso
// exposiciones muy cortas, porque cada foto abarca muchos ciclos del PWM.
// Es válida en el ESP32: 200 kHz * 2^8 (resolución) = 51.2 MHz < 80 MHz (reloj APB).
const int FREQ = 200000;
const int RES  = 8;        // brillo de 0 a 255

int  brillo[NUM_LEDS] = {0};   // todos inician en 0
bool modoId = false;           // true = encendiendo un LED a la vez
int  ledIdActual = -1;

// Escribe en los pines el brillo guardado de cada LED
void aplicarTodos() {
  for (int i = 0; i < NUM_LEDS; i++) {
    ledcWrite(PINES[i], brillo[i]);
  }
}

void mostrarEstado() {
  Serial.print("Brillo -> ");
  for (int i = 0; i < NUM_LEDS; i++) {
    Serial.print("LED");
    Serial.print(i + 1);
    Serial.print(": ");
    Serial.print(brillo[i]);
    Serial.print(i < NUM_LEDS - 1 ? " | " : "\n");
  }
}

void setup() {
  // 1) Fail-safe: todos los pines en LOW antes de nada
  for (int i = 0; i < NUM_LEDS; i++) {
    pinMode(PINES[i], OUTPUT);
    digitalWrite(PINES[i], LOW);
  }

  // 2) Convertir cada pin en salida PWM, arrancando en 0
  for (int i = 0; i < NUM_LEDS; i++) {
    ledcAttach(PINES[i], FREQ, RES);
    ledcWrite(PINES[i], 0);
  }

  Serial.begin(115200);
  Serial.print("Listo. ");
  Serial.print(NUM_LEDS);
  Serial.println(" LEDs. Comandos: 120 | 2 80 | off | id | estado");
  mostrarEstado();
}

void loop() {
  // --- Leer comando ---
  if (Serial.available()) {
    String texto = Serial.readStringUntil('\n');
    texto.trim();
    texto.toLowerCase();

    if (texto.length() > 0) {
      modoId = false;   // cualquier comando detiene el modo identificación

      if (texto == "off") {
        for (int i = 0; i < NUM_LEDS; i++) brillo[i] = 0;
        aplicarTodos();
        mostrarEstado();

      } else if (texto == "estado") {
        mostrarEstado();

      } else if (texto == "id") {
        modoId = true;
        ledIdActual = -1;
        Serial.println("Modo ID: un LED a la vez (usa el brillo guardado; si es 0 usa 60)");

      } else {
        int espacio = texto.indexOf(' ');
        if (espacio < 0) {
          // Un solo número -> todos los LEDs
          int v = texto.toInt();
          if (v >= 0 && v <= 255) {
            for (int i = 0; i < NUM_LEDS; i++) brillo[i] = v;
            aplicarTodos();
            mostrarEstado();
          }
        } else {
          // "n valor" -> solo el LED n
          int n = texto.substring(0, espacio).toInt();
          int v = texto.substring(espacio + 1).toInt();
          if (n >= 1 && n <= NUM_LEDS && v >= 0 && v <= 255) {
            brillo[n - 1] = v;
            aplicarTodos();
            mostrarEstado();
          } else {
            Serial.print("Comando no válido. Ej: 2 80  (LED 1-");
            Serial.print(NUM_LEDS);
            Serial.println(", brillo 0-255)");
          }
        }
      }
    }
  }

  // --- Modo identificación: un LED a la vez, cambia cada segundo ---
  if (modoId) {
    int turno = (millis() / 1000) % NUM_LEDS;
    if (turno != ledIdActual) {
      ledIdActual = turno;
      for (int i = 0; i < NUM_LEDS; i++) {
        int b = (brillo[i] > 0) ? brillo[i] : 60;
        ledcWrite(PINES[i], (i == turno) ? b : 0);
      }
      Serial.print("ID: encendido LED ");
      Serial.println(turno + 1);
    }
  } else if (ledIdActual != -1) {
    // Al salir del modo ID, regresar al brillo guardado
    ledIdActual = -1;
    aplicarTodos();
  }
}
