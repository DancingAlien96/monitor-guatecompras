#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Monitor de Concursos Vigentes - Guatecompras (datos abiertos OCDS)
==================================================================

Descarga el paquete de datos OCDS del mes (o meses) desde la API oficial de
Guatecompras, filtra las licitaciones/concursos en estado VIGENTE (tender.status
== "active") segun los filtros configurados, evita repetir los ya notificados y
envia un resumen por correo electronico.

NO usa scraping ni Selenium: consume la API oficial de datos abiertos
(https://ocds.guatecompras.gt/api-ocds), licencia CC BY 4.0.

Uso:
    python monitor.py                 # corre normal: filtra, deduplica y envia correo
    python monitor.py --dry-run       # NO envia correo, imprime y guarda un .html de muestra
    python monitor.py --no-dedupe     # ignora el historial (envia todos los vigentes que matcheen)
    python monitor.py --config otra_config.json

Credenciales SMTP:
    La contrasena del correo NO se guarda en el archivo de config. Se lee de la
    variable de entorno  GUATECOMPRAS_SMTP_PASSWORD.

Autor: generado para Piums.
"""

import argparse
import csv
import datetime as dt
import gzip
import io
import json
import os
import re
import smtplib
import sys
import time
import unicodedata
import zipfile
from email.message import EmailMessage
from email.utils import formataddr
from urllib.error import HTTPError, URLError
from urllib.request import urlopen, Request

API_FILES = "https://ocds.guatecompras.gt/files"
# Pagina de busqueda por NOG en Guatecompras (para enlazar cada concurso)
NOG_SEARCH_URL = "https://www.guatecompras.gt/concursos/consultaConcurso.aspx?nog={nog}"

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG = os.path.join(HERE, "config.json")
DEFAULT_STATE = os.path.join(HERE, "state.json")
DEFAULT_ENV = os.path.join(HERE, ".env")
USER_AGENT = "GuatecomprasMonitor/1.0 (+contacto)"


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #
def log(msg):
    print(f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def carga_env(path=DEFAULT_ENV):
    """Carga variables KEY=VALUE desde .env sin depender de paquetes externos."""
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def normaliza(texto):
    """Minusculas y sin acentos, para comparar de forma robusta."""
    if texto is None:
        return ""
    texto = str(texto)
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return texto.lower().strip()


def contiene_termino(texto_norm, termino_norm):
    """Coincidencia por LIMITE DE PALABRA sobre texto ya normalizado.
    Asi 'agua' coincide con la palabra 'agua' pero no con 'managua' ni 'paraguas';
    las frases ('bomba de agua') tambien funcionan."""
    if not termino_norm:
        return False
    patron = r"\b" + re.escape(termino_norm) + r"\b"
    return re.search(patron, texto_norm) is not None


# Codigos HTTP que suelen ser temporales (rate-limit / Cloudflare / caida momentanea).
# Ante estos se reintenta; ante otros (p.ej. 404) se falla de inmediato.
HTTP_REINTENTABLES = (403, 408, 429, 500, 502, 503, 504)


def http_get(url, timeout=120, reintentos=3, espera_base=60):
    """Descarga con reintentos y backoff exponencial ante bloqueos transitorios.

    La API OCDS de Guatecompras esta detras de Cloudflare y puede devolver 403/429
    temporalmente cuando hay demasiadas peticiones seguidas. En vez de perder la
    corrida, se espera y se reintenta (60s, 120s, 240s por defecto). Si el bloqueo
    persiste, la siguiente corrida programada lo recupera (el historial evita
    duplicados, asi que no se pierde ningun concurso).
    """
    req = Request(url, headers={"User-Agent": USER_AGENT})
    ultimo_error = None
    for intento in range(1, reintentos + 2):  # 1 intento inicial + N reintentos
        try:
            with urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except HTTPError as e:
            ultimo_error = e
            if e.code not in HTTP_REINTENTABLES:
                raise  # error definitivo: no tiene sentido reintentar
        except URLError as e:
            ultimo_error = e  # error de red/timeout: reintentable
        if intento <= reintentos:
            espera = espera_base * (2 ** (intento - 1))
            log(f"  Descarga fallo ({ultimo_error}). Reintento {intento}/{reintentos} en {espera}s...")
            time.sleep(espera)
    raise ultimo_error  # se agotaron los reintentos


# --------------------------------------------------------------------------- #
# Descarga y parseo del paquete OCDS
# --------------------------------------------------------------------------- #
def listar_meses_disponibles():
    """Devuelve la lista de meses publicados (mas reciente primero)."""
    data = json.loads(http_get(API_FILES, timeout=60).decode("utf-8"))
    return data.get("result", [])


def descomprimir_a_json(raw_bytes):
    """El endpoint json/{anio}/{mes} entrega un ZIP (o gzip) con un JSON dentro.
    Esta funcion devuelve el dict del paquete OCDS sin importar el envoltorio."""
    # 1) Intentar ZIP
    try:
        with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
            nombre = next((n for n in zf.namelist() if n.lower().endswith(".json")),
                          zf.namelist()[0])
            with zf.open(nombre) as fh:
                return json.loads(fh.read().decode("utf-8"))
    except zipfile.BadZipFile:
        pass
    # 2) Intentar GZIP
    try:
        return json.loads(gzip.decompress(raw_bytes).decode("utf-8"))
    except (OSError, EOFError):
        pass
    # 3) JSON plano
    return json.loads(raw_bytes.decode("utf-8"))


def iter_compiled_releases(paquete):
    """Itera los 'compiledRelease' de un record package OCDS.
    Tolera tambien release packages por si la API cambia."""
    if "records" in paquete:
        for rec in paquete.get("records", []):
            cr = rec.get("compiledRelease")
            if cr:
                yield cr
            else:
                # algunos records traen releases embebidas
                for rel in rec.get("releases", []):
                    if isinstance(rel, dict) and "tender" in rel:
                        yield rel
    elif "releases" in paquete:
        for rel in paquete.get("releases", []):
            yield rel


# --------------------------------------------------------------------------- #
# Extraccion de campos de un concurso
# --------------------------------------------------------------------------- #
def nombre_comprador(cr):
    buyer = cr.get("buyer") or {}
    if buyer.get("name"):
        return buyer["name"]
    bid = buyer.get("id")
    for parte in cr.get("parties", []) or []:
        roles = [normaliza(r) for r in (parte.get("roles") or [])]
        if (bid and parte.get("id") == bid) or "buyer" in roles:
            return parte.get("name", "")
    return ""


def region_concurso(cr):
    """Departamento/region: mejor esfuerzo a partir de direcciones de las partes."""
    candidatos = []
    for parte in cr.get("parties", []) or []:
        addr = parte.get("address") or {}
        for k in ("region", "locality", "streetAddress"):
            if addr.get(k):
                candidatos.append(addr[k])
    return " ".join(candidatos)


def extrae_concurso(cr):
    tender = cr.get("tender") or {}
    ocid = cr.get("ocid", "") or ""
    nog = ocid.split("-")[-1] if ocid else (tender.get("id") or "")
    value = tender.get("value") or {}
    periodo = tender.get("tenderPeriod") or {}
    docs = tender.get("documents") or []
    doc_url = ""
    for d in docs:
        if d.get("url"):
            doc_url = d["url"]
            break
    return {
        "ocid": ocid,
        "nog": nog,
        "titulo": tender.get("title") or "",
        "descripcion": tender.get("description") or "",
        "estado": tender.get("status") or "",
        "comprador": nombre_comprador(cr),
        "categoria": tender.get("mainProcurementCategory") or "",
        "metodo": tender.get("procurementMethodDetails") or tender.get("procurementMethod") or "",
        "monto": value.get("amount"),
        "moneda": value.get("currency") or "GTQ",
        "fecha_inicio": periodo.get("startDate") or "",
        "fecha_cierre": periodo.get("endDate") or "",
        "region": region_concurso(cr),
        "url_concurso": NOG_SEARCH_URL.format(nog=nog) if nog else "",
        "url_documento": doc_url,
        "fecha_publicacion": tender.get("datePublished") or cr.get("date") or "",
    }


# --------------------------------------------------------------------------- #
# Filtros
# --------------------------------------------------------------------------- #
def pasa_filtros(c, f):
    # Solo vigentes (active). Se controla aparte para poder loguear.
    texto_busqueda = normaliza(" ".join([
        c["titulo"], c["descripcion"], c["comprador"], c["metodo"]
    ]))

    palabras = [normaliza(p) for p in f.get("palabras_clave", []) if p.strip()]
    if palabras and not any(contiene_termino(texto_busqueda, p) for p in palabras):
        return False

    excluir = [normaliza(p) for p in f.get("excluir_palabras", []) if p.strip()]
    if excluir and any(contiene_termino(texto_busqueda, p) for p in excluir):
        return False

    entidades = [normaliza(e) for e in f.get("entidades", []) if e.strip()]
    if entidades and not any(e in normaliza(c["comprador"]) for e in entidades):
        return False

    categorias = [normaliza(x) for x in f.get("categorias", []) if x.strip()]
    if categorias and normaliza(c["categoria"]) not in categorias:
        return False

    metodos = [normaliza(m) for m in f.get("metodos", []) if m.strip()]
    if metodos and not any(m in normaliza(c["metodo"]) for m in metodos):
        return False

    deptos = [normaliza(d) for d in f.get("departamentos", []) if d.strip()]
    if deptos and not any(d in normaliza(c["region"]) for d in deptos):
        return False

    monto = c["monto"]
    mmin = f.get("monto_minimo")
    mmax = f.get("monto_maximo")
    if mmin is not None and (monto is None or monto < mmin):
        return False
    if mmax is not None and (monto is None or monto > mmax):
        return False

    return True


def cierre_vigente(c, hoy=None):
    """True si no tiene fecha de cierre o si el cierre es hoy/futuro."""
    hoy = hoy or dt.date.today().isoformat()
    fecha_cierre = c.get("fecha_cierre") or ""
    return not fecha_cierre or fecha_cierre[:10] >= hoy


# --------------------------------------------------------------------------- #
# Estado (deduplicacion)
# --------------------------------------------------------------------------- #
def carga_estado(path):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return set(json.load(fh).get("ocids_notificados", []))
        except Exception:
            return set()
    return set()


def guarda_estado(path, ocids):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"actualizado": dt.datetime.now().isoformat(),
                   "ocids_notificados": sorted(ocids)}, fh, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------- #
# Render del correo
# --------------------------------------------------------------------------- #
def fmt_monto(c):
    if c["monto"] is None:
        return "-"
    try:
        return f"{c['moneda']} {c['monto']:,.2f}"
    except Exception:
        return f"{c['moneda']} {c['monto']}"


def fmt_fecha(s):
    if not s:
        return "-"
    return str(s)[:10]


def mejor_fecha(c):
    """Devuelve (etiqueta, fecha_str) con la fecha más relevante disponible."""
    if c.get("fecha_cierre"):
        return "Cierre", fmt_fecha(c["fecha_cierre"])
    if c.get("fecha_inicio"):
        return "Inicio", fmt_fecha(c["fecha_inicio"])
    if c.get("fecha_publicacion"):
        return "Publicación", fmt_fecha(c["fecha_publicacion"])
    return "", "-"


def render_html(concursos, contexto):
    filas = []
    for c in concursos:
        enlace = c["url_concurso"] or c["url_documento"] or "#"
        filas.append(f"""
        <tr>
          <td style="padding:8px;border-bottom:1px solid #eee;vertical-align:top;">
            <a href="{enlace}" style="color:#1a5276;font-weight:bold;text-decoration:none;">{c['titulo'] or '(sin titulo)'}</a><br>
            <span style="color:#666;font-size:12px;">NOG {c['nog']} &middot; {c['metodo']}</span>
          </td>
          <td style="padding:8px;border-bottom:1px solid #eee;vertical-align:top;font-size:13px;">{c['comprador']}</td>
          <td style="padding:8px;border-bottom:1px solid #eee;vertical-align:top;font-size:13px;white-space:nowrap;">{fmt_monto(c)}</td>
          <td style="padding:8px;border-bottom:1px solid #eee;vertical-align:top;font-size:13px;white-space:nowrap;">{fmt_fecha(c['fecha_inicio'])}</td>
          <td style="padding:8px;border-bottom:1px solid #eee;vertical-align:top;font-size:13px;white-space:nowrap;">{fmt_fecha(c['fecha_cierre'])}</td>
        </tr>""")
    tabla = "".join(filas)
    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8"></head>
<body style="font-family:Arial,Helvetica,sans-serif;color:#222;margin:0;padding:0;background:#f4f6f8;">
  <div style="max-width:760px;margin:0 auto;padding:24px;">
    <h2 style="color:#1a5276;margin:0 0 4px;">Concursos vigentes - Guatecompras</h2>
    <p style="color:#555;margin:0 0 16px;font-size:13px;">
      {contexto['fecha']} &middot; {len(concursos)} concurso(s) nuevo(s) que coinciden con tus filtros.
    </p>
    <table style="width:100%;border-collapse:collapse;background:#fff;border:1px solid #e3e7eb;">
      <thead>
        <tr style="background:#1a5276;color:#fff;text-align:left;">
          <th style="padding:8px;font-size:13px;">Concurso</th>
          <th style="padding:8px;font-size:13px;">Entidad</th>
          <th style="padding:8px;font-size:13px;">Monto</th>
          <th style="padding:8px;font-size:13px;">Inicio</th>
          <th style="padding:8px;font-size:13px;">Cierre</th>
        </tr>
      </thead>
      <tbody>{tabla}</tbody>
    </table>
    <p style="color:#999;font-size:11px;margin-top:16px;">
      Fuente: datos abiertos OCDS de Guatecompras (CC BY 4.0). Estado "vigente" = tender.status "active".
      Generado automaticamente por el monitor de concursos.
    </p>
  </div>
</body></html>"""


def render_csv(concursos):
    buf = io.StringIO()
    campos = ["nog", "titulo", "comprador", "categoria", "metodo", "monto", "moneda",
              "fecha_inicio", "fecha_cierre", "estado", "region", "url_concurso", "ocid"]
    w = csv.DictWriter(buf, fieldnames=campos, extrasaction="ignore")
    w.writeheader()
    for c in concursos:
        w.writerow(c)
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# Envio de correo
# --------------------------------------------------------------------------- #
def _construir_mensaje(cfg_correo, destinatario, html, csv_text, n):
    msg = EmailMessage()
    msg["Subject"] = f"Guatecompras: {n} concurso(s) vigente(s) - {dt.date.today():%d/%m/%Y}"
    msg["From"] = formataddr((cfg_correo.get("nombre_remitente", "Monitor Guatecompras"),
                              cfg_correo["remitente"]))
    msg["To"] = destinatario
    msg["Reply-To"] = cfg_correo["remitente"]
    msg.set_content(
        f"Se encontraron {n} concurso(s) vigente(s) en Guatecompras que coinciden con tus filtros.\n\n"
        "Este mensaje contiene una tabla HTML. Si no puedes verla, revisa el archivo CSV adjunto.\n\n"
        f"Fecha: {dt.date.today():%d/%m/%Y}\n"
        "Fuente: datos abiertos OCDS de Guatecompras (CC BY 4.0)."
    )
    msg.add_alternative(html, subtype="html")
    if csv_text and cfg_correo.get("adjuntar_csv", True):
        msg.add_attachment(csv_text.encode("utf-8"), maintype="text", subtype="csv",
                           filename=f"concursos_vigentes_{dt.date.today():%Y%m%d}.csv")
    return msg


def envia_correo(cfg_correo, html, csv_text, n):
    password = os.environ.get("GUATECOMPRAS_SMTP_PASSWORD")
    if not password:
        raise RuntimeError(
            "Falta la variable de entorno GUATECOMPRAS_SMTP_PASSWORD con la contrasena SMTP.")

    host = cfg_correo.get("smtp_host", "smtp.gmail.com")
    port = int(cfg_correo.get("smtp_port", 587))

    if cfg_correo.get("usar_ssl"):
        conn = smtplib.SMTP_SSL(host, port, timeout=60)
    else:
        conn = smtplib.SMTP(host, port, timeout=60)
        conn.ehlo()
        if cfg_correo.get("usar_tls", True):
            conn.starttls()
            conn.ehlo()

    with conn:
        conn.login(cfg_correo["remitente"], password)
        for destinatario in cfg_correo["destinatarios"]:
            msg = _construir_mensaje(cfg_correo, destinatario, html, csv_text, n)
            conn.send_message(msg)


# --------------------------------------------------------------------------- #
# Principal
# --------------------------------------------------------------------------- #
def meses_objetivo(disponibles, hacia_atras):
    """Devuelve los meses a procesar: el mas reciente y N anteriores."""
    return disponibles[: max(1, hacia_atras + 1)]


def run(args):
    with open(args.config, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    filtros = cfg.get("filtros", {})
    opciones = cfg.get("opciones", {})
    correo = cfg.get("correo", {})

    log("Consultando meses disponibles en la API...")
    disponibles = listar_meses_disponibles()
    if not disponibles:
        log("La API no devolvio meses. Abortando.")
        return 1
    objetivo = meses_objetivo(disponibles, int(opciones.get("meses_hacia_atras", 0)))
    log(f"Procesando: {', '.join(m['id'] for m in objetivo)}")

    todos = []
    for m in objetivo:
        url = m["files"]["json"]
        log(f"Descargando {m['id']} -> {url}")
        raw = http_get(url, timeout=240)
        paquete = descomprimir_a_json(raw)
        n_total = n_vig = 0
        for cr in iter_compiled_releases(paquete):
            n_total += 1
            c = extrae_concurso(cr)
            if normaliza(c["estado"]) != "active":
                continue
            n_vig += 1
            if pasa_filtros(c, filtros):
                todos.append(c)
        log(f"  {m['id']}: {n_total} procesos, {n_vig} vigentes, {len(todos)} coinciden (acumulado)")

    # Quitar duplicados por ocid dentro de esta corrida
    unicos = {}
    for c in todos:
        unicos[c["ocid"] or c["nog"]] = c
    coinciden = list(unicos.values())

    # Mantener solo concursos realmente vigentes por fecha de cierre.
    if opciones.get("solo_con_cierre_vigente", True):
        hoy = dt.date.today().isoformat()
        antes = len(coinciden)
        coinciden = [c for c in coinciden if cierre_vigente(c, hoy)]
        log(f"Filtro 'solo_con_cierre_vigente': {antes} -> {len(coinciden)} concursos")

    # Deduplicacion contra el historial
    usar_dedupe = opciones.get("solo_nuevos", True) and not args.no_dedupe
    ya_vistos = carga_estado(args.state) if usar_dedupe else set()
    nuevos = [c for c in coinciden if (c["ocid"] or c["nog"]) not in ya_vistos]

    # Filtrar solo los que aún no han iniciado (o no tienen fecha de inicio)
    if opciones.get("solo_proximos_a_iniciar", False):
        hoy = dt.date.today().isoformat()
        antes = len(nuevos)
        nuevos = [c for c in nuevos if not c["fecha_inicio"] or c["fecha_inicio"][:10] >= hoy]
        log(f"Filtro 'solo_proximos_a_iniciar': {antes} -> {len(nuevos)} concursos")

    # Orden: por fecha de inicio ascendente (los que inician antes primero)
    nuevos.sort(key=lambda c: (c["fecha_inicio"] or "9999"))

    log(f"Coinciden con filtros: {len(coinciden)} | Nuevos (no notificados): {len(nuevos)}")

    if not nuevos:
        log("No hay concursos nuevos. No se envia correo.")
        return 0

    html = render_html(nuevos, {"fecha": f"{dt.date.today():%d/%m/%Y}"})
    csv_text = render_csv(nuevos)

    if args.dry_run:
        out_html = os.path.join(HERE, "preview.html")
        out_csv = os.path.join(HERE, "preview.csv")
        with open(out_html, "w", encoding="utf-8") as fh:
            fh.write(html)
        with open(out_csv, "w", encoding="utf-8") as fh:
            fh.write(csv_text)
        log(f"[DRY-RUN] No se envio correo. Vista previa: {out_html} y {out_csv}")
    else:
        log(f"Enviando correo a: {', '.join(correo.get('destinatarios', []))}")
        envia_correo(correo, html, csv_text, len(nuevos))
        log("Correo enviado.")

    # Actualizar historial (incluso en dry-run NO, para poder repetir pruebas)
    if usar_dedupe and not args.dry_run:
        ya_vistos.update((c["ocid"] or c["nog"]) for c in nuevos)
        guarda_estado(args.state, ya_vistos)
        log(f"Historial actualizado ({len(ya_vistos)} ocids).")

    return 0


def main():
    carga_env()
    p = argparse.ArgumentParser(description="Monitor de concursos vigentes de Guatecompras (OCDS).")
    p.add_argument("--config", default=DEFAULT_CONFIG, help="Ruta al archivo de configuracion JSON.")
    p.add_argument("--state", default=DEFAULT_STATE, help="Ruta al archivo de historial (dedupe).")
    p.add_argument("--dry-run", action="store_true", help="No envia correo; genera vista previa.")
    p.add_argument("--no-dedupe", action="store_true", help="Ignora el historial de notificados.")
    args = p.parse_args()
    try:
        sys.exit(run(args))
    except Exception as e:
        log(f"ERROR: {e}")
        sys.exit(2)


if __name__ == "__main__":
    main()
