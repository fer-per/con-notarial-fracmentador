"""
Repositorio de modelos de catálogo.

Carga los JSON de ``resources/modelos``, resuelve la herencia declarada
con ``hereda_de`` y expone modelos listos para usar por la infraestructura.
"""
import copy
import json
import logging
import os
import unicodedata
from typing import Dict, List, Optional

import pandas as pd

from src.domain.modelo_catalogo import (
    ConfigExcel,
    ConfigFolios,
    ConfigJerarquia,
    MapeoColumna,
    ModeloCatalogo,
    NivelJerarquia,
    UbicacionMetadato,
)

logger = logging.getLogger(__name__)

DEFAULT_MODELOS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "resources", "modelos")
)


class ModeloError(Exception):
    """Error de configuración de un modelo de catálogo."""


class ModeloRepository:
    """Carga y resuelve modelos de catálogo desde archivos JSON."""

    def __init__(self, modelos_dir: Optional[str] = None):
        self._dir = os.path.abspath(modelos_dir or DEFAULT_MODELOS_DIR)

    @property
    def directorio(self) -> str:
        return self._dir

    def listar(self) -> List[ModeloCatalogo]:
        """Devuelve los modelos disponibles, excluyendo el modelo base."""
        modelos: List[ModeloCatalogo] = []
        if not os.path.isdir(self._dir):
            return modelos

        for nombre_archivo in sorted(os.listdir(self._dir)):
            if not nombre_archivo.endswith(".json"):
                continue
            modelo_id = os.path.splitext(nombre_archivo)[0]
            if modelo_id == "base":
                continue
            try:
                modelos.append(self.cargar(modelo_id))
            except ModeloError as e:
                logger.warning("Modelo %s omitido: %s", modelo_id, e)
        return modelos

    def cargar(self, modelo_id: str) -> ModeloCatalogo:
        """Carga un modelo resolviendo su herencia."""
        if not modelo_id:
            modelo_id = "historico"
        try:
            data = self._cargar_data(modelo_id, visitados=[])
        except FileNotFoundError:
            logger.warning(
                "Modelo '%s' no encontrado en %s; usando fallback histórico.",
                modelo_id, self._dir,
            )
            return self._modelo_legacy_historico()
        return _parsear_modelo(data, modelo_id)

    def cargar_todos(self) -> Dict[str, ModeloCatalogo]:
        """Devuelve un diccionario id -> modelo."""
        return {m.id: m for m in self.listar()}

    def detectar(self, ruta_excel: str) -> Optional[str]:
        """Intenta identificar el modelo por las firmas del encabezado.

        Lee las primeras 200 filas de la hoja declarada por cada modelo y
        puntúa cuántas ``detectar_keywords`` aparecen. Devuelve el id del
        modelo con mayor puntaje o None si ninguno alcanza el mínimo.
        """
        mejor_id: Optional[str] = None
        mejor_score = 0
        mejor_minimo = 0

        for modelo in self.listar():
            keywords = modelo.excel.detectar_keywords
            if not keywords:
                continue
            try:
                df = pd.read_excel(
                    ruta_excel,
                    sheet_name=modelo.excel.hoja,
                    header=None,
                    nrows=200,
                    engine="openpyxl",
                )
            except Exception as e:
                logger.debug(
                    "No se pudo leer la hoja %r para detectar %s: %s",
                    modelo.excel.hoja, modelo.id, e,
                )
                continue

            textos = []
            for _, row in df.iterrows():
                for valor in row:
                    texto = _normalizar_texto(valor)
                    if texto:
                        textos.append(texto)
            score = sum(
                1 for kw in keywords
                if any(_normalizar_texto(kw) in texto for texto in textos)
            )
            minimo = modelo.excel.detectar_min_matches
            if score >= minimo and score > mejor_score:
                mejor_id = modelo.id
                mejor_score = score
                mejor_minimo = minimo
            elif score >= minimo and score == mejor_score and mejor_id is None:
                mejor_id = modelo.id
                mejor_score = score
                mejor_minimo = minimo

        if mejor_id is not None:
            logger.info(
                "Modelo detectado: %s (score %d, mínimo %d).",
                mejor_id, mejor_score, mejor_minimo,
            )
        return mejor_id

    # ─── Carga interna ─────────────────────────────────────────

    def _cargar_data(self, modelo_id: str, visitados: List[str]) -> dict:
        if modelo_id in visitados:
            ciclo = " -> ".join(visitados + [modelo_id])
            raise ModeloError(f"Herencia circular entre modelos: {ciclo}")

        ruta = os.path.join(self._dir, f"{modelo_id}.json")
        if not os.path.isfile(ruta):
            raise FileNotFoundError(ruta)

        try:
            with open(ruta, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            raise ModeloError(f"No se pudo leer {ruta}: {e}") from e

        if not isinstance(data, dict):
            raise ModeloError(f"El modelo {ruta} debe ser un objeto JSON.")

        padre_id = str(data.get("hereda_de") or "").strip()
        if not padre_id:
            return data

        try:
            padre = self._cargar_data(padre_id, visitados + [modelo_id])
        except FileNotFoundError as e:
            raise ModeloError(
                f"El modelo '{modelo_id}' hereda de '{padre_id}', "
                f"pero no se encontró {e}."
            ) from e

        fusionado = _fusionar(copy.deepcopy(padre), data)
        fusionado["id"] = modelo_id
        return fusionado

    def _modelo_legacy_historico(self) -> ModeloCatalogo:
        """Fallback: reutiliza ``mapa_maestro.json`` y la jerarquía clásica."""
        from src.infrastructure.mapeo_maestro import cargar_mapeo_maestro

        mapeo = cargar_mapeo_maestro()
        metadatos = {
            campo: UbicacionMetadato(
                fila=ubic.fila,
                columna=ubic.columna,
                transformacion=(
                    "siglo_romano" if campo == "siglo"
                    else "numero" if campo == "acervo"
                    else "texto"
                ),
            )
            for campo, ubic in mapeo.metadatos.items()
        }
        columnas = {
            campo: MapeoColumna(
                aliases=mapeo_col.aliases,
                indice_fallback=mapeo_col.indice_fallback,
            )
            for campo, mapeo_col in mapeo.columnas.items()
        }
        return ModeloCatalogo(
            id="historico",
            nombre="Fragmentador histórico",
            descripcion="Fallback basado en mapa_maestro.json.",
            hereda_de="",
            excel=ConfigExcel(
                detectar_keywords=("escribano", "n° de prot", "n° de folios", "registro"),
            ),
            metadatos=metadatos,
            columnas=columnas,
            jerarquia=ConfigJerarquia(niveles=()),
            folios=ConfigFolios(),
        )


# ═══ Parseo y merge ════════════════════════════════════════════

def _fusionar(base, override):
    """Fusiona dos estructuras JSON: dicts recursivos, listas reemplazan."""
    if isinstance(base, dict) and isinstance(override, dict):
        resultado = copy.deepcopy(base)
        for clave, valor in override.items():
            if clave in resultado:
                resultado[clave] = _fusionar(resultado[clave], valor)
            else:
                resultado[clave] = copy.deepcopy(valor)
        return resultado
    return copy.deepcopy(override)


def _parsear_modelo(data: dict, modelo_id: str) -> ModeloCatalogo:
    if not isinstance(data, dict):
        raise ModeloError(f"El modelo '{modelo_id}' no es un objeto JSON.")

    excel_data = data.get("excel") or {}
    jerarquia_data = data.get("jerarquia") or {}
    folios_data = data.get("folios") or {}

    return ModeloCatalogo(
        id=str(data.get("id") or modelo_id),
        nombre=str(data.get("nombre") or modelo_id),
        descripcion=str(data.get("descripcion") or ""),
        version=_entero(data.get("version"), 2),
        hereda_de=str(data.get("hereda_de") or ""),
        excel=_parsear_excel(excel_data),
        metadatos={
            str(campo): _parsear_ubicacion(valor)
            for campo, valor in (data.get("metadatos") or {}).items()
            if isinstance(valor, dict)
        },
        columnas={
            str(campo): _parsear_columna(valor)
            for campo, valor in (data.get("columnas") or {}).items()
            if isinstance(valor, dict)
        },
        jerarquia=ConfigJerarquia(
            niveles=tuple(
                _parsear_nivel(nivel)
                for nivel in (jerarquia_data.get("niveles") or [])
                if isinstance(nivel, dict)
            ),
            max_path=_entero(jerarquia_data.get("max_path"), 240),
        ),
        folios=ConfigFolios(
            comparte_hoja_si_borde=bool(folios_data.get("comparte_hoja_si_borde", False)),
            tolerar_solapamiento_borde=bool(
                folios_data.get("tolerar_solapamiento_borde", False)
            ),
        ),
        analizadores={
            str(nombre): bool(activo)
            for nombre, activo in (data.get("analizadores") or {}).items()
        },
    )


def _parsear_excel(data: dict) -> ConfigExcel:
    hoja = data.get("hoja", 0)
    if isinstance(hoja, str) and hoja.isdigit():
        hoja = int(hoja)

    return ConfigExcel(
        hoja=hoja,
        filas_encabezado=_entero(data.get("filas_encabezado"), 2),
        campos_fuertes=_tupla_texto(data.get("campos_fuertes"), ("registro", "escribano", "folios")),
        ignorar_si_sin_fuertes=bool(data.get("ignorar_si_sin_fuertes", True)),
        anotaciones=_tupla_texto(data.get("anotaciones"), ()),
        ignorar_prefijos=_tupla_texto(data.get("ignorar_prefijos"), ()),
        ignorar_regex=_tupla_texto(data.get("ignorar_regex"), ()),
        detectar_keywords=_tupla_texto(data.get("detectar_keywords"), ()),
        detectar_min_matches=_entero(data.get("detectar_min_matches"), 2),
    )


def _parsear_ubicacion(data: dict) -> UbicacionMetadato:
    return UbicacionMetadato(
        fila=max(1, _entero(data.get("fila"), 1)),
        columna=max(1, _entero(data.get("columna"), 1)),
        regex=str(data.get("regex") or ""),
        grupo=_entero(data.get("grupo"), 1),
        transformacion=str(data.get("transformacion") or "texto"),
        prefijo=str(data.get("prefijo") or ""),
    )


def _parsear_columna(data: dict) -> MapeoColumna:
    indice = data.get("indice_fallback")
    if isinstance(indice, (int, float)) and not isinstance(indice, bool):
        indice = int(indice)
    else:
        indice = None
    return MapeoColumna(
        aliases=_tupla_texto(data.get("aliases"), ()),
        indice_fallback=indice,
    )


def _parsear_nivel(data: dict) -> NivelJerarquia:
    return NivelJerarquia(
        tipo=str(data.get("tipo") or ""),
        campo=str(data.get("campo") or ""),
        plantilla=str(data.get("plantilla") or "{valor}"),
        respaldo=str(data.get("respaldo") or ""),
        valor=str(data.get("valor") or ""),
        mayusculas=bool(data.get("mayusculas", False)),
        truncar=_entero(data.get("truncar"), 0),
    )


def _entero(valor, defecto: int) -> int:
    try:
        return int(valor)
    except (TypeError, ValueError):
        return defecto


def _tupla_texto(valor, defecto) -> tuple:
    if isinstance(valor, (list, tuple)):
        return tuple(str(v) for v in valor if str(v).strip())
    if isinstance(valor, str) and valor.strip():
        return (valor,)
    return tuple(defecto)


def _normalizar_texto(valor) -> str:
    if valor is None:
        return ""
    texto = str(valor).strip().lower()
    if not texto:
        return ""
    return "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )
