"""
PJUD Scraper Core — Módulo reutilizable
Importado por la API FastAPI. No tiene main() propio.
"""

import asyncio
import httpx
import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional
from urllib.parse import urlencode

from playwright.async_api import async_playwright, Page


# ─────────────────────────────────────────────────────────────
# Modelos de datos
# ─────────────────────────────────────────────────────────────

@dataclass
class Causa:
    rol: str = ""
    tipo_recurso: str = ""        # columna 2 (antes "corte" — renombrada)
    caratulado: str = ""
    fecha_ingreso: str = ""
    estado_causa: str = ""
    corte: str = ""               # columna 6 real de la tabla

    def to_dict(self) -> dict:
        return asdict(self)


# ─────────────────────────────────────────────────────────────
# Estrategias (patrón Strategy)
# ─────────────────────────────────────────────────────────────

class BusquedaBase(ABC):
    BASE_URL = "https://oficinajudicialvirtual.pjud.cl"

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

    @abstractmethod
    async def llenar_formulario(self, page: Page) -> None: ...

    def url(self) -> str:
        return f"{self.BASE_URL}/{self.endpoint}"


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
            self.captcha_field: captcha_token,
            "action": self.captcha_action,
            "competencia": self.competencia,
            "conCorte": self.corte,
            "conTipoBusApe": self.tipo_busqueda,
            "radio-groupPenal": "1",
            "radio-group": self.radio_group,
            "conRolCausa": self.rol,
            "conEraCausa": self.anio,
            "ruc1": "", "ruc2": "", "rucPen1": "", "rucPen2": "",
            "conCaratulado": self.caratulado,
        }

    async def llenar_formulario(self, page: Page) -> None:
        await page.select_option("#competencia", value=self.competencia)
        await asyncio.sleep(0.5)
        await page.select_option("#conCorte", value=self.corte)
        await asyncio.sleep(0.3)
        await page.select_option("#conTipoBusApe", value=self.tipo_busqueda)
        await page.check("#radioRit")
        await page.fill("#conRolCausa", self.rol)
        await page.fill("#conEraCausa", self.anio)
        if self.caratulado:
            await page.fill("#conCaratulado", self.caratulado)


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
            self.captcha_field: captcha_token,
            "action": self.captcha_action,
            "radio-group": self.radio_group,
            "nomNombre": self.nombre,
            "nomApePaterno": self.ape_paterno,
            "nomApeMaterno": self.ape_materno,
            "nomEra": self.anio,
            "nomNombreJur": self.nombre_jur,
            "nomEraJur": self.anio_jur,
            "nomCompetencia": self.competencia,
        }

    async def llenar_formulario(self, page: Page) -> None:
        await page.click("text=Consulta Unificada")
        await asyncio.sleep(0.6)
        await page.click("text=Búsqueda por Nombre")
        await asyncio.sleep(0.3)
        await page.check("#radioPerNatural")
        await page.fill("#nomNombre", self.nombre)
        await page.fill("#nomApePaterno", self.ape_paterno)
        if self.ape_materno:
            await page.fill("#nomApeMaterno", self.ape_materno)
        if self.anio:
            await page.fill("#nomEra", self.anio)
        await page.select_option("#nomCompetencia", value=self.competencia)
        await asyncio.sleep(0.3)


# ─────────────────────────────────────────────────────────────
# Headers HTTP
# ─────────────────────────────────────────────────────────────

HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "es-CL,es-419;q=0.9,es;q=0.8",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Origin": "https://oficinajudicialvirtual.pjud.cl",
    "Referer": "https://oficinajudicialvirtual.pjud.cl/indexN.php",
    "X-Requested-With": "XMLHttpRequest",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
    ),
    "sec-ch-ua": '"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}


# ─────────────────────────────────────────────────────────────
# Resolver reCAPTCHA (2captcha)
# ─────────────────────────────────────────────────────────────

async def resolver_recaptcha_2captcha(site_key: str, page_url: str) -> str:
    api_key = os.getenv("TWOCAPTCHA_API_KEY")
    if not api_key:
        raise ValueError("Falta TWOCAPTCHA_API_KEY en .env")

    async with httpx.AsyncClient() as client:
        r = await client.post("https://2captcha.com/in.php", data={
            "key": api_key, "method": "userrecaptcha",
            "googlekey": site_key, "pageurl": page_url, "json": 1,
        })
        resp = r.json()
        if resp["status"] != 1:
            raise RuntimeError(f"2captcha submit error: {resp}")
        captcha_id = resp["request"]

        for intento in range(24):
            await asyncio.sleep(5)
            r = await client.get("https://2captcha.com/res.php", params={
                "key": api_key, "action": "get", "id": captcha_id, "json": 1,
            })
            resp = r.json()
            if resp["status"] == 1:
                return resp["request"]
            if resp["request"] != "CAPCHA_NOT_READY":
                raise RuntimeError(f"2captcha error: {resp}")

    raise TimeoutError("reCAPTCHA no resuelto en 2 minutos")


# ─────────────────────────────────────────────────────────────
# Obtener sesión + token via Playwright
# ─────────────────────────────────────────────────────────────

async def obtener_sesion_y_token(
    busqueda: BusquedaBase,
    usar_2captcha: bool = False,
) -> tuple[dict, str]:
    cookies_result = {}
    captcha_token = {"value": ""}

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=usar_2captcha,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        context = await browser.new_context(
            user_agent=HEADERS["User-Agent"],
            viewport={"width": 1280, "height": 800},
            locale="es-CL",
        )
        page = await context.new_page()
        await page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        await page.goto(
            "https://oficinajudicialvirtual.pjud.cl/home/index.php",
            wait_until="domcontentloaded", timeout=60000,
        )

        # Cerrar modal si aparece
        for sel in [".modal .close", ".modal-footer button", "[data-dismiss='modal']", ".btn-close"]:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=2000):
                    await btn.click()
                    await asyncio.sleep(0.5)
                    break
            except Exception:
                pass

        await page.goto(
            "https://oficinajudicialvirtual.pjud.cl/indexN.php",
            wait_until="domcontentloaded", timeout=60000,
        )

        # Esperar que la página cargue completamente — en headless tarda más
        # Intentar con múltiples selectores conocidos del formulario
        loaded = False
        for selector in ["select", "#nomNombre", "#conRolCausa", "form", ".nav-tabs"]:
            try:
                await page.wait_for_selector(selector, timeout=10000)
                loaded = True
                break
            except Exception:
                pass

        if not loaded:
            import asyncio as _asyncio
            await _asyncio.sleep(5)

        # Log URL — si no es indexN.php el sitio bloqueó o redirigió
        cur_url = page.url
        print(f"  URL actual tras carga: {cur_url}")
        if "indexN.php" not in cur_url and "index" not in cur_url:
            raise RuntimeError(f"El sitio redirigió inesperadamente a: {cur_url}")

        await busqueda.llenar_formulario(page)

        if usar_2captcha:
            site_key = await page.get_attribute(".g-recaptcha", "data-sitekey")
            token = await resolver_recaptcha_2captcha(site_key, "https://oficinajudicialvirtual.pjud.cl/indexN.php")
            await page.evaluate(f'document.getElementById("{busqueda.captcha_field}").value = "{token}"')
            captcha_token["value"] = token
        else:
            # Modo interactivo: esperar token externo inyectado vía endpoint /captcha-token
            # La API llama a este método con usar_2captcha=True siempre
            # Este branch solo se usa en modo CLI
            raise RuntimeError("Modo manual no disponible en contexto API. Usar 2captcha.")

        all_cookies = await context.cookies()
        cookies_result = {c["name"]: c["value"] for c in all_cookies}
        await browser.close()

    return cookies_result, captcha_token["value"]


# ─────────────────────────────────────────────────────────────
# Ejecutar consulta y parsear
# ─────────────────────────────────────────────────────────────

async def ejecutar_consulta(
    busqueda: BusquedaBase,
    cookies: dict,
    captcha_token: str,
) -> list[Causa]:
    payload = busqueda.payload(captcha_token)

    async with httpx.AsyncClient(verify=False, timeout=30) as client:
        r = await client.post(
            busqueda.url(),
            headers=HEADERS,
            cookies=cookies,
            content=urlencode(payload),
        )
        r.raise_for_status()

    return _parsear_respuesta(r.text)


def _parsear_respuesta(html: str) -> list[Causa]:
    # Intentar JSON
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

    # HTML con tabla — columnas reales: [lupa] | Rol | Tipo Recurso | Caratulado | Fecha Ingreso | Estado Causa | Corte
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    causas = []
    tabla = soup.find("table")
    if not tabla:
        return []

    for fila in tabla.find_all("tr")[1:]:
        celdas = fila.find_all("td")
        n = len(celdas)
        if n < 2:
            continue
        # col 0 = ícono lupa (sin texto), col 1..6 = datos
        offset = 1 if (n >= 7 and not celdas[0].get_text(strip=True)) else 0
        if n - offset >= 6:
            causas.append(Causa(
                rol=celdas[offset + 0].get_text(strip=True),
                tipo_recurso=celdas[offset + 1].get_text(strip=True),
                caratulado=celdas[offset + 2].get_text(strip=True),
                fecha_ingreso=celdas[offset + 3].get_text(strip=True),
                estado_causa=celdas[offset + 4].get_text(strip=True),
                corte=celdas[offset + 5].get_text(strip=True),
            ))
    return causas


# ─────────────────────────────────────────────────────────────
# Función principal (usada por la API)
# ─────────────────────────────────────────────────────────────

async def consultar(busqueda: BusquedaBase, usar_2captcha: bool = True) -> list[Causa]:
    cookies, token = await obtener_sesion_y_token(busqueda, usar_2captcha)
    if not token:
        raise RuntimeError("No se obtuvo token de captcha")
    return await ejecutar_consulta(busqueda, cookies, token)