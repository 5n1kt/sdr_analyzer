#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
SIMANEEM - SDR Analyzer for SIGINT Operations
===============================================
Main entry point for the SDR spectrum analyzer application.

Author: INIDETEC - DCD
Hardware: BladeRF 2.0 micro
"""

# ============================================================================
# IMPORTS
# ============================================================================
import sys
import logging
import os

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt

from controller.base_controller import MainController
from utils.config_manager import ConfigManager
from utils.theme_manager import ThemeManager


# ============================================================================
# LOGGING CONFIGURATION
# ============================================================================

def setup_logging() -> None:
    """
    Configures logging for field debugging.
    Logs are written to both file and console for real-time monitoring.
    """
    # Create logs directory if it doesn't exist
    os.makedirs("logs", exist_ok=True)
    
    logging.basicConfig(
        level=logging.INFO,
        #format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        format='%(asctime)s - %(levelname)s - %(name)s -  %(message)s',
        handlers=[
            logging.FileHandler('logs/sdr_analyzer.log'),
            logging.StreamHandler()
        ]
    )


def ensure_directories() -> None:
    """
    Creates required directories for the application.
    - recordings: IQ data captures
    - profiles: Exported configuration profiles
    - logs: Application logs
    - config: Configuration files
    """
    directories = [
        "recordings",   # IQ recordings storage
        "profiles",     # Exported profiles
        "logs",         # Application logs
        "config"        # Configuration files (bands.json, etc.)
    ]
    
    for directory in directories:
        os.makedirs(directory, exist_ok=True)
        logging.getLogger(__name__).info(f"📁 Directory ensured: {directory}/")


def setup_application_theme(app: QApplication) -> None:
    """
    Applies the initial theme to the application.
    Uses ThemeManager singleton to ensure consistent theming.
    """
    theme_manager = ThemeManager()
    theme_manager.apply_theme_to_app(app, 'dark')


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def main() -> None:
    """
    Main application entry point.
    
    Flow:
        1. Configure logging
        2. Create Qt application
        3. Apply theme
        4. Ensure directories exist
        5. Create main controller
        6. Create config manager with theme reference
        7. Load saved settings
        8. Show main window
        9. Run event loop
        10. Save settings on exit
    """
    # Step 1: Configure logging
    setup_logging()
    logger = logging.getLogger(__name__)
    
    try:
        # Step 2: Create Qt application
        app = QApplication(sys.argv)
        app.setApplicationName("SIMANEEM")
        app.setOrganizationName("INIDETEC DCD")
        
        # Step 3: Apply theme
        setup_application_theme(app)
        
        # Step 4: Ensure directories exist
        ensure_directories()
        
        # Step 5: Create main controller
        controller = MainController()
        logger.info(f"MainController created with theme_manager id: {id(controller.theme_manager)}")
        
        # Step 6: Create config manager (uses existing theme_manager)
        config_manager = ConfigManager(controller.theme_manager)
        logger.info(f"ConfigManager created with theme_manager id: {id(config_manager.theme_manager)}")
        
        # Step 7: Load saved settings
        config_manager.load_all_settings(controller)
        
        # Step 8: Show main window
        controller.show()
        
        logger.info("SDR Analyzer started successfully")
        
        # Step 9: Run event loop
        exit_code = app.exec_()
        
        # Step 10: Save settings on exit
        config_manager.save_all_settings(controller)
        logger.info("Configuration saved on exit")
        
        sys.exit(exit_code)
        
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()