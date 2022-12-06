import sys
import asyncio
import logging
import argparse
from pathlib import Path
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import *
from qasync import QEventLoop, asyncSlot

from ffmpeg import FFmpeg, FFmpegError

logger = logging.getLogger(__name__)


# TODO: consolidate classes?

class FFmpegInputTextEdit(QTextEdit):
    def __init__(self, title, parent, ffmpeg_obj: FFmpeg):
        super().__init__(title, parent)
        self.ffmpeg = ffmpeg_obj

        self.setAcceptDrops(True)
        self.textChanged.connect(self.update_ffmpeg_input)

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
                self.append(str_url)
            except Exception as e:
                logger.exception(e)

    def update_ffmpeg_input(self) -> None:
        logger.debug(f'FFmpegInputTextEdit text changed to: {self.toPlainText()}')

        logger.debug(f'Clearing FFmpeg inputs')
        self.ffmpeg._input_files = []

        for f in self.toPlainText().split('\n'):
            path_str = str(Path(f))
            logger.debug(f'Adding FFmpeg input: {path_str}')
            self.ffmpeg.input(path_str)


# TODO: Okay, turns out post-input arguments need to be attached to the output, not put as an option.
#       Fix that.
class FFmpegArgsEditor(QWidget):
    def __init__(self, parent, ffmpeg_obj: FFmpeg):
        super().__init__(parent)
        self.ffmpeg = ffmpeg_obj

        self.layout: QVBoxLayout | None = None
        self.arg_list: QWidget | None = None
        self.arg_list_layout: QVBoxLayout | None = None
        self.add_arg_button: QPushButton | None = None
        self.args = []
        self.init_ui()

    def init_ui(self):
        self.layout = QVBoxLayout()
        self.setLayout(self.layout)

        self.arg_list = QWidget()
        self.arg_list_layout = QVBoxLayout()
        self.arg_list.setLayout(self.arg_list_layout)
        self.layout.addWidget(self.arg_list)

        self.add_arg_button = QPushButton('Add option')
        self.add_arg_button.clicked.connect(self.add_argument)
        self.layout.addWidget(self.add_arg_button)

    def add_argument(self):
        temp = QTextEdit()
        temp.textChanged.connect(self.update_ffmpeg_args)
        self.arg_list_layout.addWidget(temp)

    def update_ffmpeg_args(self) -> None:
        logger.debug(f'Clearing FFmpeg options')
        self.ffmpeg._global_options = {}

        try:
            for i in range(self.arg_list_layout.count()):
                option: QTextEdit = self.arg_list_layout.itemAt(i).widget()
                option_text = option.toPlainText()
                logger.debug(f'Adding FFmpeg argument: {option_text}')
                key = option_text.split(' ')[0]
                if key == option_text:
                    self.ffmpeg.option(key)
                else:
                    value = option_text[len(key)+1:]
                    self.ffmpeg.option(key, value)
        except Exception as e:
            logger.exception(e)


class FFmpegOutputTextEdit(QTextEdit):
    def __init__(self, parent, ffmpeg_obj: FFmpeg):
        super().__init__(parent)
        self.ffmpeg = ffmpeg_obj

        self.setAcceptDrops(True)
        self.textChanged.connect(self.update_ffmpeg_output)

    def update_ffmpeg_output(self) -> None:
        logger.debug(f'FFmpegOutputTextEdit text changed to: {self.toPlainText()}')

        logger.debug(f'Clearing FFmpeg outputs')
        self.ffmpeg._output_files = []

        for f in self.toPlainText().split('\n'):
            path_str = str(Path(f))
            logger.debug(f'Adding FFmpeg output: {path_str}')
            self.ffmpeg.output(path_str)


class FFmpegConsoleDisplay(QScrollArea):
    def __init__(self, parent, ffmpeg_obj: FFmpeg):
        super().__init__(parent)
        self.ffmpeg = ffmpeg_obj

        self.ffmpeg.on('start',    lambda p: self.add_line('Start: ' + str(p)))
        self.ffmpeg.on('stderr',   lambda p: self.add_line('Stderr: ' + str(p)))
        self.ffmpeg.on('progress', lambda p: self.add_line('Progress: ' + str(p)))
        self.ffmpeg.on('error',    lambda p: self.add_line('Error: ' + str(p)))
        self.ffmpeg.on('completed',  lambda: self.add_line('Completed\n'))
        self.ffmpeg.on('terminated', lambda: self.add_line('Terminated\n'))

        logger.debug('Initializing FFmpegConsoleDisplay')
        self.progress_label: QLabel | None = None
        self.init_ui()

    def init_ui(self):
        self.progress_label = QLabel('--- Console ---', self)
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


class FFmpegExecuteTerminateButton(QPushButton):
    def __init__(self, parent, ffmpeg_obj: FFmpeg):
        super().__init__(parent)
        self.ffmpeg = ffmpeg_obj
        self.init_ui()

    def init_ui(self):
        self.ffmpeg.on('error', lambda p: self.reset())
        self.ffmpeg.on('completed', self.reset)
        self.ffmpeg.on('terminated', self.reset)

        self.setText('Go')
        self.clicked.connect(self.go)
        self.setStyleSheet(
            'color: #000000;' +
            'background-color: #ddffdd;'
        )

    def go(self) -> None:
        self.execute_ffmpeg()
        self.switch_to_stop_button()

    def stop(self):
        self.terminate_ffmpeg()
        self.switch_to_go_button()

    def reset(self):
        self.ffmpeg._executed = False
        self.ffmpeg._terminated = False
        self.switch_to_go_button()

    def switch_to_stop_button(self):
        self.setText('Terminate')
        self.setStyleSheet(
            'color: #000000;' +
            'background-color: #ffdddd;'
        )
        self.clicked.disconnect(self.go)
        self.clicked.connect(self.stop)

    def switch_to_go_button(self):
        self.setText('Go')
        self.setStyleSheet(
            'color: #000000;' +
            'background-color: #ddffdd;'
        )
        self.clicked.disconnect(self.stop)
        self.clicked.connect(self.go)

    @asyncSlot()
    async def execute_ffmpeg(self) -> None:
        logger.debug('Executing ffmpeg')
        try:
            await self.ffmpeg.execute()
        except Exception as e:
            logger.exception(e)

    def terminate_ffmpeg(self) -> None:
        logger.debug('Terminating ffmpeg')
        try:
            self.ffmpeg.terminate()
        except Exception as e:
            logger.exception(e)


class ProtoframeWindow(QMainWindow):
    """The base UI window of Protoframe"""

    def __init__(self, loop: QEventLoop, ffmpeg_obj: FFmpeg):
        super().__init__()
        self.ffmpeg = ffmpeg_obj

        logger.debug('Initializing ProtoframeWindow')
        self.central_widget: QWidget | None = None
        self.layout: QGridLayout | None = None
        self.drop_target_1: FFmpegInputTextEdit | None = None
        self.args_text_edit: QTextEdit | None = None
        self.output_text_edit: FFmpegOutputTextEdit | None = None
        self.go_stop_button: FFmpegExecuteTerminateButton | None = None
        self.console_display: FFmpegConsoleDisplay | None = None
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle('Protoframe')
        self.setGeometry(200, 200, 600, 400)
        self.setStyleSheet(
            'color: #ffffff;' +
            f'background-color: #222222;'
        )

        self.layout = QGridLayout()
        self.setLayout(self.layout)

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.central_widget.setLayout(self.layout)

        self.drop_target_1 = FFmpegInputTextEdit(None, self, self.ffmpeg)
        self.drop_target_1.setStyleSheet(
            'color: #000000;' +
            'background-color: #dddddd;'
        )

        self.args_text_edit = FFmpegArgsEditor(self, self.ffmpeg)
        self.args_text_edit.setStyleSheet(
            'color: #000000;' +
            'background-color: #dddddd;'
        )

        self.output_text_edit = FFmpegOutputTextEdit(self, self.ffmpeg)
        self.output_text_edit.setStyleSheet(
            'color: #000000;' +
            'background-color: #dddddd;'
        )

        self.go_stop_button = FFmpegExecuteTerminateButton(self, self.ffmpeg)

        self.console_display = FFmpegConsoleDisplay(self, self.ffmpeg)
        self.console_display.setStyleSheet(
            'color: #ffffff;' +
            'background-color: #111111;'
        )

        self.layout.addWidget(QLabel('Input(s):'), 0, 0)
        self.layout.addWidget(self.drop_target_1, 1, 0)
        self.layout.addWidget(QLabel('Arguments:'), 2, 0)
        self.layout.addWidget(self.args_text_edit, 3, 0)
        self.layout.addWidget(QLabel('Output(s):'), 4, 0)
        self.layout.addWidget(self.output_text_edit, 5, 0)

        spacer = QWidget()
        spacer.setMinimumWidth(50)
        self.layout.addWidget(spacer, 0, 1)

        self.layout.addWidget(self.go_stop_button, 1, 2)
        self.layout.addWidget(self.console_display, 5, 2)

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
            sys.exit(loop.run_forever())

    except Exception as e:
        logger.exception(e)


if __name__ == '__main__':
    main()
