"""
PJUD Scraper Core — Módulo reutilizable
Importado por la API FastAPI. No tiene main() propio.

Flujo:
  1. home/index.php  → cerrar modal via JS (Bootstrap aria-hidden)
  2. indexN.php      → formulario de causas
  3. llenar campos   → IDs confirmados del DOM
  4. 2captcha        → resolver reCAPTCHA automáticamente
  5. httpx POST      → endpoint XHR con cookies de sesión
"""

import asyncio
import httpx
import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from typing import Optional
from urllib.parse import urlencode

from playwright.async_api import async_playwright, Page


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


# ── Búsqueda por RIT ─────────────────────────────────────────

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

    async def llenar_formulario(self, page: Page) -> None:
        # Tab RIT ya está activo por defecto
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
        print(f"  Formulario RIT llenado: rol={self.rol}, año={self.anio}")


# ── Búsqueda por Nombre ───────────────────────────────────────

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

    async def llenar_formulario(self, page: Page) -> None:
        # Clic en tab "Búsqueda por Nombre" — está en indexN.php
        await page.click("text=Búsqueda por Nombre")
        await asyncio.sleep(0.5)
        await page.check("#radioPerNatural")
        await page.fill("#nomNombre", self.nombre)
        await page.fill("#nomApePaterno", self.ape_paterno)
        if self.ape_materno:
            await page.fill("#nomApeMaterno", self.ape_materno)
        if self.anio:
            await page.fill("#nomEra", self.anio)
        await page.select_option("#nomCompetencia", value=self.competencia)
        await asyncio.sleep(0.3)
        print(f"  Formulario Nombre llenado: {self.nombre} {self.ape_paterno}")


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
# Resolver reCAPTCHA via 2captcha
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
        print(f"  reCAPTCHA enviado a 2captcha (id: {captcha_id})...")

        for intento in range(24):
            await asyncio.sleep(5)
            r = await client.get("https://2captcha.com/res.php", params={
                "key": api_key, "action": "get", "id": captcha_id, "json": 1,
            })
            resp = r.json()
            if resp["status"] == 1:
                print(f"  ✓ reCAPTCHA resuelto en {(intento+1)*5}s")
                return resp["request"]
            if resp["request"] != "CAPCHA_NOT_READY":
                raise RuntimeError(f"2captcha error: {resp}")

    raise TimeoutError("reCAPTCHA no resuelto en 2 minutos")


# ─────────────────────────────────────────────────────────────
# Navegación y obtención de sesión
# ─────────────────────────────────────────────────────────────

async def _cerrar_modal(page: Page) -> None:
    """
    Cierra el modal de aviso PJUD via JavaScript.
    Bootstrap marca el modal con aria-hidden=true → Playwright no lo ve como visible.
    La solución es ejecutar el clic directamente en el DOM.
    """
    try:
        # Esperar que el modal tenga display:block (animación Bootstrap)
        await page.wait_for_function(
            """() => {
                const m = document.querySelector('.modal');
                return m && window.getComputedStyle(m).display !== 'none';
            }""",
            timeout=8000,
        )
        # Cerrar via JS — bypasea aria-hidden
        await page.evaluate("""
            () => {
                const btn = document.querySelector(
                    '.modal .btn[data-dismiss="modal"], .modal button[data-dismiss="modal"]'
                );
                if (btn) btn.click();
                // Fallback: forzar cierre visual
                const modal = document.querySelector('.modal');
                if (modal) {
                    modal.style.display = 'none';
                    modal.classList.remove('show');
                    document.body.classList.remove('modal-open');
                    const backdrop = document.querySelector('.modal-backdrop');
                    if (backdrop) backdrop.remove();
                }
            }
        """)
        print("  Modal cerrado via JS")
        await asyncio.sleep(0.3)
    except Exception:
        print("  Modal no detectado, continuando...")


async def obtener_sesion_y_token(
    busqueda: BusquedaBase,
    usar_2captcha: bool = True,
) -> tuple[dict, str]:
    cookies_result = {}
    captcha_token = {"value": ""}

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=usar_2captcha,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-gpu",                  # necesario en Windows headless
                "--disable-dev-shm-usage",
            ],
        )
        context = await browser.new_context(
            user_agent=HEADERS["User-Agent"],
            viewport={"width": 1280, "height": 800},
            locale="es-CL",
        )
        page = await context.new_page()
        page.set_default_timeout(90000)
        page.set_default_navigation_timeout(90000)

        await page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        # ── Paso 1: home (modal de aviso) ──────────────────────
        print("  [1/4] Navegando al home...")
        await page.goto(
            "https://oficinajudicialvirtual.pjud.cl/home/index.php",
            wait_until="domcontentloaded",
            timeout=90000,
        )
        await _cerrar_modal(page)
        await page.locator(".landing").click()


        # ── Paso 2: formulario de causas ────────────────────────
        print("  [2/4] Navegando al formulario...")
        print(f"  URL activa: {page.url}")

        await page.goto(
            "https://oficinajudicialvirtual.pjud.cl/indexN.php",
            wait_until="domcontentloaded",
            timeout=90000,
        )

        # Esperar que el formulario esté listo
        loaded = False
        for selector in ["select", "#nomNombre", "#conRolCausa", ".nav-tabs"]:
            try:
                await page.wait_for_selector(selector, timeout=10000)
                loaded = True
                break
            except Exception:
                pass
        if not loaded:
            await asyncio.sleep(5)


        # ── Paso 3: llenar formulario ───────────────────────────
        print("  [3/4] Llenando formulario...")
        print(f"  URL activa: {page.url}")
        await busqueda.llenar_formulario(page)

        # ── Paso 4: resolver reCAPTCHA ──────────────────────────
        print("  [4/4] Resolviendo reCAPTCHA...")
        if usar_2captcha:
            site_key = await page.get_attribute(".g-recaptcha", "data-sitekey")
            token = await resolver_recaptcha_2captcha(
                site_key=site_key,
                page_url="https://oficinajudicialvirtual.pjud.cl/indexN.php",
            )
            await page.evaluate(
                f'document.getElementById("{busqueda.captcha_field}").value = "{token}"'
            )
            captcha_token["value"] = token
        else:
            # Modo manual CLI
            print("  ⚠ Resuelve el reCAPTCHA en el browser y presiona ENTER...")
            await asyncio.get_event_loop().run_in_executor(None, input)
            captcha_token["value"] = await page.evaluate(
                f'document.getElementById("{busqueda.captcha_field}")?.value || ""'
            )
            if not captcha_token["value"]:
                captcha_token["value"] = await page.evaluate("""
                    () => {
                        const fields = document.querySelectorAll('textarea[id*="recaptcha"]');
                        for (const f of fields) { if (f.value) return f.value; }
                        return "";
                    }
                """)

        all_cookies = await context.cookies()
        cookies_result = {c["name"]: c["value"] for c in all_cookies}
        await browser.close()

    return cookies_result, captcha_token["value"]


# ─────────────────────────────────────────────────────────────
# Ejecutar consulta con httpx
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

    # Guardar respuesta raw para debug
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

    # HTML con tabla
    # Columnas reales: [lupa] | Rol | Tipo Recurso | Caratulado | Fecha Ingreso | Estado Causa | Corte
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    causas = []
    tabla = soup.find("table")
    if not tabla:
        print("  ⚠ Sin tabla en respuesta — revisar archivo de debug")
        return []

    for fila in tabla.find_all("tr")[1:]:
        celdas = fila.find_all("td")
        n = len(celdas)
        if n < 2:
            continue
        # col 0 = ícono lupa (sin texto) → offset=1
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

async def consultar(
    busqueda: BusquedaBase,
    usar_2captcha: bool = True,
) -> list[Causa]:
    print(f"\n=== {busqueda.__class__.__name__} ===")
    cookies, token = await obtener_sesion_y_token(busqueda, usar_2captcha)
    if not token:
        raise RuntimeError("No se obtuvo token de captcha")
    print("  Ejecutando consulta al endpoint...")
    causas = await ejecutar_consulta(busqueda, cookies, token)
    print(f"  ✓ {len(causas)} causa(s) encontrada(s)")
    return causas