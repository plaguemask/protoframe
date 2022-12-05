import sys
import asyncio
import logging
import argparse
from pathlib import Path
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import QApplication, QMainWindow, QPushButton, QScrollArea, QTextEdit, QLabel
from qasync import QEventLoop, asyncSlot

from ffmpeg import FFmpeg, FFmpegError

logger = logging.getLogger(__name__)


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
                self.ffmpeg.input(str(Path(str_url)))
            except Exception as e:
                logger.exception(e)


class FFmpegOutputTextEdit(QTextEdit):
    def __init__(self, parent, ffmpeg_obj: FFmpeg):
        super().__init__(parent)
        self.ffmpeg = ffmpeg_obj
        self.textChanged.connect(self.update_ffmpeg_output)

    def update_ffmpeg_output(self) -> None:
        logger.debug(f'FFmpegOutputTextEdit text changed to: {self.toPlainText()}')

        self.ffmpeg._output_files = []
        path_str = str(Path(self.toPlainText()))
        logger.debug(f'Setting FFmpeg output to: {path_str}')
        self.ffmpeg.output(path_str)


class FFmpegConsoleDisplay(QScrollArea):
    def __init__(self, parent, ffmpeg_obj: FFmpeg):
        super().__init__(parent)
        self.ffmpeg = ffmpeg_obj

        self.ffmpeg.on('start',    lambda p: self.add_line(str(p)))
        self.ffmpeg.on('stderr',   lambda p: self.add_line(str(p)))
        self.ffmpeg.on('progress', lambda p: self.add_line(str(p)))
        self.ffmpeg.on('error',    lambda p: self.add_line(str(p)))
        self.ffmpeg.on('completed',  lambda: self.add_line('Completed\n'))
        self.ffmpeg.on('terminated', lambda: self.add_line('Terminated\n'))

        logger.debug('Initializing FFmpegConsoleDisplay')
        self.progress_label: QLabel | None = None
        self.init_ui()

    def init_ui(self):
        self.progress_label = QLabel('--- Output ---', self)
        self.progress_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.progress_label.setWordWrap(True)

        self.setWidget(self.progress_label)
        self.setWidgetResizable(True)

        self.verticalScrollBar().rangeChanged.connect(self.scroll_to_bottom)

    def add_line(self, text: str):
        logger.debug(f'Adding line to progress_label: {text}')
        old_text = self.progress_label.text()
        self.progress_label.setText(old_text + '\n' + text)

    def scroll_to_bottom(self):
        logger.debug('Scrolling progress_area to bottom')
        v_scroll_bar = self.verticalScrollBar()
        scroll_to_bottom_value = v_scroll_bar.maximum()
        v_scroll_bar.setValue(scroll_to_bottom_value)


class ProtoframeWindow(QMainWindow):
    """The base UI window of Protoframe"""

    def __init__(self, loop: QEventLoop, ffmpeg_obj: FFmpeg):
        super().__init__()
        self.ffmpeg = ffmpeg_obj

        logger.debug('Initializing ProtoframeWindow')
        self.drop_target_1: FFmpegInputDropTarget | None = None
        self.output_text_edit: FFmpegOutputTextEdit | None = None
        self.go_button: QPushButton | None = None
        self.console_display: FFmpegConsoleDisplay | None = None
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle('Protoframe')
        self.setGeometry(200, 200, 600, 400)
        self.setStyleSheet(
            f'background-color: #222222;'
        )

        logger.debug('Initializing drop_target_1')
        self.drop_target_1 = FFmpegInputDropTarget("Drop Target 1", self, self.ffmpeg)
        self.drop_target_1.setGeometry(20, 20, 560, 100)
        self.drop_target_1.setStyleSheet(
            f'background-color: #dddddd;'
        )

        # TODO: Arguments?

        logger.debug('Initializing go_button')
        self.go_button = QPushButton('Go', self)
        self.go_button.setGeometry(20, 120, 100, 50)
        self.go_button.setStyleSheet(
            f'background-color: #ddffdd;'
        )
        self.go_button.clicked.connect(self.execute_ffmpeg)

        logger.debug('Initializing progress_label')
        self.progress_label = QLabel('--- Output ---', self)
        self.progress_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.progress_label.setWordWrap(True)

        self.console_display = FFmpegConsoleDisplay(self, self.ffmpeg)
        self.console_display.setGeometry(20, 200, 560, 100)
        self.console_display.setStyleSheet(
            'color: #eeeeee;' +
            'background-color: #111111;'
        )

        self.output_text_edit = FFmpegOutputTextEdit(self, self.ffmpeg)
        self.output_text_edit.setGeometry(20, 320, 200, 40)
        self.output_text_edit.setStyleSheet(
            'color: #111111;' +
            'background-color: #eeeeee;'
        )

        logger.debug('Showing ProtoframeWindow')
        self.show()

    @asyncSlot()
    async def execute_ffmpeg(self) -> None:
        logger.debug('Executing ffmpeg')
        await self.ffmpeg.execute()


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
        # TODO: Parse CLI configurations

        logger.debug('Initializing FFmpeg object')
        ffmpeg = FFmpeg(str(Path('ffmpeg.exe')))

        # Start app with arguments from command line
        logger.debug(f'Initializing QApplication')
        app = QApplication(sys.argv)
        loop = QEventLoop(app)
        asyncio.set_event_loop(loop)

        logger.debug(f'Initializing ProtoframeWindow')
        pfw = ProtoframeWindow(loop, ffmpeg)

        # Enter main GUI update loop
        logger.info(f'Entering GUI update loop')
        pfw.show()
        with loop:
            loop.run_forever()

    except Exception as e:
        logger.exception(e)

    logger.info(f'Exiting Protoframe')
    sys.exit()


if __name__ == '__main__':
    main()
