import sys
import logging
import argparse
from pathlib import Path
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QMouseEvent
from PyQt6.QtWidgets import QApplication, QMainWindow, QPushButton, QLabel

from ffmpeg import FFmpeg

logger = logging.getLogger(__name__)


class FFmpegGoButton(QPushButton):
    # TODO: Add disable logic for when executing ffmpeg won't work
    def __init__(self, title, parent, ffmpeg_obj: FFmpeg):
        super().__init__(title, parent)
        self.ffmpeg = ffmpeg_obj

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        self.ffmpeg.output(Path('./output.mp4'))
        logger.debug('Executing ffmpeg')
        result = self.ffmpeg.run()
        logger.debug(result)


class FFmpegInputDropTarget(QPushButton):
    def __init__(self, title, parent, ffmpeg_obj: FFmpeg):
        super().__init__(title, parent)
        self.setAcceptDrops(True)
        self.ffmpeg = ffmpeg_obj

    def dragEnterEvent(self, a0: QDragEnterEvent) -> None:
        has_urls = a0.mimeData().hasUrls()
        logger.debug(f'dragEnterEvent: {a0.mimeData().text()}')
        logger.debug(f'dragEnterEvent: hasUrls == {has_urls}')
        if has_urls:
            a0.accept()
        else:
            a0.ignore()

    def dropEvent(self, a0: QDropEvent) -> None:
        logger.debug(f'dropEvent initiated')
        for q_url in a0.mimeData().urls():
            try:
                str_url = q_url.toLocalFile()
                logger.debug(f'Adding input url {str_url}')
                self.setText(str_url)
                self.ffmpeg.input(Path(str_url))
            except Exception as e:
                logger.exception(e)


class ProtoframeWindow(QMainWindow):

    """The base UI window of Protoframe"""

    def __init__(self, ffmpeg_obj: FFmpeg):
        super().__init__()
        self.ffmpeg = ffmpeg_obj

        logger.debug('Initializing UI')
        self.drop_target_1 = None
        self.go_button = None
        self.progress_label = None
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle('Protoframe')
        self.setGeometry(200, 200, 600, 320)
        self.setStyleSheet(
            f'background-color: #222222;'
        )

        logger.debug('Initializing drop_target_1')
        self.drop_target_1 = FFmpegInputDropTarget("Drop Target 1", self, self.ffmpeg)
        self.drop_target_1.setGeometry(20, 20, 560, 100)
        self.drop_target_1.setStyleSheet(
            f'background-color: #dddddd;'
        )

        logger.debug('Initializing go_button')
        self.go_button = FFmpegGoButton("Go", self, self.ffmpeg)
        self.go_button.setGeometry(20, 120, 100, 50)
        self.go_button.setStyleSheet(
            f'background-color: #ddffdd;'
        )

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

        logger.debug('Initializing FFmpeg object')
        ffmpeg = FFmpeg(Path('ffmpeg.exe'))

        # Start app with arguments from command line
        logger.debug(f'Initializing QApplication')
        app = QApplication(sys.argv)

        logger.debug(f'Initializing ProtoframeWindow')
        pfw = ProtoframeWindow(ffmpeg)

        # Enter main GUI update loop
        logger.info(f'Entering GUI update loop')
        app.exec()

    except Exception as e:
        logger.exception(e)

    logger.info(f'Exiting Protoframe')
    sys.exit()


if __name__ == '__main__':
    main()
