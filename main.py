#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# =======================================================================
# IMPORTS
# =======================================================================
import sys
import logging

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPalette, QColor, QFont

#from controller import MainController
from controller.base_controller import MainController  
from utils.config_manager import ConfigManager
from utils.theme_manager import ThemeManager

# =======================================================================
# FUNCIONES DE CONFIGURACIÓN
# =======================================================================
def setup_logging():
    """Configura logging para debugging en campo"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('sdr_analyzer.log'),
            logging.StreamHandler()
        ]
    )

def ensure_directories():
    """Asegura que existan los directorios necesarios"""
    import os
    
    directories = [
        "recordings",      # Para archivos IQ grabados
        "profiles",        # Para perfiles exportados
        "logs"             # Para logs adicionales
    ]
    
    for directory in directories:
        os.makedirs(directory, exist_ok=True)
        logging.getLogger(__name__).info(f"📁 Directorio asegurado: {directory}/")

def setup_dark_theme(app):
    """Configura el tema inicial (ahora usa ThemeManager)."""
    theme_manager = ThemeManager()
    theme_manager.apply_theme_to_app(app, 'dark')
    # El stylesheet ahora se maneja desde ThemeManager

# =======================================================================
# PUNTO DE ENTRADA PRINCIPAL
# =======================================================================
def main():
    """Punto de entrada principal"""
    setup_logging()
    logger = logging.getLogger(__name__)
    
    try:
        app = QApplication(sys.argv)
        app.setApplicationName("SIMANEEM")
        app.setOrganizationName("INIDETEC DCD")
        
        setup_dark_theme(app)

        
        ensure_directories()
        
        # Crear controller y cargar configuración
        controller = MainController()
        logger.info(f"Controller creado con theme_manager id: {id(controller.theme_manager)}")        

        # Crear config_manager PASANDO el theme_manager del controller
        from utils.config_manager import ConfigManager
        config_manager = ConfigManager(controller.theme_manager)  # ¡Usar el existente!
        logger.info(f"ConfigManager creado con theme_manager id: {id(config_manager.theme_manager)}")
        
        # Cargar configuración
        config_manager.load_all_settings(controller)
        
        controller.show()
        
        logger.info("SDR Analyzer iniciado correctamente")
        
        # Guardar configuración al salir
        exit_code = app.exec_()
        
        # Guardar configuración actual
        config_manager.save_all_settings(controller)
        logger.info("Configuración guardada al salir")
        
        sys.exit(exit_code)
        
    except Exception as e:
        logger.error(f"Error fatal: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()