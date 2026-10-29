"""
Contenedor de Inyección de Dependencias.

Instancia única que crea y conecta todos los componentes
de infraestructura con los casos de uso.
"""
import logging

from src.infrastructure.excel_repository import ExcelRepository
from src.infrastructure.modelo_repository import ModeloRepository
from src.infrastructure.pdf_service import PDFService
from src.infrastructure.session_repository import SessionRepository
from src.infrastructure.hierarchy_builder import HierarchyBuilder

from src.application.use_cases.load_inventory import CargarInventarioUseCase
from src.application.use_cases.analyze_data import AnalizarDatosUseCase
from src.application.use_cases.manage_exclusions import GestionarExclusionesUseCase
from src.application.use_cases.fragment_pdf import FragmentarPDFUseCase
from src.application.use_cases.manage_session import GestionarSesionUseCase

from src.domain.services.folio_mapper import mapper_from_config

logger = logging.getLogger(__name__)


class Container:
    """
    Contenedor de inyección de dependencias.

    Las vistas reciben el Container y acceden a use cases a través de él.
    Encapsula la creación de infraestructura y la conexión con casos de uso.
    """

    def __init__(self):
        logger.info("Inicializando Container DI...")

        # Infraestructura
        self.modelo_repo = ModeloRepository()
        self.modelo_actual = self.modelo_repo.cargar("historico")
        self._excel_repo = ExcelRepository(self.modelo_actual)
        self._pdf_service = PDFService()
        self._session_repo = SessionRepository()
        self._hierarchy_builder = HierarchyBuilder(self.modelo_actual)

        # Casos de uso
        self.cargar_inventario = CargarInventarioUseCase(self._excel_repo)
        self.analizar_datos = AnalizarDatosUseCase()
        self.gestionar_exclusiones = GestionarExclusionesUseCase()
        self.fragmentar_pdf = FragmentarPDFUseCase(
            self._pdf_service, self._hierarchy_builder
        )
        self.gestionar_sesion = GestionarSesionUseCase(self._session_repo)

        # Acceso directo a servicios de infraestructura (para la presentación)
        self.pdf_service = self._pdf_service
        self.session = self._session_repo
        self.excel_repo = self._excel_repo

        logger.info("Container DI inicializado.")

    def set_modelo(self, modelo_id: str):
        """Activa un modelo de catálogo en el repositorio y el builder."""
        modelo = self.modelo_repo.cargar(modelo_id or "historico")
        self.modelo_actual = modelo
        self._excel_repo.set_modelo(modelo)
        self._hierarchy_builder.set_modelo(modelo)
        logger.info("Modelo de catálogo activo: %s", modelo.id)
        return modelo

    def crear_mapper(self, estado: dict):
        """
        Factory para crear un FolioMapper desde el estado de la app.

        Args:
            estado: Dict con pag_pdf_inicio, segmentos, exclusiones, page_map.
        """
        return mapper_from_config(
            pag_pdf_inicio=estado.get("pag_pdf_inicio", 1),
            segmentos=estado.get("segmentos"),
            exclusiones=estado.get("exclusiones"),
            page_map=estado.get("page_map"),
            active_pages=estado.get("active_pages"),
            total_pdf_pages=estado.get("pdf_total_pages"),
        )
