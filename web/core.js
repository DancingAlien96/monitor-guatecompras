// Logica compartida entre la pagina (index.html) y el service worker (sw.js).
// Requiere que 'fflate' este cargado antes (vendor/fflate.js).

// ----------------- Filtros (mismos que tu monitor) -----------------
var FILTROS = {
  palabras_clave: ["Purificador","Sistema de purificación","Ósmosis inversa","Planta de tratamiento","Sistema de filtración","Filtro","Filtros de sedimentos","Filtro de sedimentos","Carbón activado","Lámpara UV","Ultravioleta","Potabilización","Tratamiento de agua","Equipo de purificación","Desinfección de agua","Sistema hidráulico","Ablandador de agua","Suavizador de agua","Dosificador de cloro","Clorador","Equipo de osmosis","Membranas","Agua","Bomba de agua","Bomba centrífuga","Bomba sumergible","Bomba tipo bala","Bomba vertical","Bomba horizontal","Equipo hidroneumático","Tanque hidroneumático","Presurizador","Sistema de bombeo","Electrobomba","Variador de frecuencia","Tablero eléctrico","Equipo de presión","Motor eléctrico","Sistema contra incendio","Presostato","Sistema de recirculación","Pozo mecánico","Bombeo solar","Bomba solar","Bomba para piscina","Filtro para piscina","Calentador de piscina","Bomba de calor","Climatizador de piscina","Equipo para piscina","Jacuzzi","Sistema de filtración para piscina","Cuarto de máquinas","Tratamiento de piscina","Clorinador","Panel de control piscina","Químicos para piscina","Cloro para piscina","Hipoclorito","Pastillas de cloro","Cloro granulado","Tricloro","Diclor","Alguicida","Clarificador","Floculante","Incrementador de pH","Reductor de pH","Soda ash","Neutralizador de cloro","Estabilizador de cloro","Abrillantador de agua","Consumibles para purificadora","Cartuchos filtrantes","Filtro PP","Filtro plisado","Filtro de carbón activado","Carbón block","Carbón granular","Membrana de ósmosis inversa","Membrana RO","Membranas Vontron","Membrana 4040","Membrana 8040","Housing para membrana","Sulfato de aluminio","Productos químicos para tratamiento de agua recreativa","Porta filtro","Porta cartucho","Balastro UV","Manga de cuarzo","Resina catiónica","Sal para suavizador","Arena sílica","Zeolita","Multimedia filtrante","Medios filtrantes","Repuestos para purificadora","Repuestos de ósmosis inversa","Filtros para agua potable","Cartucho Big Blue","Prefiltro","Postfiltro","Kit de filtros","Medidor TDS","Medidor de pH","Bombas dosificadoras","Antiincrustante para membranas","Químico CIP","Limpiador de membranas","Sanitizante para sistemas de agua"],
  excluir_palabras: [], entidades: [], categorias: [],
  metodos: ["compra directa", "direct"], departamentos: [],
  monto_minimo: null, monto_maximo: null,
};
var SOLO_CIERRE_VIGENTE = true;
var API_FILES = "https://ocds.guatecompras.gt/files";
var NOG_URL = "https://www.guatecompras.gt/concursos/consultaConcurso.aspx?nog=";

// ----------------- Filtrado (puerto de monitor.py) -----------------
function normaliza(t) {
  if (t === null || t === undefined) return "";
  return String(t).normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();
}
function escaparRegex(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }
function contieneTermino(texto, term) {
  if (!term) return false;
  return new RegExp("\\b" + escaparRegex(term) + "\\b").test(texto);
}
function pasaFiltros(c, f) {
  var t = normaliza([c.titulo, c.descripcion, c.comprador, c.metodo].join(" "));
  var pal = (f.palabras_clave || []).map(normaliza).filter(Boolean);
  if (pal.length && !pal.some(function (p) { return contieneTermino(t, p); })) return false;
  var exc = (f.excluir_palabras || []).map(normaliza).filter(Boolean);
  if (exc.length && exc.some(function (p) { return contieneTermino(t, p); })) return false;
  var ent = (f.entidades || []).map(normaliza).filter(Boolean);
  if (ent.length && !ent.some(function (e) { return normaliza(c.comprador).includes(e); })) return false;
  var cat = (f.categorias || []).map(normaliza).filter(Boolean);
  if (cat.length && !cat.includes(normaliza(c.categoria))) return false;
  var met = (f.metodos || []).map(normaliza).filter(Boolean);
  if (met.length && !met.some(function (m) { return normaliza(c.metodo).includes(m); })) return false;
  var dep = (f.departamentos || []).map(normaliza).filter(Boolean);
  if (dep.length && !dep.some(function (d) { return normaliza(c.region).includes(d); })) return false;
  var m = c.monto;
  if (f.monto_minimo != null && (m == null || m < f.monto_minimo)) return false;
  if (f.monto_maximo != null && (m == null || m > f.monto_maximo)) return false;
  return true;
}
function cierreVigente(c, hoy) {
  var fc = c.fecha_cierre || "";
  return !fc || fc.slice(0, 10) >= hoy;
}

// ----------------- OCDS: extraccion -----------------
function nombreComprador(cr) {
  var b = cr.buyer || {};
  if (b.name) return b.name;
  for (var i = 0; i < (cr.parties || []).length; i++) {
    var p = cr.parties[i];
    var roles = (p.roles || []).map(function (r) { return String(r).toLowerCase(); });
    if ((b.id && p.id === b.id) || roles.indexOf("buyer") >= 0) return p.name || "";
  }
  return "";
}
function regionConcurso(cr) {
  var out = [];
  (cr.parties || []).forEach(function (p) {
    var a = p.address || {};
    ["region", "locality", "streetAddress"].forEach(function (k) { if (a[k]) out.push(a[k]); });
  });
  return out.join(" ");
}
function extrae(cr) {
  var t = cr.tender || {}, ocid = cr.ocid || "";
  var nog = ocid ? ocid.split("-").pop() : (t.id || "");
  var v = t.value || {}, per = t.tenderPeriod || {};
  return {
    ocid: ocid, nog: nog, titulo: t.title || "", descripcion: t.description || "",
    estado: t.status || "", comprador: nombreComprador(cr),
    categoria: t.mainProcurementCategory || "",
    metodo: t.procurementMethodDetails || t.procurementMethod || "",
    monto: v.amount != null ? v.amount : null, moneda: v.currency || "GTQ",
    fecha_inicio: per.startDate || "", fecha_cierre: per.endDate || "",
    region: regionConcurso(cr), url: nog ? NOG_URL + nog : "",
  };
}
function* iter(pkg) {
  if (pkg.records) for (var i = 0; i < pkg.records.length; i++) {
    var r = pkg.records[i];
    if (r.compiledRelease) yield r.compiledRelease;
    else for (var j = 0; j < (r.releases || []).length; j++)
      if (r.releases[j] && r.releases[j].tender) yield r.releases[j];
  } else if (pkg.releases) for (var k = 0; k < pkg.releases.length; k++) yield pkg.releases[k];
}
function descomprimir(bytes) {
  try {
    var files = fflate.unzipSync(bytes);
    var nombres = Object.keys(files);
    var n = nombres.find(function (x) { return x.toLowerCase().endsWith(".json"); }) || nombres[0];
    return JSON.parse(fflate.strFromU8(files[n]));
  } catch (e) {}
  try { return JSON.parse(fflate.strFromU8(fflate.gunzipSync(bytes))); } catch (e) {}
  return JSON.parse(fflate.strFromU8(bytes));
}

// ----------------- Flujo principal -----------------
async function obtenerConcursos() {
  var fr = await fetch(API_FILES);
  if (!fr.ok) throw new Error("HTTP " + fr.status + " al listar meses");
  var meses = (await fr.json()).result || [];
  if (!meses.length) throw new Error("La API no devolvio meses");
  var pr = await fetch(meses[0].files.json);
  if (!pr.ok) throw new Error("HTTP " + pr.status + " al descargar paquete");
  var buf = new Uint8Array(await pr.arrayBuffer());
  var pkg = descomprimir(buf);
  var hoy = new Date().toISOString().slice(0, 10);
  var map = new Map();
  for (var cr of iter(pkg)) {
    var c = extrae(cr);
    if (normaliza(c.estado) !== "active") continue;
    if (!pasaFiltros(c, FILTROS)) continue;
    map.set(c.ocid || c.nog, c);
  }
  var lista = Array.from(map.values());
  if (SOLO_CIERRE_VIGENTE) lista = lista.filter(function (c) { return cierreVigente(c, hoy); });
  lista.sort(function (a, b) { return (a.fecha_inicio || "9999").localeCompare(b.fecha_inicio || "9999"); });
  return lista;
}

// ----------------- Historial "ya visto" (IndexedDB, compartido pagina/SW) -----------------
function _idb() {
  return new Promise(function (res, rej) {
    var r = indexedDB.open("gc", 1);
    r.onupgradeneeded = function () { r.result.createObjectStore("kv"); };
    r.onsuccess = function () { res(r.result); };
    r.onerror = function () { rej(r.error); };
  });
}
async function _idbGet(k) {
  var db = await _idb();
  return new Promise(function (res, rej) {
    var t = db.transaction("kv").objectStore("kv").get(k);
    t.onsuccess = function () { res(t.result); };
    t.onerror = function () { rej(t.error); };
  });
}
async function _idbSet(k, v) {
  var db = await _idb();
  return new Promise(function (res, rej) {
    var tx = db.transaction("kv", "readwrite");
    tx.objectStore("kv").put(v, k);
    tx.oncomplete = function () { res(); };
    tx.onerror = function () { rej(tx.error); };
  });
}
async function leerVistos() { return new Set((await _idbGet("vistos")) || []); }
async function marcarVistos(ocids) {
  var s = await leerVistos();
  ocids.forEach(function (o) { s.add(o); });
  await _idbSet("vistos", Array.from(s));
}
