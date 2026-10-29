"""Tests de selección y detección del modelo de catálogo en WorkspaceVM."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from PySide6.QtCore import QCoreApplication

from src.presentation.viewmodels.app_state import AppStateVM
from src.presentation.viewmodels.workspace_vm import WorkspaceVM

_app = QCoreApplication.instance() or QCoreApplication([])


class _StubModeloRepo:
    def __init__(self, detectado="notarial"):
        self.detectado = detectado
        self.detectar_calls = 0

    def detectar(self, path):
        self.detectar_calls += 1
        return self.detectado


class _StubContainer:
    def __init__(self, detectado="notarial"):
        self.modelo_repo = _StubModeloRepo(detectado)
        self.modelo_actual = "historico"
        self.set_modelo_calls = []

    def set_modelo(self, modelo_id):
        self.modelo_actual = modelo_id
        self.set_modelo_calls.append(modelo_id)


class TestDeteccionModelo:
    def test_autodetecta_notarial(self):
        state = AppStateVM()
        container = _StubContainer()
        vm = WorkspaceVM(container, state)

        vm._detectar_modelo("catalogo.xlsx")

        assert state.modelo_id == "notarial"
        assert state.modelo_auto is True
        assert container.modelo_actual == "notarial"
        assert container.modelo_repo.detectar_calls == 1

    def test_override_manual_no_autodetecta(self):
        state = AppStateVM()
        state.modelo_id = "historico"
        state.modelo_auto = False
        container = _StubContainer()
        vm = WorkspaceVM(container, state)

        vm._detectar_modelo("catalogo.xlsx")

        assert state.modelo_id == "historico"
        assert container.modelo_actual == "historico"
        assert container.modelo_repo.detectar_calls == 0

    def test_set_modelo_marca_override_manual(self):
        state = AppStateVM()
        container = _StubContainer()
        vm = WorkspaceVM(container, state)

        vm.set_modelo("notarial", recargar=False)

        assert state.modelo_id == "notarial"
        assert state.modelo_auto is False
        assert container.modelo_actual == "notarial"

    def test_deteccion_sin_resultado_mantiene_modelo_actual(self):
        state = AppStateVM()
        container = _StubContainer(detectado=None)
        vm = WorkspaceVM(container, state)

        vm._detectar_modelo("catalogo.xlsx")

        assert state.modelo_id == "historico"
        assert container.modelo_actual == "historico"
