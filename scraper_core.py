"""
PJUD Scraper Core
=================
Usa curl_cffi para impersonar Chrome y bypassear el WAF F5.
Sin Playwright — todo via HTTP directo.

Flujo:
  1. curl_cffi GET indexN.php → cookies de sesión válidas
  2. curl_cffi GET google recaptcha anchor → anchor token
  3. curl_cffi POST google recaptcha reload → token v3 final
  4. curl_cffi POST endpoint PJUD → resultados
"""

import json
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from urllib.parse import urlencode

from curl_cffi.requests import AsyncSession
from dotenv import load_dotenv

load_dotenv()

RECAPTCHA_SITE_KEY = "6LelLWkUAAAAANPDMkBxllo_QJe5RQVpg6V2pIDt"
RECAPTCHA_CO       = "aHR0cHM6Ly9vZmljaW5hanVkaWNpYWx2aXJ0dWFsLnBqdWQuY2w6NDQz"
RECAPTCHA_V        = "ne1iDVwClkE7nKD3uA9Vqsvl"
BASE_URL           = "https://oficinajudicialvirtual.pjud.cl"


# ─────────────────────────────────────────────────────────────
# Modelos
# ─────────────────────────────────────────────────────────────

@dataclass
class Causa:
    rol: str = ""
    tipo_recurso: str = ""
    caratulado: str = ""
    fecha_ingreso: str = ""
    estado_causa: str = ""
    corte: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ─────────────────────────────────────────────────────────────
# Estrategias
# ─────────────────────────────────────────────────────────────

class BusquedaBase(ABC):
    @property
    @abstractmethod
    def endpoint(self) -> str: ...

    @property
    @abstractmethod
    def captcha_field(self) -> str: ...

    @property
    @abstractmethod
    def captcha_action(self) -> str: ...

    @abstractmethod
    def payload(self, captcha_token: str) -> dict: ...

    def url(self) -> str:
        return f"{BASE_URL}/{self.endpoint}"


@dataclass
class BusquedaRit(BusquedaBase):
    rol: str
    anio: str
    competencia: str = "2"
    corte: str = "0"
    tipo_busqueda: str = "1"
    radio_group: str = "1"
    caratulado: str = ""

    endpoint       = "ADIR_871/apelaciones/consultaRitApelaciones.php"
    captcha_field  = "g-recaptcha-response-rit"
    captcha_action = "validate_captcha_rit"

    def payload(self, captcha_token: str) -> dict:
        return {
            self.captcha_field:  captcha_token,
            "action":            self.captcha_action,
            "competencia":       self.competencia,
            "conCorte":          self.corte,
            "conTipoBusApe":     self.tipo_busqueda,
            "radio-groupPenal":  "1",
            "radio-group":       self.radio_group,
            "conRolCausa":       self.rol,
            "conEraCausa":       self.anio,
            "ruc1": "", "ruc2": "", "rucPen1": "", "rucPen2": "",
            "conCaratulado":     self.caratulado,
        }


@dataclass
class BusquedaNombre(BusquedaBase):
    nombre: str
    ape_paterno: str
    ape_materno: str = ""
    anio: str = ""
    competencia: str = "1"
    nombre_jur: str = ""
    anio_jur: str = ""
    radio_group: str = "N"

    endpoint       = "ADIR_871/suprema/consultaNombreSuprema.php"
    captcha_field  = "g-recaptcha-response-nombre"
    captcha_action = "validate_captcha_nombre"

    def payload(self, captcha_token: str) -> dict:
        return {
            self.captcha_field:  captcha_token,
            "action":            self.captcha_action,
            "radio-group":       self.radio_group,
            "nomNombre":         self.nombre,
            "nomApePaterno":     self.ape_paterno,
            "nomApeMaterno":     self.ape_materno,
            "nomEra":            self.anio,
            "nomNombreJur":      self.nombre_jur,
            "nomEraJur":         self.anio_jur,
            "nomCompetencia":    self.competencia,
        }


# ─────────────────────────────────────────────────────────────
# Paso 1: obtener cookies de sesión
# ─────────────────────────────────────────────────────────────

async def obtener_cookies() -> dict:
    """Navega a indexN.php impersonando Chrome para obtener cookies válidas."""
    async with AsyncSession(impersonate="chrome120", verify=False) as s:
        r = await s.get(
            f"{BASE_URL}/indexN.php",
            headers={"Accept-Language": "es-CL,es;q=0.9"},
        )

    if "Request Rejected" in r.text:
        raise RuntimeError("WAF bloqueó la navegación inicial con curl_cffi")

    cookies = {k: v for k, v in r.cookies.items()}
    print(f"  Cookies obtenidas: {list(cookies.keys())}")
    return cookies


# ─────────────────────────────────────────────────────────────
# Paso 2: obtener token reCAPTCHA v3
# ─────────────────────────────────────────────────────────────

async def obtener_token_v3(action: str, cookies: dict) -> str:
    """
    Obtiene token reCAPTCHA v3 directamente desde la API de Google.
    No requiere browser — solo el site_key y el action.
    """
    async with AsyncSession(impersonate="chrome120", verify=False) as s:

        # Paso A: anchor — obtiene el token inicial
        r_anchor = await s.get(
            "https://www.google.com/recaptcha/api2/anchor",
            params={
                "ar": "1",
                "k":  RECAPTCHA_SITE_KEY,
                "co": RECAPTCHA_CO,
                "hl": "es",
                "v":  RECAPTCHA_V,
                "size": "invisible",
                "cb": "nega3fn9bcxh",
            },
        )
        match = re.search(r'"recaptcha-token" value="([^"]+)"', r_anchor.text)
        if not match:
            raise RuntimeError(
                f"No se encontró recaptcha-token. "
                f"Respuesta anchor: {r_anchor.text[:300]}"
            )
        anchor_token = match.group(1)

        # Paso B: reload — canjea anchor token por token v3 final
        r_reload = await s.post(
            "https://www.google.com/recaptcha/api2/reload",
            params={"k": RECAPTCHA_SITE_KEY},
            data={
                "v":      RECAPTCHA_V,
                "reason": "q",
                "c":      anchor_token,
                "k":      RECAPTCHA_SITE_KEY,
                "co":     RECAPTCHA_CO,
                "hl":     "es",
                "size":   "invisible",
                "action": action,
            },
        )
        match2 = re.search(r'"rresp","([^"]+)"', r_reload.text)
        if not match2:
            raise RuntimeError(
                f"No se pudo obtener token v3 de Google. "
                f"Respuesta reload: {r_reload.text[:300]}"
            )

    token = match2.group(1)
    print(f"  ✓ Token reCAPTCHA v3 ({len(token)} chars)")
    return token


# ─────────────────────────────────────────────────────────────
# Paso 3: POST al endpoint PJUD
# ─────────────────────────────────────────────────────────────

async def ejecutar_consulta(
    busqueda: BusquedaBase,
    cookies: dict,
    token: str,
) -> list[Causa]:
    payload = busqueda.payload(token)

    async with AsyncSession(impersonate="chrome120", verify=False) as s:
        r = await s.post(
            busqueda.url(),
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Origin":       BASE_URL,
                "Referer":      f"{BASE_URL}/indexN.php",
                "X-Requested-With": "XMLHttpRequest",
            },
            cookies=cookies,
            data=urlencode(payload),
        )
        r.raise_for_status()

    debug_file = f"respuesta_{busqueda.__class__.__name__.lower()}.html"
    with open(debug_file, "w", encoding="utf-8") as f:
        f.write(r.text)
    print(f"  Respuesta guardada en {debug_file}")

    return _parsear_respuesta(r.text)


def _parsear_respuesta(html: str) -> list[Causa]:
    # Intentar JSON primero
    try:
        data = json.loads(html)
        items = data if isinstance(data, list) else data.get("causas", [])
        return [Causa(
            rol=str(item.get("ROL", item.get("rol", ""))),
            tipo_recurso=str(item.get("TIPO_RECURSO", item.get("tipoRecurso", ""))),
            caratulado=str(item.get("CARATULADO", item.get("caratulado", ""))),
            fecha_ingreso=str(item.get("FECHA_INGRESO", item.get("fechaIngreso", ""))),
            estado_causa=str(item.get("ESTADO", item.get("estadoCausa", ""))),
            corte=str(item.get("CORTE", item.get("corte", ""))),
        ) for item in items]
    except (json.JSONDecodeError, TypeError):
        pass

    # El servidor devuelve filas <tr> sueltas sin <table> envolvente
    # Envolver en tabla para que BeautifulSoup pueda parsear correctamente
    from bs4 import BeautifulSoup

    # Intentar con tabla envolvente primero
    wrapped = f"<table>{html}</table>"
    soup = BeautifulSoup(wrapped, "lxml")
    filas = soup.find_all("tr")

    # Si no encontró filas, buscar directamente en el HTML original
    if not filas:
        soup = BeautifulSoup(html, "lxml")
        filas = soup.find_all("tr")

    causas = []
    for fila in filas:
        celdas = fila.find_all("td")
        n = len(celdas)
        if n < 2:
            continue

        # Ignorar filas de paginación (tienen colspan)
        if celdas[0].get("colspan"):
            continue

        # col 0 = ícono lupa (contiene <a> o <i>, sin texto) → offset 1
        primer_texto = celdas[0].get_text(strip=True)
        offset = 1 if (not primer_texto or len(primer_texto) < 3) else 0

        if n - offset >= 6:
            causas.append(Causa(
                rol=celdas[offset + 0].get_text(strip=True),
                tipo_recurso=celdas[offset + 1].get_text(strip=True),
                caratulado=celdas[offset + 2].get_text(strip=True),
                fecha_ingreso=celdas[offset + 3].get_text(strip=True),
                estado_causa=celdas[offset + 4].get_text(strip=True),
                corte=celdas[offset + 5].get_text(strip=True),
            ))
    print(f"  Parser: {len(filas)} filas encontradas → {len(causas)} causas")
    return causas


# ─────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────

async def consultar(
    busqueda: BusquedaBase,
    usar_2captcha: bool = True,
) -> list[Causa]:
    print(f"\n=== {busqueda.__class__.__name__} ===")
    cookies = await obtener_cookies()
    token   = await obtener_token_v3(busqueda.captcha_action, cookies)
    causas  = await ejecutar_consulta(busqueda, cookies, token)
    print(f"  ✓ {len(causas)} causa(s)")
    return causas