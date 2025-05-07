#!/usr/bin/env python3
"""
text2sql_gui.py

A PyQt5 GUI with Start/Stop recording and Convert buttons working independently.
"""

import sys
import threading
import pyaudio
import speech_recognition as sr
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QTextEdit, QPushButton,
    QFileDialog, QMessageBox, QVBoxLayout, QHBoxLayout
)
from core_fr import text_to_sql  # your offline core

class ProcessAudioWorker(QThread):
    finished = pyqtSignal(str)
    error    = pyqtSignal(str)
    def __init__(self, audio_data):
        super().__init__()
        self.audio_data = audio_data
    def run(self):
        recognizer = sr.Recognizer()
        try:
            text = recognizer.recognize_google(self.audio_data)
            self.finished.emit(text)
        except sr.UnknownValueError:
            self.error.emit("Could not understand audio.")
        except Exception as e:
            self.error.emit(str(e))

class AudioRecorder:
    def __init__(self):
        self.p = pyaudio.PyAudio()
        self.stream = None
        self.frames = []
        self.recording = False
        self.rate = 16000
        self.channels = 1
        self.format = pyaudio.paInt16

    def start(self):
        self.frames = []
        self.stream = self.p.open(
            format=self.format,
            channels=self.channels,
            rate=self.rate,
            input=True,
            frames_per_buffer=1024
        )
        self.recording = True
        threading.Thread(target=self._record, daemon=True).start()

    def _record(self):
        while self.recording:
            data = self.stream.read(1024, exception_on_overflow=False)
            self.frames.append(data)

    def stop(self):
        self.recording = False
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
            self.stream = None
        raw = b"".join(self.frames)
        sample_width = self.p.get_sample_size(self.format)
        return sr.AudioData(raw, self.rate, sample_width)

class SQLWorker(QThread):
    finished = pyqtSignal(str)
    error    = pyqtSignal(str)
    def __init__(self, prompt: str):
        super().__init__()
        self.prompt = prompt
    def run(self):
        try:
            sql = text_to_sql(self.prompt)
            self.finished.emit(sql)
        except Exception as e:
            self.error.emit(str(e))

class Text2SQLApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Text → SQL Converter")
        self.resize(700, 500)

        # Input & output
        self.input_edit  = QTextEdit()
        self.output_edit = QTextEdit()
        self.output_edit.setReadOnly(True)

        # Buttons
        self.run_btn    = QPushButton("➤ Convert to SQL")
        self.voice_btn  = QPushButton("🎤 Start Recording")
        self.save_btn   = QPushButton("💾 Save SQL")
        self.status_lbl = QLabel("Ready")

        btns = QHBoxLayout()
        btns.addWidget(self.run_btn)
        btns.addWidget(self.voice_btn)
        btns.addWidget(self.save_btn)

        layout = QVBoxLayout()
        layout.addWidget(QLabel("Enter prompt:"))
        layout.addWidget(self.input_edit)
        layout.addLayout(btns)
        layout.addWidget(QLabel("Generated SQL:"))
        layout.addWidget(self.output_edit)
        layout.addWidget(self.status_lbl)
        self.setLayout(layout)

        # Connect signals
        self.run_btn.clicked.connect(self.on_convert)
        self.voice_btn.clicked.connect(self.on_record_toggle)
        self.save_btn.clicked.connect(self.on_save)

        # Recorder and workers
        self.recorder = AudioRecorder()
        self.is_recording = False
        self.process_worker = None
        self.sql_worker = None

    def on_convert(self):
        prompt = self.input_edit.toPlainText().strip()
        if not prompt:
            QMessageBox.warning(self, "Input Required", "Please enter a prompt.")
            return
        self._set_busy_sql("Generating SQL…")
        self.sql_worker = SQLWorker(prompt)
        self.sql_worker.finished.connect(self._on_sql_ready)
        self.sql_worker.error.connect(self._on_sql_error)
        self.sql_worker.start()

    def _on_sql_ready(self, sql: str):
        self.output_edit.setPlainText(sql)
        self._set_ready()

    def _on_sql_error(self, msg: str):
        self._set_ready(error=True)
        QMessageBox.critical(self, "Generation Error", msg)

    def on_record_toggle(self):
        if not self.is_recording:
            # Start recording
            self.recorder.start()
            self.is_recording = True
            self.voice_btn.setText("■ Stop Recording")
            self._set_busy_rec("Recording…")
        else:
            # Stop recording
            audio_data = self.recorder.stop()
            self.is_recording = False
            self.voice_btn.setText("🎤 Start Recording")
            self.status_lbl.setText("Transcribing…")
            # Process in background
            self.process_worker = ProcessAudioWorker(audio_data)
            self.process_worker.finished.connect(self._on_record_ready)
            self.process_worker.error.connect(self._on_record_error)
            self.process_worker.start()

    def _on_record_ready(self, text: str):
        self.input_edit.setPlainText(text)
        self._set_ready()

    def _on_record_error(self, msg: str):
        self._set_ready(error=True)
        QMessageBox.critical(self, "Speech Error", msg)

    def on_save(self):
        sql = self.output_edit.toPlainText().strip()
        if not sql:
            QMessageBox.warning(self, "Nothing to Save", "Generate some SQL first.")
            return
        filename, _ = QFileDialog.getSaveFileName(
            self, "Save SQL File", "", "SQL Files (*.sql);;All Files (*)"
        )
        if filename:
            with open(filename, "w", encoding="utf-8") as f:
                f.write(sql)
            self.status_lbl.setText(f"Saved to {filename}")

    def _set_busy_sql(self, msg: str):
        # Disable everything during SQL generation
        self.run_btn.setEnabled(False)
        self.voice_btn.setEnabled(False)
        self.save_btn.setEnabled(False)
        self.status_lbl.setText(msg)

    def _set_busy_rec(self, msg: str):
        # Disable Convert & Save but leave Stop enabled
        self.run_btn.setEnabled(False)
        self.save_btn.setEnabled(False)
        # voice_btn remains enabled for stopping
        self.status_lbl.setText(msg)

    def _set_ready(self, error: bool=False):
        # Re-enable all controls
        self.run_btn.setEnabled(True)
        self.voice_btn.setEnabled(True)
        self.save_btn.setEnabled(True)
        self.status_lbl.setText("Error." if error else "Done.")

if __name__ == "__main__":
    from PyQt5.QtWidgets import QLabel
    app = QApplication(sys.argv)
    win = Text2SQLApp()
    win.show()
    sys.exit(app.exec_())
