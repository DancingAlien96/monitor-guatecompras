#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prueba local de la logica (sin red): parseo OCDS, filtros, dedupe y render."""
import io
import json
import zipfile
import gzip
import monitor as M

# --- Paquete OCDS sintetico que imita la estructura real de Guatecompras --- #
PAQUETE = {
    "uri": "https://ocds.guatecompras.gt/...",
    "version": "1.1",
    "records": [
        {  # vigente + coincide (equipo medico)
            "ocid": "ocds-xqjsxa-12345678",
            "compiledRelease": {
                "ocid": "ocds-xqjsxa-12345678",
                "date": "2026-06-10T09:00:00-06:00",
                "tender": {
                    "id": "12345678",
                    "title": "Adquisicion de EQUIPO MEDICO para hospital regional",
                    "description": "Compra de monitores y camillas",
                    "status": "active",
                    "mainProcurementCategory": "goods",
                    "procurementMethodDetails": "Licitacion publica",
                    "value": {"amount": 1500000.0, "currency": "GTQ"},
                    "tenderPeriod": {"startDate": "2026-06-10", "endDate": "2026-06-30"},
                    "datePublished": "2026-06-10",
                    "documents": [{"url": "https://www.guatecompras.gt/doc/abc.pdf"}],
                },
                "buyer": {"id": "MSPAS", "name": "Ministerio de Salud Publica"},
                "parties": [
                    {"id": "MSPAS", "name": "Ministerio de Salud Publica",
                     "roles": ["buyer"], "address": {"region": "Guatemala"}}
                ],
            },
        },
        {  # vigente pero NO coincide (no keyword) -> debe filtrarse
            "ocid": "ocds-xqjsxa-22222222",
            "compiledRelease": {
                "ocid": "ocds-xqjsxa-22222222",
                "tender": {
                    "id": "22222222",
                    "title": "Servicio de jardineria municipal",
                    "status": "active",
                    "mainProcurementCategory": "services",
                    "procurementMethodDetails": "Cotizacion",
                    "value": {"amount": 50000.0, "currency": "GTQ"},
                    "tenderPeriod": {"endDate": "2026-06-20"},
                },
                "buyer": {"name": "Municipalidad de Xela"},
                "parties": [{"name": "Municipalidad de Xela", "roles": ["buyer"],
                             "address": {"region": "Quetzaltenango"}}],
            },
        },
        {  # coincide keyword pero NO vigente (complete) -> debe filtrarse
            "ocid": "ocds-xqjsxa-33333333",
            "compiledRelease": {
                "ocid": "ocds-xqjsxa-33333333",
                "tender": {
                    "id": "33333333",
                    "title": "Construccion de carretera (adjudicado)",
                    "status": "complete",
                    "mainProcurementCategory": "works",
                    "procurementMethodDetails": "Licitacion publica",
                    "value": {"amount": 9000000.0, "currency": "GTQ"},
                    "tenderPeriod": {"endDate": "2026-05-01"},
                },
                "buyer": {"name": "CIV"},
            },
        },
        {  # vigente + coincide (construccion) -> incluir
            "ocid": "ocds-xqjsxa-44444444",
            "compiledRelease": {
                "ocid": "ocds-xqjsxa-44444444",
                "tender": {
                    "id": "44444444",
                    "title": "CONSTRUCCION de escuela primaria",
                    "status": "active",
                    "mainProcurementCategory": "works",
                    "procurementMethodDetails": "Licitacion publica",
                    "value": {"amount": 2500000.0, "currency": "GTQ"},
                    "tenderPeriod": {"startDate": "2026-06-01", "endDate": "2026-06-25"},
                },
                "buyer": {"name": "Ministerio de Educacion"},
                "parties": [{"name": "Ministerio de Educacion", "roles": ["buyer"],
                             "address": {"region": "Peten"}}],
            },
        },
        {  # active pero cierre vencido -> no debe pasar cierre_vigente
            "ocid": "ocds-xqjsxa-55555555",
            "compiledRelease": {
                "ocid": "ocds-xqjsxa-55555555",
                "tender": {
                    "id": "55555555",
                    "title": "CONSTRUCCION de pozo mecanico",
                    "status": "active",
                    "mainProcurementCategory": "works",
                    "procurementMethodDetails": "Cotizacion",
                    "value": {"amount": 300000.0, "currency": "GTQ"},
                    "tenderPeriod": {"startDate": "2026-05-01", "endDate": "2026-05-15"},
                },
                "buyer": {"name": "Municipalidad"},
            },
        },
    ],
}

FILTROS = {
    "palabras_clave": ["equipo medico", "construccion"],
    "excluir_palabras": [],
    "entidades": [],
    "categorias": [],
    "metodos": [],
    "departamentos": [],
    "monto_minimo": None,
    "monto_maximo": None,
}


def test_descompresion():
    raw = json.dumps(PAQUETE).encode("utf-8")
    # zip
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("2026-6.json", raw)
    assert M.descomprimir_a_json(buf.getvalue())["records"]
    # gzip
    assert M.descomprimir_a_json(gzip.compress(raw))["records"]
    # plano
    assert M.descomprimir_a_json(raw)["records"]
    print("OK  descompresion: zip / gzip / plano")


def test_filtros_y_estado():
    coinciden = []
    vigentes = 0
    for cr in M.iter_compiled_releases(PAQUETE):
        c = M.extrae_concurso(cr)
        if M.normaliza(c["estado"]) != "active":
            continue
        vigentes += 1
        if M.pasa_filtros(c, FILTROS):
            coinciden.append(c)
    nogs = sorted(c["nog"] for c in coinciden)
    print(f"OK  vigentes={vigentes} (esperado 4)  coinciden={nogs} (esperado 12345678,44444444,55555555)")
    assert vigentes == 4, vigentes
    assert nogs == ["12345678", "44444444", "55555555"], nogs

    con_cierre_vigente = [c["nog"] for c in coinciden if M.cierre_vigente(c, "2026-06-16")]
    assert con_cierre_vigente == ["12345678", "44444444"], con_cierre_vigente
    print("OK  cierre_vigente excluye active con fecha de cierre vencida")

    # exclusion
    f2 = dict(FILTROS, excluir_palabras=["escuela"])
    c44 = next(M.extrae_concurso(cr) for cr in M.iter_compiled_releases(PAQUETE)
               if M.extrae_concurso(cr)["nog"] == "44444444")
    assert not M.pasa_filtros(c44, f2)
    print("OK  excluir_palabras filtra el de 'escuela'")

    # monto
    f3 = dict(FILTROS, monto_minimo=2000000)
    sel = [M.extrae_concurso(cr)["nog"] for cr in M.iter_compiled_releases(PAQUETE)
           if M.normaliza(M.extrae_concurso(cr)["estado"]) == "active"
           and M.pasa_filtros(M.extrae_concurso(cr), f3)]
    assert sel == ["44444444"], sel
    print("OK  monto_minimo=2,000,000 deja solo 44444444")

    # departamento
    f4 = dict(FILTROS, departamentos=["peten"])
    sel = [M.extrae_concurso(cr)["nog"] for cr in M.iter_compiled_releases(PAQUETE)
           if M.normaliza(M.extrae_concurso(cr)["estado"]) == "active"
           and M.pasa_filtros(M.extrae_concurso(cr), f4)]
    assert sel == ["44444444"], sel
    print("OK  departamento 'Peten' deja solo 44444444")


def test_render():
    coinciden = [M.extrae_concurso(cr) for cr in M.iter_compiled_releases(PAQUETE)
                 if M.normaliza(M.extrae_concurso(cr)["estado"]) == "active"
                 and M.pasa_filtros(M.extrae_concurso(cr), FILTROS)]
    html = M.render_html(coinciden, {"fecha": "15/06/2026"})
    csv_text = M.render_csv(coinciden)
    assert "EQUIPO MEDICO" in html and "12345678" in html
    assert "GTQ 1,500,000.00" in html
    assert "nog,titulo" in csv_text
    with open("preview.html", "w", encoding="utf-8") as fh:
        fh.write(html)
    with open("preview.csv", "w", encoding="utf-8") as fh:
        fh.write(csv_text)
    print("OK  render html/csv (preview.html, preview.csv escritos)")


if __name__ == "__main__":
    test_descompresion()
    test_filtros_y_estado()
    test_render()
    print("\nTODAS LAS PRUEBAS PASARON")
