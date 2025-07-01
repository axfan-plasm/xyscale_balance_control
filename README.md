Программа для управления весами. Для создания exe-файла выполнить команду
pyinstaller --name BalanceGUI --onefile --windowed --icon icon.ico --hidden-import serial.tools.list_ports --hidden-import matplotlib.backends.backend_qt5agg balance_exe.py
