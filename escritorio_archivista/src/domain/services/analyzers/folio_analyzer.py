"""
Analizador de folios — detecta errores de secuencia en el inventario.

Detecta:
1. FORMATO — folio_str no parseable (fatal)
2. SOLAPAMIENTO — el folio de inicio ya fue cubierto por un rango
   anterior, incluido el mismo folio inicial repetido (advertencia)
3. SALTO — salto no justificado por exclusiones (advertencia)
"""
import logging
from typing import List, Optional

from src.domain.entities import (
    AnalysisResult,
    AnalysisError,
    InventoryRecord,
    ExclusionRule,
)
from src.domain.services.folio_parser import (
    parse_folios,
    folio_to_int,
    int_to_folio,
    format_folio,
    es_sin_folio,
)

logger = logging.getLogger(__name__)


def analizar_folios(
    records: List[InventoryRecord],
    exclusions: Optional[List[ExclusionRule]] = None,
) -> AnalysisResult:
    """
    Analiza la secuencia de folios del inventario.

    Args:
        records: Lista de registros en orden.
        exclusions: Lista de exclusiones activas.

    Returns:
        AnalysisResult con errores y advertencias encontrados.
    """
    exclusions = exclusions or []
    errores: List[AnalysisError] = []
    advertencias: List[AnalysisError] = []
    seen_starts: dict = {}  # {folio_int_inicio: record_id}
    max_hasta_int: Optional[int] = None
    expected_next_int: Optional[int] = None
    prev_protocolo: Optional[str] = None
    last_was_sf = False
    validados = 0
    revisados = 0

    for record in records:
        revisados += 1

        # Cada protocolo tiene su propia secuencia de folios (los folios se
        # reinician entre protocolos), por lo que se resetea el estado.
        if prev_protocolo is not None and record.protocolo != prev_protocolo:
            seen_starts = {}
            max_hasta_int = None
            expected_next_int = None
            last_was_sf = False
        prev_protocolo = record.protocolo

        parsed = parse_folios(record.folios)

        # 1. SIN_FOLIO — el folio está marcado como "S/F" (sin foliación): es
        # una decisión intencional del inventario, no un error de formato.
        # No puede validarse la secuencia alrededor de este registro, por lo
        # que el salto de un registro precedente queda justificado.
        if parsed is None and es_sin_folio(record.folios):
            advertencias.append(AnalysisError(
                record_id=record.id,
                fila=record.fila,
                tipo="SIN_FOLIO",
                descripcion=(
                    "El registro no tiene foliación (S/F). "
                    "Indique manualmente su rango de páginas PDF."
                ),
                valor_actual=record.folios,
                valor_esperado="",
                fatal=False,
            ))
            last_was_sf = True
            continue

        # 2. FORMATO
        if parsed is None:
            errores.append(AnalysisError(
                record_id=record.id,
                fila=record.fila,
                tipo="FORMATO",
                descripcion=f"El folio '{record.folios}' no tiene un formato válido.",
                valor_actual=record.folios,
                valor_esperado="NNNr-NNNv",
                fatal=True,
            ))
            continue

        desde_num, desde_cara, hasta_num, hasta_cara = parsed
        desde_int = folio_to_int(desde_num, desde_cara)
        hasta_int = folio_to_int(hasta_num, hasta_cara)

        # Los registros que comparten hoja (comparte_hoja=True) arrancan en
        # el mismo folio donde terminó el anterior: SOLAPAMIENTO y SALTO son
        # esperados en ese caso y no se reportan.
        comparte_hoja = bool(getattr(record, "comparte_hoja", False))

        # 2. SOLAPAMIENTO — el folio de inicio ya está cubierto por el rango
        # más amplio visto en el protocolo actual. Incluye el borde compartido
        # y el mismo folio inicial repetido.
        if (
            not comparte_hoja
            and max_hasta_int is not None
            and desde_int <= max_hasta_int
        ):
            inicio_repetido = seen_starts.get(desde_int)
            if inicio_repetido:
                descripcion = (
                    f"El folio de inicio '{record.folios}' se repite y se "
                    f"solapa con el rango del registro {inicio_repetido}."
                )
            else:
                descripcion = (
                    f"El rango '{record.folios}' se solapa con el rango ya "
                    f"delimitado hasta el folio "
                    f"{_format_folio_int(max_hasta_int)}."
                )
            advertencias.append(AnalysisError(
                record_id=record.id,
                fila=record.fila,
                tipo="SOLAPAMIENTO",
                descripcion=descripcion,
                valor_actual=record.folios,
                valor_esperado=(
                    f"Inicio > folio {_format_folio_int(max_hasta_int)}"
                ),
                fatal=False,
            ))
            max_hasta_int = max(max_hasta_int, hasta_int)
            expected_next_int = max_hasta_int + 1
            seen_starts.setdefault(desde_int, record.id)
            last_was_sf = False
            if record.estado == "VALIDADO":
                validados += 1
            continue

        # 3. SALTO
        if (
            not comparte_hoja
            and expected_next_int is not None
            and desde_int != expected_next_int
        ):
            if not last_was_sf and not _salto_aprobado(expected_next_int, desde_int, exclusions):
                advertencias.append(AnalysisError(
                    record_id=record.id,
                    fila=record.fila,
                    tipo="SALTO",
                    descripcion=(
                        f"Salto de secuencia: se esperaba el folio "
                        f"{_format_folio_int(expected_next_int)} pero se "
                        f"encontró {_format_folio_int(desde_int)}."
                    ),
                    valor_actual=record.folios,
                    valor_esperado=f"Folio {_format_folio_int(expected_next_int)}",
                    fatal=False,
                ))

        # Actualizar tracking con el mayor folio cubierto del protocolo.
        if max_hasta_int is None or hasta_int > max_hasta_int:
            max_hasta_int = hasta_int
        expected_next_int = max_hasta_int + 1
        seen_starts.setdefault(desde_int, record.id)
        last_was_sf = False

        if record.estado == "VALIDADO":
            validados += 1

    return AnalysisResult(
        nombre="Analizador de Folios",
        total_revisados=revisados,
        errores=errores,
        advertencias=advertencias,
        info_extra={
            "validados": validados,
            "revisar": len(errores),
        },
    )


def _format_folio_int(n: int) -> str:
    """Formatea un entero de folio como '003r'/'004v' (con recto/verso)."""
    num, cara = int_to_folio(n)
    return format_folio(num, cara)


def _salto_aprobado(
    expected: int,
    actual: int,
    exclusions: List[ExclusionRule],
) -> bool:
    """
    Verifica si un salto de secuencia está aprobado por alguna exclusión.

    Busca exclusiones de tipo SALTO cuyo rango cubra [expected, actual-1].
    """
    for excl in exclusions:
        if excl.tipo == "SALTO":
            excl_desde = int(excl.desde)
            excl_hasta = int(excl.hasta)
            if excl_desde <= expected and excl_hasta >= actual - 1:
                return True
    return False
