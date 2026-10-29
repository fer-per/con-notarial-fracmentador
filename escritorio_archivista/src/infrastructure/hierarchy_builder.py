"""
Constructor de jerarquía documental configurable (11/12 niveles).

Genera las rutas de carpetas para organizar los fragmentos PDF
siguiendo la plantilla del modelo de catálogo activo. La jerarquía
SIEMPRE se construye de forma íntegra; cada nivel que carece del dato
correspondiente usa un nombre de respaldo (SIN ...) y se continúa con
los siguientes niveles.

Niveles históricos:
1. ACERVO DOCUMENTAL NUMERO {acervo_num}     ← metadato (fila del Excel)
2. SIGLO {siglo_arabigo}                     ← metadato (fila del Excel)
3. FONDO DOCUMENTAL                          ← constante
4. {escribano}                               ← metadato (fila del Excel)
5. {año}                                     ← de la fecha de inicio
6. PROTOCOLO {protocolo}                     ← del registro
7. REGISTRO {registro}                       ← número real del catálogo
8. {titulo}                                  ← valor literal de la columna
9. {mes}                                     ← de la fecha de inicio
10. {interesado1}                            ← 1er interesado (antes de la coma)
11. {interesado2}.pdf                        ← nombre del archivo

Los niveles 1 a 9 se escriben EN MAYÚSCULAS; los niveles 10 y 11
(interesados) conservan la grafía original de la columna.

Respaldo por nivel cuando falta el dato:
- SIN SIGLO, SIN ESCRIBANO, SIN AÑO, SIN PROTOCOLO, SIN REGISTRO,
  SIN TITULO DE ESCRITURA, SIN MES.
- Para interesados: se usa el siguiente disponible; si no hay ninguno,
  "DATOS DE LOS INTERESADOS ILEGIBLES".

Si dos PDFs comparten el mismo nombre dentro de la misma carpeta,
se asigna numeración sucesiva: {nombre}.pdf, {nombre}_2.pdf, ...
"""
import logging
import os
import re
from typing import Optional, Tuple

from src.domain.entities import InventoryRecord
from src.domain.modelo_catalogo import ModeloCatalogo, NivelJerarquia
from src.domain.ports.hierarchy_port import HierarchyBuilderPort
from src.domain.value_objects import (
    MONTH_NAMES,
    YEAR_MIN,
    YEAR_MAX,
    INVALID_FILENAME_CHARS,
    ROMAN_TO_ARABIC,
    SIN_SIGLO,
    SIN_ESCRIBANO,
    SIN_ANIO,
    SIN_PROTOCOLO,
    SIN_REGISTRO,
    SIN_TITULO,
    SIN_MES,
    INTERESADOS_ILEGIBLES,
)
from src.infrastructure.modelo_repository import ModeloRepository

logger = logging.getLogger(__name__)


class HierarchyBuilder(HierarchyBuilderPort):
    """
    Implementación del constructor de jerarquía de 11 niveles.

    La jerarquía siempre se construye completa; cada nivel sin dato
    usa su nombre de respaldo.
    """

    def __init__(self, modelo: Optional[ModeloCatalogo] = None):
        self._modelo = modelo or ModeloRepository().cargar("historico")

    def set_modelo(self, modelo: ModeloCatalogo):
        """Cambia la plantilla de jerarquía usada por el builder."""
        self._modelo = modelo

    def construir_ruta(
        self,
        record: InventoryRecord,
        output_dir: str,
        acervo_num: str = "",
        escribano: str = "",
        siglo: str = "",
    ) -> str:
        """Construye la ruta completa según la plantilla del modelo activo."""
        anio, mes = self._extraer_anio_mes(record)
        registro_id = record.id.replace("#", "")

        niveles_modelo = self._modelo.jerarquia.niveles
        if niveles_modelo:
            niveles = [
                self._render_nivel(
                    nivel, record, acervo_num, escribano, siglo, anio, mes
                )
                for nivel in niveles_modelo
            ]
        else:
            # Fallback para el modelo legacy sin plantilla declarada.
            niveles = [
                self._nivel_acervo(acervo_num),
                self._nivel_siglo(siglo, anio),
                "FONDO DOCUMENTAL",
                self._nivel_escribano(escribano),
                self._nivel_anio(anio),
                self._nivel_protocolo(record),
                self._nivel_registro(record, registro_id),
                self._nivel_titulo(record),
                self._nivel_mes(mes),
                self._nivel_interesado1(record),
                self._nombre_archivo(record, registro_id),
            ]

        full_path = os.path.join(output_dir, *niveles)
        return self._resolver_colision(full_path)

    def _render_nivel(
        self,
        nivel: NivelJerarquia,
        record: InventoryRecord,
        acervo_num: str,
        escribano: str,
        siglo: str,
        anio: Optional[int],
        mes: Optional[int],
    ) -> str:
        """Renderiza un nivel declarativo de la plantilla."""
        tipo = nivel.tipo
        respaldo = nivel.respaldo
        plantilla = nivel.plantilla or "{valor}"

        if tipo == "constante":
            valor = nivel.valor
        elif tipo == "acervo":
            valor = self._valor_acervo(acervo_num)
            if not valor:
                return respaldo
        elif tipo == "siglo":
            valor = self._valor_siglo(siglo, anio)
            if not valor:
                return respaldo
        elif tipo == "escribano":
            valor = self._sanitize((escribano or "").strip())
            if not (escribano or "").strip():
                return respaldo
        elif tipo == "anio":
            if anio is None:
                return respaldo
            valor = str(anio)
        elif tipo == "mes":
            if mes is None:
                return respaldo
            valor = MONTH_NAMES.get(mes, respaldo)
        elif tipo == "protocolo":
            valor = self._sanitize((record.protocolo or "").strip())
            if not (record.protocolo or "").strip():
                return respaldo
        elif tipo == "tomo":
            valor = self._sanitize((record.tomo or "").strip())
            if not (record.tomo or "").strip():
                return respaldo
        elif tipo == "registro":
            raw = self._valor_registro(record)
            if not raw:
                return respaldo
            valor = self._sanitize(raw)
        elif tipo == "escritura":
            raw = (record.escritura or "").strip()
            if raw in ("-", "—"):
                raw = ""
            if not raw:
                return respaldo
            valor = self._sanitize(raw)
        elif tipo == "titulo":
            valor = self._sanitize((record.titulo or "").strip())
            if not (record.titulo or "").strip():
                return respaldo
        elif tipo == "interesado1":
            valor = self._primer_interesado_disponible(
                record.interesado1, record.interesado2, record.interesado3
            )
            if not valor:
                return respaldo
            valor = self._sanitize(valor)
        elif tipo == "archivo":
            nombre = self._primer_interesado_disponible(
                record.interesado2, record.interesado1, record.interesado3
            )
            if not nombre:
                return respaldo
            return f"{self._sanitize(nombre)}.pdf"
        elif tipo == "campo":
            campo = nivel.campo or ""
            raw = str(getattr(record, campo, "") or "").strip()
            if not raw:
                return respaldo
            valor = self._sanitize(raw)
        else:
            valor = nivel.valor or respaldo

        if nivel.mayusculas:
            valor = valor.upper()
        if nivel.truncar and len(valor) > nivel.truncar:
            valor = valor[:nivel.truncar].rstrip()
        return plantilla.format(valor=valor)

    @staticmethod
    def _valor_acervo(acervo_num: str) -> str:
        valor = (acervo_num or "").strip()
        return HierarchyBuilder._sanitize(valor) if valor else ""

    @staticmethod
    def _valor_siglo(siglo: str, anio: Optional[int]) -> str:
        romano = (siglo or "").strip().upper()
        if romano:
            arabico = ROMAN_TO_ARABIC.get(romano)
            return str(arabico) if arabico is not None else romano
        if anio is not None:
            return str((anio // 100) + 1)
        return ""

    @staticmethod
    def _valor_registro(record: InventoryRecord) -> str:
        valor = (record.registro or "").strip()
        if valor and valor not in ("0", "00:00:00") and ":" not in valor \
                and not re.search(r'(?i)(registro|protocolo|indice|salto)', valor):
            return valor
        return ""

    @staticmethod
    def _nivel_acervo(acervo_num: str) -> str:
        """Nivel 1: número de acervo (metadato global), en mayúsculas."""
        valor = (acervo_num or "").strip()
        if not valor:
            return "ACERVO DOCUMENTAL"
        return f"ACERVO DOCUMENTAL NUMERO {HierarchyBuilder._sanitize(valor).upper()}"

    @staticmethod
    def _nivel_siglo(siglo: str, anio: Optional[int]) -> str:
        """Nivel 2: siglo en números arábigos (metadato); sin metadato se deriva del año."""
        romano = (siglo or "").strip().upper()
        if romano:
            arabico = ROMAN_TO_ARABIC.get(romano)
            if arabico is not None:
                return f"SIGLO {arabico}"
            return f"SIGLO {romano}"
        if anio is not None:
            return f"SIGLO {(anio // 100) + 1}"
        return SIN_SIGLO

    @staticmethod
    def _nivel_escribano(escribano: str) -> str:
        """Nivel 4: escribano global en mayúsculas; si falta, respaldo."""
        valor = (escribano or "").strip()
        if not valor:
            return SIN_ESCRIBANO
        return HierarchyBuilder._sanitize(valor).upper()

    @staticmethod
    def _nivel_anio(anio: Optional[int]) -> str:
        """Nivel 5: año; si falta, respaldo."""
        if anio is None:
            return SIN_ANIO
        return str(anio)

    @staticmethod
    def _nivel_protocolo(record: InventoryRecord) -> str:
        """Nivel 6: protocolo en mayúsculas; si falta, respaldo."""
        protocolo = (record.protocolo or "").strip()
        if not protocolo:
            return SIN_PROTOCOLO
        return f"PROTOCOLO {HierarchyBuilder._sanitize(protocolo).upper()}"

    @staticmethod
    def _nivel_registro(record: InventoryRecord, registro_id: str) -> str:
        """
        Nivel 7: número real del registro en mayúsculas; si falta o es
        inválido, respaldo.
        """
        valor = (record.registro or "").strip()

        # Valores que no son un número de registro: vacío, hora mal
        # interpretada, filas de índice/sub-encabezado o anotaciones.
        if valor and valor not in ("0", "00:00:00") and ":" not in valor \
                and not re.search(r'(?i)(registro|protocolo|indice|salto)', valor):
            return f"REGISTRO {HierarchyBuilder._sanitize(valor).upper()}"

        return SIN_REGISTRO

    @staticmethod
    def _nivel_titulo(record: InventoryRecord) -> str:
        """Nivel 8: título literal de la columna en mayúsculas; si falta, respaldo."""
        titulo = (record.titulo or "").strip()
        if not titulo:
            return SIN_TITULO
        return HierarchyBuilder._sanitize(titulo).upper()

    @staticmethod
    def _nivel_mes(mes: Optional[int]) -> str:
        """Nivel 9: mes del MONTH_NAMES; si falta, respaldo."""
        if mes is None:
            return SIN_MES
        return MONTH_NAMES.get(mes, SIN_MES)

    @staticmethod
    def _nivel_interesado1(record: InventoryRecord) -> str:
        """
        Nivel 10: carpeta del interesado 1.

        Si no hay interesado 1 se usa el 2; si no, el 3; si no hay
        ninguno se usa 'DATOS DE LOS INTERESADOS ILEGIBLES'.
        """
        nombre = HierarchyBuilder._primer_interesado_disponible(
            record.interesado1, record.interesado2, record.interesado3
        )
        if nombre:
            return HierarchyBuilder._sanitize(nombre)
        return INTERESADOS_ILEGIBLES

    @staticmethod
    def _nombre_archivo(record: InventoryRecord, registro_id: str) -> str:
        """
        Nivel 11: nombre del archivo PDF.

        Usa el interesado 2; si no hay, el 1; si no, el 3; si no hay
        ninguno, 'DATOS DE LOS INTERESADOS ILEGIBLES.pdf'.
        """
        nombre = HierarchyBuilder._primer_interesado_disponible(
            record.interesado2, record.interesado1, record.interesado3
        )
        if nombre:
            return f"{HierarchyBuilder._sanitize(nombre)}.pdf"
        return f"{INTERESADOS_ILEGIBLES}.pdf"

    @staticmethod
    def _primer_interesado_disponible(*nombres) -> str:
        """Devuelve el primer interesado no vacío (truncado a la primera coma)."""
        for nombre in nombres:
            if not nombre:
                continue
            resultado = HierarchyBuilder._primer_interesado(nombre)
            if resultado:
                return resultado
        return ""

    @staticmethod
    def _primer_interesado(nombre: str) -> str:
        """
        Toma solo el primer interesado de un nombre compuesto.

        En el inventario, un interesado puede listar varias personas
        separadas por coma, guion o paréntesis (ej: "Luis de Rueda,
        Juan de Mendoza", "Ana (hija de Pedro)"). Se usa únicamente el
        texto anterior al primer separador, sin incluirlo, para carpetas
        y nombres de archivo más cortos.
        """
        if not nombre:
            return ""
        # Cortar en el primer separador: coma, guion o paréntesis.
        for sep in (",", "-", "(", ")"):
            idx = nombre.find(sep)
            if idx != -1:
                nombre = nombre[:idx]
                break
        return nombre.strip()

    def _extraer_anio_mes(
        self, record: InventoryRecord
    ) -> Tuple[Optional[int], Optional[int]]:
        """
        Extrae año y mes de las fechas del registro.

        Busca una fecha válida en ``fecha_inicio`` y ``fecha_fin``. Como
        último recurso, intenta encontrar un año válido en el número de
        registro.

        Returns:
            Tupla ``(anio, mes)`` si hay una fecha válida; ``(None, None)``
            si el registro no tiene fecha.
        """
        for campo in (record.fecha_inicio, record.fecha_fin):
            if not campo:
                continue
            resultado = self._parsear_fecha(campo)
            if resultado is not None:
                return resultado

        # Fallback: buscar un año válido en el número de registro
        if record.registro:
            match = re.search(r'(\d{4})', record.registro)
            if match and self._es_anio_valido(int(match.group(1))):
                return int(match.group(1)), None

        return None, None

    @staticmethod
    def _parsear_fecha(valor: str) -> Optional[Tuple[int, int]]:
        """
        Parsea una fecha textual en ``(anio, mes)``.

        Acepta formatos ``d/m/yyyy``, ``yyyy-mm-dd`` y cualquier año de
        4 dígitos dentro del texto. Si solo aparece el año, devuelve
        ``(anio, None)`` (mes desconocido). Devuelve ``None`` si no hay
        una fecha válida.
        """
        # Formato d/m/yyyy
        match = re.match(r'(\d{1,2})/(\d{1,2})/(\d{4})', valor)
        if match:
            mes, anio = int(match.group(2)), int(match.group(3))
            if 1 <= mes <= 12 and HierarchyBuilder._es_anio_valido(anio):
                return anio, mes
            else: 
                re.match(r'(\d{1,2})//(\d{1,2})//(\d{4})', valor)
            return None

        # Formato yyyy-mm-dd
        match = re.match(r'(\d{4})-(\d{1,2})-(\d{1,2})', valor)
        if match:
            anio, mes = int(match.group(1)), int(match.group(2))
            if 1 <= mes <= 12 and HierarchyBuilder._es_anio_valido(anio):
                return anio, mes
            return None

        # Cualquier año de 4 dígitos dentro del texto
        match = re.search(r'(\d{4})', valor)
        if match and HierarchyBuilder._es_anio_valido(int(match.group(1))):
            return int(match.group(1)), None

        return None

    @staticmethod
    def _es_anio_valido(anio: int) -> bool:
        """True si el año está dentro del rango histórico permitido."""
        return YEAR_MIN <= anio <= YEAR_MAX

    @staticmethod
    def _sanitize(name: str) -> str:
        """
        Sanitiza un nombre para uso en sistema de archivos Windows.

        Reemplaza caracteres inválidos, colapsa espacios y underscores.
        """
        if not name:
            return "SIN_NOMBRE"

        # Reemplazar caracteres inválidos
        for char in INVALID_FILENAME_CHARS:
            name = name.replace(char, '_')

        # Colapsar múltiples espacios y underscores
        name = re.sub(r'[\s_]+', ' ', name).strip()

        if not name:
            return "SIN_NOMBRE"

        return name

    @staticmethod
    def _resolver_colision(full_path: str) -> str:
        """
        Si la ruta ya existe, agrega numeración sucesiva al archivo.

        Ej: ``{nombre}.pdf`` → ``{nombre}_2.pdf`` → ``{nombre}_3.pdf``.
        La numeración sigue el orden de creación de los archivos.
        """
        if not os.path.exists(full_path):
            return full_path

        base, ext = os.path.splitext(full_path)
        counter = 2
        while os.path.exists(f"{base}_{counter}{ext}"):
            counter += 1
        return f"{base}_{counter}{ext}"
