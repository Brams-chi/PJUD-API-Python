"""
PJUD API — FastAPI
Expone el scraper como endpoints REST con respuesta JSON estandarizada.

Endpoints:
  GET  /health
  POST /causas/rit
  POST /causas/nombre

Ejecutar:
  python -m uvicorn api:app --reload --port 8000
"""

import os
import sys
import time
import asyncio
from datetime import datetime
from typing import Optional

# ── Fix Windows: Playwright requiere SelectorEventLoop, no ProactorEventLoop ──
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# Cargar .env antes de cualquier otra cosa
load_dotenv()

from scraper_core import BusquedaNombre, BusquedaRit, Causa, consultar


# ─────────────────────────────────────────────────────────────
# Validación temprana de configuración
# ─────────────────────────────────────────────────────────────

if not os.getenv("TWOCAPTCHA_API_KEY"):
    raise RuntimeError(
        "Falta TWOCAPTCHA_API_KEY en el archivo .env\n"
        "Crea el archivo .env con: TWOCAPTCHA_API_KEY=tu_key_aqui"
    )


# ─────────────────────────────────────────────────────────────
# App
# ─────────────────────────────────────────────────────────────

app = FastAPI(
    title="PJUD Scraper API",
    description=(
        "Consulta de causas del Poder Judicial de Chile.\n\n"
        "Cada request abre un browser headless, resuelve el reCAPTCHA "
        "automáticamente via 2captcha y retorna los resultados en JSON.\n\n"
        "**Tiempo estimado por consulta:** 20-40 segundos."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # Restringir al dominio del cliente web en producción
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────────────────────
# Schemas Pydantic
# ─────────────────────────────────────────────────────────────

class BusquedaRitRequest(BaseModel):
    rol: str = Field(..., example="121212")
    anio: str = Field(..., example="2019")
    competencia: str = Field("2", description="2=Corte Apelaciones, 1=Corte Suprema")
    corte: str = Field("0", description="0=Todas")
    tipo_busqueda: str = Field("1", description="1=Expediente 1ª Instancia")

    model_config = {
        "json_schema_extra": {
            "example": {"rol": "121212", "anio": "2019"}
        }
    }


class BusquedaNombreRequest(BaseModel):
    nombre: str = Field(..., example="Carlos")
    ape_paterno: str = Field(..., example="Suazo")
    ape_materno: str = Field("", example="")
    anio: str = Field("", example="")
    competencia: str = Field("1", description="1=Corte Suprema, 2=Corte Apelaciones")

    model_config = {
        "json_schema_extra": {
            "example": {
                "nombre": "Carlos",
                "ape_paterno": "Suazo",
                "ape_materno": "",
                "competencia": "1"
            }
        }
    }


class CausaSchema(BaseModel):
    rol: str
    tipo_recurso: str
    caratulado: str
    fecha_ingreso: str
    estado_causa: str
    corte: str


class ApiResponse(BaseModel):
    success: bool
    timestamp: str
    tipo_busqueda: str
    total: int
    duracion_segundos: float
    causas: list[CausaSchema]


class ErrorResponse(BaseModel):
    success: bool = False
    timestamp: str
    error: str
    detalle: Optional[str] = None


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _ts() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _causas_to_schema(causas: list[Causa]) -> list[CausaSchema]:
    return [CausaSchema(**c.to_dict()) for c in causas]


def _error(error: str, detalle: str = None, status: int = 500) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "success": False,
            "timestamp": _ts(),
            "error": error,
            "detalle": detalle,
        },
    )


# ─────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────

@app.get("/health", tags=["Sistema"], summary="Estado de la API")
async def health():
    return {
        "success": True,
        "timestamp": _ts(),
        "status": "ok",
        "version": "1.0.0",
        "captcha_configurado": bool(os.getenv("TWOCAPTCHA_API_KEY")),
    }


@app.post(
    "/causas/rit",
    response_model=ApiResponse,
    tags=["Causas"],
    summary="Búsqueda por RIT — Corte de Apelaciones",
    responses={
        200: {"description": "Causas encontradas"},
        422: {"description": "Parámetros inválidos o falta API key"},
        503: {"description": "Timeout en reCAPTCHA o PJUD no disponible"},
        500: {"description": "Error interno del scraper"},
    },
)
async def buscar_por_rit(body: BusquedaRitRequest):
    t0 = time.time()
    try:
        busqueda = BusquedaRit(
            rol=body.rol,
            anio=body.anio,
            competencia=body.competencia,
            corte=body.corte,
            tipo_busqueda=body.tipo_busqueda,
        )
        causas = await consultar(busqueda, usar_2captcha=True)
        return ApiResponse(
            success=True,
            timestamp=_ts(),
            tipo_busqueda="rit",
            total=len(causas),
            duracion_segundos=round(time.time() - t0, 2),
            causas=_causas_to_schema(causas),
        )
    except ValueError as e:
        return _error("Configuración inválida", str(e), 422)
    except TimeoutError as e:
        return _error("Timeout resolviendo reCAPTCHA", str(e), 503)
    except RuntimeError as e:
        return _error("Error en scraper", str(e), 500)
    except Exception as e:
        return _error("Error inesperado", str(e), 500)


@app.post(
    "/causas/nombre",
    response_model=ApiResponse,
    tags=["Causas"],
    summary="Búsqueda por Nombre — Corte Suprema",
    responses={
        200: {"description": "Causas encontradas"},
        422: {"description": "Parámetros inválidos o falta API key"},
        503: {"description": "Timeout en reCAPTCHA o PJUD no disponible"},
        500: {"description": "Error interno del scraper"},
    },
)
async def buscar_por_nombre(body: BusquedaNombreRequest):
    t0 = time.time()
    try:
        busqueda = BusquedaNombre(
            nombre=body.nombre,
            ape_paterno=body.ape_paterno,
            ape_materno=body.ape_materno,
            anio=body.anio,
            competencia=body.competencia,
        )
        causas = await consultar(busqueda, usar_2captcha=True)
        return ApiResponse(
            success=True,
            timestamp=_ts(),
            tipo_busqueda="nombre",
            total=len(causas),
            duracion_segundos=round(time.time() - t0, 2),
            causas=_causas_to_schema(causas),
        )
    except ValueError as e:
        return _error("Configuración inválida", str(e), 422)
    except TimeoutError as e:
        return _error("Timeout resolviendo reCAPTCHA", str(e), 503)
    except RuntimeError as e:
        return _error("Error en scraper", str(e), 500)
    except Exception as e:
        return _error("Error inesperado", str(e), 500)


# ─────────────────────────────────────────────────────────────
# Handler global
# ─────────────────────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return _error("Error interno del servidor", str(exc), 500)


# ─────────────────────────────────────────────────────────────
# Entrypoint Windows-compatible
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api:app",
        host="0.0.0.0",
        port=8000,
        reload=False,  # reload=True es incompatible con SelectorEventLoop en Windows
        loop="asyncio",
    )