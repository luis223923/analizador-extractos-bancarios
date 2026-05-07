"""
Clase base abstracta para todos los parsers de banco.

Para agregar un banco nuevo:
1. Crear banks/nombre_banco.py
2. Crear una clase que herede de BankParser
3. Implementar can_parse() y parse()
4. El sistema lo detectará automáticamente
"""

from abc import ABC, abstractmethod
import pandas as pd


class BankParser(ABC):
    """Contrato que debe cumplir cada parser de banco."""

    # Nombre legible del banco, usado en la columna 'banco' del esquema estándar
    bank_name: str = "Desconocido"

    # Prioridad de detección: mayor número = se prueba antes (0-100)
    priority: int = 0

    @abstractmethod
    def can_parse(self, df: pd.DataFrame, filename: str = "") -> bool:
        """
        Determina si este parser puede manejar el DataFrame dado.

        Recibe el DataFrame en crudo tal como lo leyó el loader.
        Debe ser rápido y no modificar el DataFrame.
        """

    @abstractmethod
    def parse(self, df: pd.DataFrame, filename: str = "") -> pd.DataFrame:
        """
        Convierte el DataFrame crudo al esquema estándar.

        Debe devolver un DataFrame con exactamente las columnas de schema.STANDARD_COLUMNS.
        Puede lanzar ValueError si los datos son inválidos.
        """
