import sys
import asyncio
import logging
import argparse
from typing import Dict, Callable, Optional, Tuple
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


class GoodStyleSheet(Dict):
    def to_string(self):
        s = ''
        for i in self.items():
            s += f'{i[0]}: {i[1]}; '
        return s


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


class DragAndDropFilePicker(QLabel):
    def __init__(self, parent, get_directory: Callable, on_edit: Optional[Callable] = None):
        super().__init__(parent)
        self.on_edit = on_edit
        self.get_directory = get_directory
        self.setAcceptDrops(True)
        self.setStyleSheet('''
            background-color: #eeaaff;
            color: #332244;
            text-align: center;
            border-radius: 15px;
        ''')
        self.setText('Drop input file here\nor click to browse...')
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumWidth(250)
        self.setMargin(10)
        self.setWordWrap(True)

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        logger.debug(f'mouseReleaseEvent initiated')
        try:
            directory = str(self.get_directory())
            dlg = QFileDialog(self, 'Choose input file', directory, '')
            dlg.setFileMode(QFileDialog.FileMode.ExistingFile)
            logger.debug(f'Executing file dialog at "{directory}"')
            if dlg.exec():
                filepath = Path(dlg.selectedFiles()[0])
                logger.debug(f'File selected: {filepath}')
                self.set_label_from_path(filepath)
                if self.on_edit:
                    self.on_edit(filepath)
        except Exception as e:
            logger.exception(e)

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
        self.setText(p.name)


class LockableComboBox(QComboBox):
    def __init__(self, parent, locked_style: GoodStyleSheet):
        super().__init__(parent)
        self.locked_style: GoodStyleSheet = locked_style
        self._unlocked_style: str = ''

    def changeEvent(self, e: QEvent) -> None:
        if e.type() == QEvent.Type.EnabledChange:
            if not self.isEnabled():
                self._unlocked_style = self.styleSheet()
                self.setStyleSheet(self.locked_style.to_string())
                return
            self.setStyleSheet(self._unlocked_style)


class SplitFileDisplay(QWidget):
    def __init__(self, parent, on_edit: Optional[Callable] = None):
        super().__init__(parent)
        self.on_edit = on_edit
        self.setAcceptDrops(True)
        self.setStyleSheet('''
            background-color: #eeaaff;
            color: #332244;
            text-align: center;
            border-radius: 15px;
        ''')

        self.layout = QHBoxLayout()
        self.setLayout(self.layout)

        self.name_label = QLineEdit(self)
        self.name_label.setText('')
        self.name_label.setMinimumWidth(200)
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_label.setStyleSheet('''
            background-color: #221133;
            color: #eeaaff;
            border: 2px solid #eeaaff;
        ''')
        self.layout.addWidget(self.name_label)

        self.ext_label = LockableComboBox(self, locked_style=GoodStyleSheet({
            'background-color': '#ddccee',
            'color': '#554f5b',
        }))
        self.ext_label.setFixedWidth(100)
        self.ext_label.setEditable(True)
        self.ext_label.addItems(('.mp4', '.mp3', '.gif'))
        self.layout.addWidget(self.ext_label)

        self.name_label.textEdited.connect(self._on_edit)
        self.ext_label.currentTextChanged.connect(self._on_edit)

    def set_label_from_path(self, p: Path) -> None:
        logger.debug(f'Setting label to {p}')
        self.name_label.setText(p.stem)
        if self.ext_label.isEnabled():
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


class FFmpegConsoleDisplay(QScrollArea):
    def __init__(self, parent):
        super().__init__(parent)
        self.setStyleSheet('''
            color: #dddddd;
            background-color: #444444;
            border-radius: 5px;
            font-size: 12pt;
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
    STOP_COLOR = '#dd8888'
    GO_COLOR = '#aaeeaa'

    def __init__(self, parent, on_click: Callable) -> None:
        super().__init__(parent)
        self.on_click = on_click
        self.gss = GoodStyleSheet({
            'background-color': self.GO_COLOR,
            'color': '#000000',
            'font-size': '32pt',
            'font-style': 'bold',
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
        self.unavailable_cover_gss['background-color'] = '#666'
        self.opacity_effect = QGraphicsOpacityEffect()
        self.opacity_effect.setOpacity(0.8)
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
            self.gss['background-color'] = self.STOP_COLOR
        else:
            self.label.setText("GO")
            self.gss['background-color'] = self.GO_COLOR
        self.setStyleSheet(self.gss.to_string())

    def set_availability(self, availability: bool) -> None:
        logger.debug(f'Setting availability to {availability}')
        self.available = availability
        self.opacity_effect.setOpacity(
            0 if availability else 0.7
        )


class Preset:
    def __init__(self, name: str, args: Dict, locked_output_type: Optional[str] = None):
        self.name = name
        self.args = args
        self.locked_output_type = locked_output_type


class PresetDropdown(QComboBox):
    def __init__(self, parent, presets: Tuple[Preset, ...]):
        super().__init__(parent)
        self.setStyleSheet('''
            background-color: #eeaaff;
            color: #332244;
            text-align: center;
            border-radius: 15px;
        ''')
        self.setMinimumWidth(220)

        self.presets = presets
        for p in presets:
            self.addItem(p.name)

    def get_current_preset(self) -> Preset:
        return self.presets[self.currentIndex()]


class ProtoframeWindow(QMainWindow):
    """The base UI window of Protoframe"""

    def __init__(self, loop: QEventLoop, ffmpeg_obj: FFmpeg, ff_conf: FFmpegConfig):
        super().__init__()
        self.loop = loop
        self.ffmpeg = ffmpeg_obj
        self.ff_conf = ff_conf

        self.gss = GoodStyleSheet({
            'color': 'white',
            'background-color': '#0a0300',
            'font-family': 'Rubik',
            'font-size': '16pt',
        })

        self.presets = (
            Preset('Default settings', {}),
            Preset('Do nothing (copy)', {'-c': 'copy'}),
            Preset('Remove audio', {'-c': 'copy', '-an': None}),
            Preset('SUPER COMPRESS', {'-crf': '50', '-b:a': '32k'}),
            Preset('Reverse', {'-vf': 'reverse', '-af': 'areverse'}),
            Preset('Speed up 2x', {'-vf': 'setpts=0.5*PTS', '-af': 'atempo=2.0'}),
            Preset('HQ GIF', {'-vf': 'split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse', 'loop': '0'},
                   locked_output_type='.gif'),
        )

        logger.debug('Initializing ProtoframeWindow')
        self.central_widget: QWidget
        self.layout: QGridLayout
        self.top_row: QHBoxLayout
        self.bottom_row: QHBoxLayout

        self.input_box: DragAndDropFilePicker
        self.preset_dropdown: PresetDropdown
        self.output_box: DragAndDropFilePicker
        self.go_stop_button: FFmpegGoStopButton
        self.console_display: FFmpegConsoleDisplay
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle('Protoframe')
        self.setStyleSheet(self.gss.to_string())

        # Widgets

        self.central_widget = QWidget(self)
        self.setCentralWidget(self.central_widget)

        self.input_box = DragAndDropFilePicker(self, get_directory=self.get_directory, on_edit=self.on_input_edit)
        self.input_box.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.output_box = SplitFileDisplay(self, on_edit=self.on_output_edit)

        self.preset_dropdown = PresetDropdown(self, presets=self.presets)
        self.preset_dropdown.activated.connect(lambda index: self.on_preset_edit(self.presets[index]))

        self.go_stop_button = FFmpegGoStopButton(self, on_click=self.on_go_stop_button_click)
        self.console_display = FFmpegConsoleDisplay(self)

        arrow_gss = '''
            color: white;
            font-size: 48pt;
            font-style: bold;
            text-align: center;
        '''
        right_arrow_label = QLabel('🡆')
        right_arrow_label.setStyleSheet(arrow_gss)
        right_arrow_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right_arrow_label_2 = QLabel('🡆')
        right_arrow_label_2.setStyleSheet(arrow_gss)
        right_arrow_label_2.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Layouts

        self.top_row = QHBoxLayout()
        self.top_row.addWidget(self.input_box, stretch=1)
        self.top_row.addWidget(right_arrow_label)
        self.top_row.addWidget(self.preset_dropdown, stretch=1)
        self.top_row.addWidget(right_arrow_label_2)
        self.top_row.addWidget(self.output_box, stretch=1)

        spacer = QWidget()
        spacer.setMinimumHeight(20)

        self.bottom_row = QHBoxLayout()
        self.bottom_row.addWidget(self.go_stop_button, stretch=1)
        self.bottom_row.addWidget(self.console_display, stretch=3)

        self.layout = QVBoxLayout()
        self.layout.setContentsMargins(20, 20, 20, 20)
        self.layout.addLayout(self.top_row)
        self.layout.addWidget(spacer)
        self.layout.addLayout(self.bottom_row)

        self.central_widget.setLayout(self.layout)

        # Triggers

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

    def closeEvent(self, *args, **kwargs):
        super().closeEvent(*args, **kwargs)
        logger.debug('Closing GUI event loop')
        self.loop.close()

    def get_directory(self) -> Path:
        return self.ff_conf.input.parent

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

    def on_preset_edit(self, selected: Preset) -> None:
        logger.debug(f'User selected preset "{selected.name}"')

        if selected.locked_output_type:
            self.output_box.ext_label.setEnabled(False)
            self.output_box.ext_label.setCurrentText(selected.locked_output_type)
        else:
            self.output_box.ext_label.setEnabled(True)

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
        self.ff_conf.output_options = self.preset_dropdown.get_current_preset().args
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
        logger.debug(f'Entering GUI update loop')
        pfw.show()
        with loop:
            sys.exit(loop.run_forever())

    except Exception as e:
        logger.exception(e)


if __name__ == '__main__':
    main()
