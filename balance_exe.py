import sys
import os
import serial
import serial.tools.list_ports
import re
import csv
from datetime import datetime
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QTabWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QLineEdit, QPushButton,
    QMessageBox, QSizePolicy, QGroupBox,
)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure



class StreamThread(QThread):
    """Поток постоянного чтения из порта."""
    new_data = pyqtSignal(float, float, bool)  # (elapsed_sec, value, stable)

    def __init__(self, serial_conn, experiment_start):
        super().__init__()
        self.serial_conn = serial_conn
        self.experiment_start = experiment_start
        self._running = True

    def run(self):
        while self._running:
            try:
                raw = self.serial_conn.readline()             # блокирует, ждёт новой строки
                text = raw.decode('ascii', errors='ignore').strip()
                if not text:
                    continue
                self.last_raw = text
                # парсим число
                m = re.search(r"([\d.]+)", text)
                val = float(m.group(1)) if m else None
                stable = False
                if len(text) >= 13 and text[12].upper() == 'S':
                    stable = True
                # время от старта
                elapsed = (datetime.now() - self.experiment_start).total_seconds()
                # сигналим GUI
                self.new_data.emit(elapsed, val, stable)
            except Exception:
                # при ошибке просто продолжаем
                continue

    def stop(self):
        self._running = False
        self.wait()  # дождаться завершения





class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Balance GUI")
        self.resize(800, 600)

        self.serial_conn = None # Переменная для последовательного соединения
        self.stream_thread = None
        self.experiment_start = None    #время начала эксперимента
        self.connection_time = None
        self.recording = False
        self.collected_data = []          # список (delta_ms, value, stable_flag)
        self.auto_x = []
        self.auto_y = []
        self.auto_timer = QTimer()
        self.auto_timer.timeout.connect(self._on_auto_tick)
        self.local_recording = False
        self.local_experiment_start = None
        self.local_buffer = []
        self.local_x = []
        self.local_y = []
        self.auto_name_counter = 0

        # Основной виджет: вкладки
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        # Вкладка 1: COM Port
        self.tab_com = QWidget()
        self.tabs.addTab(self.tab_com, "COM Port")
        self._init_com_tab()

        # Вкладка 2: Manual Commands
        self.tab_commands = QWidget()
        self.tabs.addTab(self.tab_commands, "Commands")
        self._init_commands_tab()

        # Вкладка 3: Auto Commands
        self.fig_auto = Figure(figsize=(5,3))
        self.ax_auto = self.fig_auto.add_subplot(111)
        self.line_auto, = self.ax_auto.plot(self.auto_x, self.auto_y, 'b-', lw=1, label="All data")
        self.line_local, = self.ax_auto.plot(self.local_x, self.local_y, 'r.', markersize=4, label="Local recording")
        self.tab_auto = QWidget()
        self.tabs.addTab(self.tab_auto, "Auto Commands")
        self._init_auto_tab()

        if getattr(sys, 'frozen', False):
            self.base_dir = os.path.dirname(sys.executable)
        else:
            self.base_dir = os.getcwd()

    def _init_com_tab(self):
        layout = QVBoxLayout()
        h_layout = QHBoxLayout()
        h_layout.addWidget(QLabel("Select COM Port:"))
        self.combo_ports = QComboBox()
        h_layout.addWidget(self.combo_ports)
        btn_refresh = QPushButton("Refresh")
        btn_refresh.clicked.connect(self.populate_ports)
        h_layout.addWidget(btn_refresh)
        layout.addLayout(h_layout)
        self.btn_connect = QPushButton("Connect")
        self.btn_connect.clicked.connect(self.connect_port)
        layout.addWidget(self.btn_connect)
        self.lbl_status = QLabel("Not connected")
        layout.addWidget(self.lbl_status)
        save_layout = QHBoxLayout()
        save_layout.addWidget(QLabel("Save folder (relative):"))
        self.input_rel_path = QLineEdit("data")
        save_layout.addWidget(self.input_rel_path)
        layout.addLayout(save_layout)
        h_time = QHBoxLayout()
        h_time.addWidget(QLabel("Start time (HH:MM:SS):"))
        self.input_start_time = QLineEdit()
        self.input_start_time.setPlaceholderText("e.g. 14:30:00")
        self.input_start_time.returnPressed.connect(self.set_manual_start)
        h_time.addWidget(self.input_start_time)
        btn_time_set = QPushButton("Set")
        btn_time_set.clicked.connect(self.set_manual_start)
        h_time.addWidget(btn_time_set)
        layout.addLayout(h_time)
        layout.addStretch()  # заберёт всё свободное место вверх
        self.btn_onoff = QPushButton("On/Off")
        self.btn_onoff.clicked.connect(self.toggle_onoff)
        layout.addWidget(self.btn_onoff)
        self.tab_com.setLayout(layout)
        self.populate_ports()

    def _init_commands_tab(self):
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignTop)

        # ─── Верхняя часть: ввод + отправка ─────────────────────────────
        top_layout = QHBoxLayout()
        top_layout.setSpacing(8)
        top_layout.addWidget(QLabel("Enter Command:"))
        self.input_cmd = QLineEdit()
        self.input_cmd.setPlaceholderText("T,C,E,M,O,t,c,e,m,o")
        self.input_cmd.returnPressed.connect(self.send_command)
        top_layout.addWidget(self.input_cmd)
        btn_send = QPushButton("Send")
        btn_send.clicked.connect(self.send_command)
        top_layout.addWidget(btn_send)
        layout.addLayout(top_layout)
        layout.addStretch()

        # ─── Центральная часть: 4 основных кнопки ────────────────────────
        center_layout = QHBoxLayout()
        center_layout.setSpacing(12)
        btn_print = QPushButton("Print/Enter")
        btn_print.clicked.connect(lambda: self._send_manual("E"))
        center_layout.addWidget(btn_print)
        btn_menu = QPushButton("Menu/Down")
        btn_menu.clicked.connect(lambda: self._send_manual("M"))
        center_layout.addWidget(btn_menu)
        btn_cal = QPushButton("Cal/Up")
        btn_cal.clicked.connect(lambda: self._send_manual("C"))
        center_layout.addWidget(btn_cal)
        btn_tare = QPushButton("O/T")
        btn_tare.clicked.connect(lambda: self._send_manual("T"))
        center_layout.addWidget(btn_tare)
        layout.addLayout(center_layout)

        # ─── Панель HOLD с 4 кнопками ────────────────────────────────────
        hold_group = QGroupBox("HOLD")
        hold_layout = QHBoxLayout()
        hold_layout.setSpacing(12)
        btn_h_print = QPushButton("H_print")
        btn_h_print.clicked.connect(lambda: self._send_manual("e"))
        hold_layout.addWidget(btn_h_print)
        btn_h_menu = QPushButton("H_menu")
        btn_h_menu.clicked.connect(lambda: self._send_manual("m"))
        hold_layout.addWidget(btn_h_menu)
        btn_h_cal = QPushButton("H_cal")
        btn_h_cal.clicked.connect(lambda: self._send_manual("c"))
        hold_layout.addWidget(btn_h_cal)
        btn_h_tare = QPushButton("H_tare")
        btn_h_tare.clicked.connect(lambda: self._send_manual("t"))
        hold_layout.addWidget(btn_h_tare)
        hold_group.setLayout(hold_layout)
        layout.addWidget(hold_group)
        layout.addStretch()

        self.tab_commands.setLayout(layout)

    def _init_auto_tab(self):
        # Разделяем окно на левую панель кнопок и правую область
        main_layout = QHBoxLayout()

        # Левая панель: автоматические команды и настройки
        left_panel = QVBoxLayout()
        left_panel.addWidget(QLabel("Auto Commands:"))

        # 1) Переключатель режима и кнопка Set
        self.start_button = QPushButton(f"Start")
        self.start_button.clicked.connect(self.toggle_recording)
        left_panel.addWidget(self.start_button)
        left_panel.addStretch()

        self.input_filename = QLineEdit()
        self.input_filename.setPlaceholderText("Filename (without .csv)")
        left_panel.addWidget(self.input_filename)
        self.btn_extra_start = QPushButton("Local start")
        self.btn_extra_start.clicked.connect(self.extra_start)
        left_panel.addWidget(self.btn_extra_start)
        self.btn_extra_stop = QPushButton("Stop & Save")
        self.btn_extra_stop.clicked.connect(self.extra_stop_and_save)
        left_panel.addWidget(self.btn_extra_stop)
        left_panel.addStretch()

        self.btn_tare = QPushButton("Tare")
        self.btn_tare.clicked.connect(self.send_tare)
        left_panel.addWidget(self.btn_tare)
        left_panel.addStretch()

        self.btn_calibrate = QPushButton("Calibrate")
        self.btn_calibrate.clicked.connect(self.send_calibrate)
        left_panel.addWidget(self.btn_calibrate)

        # Правая панель: вывод и график
        right_panel = QVBoxLayout()
        self.auto_output = QLineEdit()
        self.auto_output.setReadOnly(True)
        self.auto_output.setPlaceholderText("Auto response...")
        self.auto_output.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.auto_output.setMaximumHeight(self.auto_output.sizeHint().height())
        right_panel.addWidget(self.auto_output)

        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("Window (s):"))
        self.input_window = QLineEdit()
        self.input_window.setMaximumWidth(60)
        self.input_window.setPlaceholderText("all")
        ctrl.addWidget(self.input_window)
        self.btn_reset_x = QPushButton("Reset X")
        ctrl.addWidget(self.btn_reset_x)
        ctrl.addWidget(QLabel("Ymin:"))
        self.input_ymin = QLineEdit()
        self.input_ymin.setMaximumWidth(60)
        ctrl.addWidget(self.input_ymin)
        ctrl.addWidget(QLabel("Ymax:"))
        self.input_ymax = QLineEdit()
        self.input_ymax.setMaximumWidth(60)
        ctrl.addWidget(self.input_ymax)
        self.btn_autoscale_y = QPushButton("Autoscale Y")
        ctrl.addWidget(self.btn_autoscale_y)
        right_panel.addLayout(ctrl)
        self.input_window.returnPressed.connect(self._update_x_axis)
        self.input_ymin.returnPressed.connect(self._update_y_axis)
        self.input_ymax.returnPressed.connect(self._update_y_axis)
        self.btn_reset_x.clicked.connect(self._reset_x_axis)
        self.btn_autoscale_y.clicked.connect(self._reset_y_axis)

        self.canvas_auto = FigureCanvas(self.fig_auto)
        right_panel.addWidget(self.canvas_auto)

        main_layout.addLayout(left_panel, 1)
        main_layout.addLayout(right_panel, 3)
        self.tab_auto.setLayout(main_layout)

    def populate_ports(self):
        self.combo_ports.clear()
        ports = serial.tools.list_ports.comports()
        if ports:
            for port in ports:
                self.combo_ports.addItem(port.device)
        else:
            self.combo_ports.addItem("No ports found")

    def connect_port(self):
        selected = self.combo_ports.currentText()
        if selected in ("", "No ports found"):
            QMessageBox.warning(self, "Warning", "No valid port selected.")
            return
        try:
            if self.serial_conn and self.serial_conn.is_open:
                self.serial_conn.close()
            self.serial_conn = serial.Serial(port=selected, baudrate=2400, timeout=1)
            self.lbl_status.setText(f"Connected to {selected}")
            self.connectiont = datetime.now()
            self.experiment_start = datetime.now()
            rel = self.input_rel_path.text().strip() or "."
            base = os.path.join(self.base_dir, rel)
            self.save_base = base
            self.connection_ts = int(self.experiment_start.timestamp())
            self.collected_data.clear()
            self.last_data = None
            self.stream_thread = StreamThread(self.serial_conn, self.experiment_start)
            self.stream_thread.new_data.connect(self.handle_new_data)
            self.stream_thread.start()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to connect: {e}")
            self.lbl_status.setText("Not connected")

    def send_command(self):
        cmd = self.input_cmd.text().strip()
        if not re.fullmatch(r"[TtCcEeMmOo]", cmd):
            QMessageBox.warning(self, "Invalid", "Command must be one of T,C,E,M,O (case-sensitive)")
            self.input_cmd.clear()
            return
        if not self.serial_conn or not self.serial_conn.is_open:
            QMessageBox.warning(self, "Not connected", "Please connect to a COM port first.")
            self.input_cmd.clear()
            return
        try:
            self.serial_conn.write((cmd + "\r").encode('ascii'))
        except Exception as e:
            self.output_view.setText(f"Error: {e}")
        finally:
            self.input_cmd.clear()
    
    def _send_manual(self, cmd: str):
        """Универсальный метод отправки команд одной буквой."""
        if not hasattr(self, "serial_conn") or not self.serial_conn or not self.serial_conn.is_open:
            QMessageBox.warning(self, "Not connected", "Please connect to a COM port first.")
            return
        try:
            self.serial_conn.write(f"{cmd}\r".encode('ascii'))
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to send command {cmd}: {e}")

    def toggle_onoff(self):
        if not self.serial_conn or not self.serial_conn.is_open:
            QMessageBox.warning(self, "Not connected", "Please connect to a COM port first.")
            self.input_cmd.clear()
            return
        try:
            self.serial_conn.write(("O\r").encode('ascii'))
        except Exception as e:
            self.output_view.setText(f"Error: {e}")

    def set_manual_start(self):
        text = self.input_start_time.text().strip()
        try:
            t = datetime.strptime(text, "%H:%M:%S")
        except ValueError:
            QMessageBox.warning(self, "Invalid time", "Enter time as HH:MM:SS")
            return
        # подставляем дату сегодня, но время – из поля
        now = datetime.now()
        self.experiment_start = datetime.combine(now.date(), t.time())

    def toggle_recording(self):
        # Переключаем флаг
        self.recording = not self.recording
        # Меняем надпись кнопки
        self.start_button.setText("Stop" if self.recording else "Start")
        # Сброс графика/данных, если нужно
        if self.recording:
            self.auto_x.clear()
            self.auto_y.clear()
            self.collected_data.clear()
            self.experiment_start = datetime.now()

    def _on_auto_tick(self):
        # Вызывается QTimer в режиме serial
        if self.recording:
            self._collect_auto_data()
    
    def handle_new_data(self, elapsed, value, stable):
        """Обновляет график и поле вывода при любом поступлении данных."""
        if not self.recording:
            return
        
        raw = self.stream_thread.last_raw
        self.auto_output.setText(raw)
        if len(self.auto_x) >= 50000:
            self.auto_x.pop(0); self.auto_y.pop(0)
        self.auto_x.append(elapsed)
        self.auto_y.append(value or 0.0)
        self.line_auto.set_data(self.auto_x, self.auto_y)

        if self.local_recording:
            self.local_x.append(elapsed)
            self.local_y.append(value or 0.0)
            self.local_buffer.append((elapsed, value, stable))
            self.line_local.set_data(self.local_x, self.local_y)
        
        self._update_y_axis()
        self._update_x_axis(latest_elapsed=elapsed)
        
        self.canvas_auto.draw()
        # сохраняем в память
        self.collected_data.append((elapsed, value, stable))

    def extra_start(self):
        """Начать собирать в дополнительный буфер."""
        self.local_buffer.clear()
        self.local_x.clear()
        self.local_y.clear()
        self.line_local.set_data(self.local_x, self.local_y)
        self.canvas_auto.draw()
        # Перезаписываем флаг, если используете его для авто-режима
        self.local_recording = True
        self.local_experiment_start = datetime.now()
        self.btn_extra_start.setEnabled(False)
        self.btn_extra_stop.setEnabled(True)
    
    def extra_stop_and_save(self):
        """Остановить сбор и сохранить весь дополнительный буфер в CSV."""
        self.local_recording = False

        # Определяем имя файла
        name = self.input_filename.text().strip()
        if not name:
            name = f"balance{self.auto_name_counter}"
            self.auto_name_counter += 1
        folder = os.path.join(self.save_base, f"exp_{self.connection_ts}")
        os.makedirs(folder, exist_ok=True)
        fname = os.path.join(folder, name + ".csv")

        # Пишем CSV
        try:
            with open(fname, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([self.local_experiment_start.strftime("%H:%M:%S.%f")])
                # заголовок
                writer.writerow(["elapsed_sec", "value", "stable"])
                # сами данные
                for elapsed, val, stable in self.local_buffer:
                    writer.writerow([elapsed, val, stable])
                self.btn_extra_start.setEnabled(True)
                self.btn_extra_stop.setEnabled(False)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Не удалось сохранить «{fname}»: {e}")
        else:
            QMessageBox.information(self, "Saved", f"Доп. данные сохранены в {fname}")
            # чистим поле, если нужно
            self.input_filename.clear()

    def send_tare(self):
        """Посылает команду T (tare) на прибор."""
        if not self.serial_conn or not self.serial_conn.is_open:
            QMessageBox.warning(self, "Not connected", "Please connect to a COM port first.")
            return
        try:
            # Tare
            self.serial_conn.write("T\r".encode('ascii'))
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to send Tare command:\n{e}")

    def send_calibrate(self):
        if not self.serial_conn or not self.serial_conn.is_open:
            QMessageBox.warning(self, "Not connected", "Please connect to a COM port first.")
            return
        try:
            self.serial_conn.write("C\r".encode('ascii'))
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to send Calibrate command:\n{e}")

    def _update_x_axis(self, latest_elapsed: float = None):
        """Перерисовать только X-ось в соответствии с input_window."""
        if latest_elapsed is None and self.auto_x:
            latest_elapsed = self.auto_x[-1]
        txt = self.input_window.text().strip()
        if txt:
            try:
                w = float(txt)
                start = max(0, latest_elapsed - w)
                self.ax_auto.set_xlim(start, latest_elapsed)
            except ValueError:
                pass
        else:
            if self.auto_x:
                self.ax_auto.set_xlim(0, max(self.auto_x))

    def _update_y_axis(self):
        """Перерисовать только Y-ось в соответствии с input_ymin/input_ymax."""
        ymin_txt = self.input_ymin.text().strip()
        ymax_txt = self.input_ymax.text().strip()
        if ymin_txt and ymax_txt:
            try:
                y0 = float(ymin_txt)
                y1 = float(ymax_txt)
                self.ax_auto.set_ylim(y0, y1)
            except ValueError:
                pass
        else:
            self.ax_auto.relim()
            self.ax_auto.set_autoscaley_on(True)
            self.ax_auto.autoscale_view()

    def _reset_x_axis(self):
        """Сбросить настройку X-оси (window) на полный диапазон от 0 до текущего."""
        self.input_window.clear()
        self._update_x_axis()

    def _reset_y_axis(self):
        """Сбросить Y-ось в автоподбор."""
        self.input_ymin.clear()
        self.input_ymax.clear()
        self._update_y_axis()

    def closeEvent(self, event):
        reply = QMessageBox.question(
            self, "Save Data?", "Save all data before exit?", 
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
        )
        if reply == QMessageBox.Yes:
            self._save_experiment_data()
        if self.stream_thread:
            self.stream_thread.stop()
        event.accept()

    def _save_experiment_data(self):
        if not self.experiment_start or not hasattr(self, "save_base"):
            return
        folder = os.path.join(self.save_base, f"exp_{self.connection_ts}")
        os.makedirs(folder, exist_ok=True)
        fname = os.path.join(folder, f"data_{self.connection_ts}.csv")
        with open(fname, 'w', newline='') as f:
            writer = csv.writer(f)
            # 1) время старта: абсолютное и точное
            writer.writerow([
                self.experiment_start.strftime("%H:%M:%S.%f")
            ])
            # 2) данные: delta_ms, value, stable
            for delta, val, stable in self.collected_data:
                writer.writerow([delta, val, stable])




if __name__ == "__main__":
    app = QApplication(sys.argv)
    mw = MainWindow()
    mw.show()
    sys.exit(app.exec_())
