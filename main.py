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
        self.input: Path = Path()
        self.globals: Dict = {}
        self.output_options: Dict = {}
        self.output: Path = Path()

    def is_valid(self) -> bool:
        logger.debug(f'FFmpegConfig validity check:')
        logger.debug(f'\tInput:  {self.input}')
        logger.debug(f'\tOutput: {self.output}')
        if not self.input.suffix or not self.output.suffix:
            logger.debug('\t✗ INVALID')
            return False
        logger.debug('\t✓ VALID')
        return True

    def give_config_to_ffmpeg(self, ffmpeg_obj: FFmpeg):
        logger.debug('Clearing FFmpeg object settings')
        ffmpeg_obj._input_files.clear()
        ffmpeg_obj._output_files.clear()
        ffmpeg_obj._global_options.clear()

        logger.debug(f'Adding input {self.input} to FFmpeg object')
        ffmpeg_obj.input(str(self.input))
        for glop in self.globals:
            logger.debug(f'Adding global option {glop} to FFmpeg object')
            ffmpeg_obj.option(glop, self.globals[glop])
        logger.debug(f'Adding output {self.output} to FFmpeg object')
        ffmpeg_obj.output(str(self.output), self.output_options)


class DragAndDropFilePicker(QWidget):
    def __init__(self, parent, existing_files_only: bool = False, on_edit: Optional[Callable] = None):
        super().__init__(parent)
        self.existing_files_only = existing_files_only
        self.on_edit = on_edit
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
            filepath = Path(dlg.selectedFiles()[0])
            logger.debug(f'File selected: {filepath}')
            self.set_label_from_path(filepath)
            if self.on_edit:
                self.on_edit(filepath)

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
        if self.on_edit:
            self.on_edit(filepath)

    def set_label_from_path(self, p: Path) -> None:
        logger.debug(f'Setting label to {p}')
        self.label.setText(p.name)


class SplitFileDisplay(QWidget):
    def __init__(self, parent, on_edit: Optional[Callable] = None):
        super().__init__(parent)
        self.on_edit = on_edit
        self.setAcceptDrops(True)

        self.layout = QHBoxLayout()
        self.setLayout(self.layout)

        self.setStyleSheet('''
            background-color: #332244;
            color: #eef8ff;
            font-family: Rubik;
            font-size: 12pt;
            text-align: center;
            border-radius: 15px;
        ''')

        self.name_layout = QStackedLayout()
        self.name_layout.setStackingMode(QStackedLayout.StackingMode.StackAll)
        self.layout.addLayout(self.name_layout)

        self.name_label = QLineEdit(self)
        self.name_label.setText('Select file...')
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_layout.addWidget(self.name_label)

        self.ext_layout = QStackedLayout()
        self.ext_layout.setStackingMode(QStackedLayout.StackingMode.StackAll)
        self.layout.addLayout(self.ext_layout)

        self.ext_label = QComboBox(self)
        self.ext_label.setEditable(True)
        self.ext_label.addItems(('.mp4', '.mp3', '.gif'))
        self.ext_layout.addWidget(self.ext_label)

        self.name_label.textEdited.connect(self._on_edit)
        self.ext_label.currentTextChanged.connect(self._on_edit)

    def set_label_from_path(self, p: Path) -> None:
        logger.debug(f'Setting label to {p}')
        self.name_label.setText(p.stem)
        self.ext_label.setCurrentText(p.suffix)

    def get_stem(self) -> str:
        return self.name_label.text()

    def get_suffix(self) -> str:
        return self.ext_label.currentText()

    def get_name(self) -> str:
        return self.get_stem() + self.get_suffix()

    def _on_edit(self, e) -> None:
        logger.debug(f'User edited output to "{self.get_name()}"')
        if self.on_edit:
            self.on_edit(self.get_name())


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


class GoodStyleSheet(Dict):
    def to_string(self):
        s = ''
        for i in self.items():
            s += f'{i[0]}: {i[1]}; '
        return s


class FFmpegGoStopButton(QWidget):
    def __init__(self, parent, on_click: Callable) -> None:
        super().__init__(parent)
        self.on_click = on_click
        self.gss = GoodStyleSheet({
            'background-color': '#114411',
            'color': '#eef8ff',
            'font-family': 'Rubik',
            'font-size': '12pt',
            'text-align': 'center',
            'border-radius': '15px',
        })
        self.setStyleSheet(self.gss.to_string())
        self.in_progress = False

        self.layout = QStackedLayout()
        self.layout.setStackingMode(QStackedLayout.StackingMode.StackAll)
        self.setLayout(self.layout)

        self.available = False
        self.unavailable_cover = QWidget()
        self.unavailable_cover_gss = GoodStyleSheet(self.gss.copy())
        self.unavailable_cover_gss['background-color'] = '#444444'
        self.opacity_effect = QGraphicsOpacityEffect()
        self.opacity_effect.setOpacity(0.5)
        self.unavailable_cover.setGraphicsEffect(self.opacity_effect)
        self.unavailable_cover.setStyleSheet(self.unavailable_cover_gss.to_string())
        self.layout.addWidget(self.unavailable_cover)

        self.label = QLabel(self)
        self.label.setText("GO")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layout.addWidget(self.label)

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        if self.available:
            if self.on_click:
                self.on_click(self.in_progress)
            self.set_in_progress_state(not self.in_progress)

    def set_in_progress_state(self, in_progress: bool) -> None:
        self.in_progress = in_progress
        logger.debug(f'Setting in-progress state to {in_progress}')
        if in_progress:
            self.label.setText("STOP")
            self.gss['background-color'] = '#441111'
        else:
            self.label.setText("GO")
            self.gss['background-color'] = '#114411'
        self.setStyleSheet(self.gss.to_string())

    def set_availability(self, availability: bool) -> None:
        logger.debug(f'Setting availability to {availability}')
        self.available = availability
        self.opacity_effect.setOpacity(
            0 if availability else 0.5
        )


class ProtoframeWindow(QMainWindow):
    """The base UI window of Protoframe"""

    def __init__(self, loop: QEventLoop, ffmpeg_obj: FFmpeg, ff_conf: FFmpegConfig):
        super().__init__()
        self.ffmpeg = ffmpeg_obj
        self.ff_conf = ff_conf

        self.presets = {
            'do nothing (copy)': {'-c': 'copy'},
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

        self.input_box = DragAndDropFilePicker(self, existing_files_only=True, on_edit=self.on_input_edit)
        self.output_box = SplitFileDisplay(self, on_edit=self.on_output_edit)

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

    def on_input_edit(self, new_path: Path) -> None:
        logger.debug(f'Setting FFConfig input to "{new_path}"')
        self.ff_conf.input = new_path

        out_path = new_path.parent / (new_path.stem + '_edit' + new_path.suffix)
        self.output_box.set_label_from_path(out_path)
        self.on_output_edit(out_path)

        self.go_stop_button.set_availability(self.ff_conf.is_valid())

    def on_output_edit(self, file_name: str | Path) -> None:
        out_path = Path()
        if self.ff_conf.output.is_file():
            out_path = self.ff_conf.output.parent / file_name
        else:
            if self.ff_conf.input.is_file():
                out_path = self.ff_conf.input.parent / file_name
            else:
                out_path /= file_name
        logger.debug(f'Setting FFConfig output to "{out_path}"')
        self.ff_conf.output = out_path

        self.go_stop_button.set_availability(self.ff_conf.is_valid())

    def reset_ffmpeg(self):
        self.go_stop_button.set_in_progress_state(False)
        self.ffmpeg._executed = False
        self.ffmpeg._terminated = False

    def on_go_stop_button_click(self, in_progress: bool) -> None:
        if not in_progress:
            self._execute_ffmpeg()
        else:
            self._terminate_ffmpeg()

    @asyncSlot()
    async def _execute_ffmpeg(self) -> None:
        logger.debug('Executing ffmpeg')
        self.ff_conf.globals['-y'] = None
        if self.preset_dropdown.currentText() != self.preset_dropdown.placeholderText():
            self.ff_conf.output_options = self.presets[self.preset_dropdown.currentText()]
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
