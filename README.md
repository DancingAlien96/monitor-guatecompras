# Monitor de Concursos Vigentes — Guatecompras

Automatización en **Python** que revisa los concursos **vigentes** publicados en
Guatecompras, los filtra según tus criterios y envía un resumen por **correo
electrónico**. Pensado para correr solo (cron / Programador de tareas).

No usa scraping ni Selenium: consume la **API oficial de datos abiertos OCDS** de
Guatecompras (`https://ocds.guatecompras.gt`, licencia CC BY 4.0), que se actualiza
a diario. Esto lo hace estable y fácil de mantener.

"Vigente" = la licitación está en estado OCDS `active` (etapa de adjudicación/recepción
de ofertas abierta).

---

## 1. Requisitos

- Python 3.8 o superior. Verifica con: `python3 --version`
- Sin librerías externas (usa solo la librería estándar).
- La máquina debe tener salida a internet hacia `ocds.guatecompras.gt`.
- Una cuenta de correo desde la cual enviar (con acceso SMTP).

## 2. Archivos

| Archivo | Para qué |
|---|---|
| `monitor.py` | El programa principal. |
| `config.example.json` | Plantilla de configuración. **Cópiala a `config.json` y edítala.** |
| `state.json` | Se crea solo. Guarda los concursos ya notificados (para no repetir). |
| `test_local.py` | Pruebas de la lógica (no requiere internet). |

## 3. Configuración

Copia la plantilla y edítala:

```bash
cp config.example.json config.json
```

### 3.1 Filtros (`"filtros"`)

Todos los filtros son **opcionales**. Deja una lista vacía `[]` o `null` para no aplicarlo.
Cuando hay varios valores en una lista, basta con que coincida **uno** (OR). Las
comparaciones ignoran mayúsculas y acentos.

| Campo | Qué hace | Ejemplo |
|---|---|---|
| `palabras_clave` | El concurso debe contener al menos una, en título/descripción/entidad/método. | `["equipo medico", "insumos"]` |
| `excluir_palabras` | Descarta concursos que contengan alguna. | `["usado", "arrendamiento"]` |
| `entidades` | Solo de estas entidades compradoras (coincidencia parcial). | `["ministerio de salud"]` |
| `categorias` | Tipo: `goods` (bienes), `works` (obra), `services` (servicios). | `["goods", "works"]` |
| `metodos` | Método de compra (parcial). | `["licitacion", "cotizacion"]` |
| `departamentos` | Mejor esfuerzo por dirección de la entidad. | `["guatemala", "peten"]` |
| `monto_minimo` / `monto_maximo` | Rango del monto del concurso (en quetzales). | `90000` |

> Envíame tus filtros y te dejo el `config.json` ya armado.

### 3.2 Correo (`"correo"`)

```json
"correo": {
  "smtp_host": "smtp.gmail.com",
  "smtp_port": 587,
  "usar_tls": true,
  "usar_ssl": false,
  "remitente": "tucorreo@gmail.com",
  "nombre_remitente": "Monitor Guatecompras",
  "destinatarios": ["cliente@dominio.com"],
  "asunto_prefijo": "[Guatecompras] Concursos vigentes",
  "adjuntar_csv": true
}
```

Presets de SMTP comunes:

| Proveedor | smtp_host | puerto | usar_tls | usar_ssl |
|---|---|---|---|---|
| Gmail / Google Workspace | `smtp.gmail.com` | 587 | true | false |
| Outlook / Microsoft 365 | `smtp.office365.com` | 587 | true | false |
| Otro (SSL directo) | el de tu proveedor | 465 | false | true |

### 3.3 Contraseña del correo (importante, por seguridad)

La contraseña **no** se guarda en `config.json`. Se lee desde `.env` o desde una
variable de entorno del sistema.

Crea el archivo `.env` desde la plantilla:

```bash
cp .env.example .env
```

Y edita su contenido:

```env
GUATECOMPRAS_SMTP_PASSWORD="tu_contrasena_o_app_password"
```

También puedes definirla directamente en el entorno:

```bash
export GUATECOMPRAS_SMTP_PASSWORD="tu_contrasena_o_app_password"
```

- **Gmail / Google Workspace:** no sirve tu contraseña normal. Activa verificación
  en 2 pasos y crea una **"Contraseña de aplicación"** de 16 caracteres; usa esa.
- **Outlook/365:** según la cuenta, también puede requerir contraseña de aplicación.

## 4. Probar antes de enviar

Prueba sin enviar correo (genera `preview.html` y `preview.csv` para revisar):

```bash
python3 monitor.py --dry-run
```

Correr la lógica sin internet (pruebas):

```bash
python3 test_local.py
```

## 5. Ejecutar de verdad

```bash
export GUATECOMPRAS_SMTP_PASSWORD="..."
python3 monitor.py
```

Solo envía correo si hay concursos **nuevos** (no notificados antes). El historial se
guarda en `state.json`. Para forzar el reenvío de todos los que coinciden:
`python3 monitor.py --no-dedupe`.

## 6. Automatizar

### macOS / Linux (cron)

Edita el crontab con `crontab -e` y agrega (ejemplo: todos los días a las 7:00 a.m.):

```cron
0 7 * * * cd /ruta/al/guatecompras_monitor && GUATECOMPRAS_SMTP_PASSWORD="..." /usr/bin/python3 monitor.py >> monitor.log 2>&1
```

Si ya usas `.env`, no necesitas poner la contraseña en el cron. Para correr 3 veces
al día, por ejemplo a las 7:00, 12:00 y 17:00:

```cron
0 7,12,17 * * * cd /ruta/al/guatecompras_monitor && /usr/bin/python3 monitor.py >> monitor.log 2>&1
```

### Windows (Programador de tareas)

1. Crea un archivo `correr.bat`:
   ```bat
   cd C:\ruta\al\guatecompras_monitor
   python monitor.py >> monitor.log 2>&1
   ```
2. Guarda la contraseña en `.env`.
3. Programador de tareas → Crear tarea básica → diaria → Acción: iniciar `correr.bat`.
4. Para 3 veces al día, crea 3 desencadenadores diarios para la misma tarea.

## 6.bis. Producción con Docker (recomendado)

El proyecto incluye un contenedor que corre el monitor **2 veces al día**
(mañana y noche) usando `cron` interno, con la zona horaria de Guatemala.

### Requisitos
- Docker y Docker Compose instalados en el servidor.
- `config.json` y `.env` creados (ver secciones 3.1–3.3).

### Puesta en marcha

```bash
# 1. Configura tus filtros/correo y la contraseña
cp config.example.json config.json   # edítalo
cp .env.example .env                  # pon GUATECOMPRAS_SMTP_PASSWORD

# 2. Construye y arranca en segundo plano
docker compose up -d --build

# 3. Ver los logs en vivo
docker compose logs -f
```

El contenedor queda corriendo (`restart: unless-stopped`) y dispara el monitor
automáticamente a las **07:00** y **19:00** hora de Guatemala.

### Cambiar los horarios

Edita las variables en `docker-compose.yml` (formato cron, hora local según `TZ`):

```yaml
environment:
  TZ: America/Guatemala
  CRON_MORNING: "0 7 * * *"    # 7:00 a.m.
  CRON_NIGHT:   "0 19 * * *"   # 7:00 p.m.
```

Luego aplica los cambios: `docker compose up -d`.

### Probar el contenedor sin esperar al horario

Pon `RUN_ON_START: "true"` en `docker-compose.yml` (o lánzalo así una vez):

```bash
RUN_ON_START=true docker compose up --build
```

Ejecuta una corrida inmediata al arrancar; revísala con `docker compose logs -f`.

### Persistencia

- `state.json` (historial anti-repetición) y `monitor.log` se guardan en el
  volumen `monitor-data`, así que **sobreviven** a reinicios y reconstrucciones.
- `config.json` se monta de solo lectura; cambia el archivo y reinicia el
  contenedor (`docker compose restart`) para aplicar nuevos filtros.

> **Nota:** como la fuente OCDS se actualiza una vez al día y el monitor
> deduplica, la corrida de la noche normalmente **no enviará correo** salvo que
> hayan aparecido concursos nuevos durante el día. Es el comportamiento esperado:
> solo recibes correo cuando hay algo nuevo, revisado dos veces al día.

### En una Raspberry Pi (ideal para este proyecto)

Una Raspberry Pi en tu oficina es la mejor opción: bajo consumo, siempre
encendida e **IP guatemalteca** (la API de Guatecompras solo responde bien a
IPs de Guatemala y bloquea descargas demasiado frecuentes). La imagen es
multi-arquitectura, así que corre en ARM sin cambios.

Requisitos: **Raspberry Pi OS de 64 bits** (recomendado) y Docker.

```bash
# 1. Instalar Docker (una sola vez)
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER      # luego cierra sesión y vuelve a entrar

# 2. Clonar y configurar
git clone https://github.com/DancingAlien96/monitor-guatecompras.git
cd monitor-guatecompras
cp config.example.json config.json   # edita filtros y correos
cp .env.example .env                  # pon GUATECOMPRAS_SMTP_PASSWORD

# 3. Construir y arrancar
docker compose up -d --build

# 4. Que arranque solo cuando se reinicie la Pi
sudo systemctl enable docker         # el contenedor vuelve con Docker (restart: unless-stopped)
```

Ver los logs:

```bash
docker compose logs -f
# o el log persistente de las corridas programadas:
docker compose exec monitor cat /app/data/monitor.log
```

**Memoria (importante en Pi de 1–2 GB):** el script carga el paquete mensual
completo en RAM. Para evitar que la Pi se quede sin memoria, activa swap:

```bash
sudo dphys-swapfile swapoff
sudo sed -i 's/^CONF_SWAPSIZE=.*/CONF_SWAPSIZE=2048/' /etc/dphys-swapfile
sudo dphys-swapfile setup && sudo dphys-swapfile swapon
```

En una Pi 4/5 con 4 GB o más normalmente no hace falta.

## 7. Notas y límites

- **Cobertura OCDS:** incluye licitación, cotización, compra directa y baja cuantía
  con NOG desde 2020. Excluye el módulo NPG y registros previos a 2020.
- **Frecuencia de datos:** la fuente se actualiza diariamente; correr más de una vez
  al día no aporta datos nuevos.
- **`meses_hacia_atras`:** `0` procesa solo el mes en curso (lo normal). Ponlo en `1`
  los primeros días del mes para no perder concursos abiertos a fin del mes anterior.
- **`solo_con_cierre_vigente`:** `true` descarta concursos cuyo estado siga como
  `active` en la API pero cuya fecha de cierre ya pasó.
- **Departamento:** es "mejor esfuerzo" según la dirección registrada de la entidad;
  no todos los registros la traen.
- **Enlace al concurso:** se arma con el NOG hacia la consulta de Guatecompras; si la
  ruta exacta cambiara, el NOG igual te permite ubicarlo en el portal.

## 8. Fuente

Datos abiertos OCDS de Guatecompras — Ministerio de Finanzas Públicas.
API: https://ocds.guatecompras.gt/api-ocds · Licencia CC BY 4.0.
