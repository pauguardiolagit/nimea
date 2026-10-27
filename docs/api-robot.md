# API entre el robot y la app

El robot habla con el backend de la app de la familia (Base44). Este contrato coincide con el prompt v2 de la app.

Cada ruta es una función de Base44 y se llama con `POST <NIMEA_API_URL>/<función>`, con cuerpo JSON y la cabecera `X-Nimea-Token: <token del dispositivo>` (empieza por `nim_`). No se usa `Authorization`, que Base44 reserva para la sesión de un usuario.

`NIMEA_API_URL` es la base de las funciones en el subdominio de la app, sin barra final: `https://nimea.base44.app/functions`. Desde `app.base44.com` Base44 devuelve 403.

| Ruta del contrato | Función de Base44 |
|---|---|
| `/robot/contexto` | `robotContexto` |
| `/robot/sesion` | `robotSesion` |
| `/robot/toma` | `robotToma` |
| `/robot/mensaje` | `robotMensaje` |
| `/robot/mensaje/{id}/entregado` | `robotEntregado`, con el `id` dentro del cuerpo |
| `/robot/aviso` | `robotAviso` |
| `/robot/estado` | `robotEstado` |

La traducción está en `nimea_robot/api.py`. En la cola sin conexión se guardan las rutas del contrato, así que cambiar de backend no rompe lo pendiente.

## /robot/contexto

Lo que el robot necesita saber. Se descarga al arrancar, cada 10 minutos y antes de cada conversación por iniciativa propia. Si falla, el robot usa la última copia guardada.

```json
{
  "persona": {"id": "", "nombre": "", "apodo": "", "fecha_nacimiento": "", "ciudad": "",
              "aficiones": [], "temas_favoritos": [], "temas_evitar": [], "notas": "",
              "horario": {"levantarse": "08:30", "comidas": ["14:00", "21:00"], "siesta": "16:00", "dormir": "23:00"}},
  "familiares": [{"id": "", "nombre": "", "parentesco": "", "alias_voz": [], "telefono": ""}],
  "recuerdos": [{"id": "", "titulo": "", "descripcion": "", "tipo": "", "fecha": ""}],
  "medicacion": [{"id": "", "nombre": "", "dosis": "", "horas": ["09:00"], "dias": [], "instrucciones": ""}],
  "mensajes_pendientes": [{"id": "", "autor_id": "", "autor_nombre": "", "tipo": "audio|reto|texto",
                           "texto": "", "audio_url": "", "fecha": ""}],
  "visitas": [{"familiar_nombre": "", "fecha": "", "tipo": "", "mensaje": ""}],
  "pautas": [{"id": "", "tipo": "ejercicio|rutina|comida|cita|indicacion", "titulo": "", "detalle": "",
              "horas": ["18:00"], "dias": [], "fecha": ""}],
  "ajustes": {"volumen": 0.9, "horario_descanso": "22:30-08:30"}
}
```

`dias` usa "lun", "mar", "mie", "jue", "vie", "sab", "dom" (el robot también acepta 0 a 6, con 0 = lunes); vacío significa todos los días. `telefono` es el número de WhatsApp del familiar, para que en el futuro Nimea pueda llamarle desde el Android de la peana. `pautas` son ejercicios, rutinas, comidas y citas que la familia le dicta a la Nimea de la app: el robot las propone a su hora (una vez, en los 30 minutos siguientes) y, si llevan `fecha`, solo ese día. `mensajes_pendientes` puede venir vacío: el contacto con la familia va por WhatsApp. Opcional en `persona`: `trato` ("tú" o "usted").

## Envíos del robot

Todos pasan por una cola en disco: si no hay red, se guardan y se envían en orden con el siguiente latido. Un error 4xx se descarta y queda en el registro; un 5xx o un fallo de red se reintenta.

| Ruta | Cuerpo |
|---|---|
| `POST /robot/sesion` | `inicio`, `fin`, `minutos`, `retos` [`{tipo, enunciado, resultado}`], `temas`, `personas_mencionadas`, `frase_destacada`, `resumen`, `bienestar` [`{dimension, valor 1-5, nota}`] |
| `POST /robot/toma` | `medicacion_id`, `hora_prevista`, `estado` (confirmada, no_confirmada, pospuesta), `hora_confirmacion` |
| `POST /robot/mensaje` | `responde_a` (id o null), `para_familiar_id` (o null), `transcripcion`, `audio_wav_base64`, `fecha` |
| `POST /robot/mensaje/{id}/entregado` | `id`, `estado` (entregado, escuchado) |
| `POST /robot/aviso` | `tipo` (peticion, pastilla_no_confirmada, animo_bajo, sin_actividad), `texto`, `nivel` (informativo, importante), `fecha` |
| `POST /robot/estado` | latido cada 5 minutos: `estado`, `conexion`, `version`, `pendientes` |

Dimensiones de bienestar: `alegria`, `mente`, `movimiento`, `alimentacion`, `conexion`, `descanso`, `rutina`.

Tipos de reto: `memoria`, `lenguaje`, `calculo`, `orientacion`, `refranes`, `adivinanzas`. Resultados: `acertado`, `con_ayuda`, `no_acertado`.
