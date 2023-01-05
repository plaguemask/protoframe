import sys
import asyncio
import logging
import argparse
from enum import Enum
from typing import List, Dict, Callable, Optional
from pathlib import Path
from PyQt6.QtCore import *
from PyQt6.QtGui import *
from PyQt6.QtWidgets import *
from qasync import QEventLoop, asyncSlot

from ffmpeg import FFmpeg, FFmpegError

logger = logging.getLogger(__name__)


def local_file_q_url_to_path(q_url: QUrl) -> Path:
    return Path(q_url.toString(QUrl.UrlFormattingOption.PreferLocalFile))


path = local_file_q_url_to_path


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


class DragAndDropFilePicker(QWidget):
    def __init__(self, parent, existing_files_only: bool = False, on_file_drop: Optional[Callable] = None):
        super().__init__(parent)
        self.existing_files_only = existing_files_only
        self.on_file_drop = on_file_drop
        self.setAcceptDrops(True)

        self.layout = QStackedLayout()
        self.layout.setStackingMode(QStackedLayout.StackingMode.StackAll)
        self.setLayout(self.layout)

        self.setStyleSheet('''
            background-color: #332244;
            color: #eef8ff;
            font-family: Rubik;
            font-size: 12pt;
            text-align: center;
            border-radius: 15px;
        ''')

        self.label = QLabel(self)
        self.label.setText('Select file...')
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layout.addWidget(self.label)

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        logger.debug(f'mouseReleaseEvent initiated')
        dlg = QFileDialog()
        dlg.setFileMode(
            QFileDialog.FileMode.ExistingFile if self.existing_files_only else QFileDialog.FileMode.AnyFile
        )

        logger.debug(f'Executing file dialog')
        if dlg.exec():
            filename = dlg.selectedFiles()[0]
            logger.debug(f'File selected: {filename}')
            self.label.setText(filename)

    def dragEnterEvent(self, e: QDragEnterEvent) -> None:
        data = e.mimeData()
        if data.hasUrls() and data.urls()[0].isLocalFile():
            e.accept()
        else:
            e.ignore()

    def dropEvent(self, e: QDropEvent) -> None:
        logger.debug(f'dropEvent initiated')
        q_url = e.mimeData().urls()[0]
        filepath = path(q_url)
        logger.debug(f'File dropped: {q_url}')
        self.set_label_from_path(filepath)
        if self.on_file_drop:
            self.on_file_drop(filepath)

    def set_label_from_path(self, p: Path) -> None:
        logger.debug(f'Setting label to {p}')
        self.label.setText(p.name)


class PresetDropdown(QComboBox):
    def __init__(self, parent):
        super().__init__(parent)
        self.setStyleSheet('''
            background-color: #111144;
            color: #eef8ff;
            font-family: Rubik;
            font-size: 12pt;
            text-align: center;
            border-radius: 15px;
        ''')
        self.setPlaceholderText('what do?')
        self.setMinimumWidth(200)


class FFmpegConsoleDisplay(QScrollArea):
    def __init__(self, parent):
        super().__init__(parent)
        self.setStyleSheet('''
            color: #dddddd;
            background-color: #444444;
            border-radius: 5px;
        ''')

        logger.debug('Initializing FFmpegConsoleDisplay')
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


class FFmpegGoStopButton(QWidget):
    def __init__(self, parent, on_click: Callable):
        super().__init__(parent)
        self.on_click_func = on_click
        self.setStyleSheet('''
            background-color: #114411;
            color: #eef8ff;
            font-family: Rubik;
            font-size: 12pt;
            text-align: center;
            border-radius: 15px;
        ''')
        self.activated = False

        self.layout = QStackedLayout()
        self.layout.setStackingMode(QStackedLayout.StackingMode.StackAll)
        self.setLayout(self.layout)

        self.label = QLabel(self)
        self.label.setText("GO")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layout.addWidget(self.label)

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        if self.activated:
            self.activated = False
            self.switch_to_stop_button()
        else:
            self.activated = True
            self.switch_to_go_button()
        self.on_click_func(self.activated)

    def switch_to_stop_button(self):
        self.label.setText("STOP")
        self.setStyleSheet('''
            background-color: #441111;
            color: #eef8ff;
            font-family: Rubik;
            font-size: 12pt;
            text-align: center;
            border-radius: 15px;
        ''')

    def switch_to_go_button(self):
        self.label.setText("GO")
        self.setStyleSheet('''
            background-color: #114411;
            color: #eef8ff;
            font-family: Rubik;
            font-size: 12pt;
            text-align: center;
            border-radius: 15px;
        ''')


class ProtoframeWindow(QMainWindow):
    """The base UI window of Protoframe"""

    def __init__(self, loop: QEventLoop, ffmpeg_obj: FFmpeg, ff_conf: FFmpegConfig):
        super().__init__()
        self.ffmpeg = ffmpeg_obj
        self.ff_conf = ff_conf

        self.presets = {
            'SUPER COMPRESS': {'-crf': '50'},
            'reverse': {'-vf': 'reverse', '-af': 'areverse'},
            'speed up 2x': {'-vf': 'setpts=0.5*PTS'},
            'HQ GIF': {'-vf': 'split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse', 'loop': '0'}
        }

        logger.debug('Initializing ProtoframeWindow')
        self.central_widget: QWidget | None = None
        self.layout: QGridLayout | None = None
        self.input_box: DragAndDropFilePicker | None = None
        self.preset_dropdown: PresetDropdown | None = None
        self.output_box: DragAndDropFilePicker | None = None
        self.go_stop_button: FFmpegGoStopButton | None = None
        self.console_display: FFmpegConsoleDisplay | None = None
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle('Protoframe')
        self.setGeometry(200, 200, 600, 400)
        self.setStyleSheet(
            'color: #ffffff;' +
            f'background-color: #0a0300;'
        )

        self.layout = QGridLayout()
        self.setLayout(self.layout)

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.central_widget.setLayout(self.layout)

        self.input_box = DragAndDropFilePicker(self, existing_files_only=True,
                                               on_file_drop=self.update_output_based_on_new_input)
        self.output_box = DragAndDropFilePicker(self, existing_files_only=False)

        self.preset_dropdown = PresetDropdown(self)
        for preset in self.presets:
            self.preset_dropdown.addItem(preset)

        self.go_stop_button = FFmpegGoStopButton(self, self.on_go_stop_button_click)

        self.console_display = FFmpegConsoleDisplay(self)

        self.layout.addWidget(QLabel('Input:'), 0, 0)
        self.layout.addWidget(self.input_box, 1, 0)
        self.layout.addWidget(self.preset_dropdown, 1, 1)
        self.layout.addWidget(QLabel('Output:'), 0, 2)
        self.layout.addWidget(self.output_box, 1, 2)

        spacer = QWidget()
        spacer.setMinimumHeight(50)
        self.layout.addWidget(spacer, 2, 0)

        self.layout.addWidget(self.go_stop_button, 3, 0, 1, 3)
        self.layout.addWidget(self.console_display, 4, 0, 1, 3)

        self.ffmpeg.on('error', lambda p: self.reset_ffmpeg())
        self.ffmpeg.on('completed',       self.reset_ffmpeg)
        self.ffmpeg.on('terminated',      self.reset_ffmpeg)

        self.ffmpeg.on('start',    lambda p: self.console_display.add_line('Start: ' + str(p)))
        self.ffmpeg.on('stderr',   lambda p: self.console_display.add_line('Stderr: ' + str(p)))
        self.ffmpeg.on('progress', lambda p: self.console_display.add_line('Progress: ' + str(p)))
        self.ffmpeg.on('error',    lambda p: self.console_display.add_line('Error: ' + str(p)))
        self.ffmpeg.on('completed',  lambda: self.console_display.add_line('Completed\n'))
        self.ffmpeg.on('terminated', lambda: self.console_display.add_line('Terminated\n'))

        logger.debug('Showing ProtoframeWindow')
        self.show()

    def update_output_based_on_new_input(self, new_path: Path) -> None:
        out_path = new_path.parent / (new_path.stem + '_edit' + new_path.suffix)
        self.output_box.set_label_from_path(out_path)

    def reset_ffmpeg(self):
        self.ffmpeg._executed = False
        self.ffmpeg._terminated = False

    def on_go_stop_button_click(self, activated: bool) -> None:
        if activated:
            self._execute_ffmpeg()
        else:
            self._terminate_ffmpeg()

    @asyncSlot()
    async def _execute_ffmpeg(self) -> None:
        logger.debug('Executing ffmpeg')
        self.ff_conf.globals['-y'] = None
        self.ff_conf.inputs.append(Path(self.input_box.label.text()))
        if self.preset_dropdown.currentText() != self.preset_dropdown.placeholderText():
            self.ff_conf.output_options = self.presets[self.preset_dropdown.currentText()]
        self.ff_conf.output = Path(self.output_box.label.text())
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
