# API entre el robot y la app

El robot habla con el backend de la app de la familia (Base44). Este contrato coincide con el prompt v2 de la app.

Todas las llamadas llevan la cabecera `Authorization: Bearer <token del dispositivo>` y van en JSON. `NIMEA_API_URL` es la URL base, sin barra final.

## GET /robot/contexto

Lo que el robot necesita saber. Se descarga al arrancar, cada 10 minutos y antes de cada conversación por iniciativa propia. Si falla, el robot usa la última copia guardada.

```json
{
  "persona": {"id": "", "nombre": "", "apodo": "", "fecha_nacimiento": "", "ciudad": "",
              "aficiones": [], "temas_favoritos": [], "temas_evitar": [], "notas": "",
              "horario": {"levantarse": "08:30", "comidas": ["14:00", "21:00"], "siesta": "16:00", "dormir": "23:00"}},
  "familiares": [{"id": "", "nombre": "", "parentesco": "", "alias_voz": []}],
  "recuerdos": [{"id": "", "titulo": "", "descripcion": "", "tipo": "", "fecha": ""}],
  "medicacion": [{"id": "", "nombre": "", "dosis": "", "horas": ["09:00"], "dias": [], "instrucciones": ""}],
  "mensajes_pendientes": [{"id": "", "autor_id": "", "autor_nombre": "", "tipo": "audio|reto|texto",
                           "texto": "", "audio_url": "", "fecha": ""}],
  "visitas": [{"familiar_nombre": "", "fecha": "", "tipo": "", "mensaje": ""}],
  "ajustes": {"volumen": 0.9, "horario_descanso": "22:30-08:30"}
}
```

`dias` usa 0 para lunes y 6 para domingo; vacío significa todos los días. Opcional en `persona`: `trato` ("tú" o "usted").

## Envíos del robot

Todos pasan por una cola en disco: si no hay red, se guardan y se envían en orden con el siguiente latido. Un error 4xx se descarta y queda en el registro; un 5xx o un fallo de red se reintenta.

| Ruta | Cuerpo |
|---|---|
| `POST /robot/sesion` | `inicio`, `fin`, `minutos`, `retos` [`{tipo, enunciado, resultado}`], `temas`, `personas_mencionadas`, `frase_destacada`, `resumen`, `bienestar` [`{dimension, valor 1-5, nota}`] |
| `POST /robot/toma` | `medicacion_id`, `hora_prevista`, `estado` (confirmada, no_confirmada, pospuesta), `hora_confirmacion` |
| `POST /robot/mensaje` | `responde_a` (id o null), `para_familiar_id` (o null), `transcripcion`, `audio_wav_base64`, `fecha` |
| `POST /robot/mensaje/{id}/entregado` | `estado` (entregado, escuchado) |
| `POST /robot/aviso` | `tipo`, `texto`, `nivel` (informativo, importante), `fecha` |
| `POST /robot/estado` | latido cada 5 minutos: `estado`, `conexion`, `version`, `pendientes` |

Dimensiones de bienestar: `alegria`, `mente`, `movimiento`, `alimentacion`, `conexion`, `descanso`, `rutina`.

Tipos de reto: `memoria`, `lenguaje`, `calculo`, `orientacion`, `refranes`, `adivinanzas`. Resultados: `acertado`, `con_ayuda`, `no_acertado`.
