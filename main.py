#!/usr/bin/env python3
"""
SW TEST Automation Tool
Main entry point for the test automation application.
"""

import sys
import os
from enum import Enum
from pathlib import Path
import argparse


class ExecutionMode(Enum):
    """Execution modes for the application."""
    UI = "ui"
    AUTO = "auto"
    CHECK = "check"


class SystemConfig:
    """System configuration class."""

    def __init__(self):
        self.version = "v1.0"
        self.execution_mode = ExecutionMode.UI
        self.yaml_override = False

    def configure_from_args(self, args: argparse.Namespace) -> None:
        """Configure system from command line arguments."""
        if args.mode:
            try:
                self.execution_mode = ExecutionMode(args.mode.lower())
            except ValueError:
                print(f"Invalid execution mode: {args.mode}")
                sys.exit(1)
        self.yaml_override = args.yaml


class Application:
    """Main application class."""

    def __init__(self, config: SystemConfig):
        self.config = config

    def run(self) -> None:
        """Run the application based on configuration."""
        print("Preparing equipment for initialization, please wait while loading...\n")

        try:
            if self.config.execution_mode == ExecutionMode.UI:
                self._run_ui_mode()
            elif self.config.execution_mode == ExecutionMode.CHECK:
                self._run_check_mode()
            else:  # AUTO mode
                self._run_auto_mode()
            # Execute subsystem shutdown code upon program termination
            os._exit(0)

        except Exception as e:
            print(f"Error running application: {e}")
            sys.exit(1)

    def _run_ui_mode(self) -> None:
        """Run application in UI mode."""
        try:
            # Fix for High DPI displays
            # os.environ["QT_FONT_DPI"] = "96"

            from PySide6.QtWidgets import QApplication, QSplashScreen
            from PySide6.QtGui import QPixmap

            app = QApplication(sys.argv)

            # Show splash screen
            splash_path = Path("./static/images/loading.png")
            if splash_path.exists():
                splash = QSplashScreen(QPixmap(str(splash_path)))
                splash.show()
            else:
                splash = None
                print("Warning: Splash screen image not found")

            from Qt import MainWindow
            from Lib.Common import logging_initialize, logging_print

            # Initialize logging
            logging_initialize()
            logging_print(
                f"The program is named SW TEST Automation {self.config.version}. "
                "It provides the functions for the measurement and automation with various devices\n"
            )

            # Create and show main window
            window = MainWindow()
            if splash:
                splash.finish(window)

            # Start event loop
            sys.exit(app.exec())

        except ImportError as e:
            print(f"Failed to import required UI modules: {e}")
            print("Please ensure PySide6 and Qt modules are properly installed.")
            sys.exit(1)

    def _run_check_mode(self) -> None:
        """Run application in check mode."""
        try:
            from prereq.check_env import CheckEnv

            check_env = CheckEnv()
            check_env.run()

        except ImportError as e:
            print(f"Failed to import check environment module: {e}")
            sys.exit(1)

    def _run_auto_mode(self) -> None:
        """Run application in auto mode."""
        try:
            from Lib.Common import Configure
            from Lib.TestProcess import AutoTest

            print(
                f"The program is named SW TEST Automation {self.config.version}. "
                "It provides the functions for the measurement and automation with various devices\n"
            )

            # Determine YAML path by --yaml within git path
            yaml_path = self._get_yaml_path()

            # Initialize and run auto test
            auto_test = AutoTest(test_yaml=yaml_path)
            print(f"Current Test Environment\n{auto_test.df_inst}\n")
            auto_test.run()

        except ImportError as e:
            print(f"Failed to import required modules for auto mode: {e}")
            sys.exit(1)
        except Exception as e:
            print(f"Error in auto mode: {e}")
            sys.exit(1)

    def _get_yaml_path(self) -> str:
        """Get the appropriate YAML configuration path."""
        default_path = "./data/config/test_map.yaml"

        if not self.config.yaml_override:
            return default_path

        try:
            from Lib.Common import Configure
            git_path = Configure.set['system']['git_path']
            custom_path = os.path.join(git_path, 'test_map.yaml')
            return custom_path if os.path.exists(custom_path) else default_path

        except (ImportError, KeyError, TypeError):
            print("Warning: Could not load custom YAML path, using default")
            return default_path


def parse_arguments() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="SW TEST Automation Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument(
        'mode',
        nargs='?',
        choices=['ui', 'auto', 'check'],
        default='ui',
        help='Execution mode (default: ui)'
    )

    parser.add_argument(
        '--yaml',
        action='store_true',
        help='Use alternative YAML configuration path'
    )

    parser.add_argument(
        '--version',
        action='version',
        version='SW TEST Automation v1.0'
    )

    return parser.parse_args()


def main() -> None:
    """Main entry point."""
    try:
        # Parse command line arguments
        args = parse_arguments()

        # Create and configure system
        config = SystemConfig()
        config.configure_from_args(args)

        # Create and run application
        app = Application(config)
        app.run()

    except KeyboardInterrupt:
        print("\nApplication interrupted by user")
        sys.exit(130)  # Standard exit code for SIGINT
    except Exception as e:
        print(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
