import sys
import asyncio
import logging
import argparse
from typing import List, Dict, Tuple, Optional
from pathlib import Path
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import *
from qasync import QEventLoop, asyncSlot

from ffmpeg import FFmpeg, FFmpegError

logger = logging.getLogger(__name__)


class FFmpegConfig:
    def __init__(self):
        self.inputs: List[Path] = []
        self.globals: Dict = {}
        self.output_options: Dict = {}
        self.output: Path = Path()

    def give_config_to_ffmpeg(self, ffmpeg_obj: FFmpeg):
        logger.debug('Clearing FFmpeg object settings')
        ffmpeg_obj._input_files.clear()
        ffmpeg_obj._output_files.clear()
        ffmpeg_obj._global_options.clear()

        for p in self.inputs:
            logger.debug(f'Adding input {p} to FFmpeg object')
            ffmpeg_obj.input(str(p))
        for glop in self.globals:
            logger.debug(f'Adding global option {glop} to FFmpeg object')
            ffmpeg_obj.option(glop, self.globals[glop])
        logger.debug(f'Adding output {self.output} to FFmpeg object')
        ffmpeg_obj.output(str(self.output), self.output_options)


# TODO: consolidate classes?

class FFmpegInputTextEdit(QTextEdit):
    def __init__(self, title, parent, ff_conf: FFmpegConfig):
        super().__init__(title, parent)
        self.ff_conf = ff_conf

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
        self.ff_conf.inputs.clear()

        for f in self.toPlainText().split('\n'):
            path = Path(f)
            logger.debug(f'Adding FFmpeg input: {path}')
            self.ff_conf.inputs.append(path)


class FFmpegOptionCheckBox(QCheckBox):
    def __init__(self, text: str, parent, option: str, ff_conf: FFmpegConfig):
        super().__init__(text, parent)

        self.ff_conf = ff_conf
        self.option = option
        self.stateChanged.connect(self.on_changed)

    def on_changed(self):
        logger.debug(f'State changed for "{self.option}" option to {self.isChecked()}')
        if self.isChecked():
            self.ff_conf.globals[self.option] = None
        else:
            self.ff_conf.globals.pop(self.option)


class FFmpegDualOptionCheckBox(QCheckBox):
    def __init__(self, text: str, parent, option_unchecked: str, option_checked: str, ff_conf: FFmpegConfig):
        super().__init__(text, parent)

        self.ff_conf = ff_conf
        self.op_unchecked = option_unchecked
        self.op_checked = option_checked
        self.stateChanged.connect(self.on_changed)

        self.ff_conf.globals[self.op_unchecked] = None

    def on_changed(self):
        if self.isChecked():
            logger.debug(f'State changed from "{self.op_unchecked}" option to "{self.op_checked}"')
            self.ff_conf.globals.pop(self.op_unchecked)
            self.ff_conf.globals[self.op_checked] = None
        else:
            logger.debug(f'State changed from "{self.op_checked}" option to "{self.op_unchecked}"')
            self.ff_conf.globals.pop(self.op_checked)
            self.ff_conf.globals[self.op_unchecked] = None


class FFmpegArgsEditor(QWidget):
    def __init__(self, parent, ff_conf: FFmpegConfig):
        super().__init__(parent)
        self.ff_conf = ff_conf

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
        logger.debug(f'Clearing FFmpeg output options')
        self.ff_conf.output_options.clear()

        try:
            for i in range(self.arg_list_layout.count()):
                option: QTextEdit = self.arg_list_layout.itemAt(i).widget()
                option_text = option.toPlainText()
                if not option_text:
                    continue

                split = option_text.split(' ', maxsplit=1)
                key = split[0]
                if len(split) > 1 and split[1]:
                    value = split[1]
                else:
                    value = None

                logger.debug(f'Adding FFmpeg output argument: "{key}", "{value}"')
                self.ff_conf.output_options[key] = value
        except Exception as e:
            logger.exception(e)


class FFmpegOutputTextEdit(QTextEdit):
    def __init__(self, parent, ff_conf: FFmpegConfig):
        super().__init__(parent)
        self.ff_conf = ff_conf

        self.setAcceptDrops(True)
        self.textChanged.connect(self.update_ffmpeg_output)

    def update_ffmpeg_output(self) -> None:
        logger.debug(f'FFmpegOutputTextEdit text changed to: {self.toPlainText()}')
        path = Path(self.toPlainText())
        logger.debug(f'Adding FFmpeg output: {path}')
        self.ff_conf.output = path


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


class FFmpegGoStopButton(QPushButton):
    def __init__(self, parent, ff_conf: FFmpegConfig, ffmpeg_obj: FFmpeg):
        super().__init__(parent)
        self.ffmpeg = ffmpeg_obj
        self.ff_conf = ff_conf
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
        self._execute_ffmpeg()
        self.switch_to_stop_button()

    def stop(self):
        self._terminate_ffmpeg()
        self.switch_to_go_button()

    def reset(self):
        self.ffmpeg._executed = False
        self.ffmpeg._terminated = False
        self.switch_to_go_button()

    def switch_to_stop_button(self):
        self.setText('Stop')
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
    async def _execute_ffmpeg(self) -> None:
        logger.debug('Executing ffmpeg')
        self.ff_conf.give_config_to_ffmpeg(self.ffmpeg)
        try:
            await self.ffmpeg.execute()
        except Exception as e:
            logger.exception(e)

    def _terminate_ffmpeg(self) -> None:
        logger.debug('Terminating ffmpeg')
        try:
            self.ffmpeg.terminate()
        except Exception as e:
            logger.exception(e)


class ProtoframeWindow(QMainWindow):
    """The base UI window of Protoframe"""

    def __init__(self, loop: QEventLoop, ffmpeg_obj: FFmpeg, ff_conf: FFmpegConfig):
        super().__init__()
        self.ffmpeg = ffmpeg_obj
        self.ff_conf = ff_conf

        logger.debug('Initializing ProtoframeWindow')
        self.central_widget: QWidget | None = None
        self.layout: QGridLayout | None = None
        self.drop_target_1: FFmpegInputTextEdit | None = None
        self.args_text_edit: QTextEdit | None = None
        self.output_text_edit: FFmpegOutputTextEdit | None = None
        self.overwrite_checkbox: FFmpegOptionCheckBox | None = None
        self.go_stop_button: FFmpegGoStopButton | None = None
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

        self.drop_target_1 = FFmpegInputTextEdit(None, self, self.ff_conf)
        self.drop_target_1.setStyleSheet(
            'color: #000000;' +
            'background-color: #dddddd;'
        )

        self.args_text_edit = FFmpegArgsEditor(self, self.ff_conf)
        self.args_text_edit.setStyleSheet(
            'color: #000000;' +
            'background-color: #dddddd;'
        )

        self.output_text_edit = FFmpegOutputTextEdit(self, self.ff_conf)
        self.output_text_edit.setStyleSheet(
            'color: #000000;' +
            'background-color: #dddddd;'
        )

        self.overwrite_checkbox = FFmpegDualOptionCheckBox('Overwrite files?', self, 'n', 'y', self.ff_conf)

        self.go_stop_button = FFmpegGoStopButton(self, self.ff_conf, self.ffmpeg)

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

        self.layout.addWidget(self.overwrite_checkbox, 1, 2)
        self.layout.addWidget(self.go_stop_button, 3, 2)
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
        ff_conf = FFmpegConfig()
        ffmpeg = FFmpeg(str(Path('ffmpeg.exe')))

        # Start app with arguments from command line
        logger.debug(f'Initializing QApplication')
        app = QApplication(sys.argv)
        loop = QEventLoop(app)
        asyncio.set_event_loop(loop)

        pfw = ProtoframeWindow(loop, ffmpeg, ff_conf)

        # Enter main GUI update loop
        logger.info(f'Entering GUI update loop')
        pfw.show()
        with loop:
            sys.exit(loop.run_forever())

    except Exception as e:
        logger.exception(e)


if __name__ == '__main__':
    main()
