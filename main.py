import os
import sys
import logging
import argparse
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget


logger = logging.getLogger(__name__)


class ProtoframeWindow(QMainWindow):

    """The base UI window of Protoframe"""

    def __init__(self):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.init_ui()

    def init_ui(self):
        logger.debug('Initializing UI')

        self.setWindowTitle('Protoframe')

        logger.debug('Showing ProtoframeWindow')
        self.show()


def main() -> None:
    try:
        # Defaults for when no command line arguments are given
        log_path = 'protoframe.log'
        config_path = 'config.ini'

        # Parse command line arguments
        user_cmd_args = sys.argv[1:]
        if user_cmd_args:
            logger.debug(f'Additional command line arguments given: {user_cmd_args}')
            parser = argparse.ArgumentParser(
                description='Protoframe: An FFmpeg GUI that does exactly what you want it to.'
            )
            parser.add_argument('--configfile', type=str, help='Path to configuration file')
            parser.add_argument('--logfile', type=str, help='Path to log file')
            args = parser.parse_args()

            if args.configfile:
                logger.debug(f'Setting config file to "{args.configfile}"')
                config_path = args.configfile
            if args.logfile:
                logger.debug(f'Setting log file to "{args.logfile}"')
                log_path = args.logfile

        # Configure logging
        logging.basicConfig(filename=log_path,
                            filemode='w',
                            encoding='utf-8',
                            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                            level=logging.DEBUG)

        # Load config
        # TODO: Parse configurations

        # Start app with arguments from command line
        logger.debug(f'Initializing QApplication')
        app = QApplication(sys.argv)

        logger.debug(f'Initializing ProtocommWindow')
        pcw = ProtoframeWindow()

        # Enter main GUI update loop
        logger.info(f'Entering GUI update loop')
        app.exec()

    except Exception as e:
        logger.exception(e)

    logger.info(f'Exiting Protoframe')
    sys.exit()


if __name__ == '__main__':
    main()
