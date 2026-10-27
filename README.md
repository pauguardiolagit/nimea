# Nimea

**Compañía que nos acerca.** Software del robot Nimea, un acompañante para personas mayores que vive en un Reachy Mini y se conecta con la app de la familia.

Nimea conversa por voz, propone juegos para tener la mente despierta, recuerda las pastillas, entrega los audios y retos que manda la familia y graba las respuestas. Al final de cada charla envía a la app un resumen con los siete indicadores de bienestar. Nunca sustituye a la familia: es el punto de encuentro.

## Qué hace la versión 0.1

- Se despierta al oír **"Nimea"** y se vuelve a dormir con la cabeza baja tras un rato de silencio.
- Conversa **voz a voz** con la API Realtime de OpenAI: contesta en menos de un segundo, con una voz natural, en español de España. También puede usar Claude como cerebro (`NIMEA_MOTOR=claude`).
- **Toma la iniciativa**: recuerda las pastillas (con hasta tres intentos), avisa cuando llegan mensajes de la familia y da los buenos días.
- **Mensajes de la familia**: reproduce audios, lee retos y textos, graba la respuesta en voz y se la manda al móvil de quien la envió. También puede mandar un audio nuevo a cualquier familiar.
- **Bienestar**: anota en silencio alegría, mente despierta, movimiento, alimentación, conexión, descanso y rutina, sin encuestas.
- **Cuerpo**: gestos de alegría, asentir, pensar, sorpresa, cariño y baile; sigue la cara de la persona mientras hablan y mueve la cabeza al hablar.
- **Ve** con la cámara solo cuando se le pide ("Nimea, mira esta foto"). La imagen no se guarda ni se envía a la familia.
- **Memoria**: recuerda lo que le contaron otros días y respeta lo que se le pide guardar en privado.
- **Sin conexión no se pierde nada**: todo lo que va a la app pasa por una cola en disco que se vacía al volver la red.

## Probarla sin robot

Para ver cómo conversa y qué enviaría a la app, basta con un ordenador:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
export OPENAI_API_KEY=...
python -m nimea_robot.consola                    # Carmen te llama
python -m nimea_robot.consola --motivo mensajes  # Nimea le cuenta que Lucía le ha escrito
python -m nimea_robot.consola --motivo pastilla
python -m nimea_robot.consola --motivo pauta     # le propone el paseo que pidió la familia
python -m nimea_robot.consola --motor claude     # la misma charla con Claude (ANTHROPIC_API_KEY)
```

Escribes como si fueras Carmen (datos de demostración en `nimea_robot/demo.json`). Es la misma sesión que usa el robot, pero en texto. Al final se muestra el resumen de la sesión tal y como llegaría a la app.

## Instalarla en el Reachy Mini

1. Copia `.env.example` como `.env` y rellena las claves (IA, voz y la URL y el token de la app).
2. Instala con las dependencias del robot:
   ```bash
   pip install -e ".[robot]"
   ```
3. Lánzala:
   - Como app del Reachy Mini: queda registrada con el nombre `nimea` y se arranca desde el panel del robot.
   - A mano: `python -m nimea_robot.main`.

Con el Reachy Mini con cable se ejecuta en el ordenador al que está conectado. En la versión inalámbrica se ejecuta en el propio robot.

Hace falta `ffmpeg` para reproducir los audios de la familia que no sean WAV.

### Voz

- Por defecto, la voz sale directamente del modelo Realtime de OpenAI (voz `marin`, se cambia con `OPENAI_VOZ`). No hay transcripción ni síntesis por medio.
- Las respuestas que la persona graba para la familia se transcriben con OpenAI (`gpt-4o-mini-transcribe`).
- Mientras Nimea habla, el micro no se envía, para que no se oiga a sí misma. Si el micro del robot cancela bien el eco, `NIMEA_INTERRUMPIR=1` permite cortarla al hablar.
- Con `NIMEA_MOTOR=claude`, la voz es aparte: OpenAI, ElevenLabs o Piper en local (`NIMEA_TTS`).

### Palabra de activación

Mientras no tengamos un modelo propio, Nimea detecta su nombre transcribiendo en local (Whisper) las frases cortas que oye. Nada de lo que se dice antes de "Nimea" sale de casa. Para el piloto conviene entrenar un modelo de openWakeWord para "Nimea", con ejemplos negativos como "anímate", y apuntar a él con `NIMEA_MODELO_PALABRA`. Gasta mucha menos CPU.

## La IA

- **Por defecto, OpenAI Realtime** (`gpt-realtime-2.1-mini`, se cambia con `OPENAI_MODELO_REALTIME`): cerebro y voz en una sola conexión, la opción más natural y barata para el día a día. Detección de turno semántica y paciente, porque las personas mayores hacen pausas al hablar.
- **Alternativa, Claude** (`NIMEA_MOTOR=claude`): `claude-opus-5-5` con esfuerzo `low`, respuesta en streaming cortada en frases y respaldo automático ante rechazos (`fallbacks: "default"`).
- Los dos usan las mismas instrucciones (`nimea_robot/prompts.py`) y las mismas herramientas (`nimea_robot/tools.py`).

## Estructura

| Archivo | Qué hace |
|---|---|
| `main.py` | App del Reachy Mini: monta todas las piezas |
| `companion.py` | Bucle principal: reposo, palabra de activación, conversación, iniciativa |
| `realtime.py` | Conversación voz a voz con OpenAI Realtime |
| `brain.py` | Conversación con Claude (alternativa) |
| `prompts.py` | Personalidad e instrucciones de Nimea |
| `tools.py` | Herramientas: mensajes, retos, pastillas, bienestar, gestos, cámara, memoria |
| `agenda.py` | Cuándo despertarse sola: pastillas, mensajes, buenos días, descanso |
| `api.py` | Conexión con la app de la familia y cola sin conexión |
| `audio.py`, `vad.py`, `stt.py`, `tts.py`, `wakeword.py` | Voz: oír, cortar frases, transcribir, hablar y oír su nombre |
| `gestures.py` | Lenguaje corporal |
| `bienestar.py` | Sesión y siete indicadores |
| `consola.py` | Modo texto para probar sin robot |

El contrato con la app está en [docs/api-robot.md](docs/api-robot.md).

## Tests

```bash
pip install -e ".[dev]"
pytest
```

## Privacidad

- No se graba audio ni vídeo de ambiente. Solo se envían a la app las respuestas que la persona graba a propósito, y resúmenes.
- La familia ve resúmenes, temas y una frase destacada, nunca la conversación completa.
- Nimea interpreta el ánimo a partir de lo que se habla, y la app lo indica.
- Nimea no es un dispositivo médico.

## Próximos pasos

- Probarla con la voz y el robot reales y ajustar los tiempos de escucha.
- Entrenar el modelo de la palabra "Nimea".
- Ejercicios guiados de movimiento con la cámara.
- Pantalla con un Android en una peana para las videollamadas.
- Que interrumpa su frase si la persona empieza a hablar.
