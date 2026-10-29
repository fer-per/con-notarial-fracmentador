"""
Modelos de catálogo — configuración declarativa del inventario.

Un modelo describe cómo leer un Excel, qué metadatos extraer, cómo mapear
sus columnas y cómo construir la jerarquía de salida. Los modelos pueden
heredar de otro modelo (por ejemplo, ``notarial`` hereda de ``base``)
para compartir la configuración común sin duplicarla.

Este módulo no depende de pandas, openpyxl ni de la capa de presentación.
"""
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple, Union


@dataclass(frozen=True)
class UbicacionMetadato:
    """Fila y columna (1-based) donde vive un metadato del encabezado."""

    fila: int
    columna: int = 1
    regex: str = ""
    grupo: int = 1
    transformacion: str = "texto"
    prefijo: str = ""


@dataclass(frozen=True)
class MapeoColumna:
    """Aliases y columna de respaldo por índice para mapear una columna."""

    aliases: Tuple[str, ...] = ()
    indice_fallback: Optional[int] = None


@dataclass(frozen=True)
class ConfigExcel:
    """Cómo localizar y filtrar los datos dentro del libro Excel."""

    hoja: Union[int, str] = 0
    filas_encabezado: int = 2
    campos_fuertes: Tuple[str, ...] = ("registro", "escribano", "folios")
    ignorar_si_sin_fuertes: bool = True
    anotaciones: Tuple[str, ...] = ()
    ignorar_prefijos: Tuple[str, ...] = ()
    ignorar_regex: Tuple[str, ...] = ()
    detectar_keywords: Tuple[str, ...] = ()
    detectar_min_matches: int = 2


@dataclass(frozen=True)
class NivelJerarquia:
    """Un nivel de la ruta de salida.

    ``tipo`` identifica el valor a renderizar (``acervo``, ``siglo``,
    ``constante``, ``campo``, ``interesado1``, ``archivo``, etc.).
    """

    tipo: str
    campo: str = ""
    plantilla: str = "{valor}"
    respaldo: str = ""
    valor: str = ""
    mayusculas: bool = False
    truncar: int = 0


@dataclass(frozen=True)
class ConfigJerarquia:
    """Plantilla de niveles para construir la ruta de un registro."""

    niveles: Tuple[NivelJerarquia, ...] = ()
    max_path: int = 240


@dataclass(frozen=True)
class ConfigFolios:
    """Política de secuencia de folios para el modelo."""

    comparte_hoja_si_borde: bool = False
    tolerar_solapamiento_borde: bool = False


@dataclass(frozen=True)
class ModeloCatalogo:
    """Configuración completa de un tipo de catálogo/inventario."""

    id: str
    nombre: str
    descripcion: str = ""
    version: int = 2
    hereda_de: str = ""
    excel: ConfigExcel = field(default_factory=ConfigExcel)
    metadatos: Dict[str, UbicacionMetadato] = field(default_factory=dict)
    columnas: Dict[str, MapeoColumna] = field(default_factory=dict)
    jerarquia: ConfigJerarquia = field(default_factory=ConfigJerarquia)
    folios: ConfigFolios = field(default_factory=ConfigFolios)
    analizadores: Dict[str, bool] = field(default_factory=dict)

    def ubicacion_metadato(self, campo: str) -> Optional[UbicacionMetadato]:
        """Devuelve la ubicación de un metadato o None si no está mapeado."""
        return self.metadatos.get(campo)
