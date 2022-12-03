import subprocess
from pathlib import Path


class FFmpeg:
    def __init__(self, exe_path: Path):
        self.exe = exe_path
        self.inputs = []
        self.arguments = []
        self.outputs = []

    def input(self, filepath: Path):
        self.inputs.append(filepath)

    def arg(self, arg_type: str, value: str):
        self.arguments.append((arg_type, value))

    def output(self, filepath: Path):
        self.outputs.append(filepath)

    def run(self):
        command = [str(self.exe)]
        for n in self.inputs:
            command.append('-i')
            command.append(n)
        for a in self.arguments:
            command.append(a[0])
            command.append(a[1])
        for o in self.outputs:
            command.append(o)
        return subprocess.run(command, capture_output=True, text=True, check=True)
