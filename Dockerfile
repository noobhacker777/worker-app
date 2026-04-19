# escape=`
FROM python:3.11-windowsservercore-ltsc2022 AS builder

SHELL ["cmd", "/S", "/C"]

WORKDIR C:\app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt pyinstaller

COPY . .

RUN pyinstaller --noconfirm --clean --onefile --windowed --name Worker gui.py

FROM mcr.microsoft.com/windows/servercore:ltsc2022

WORKDIR C:\release

COPY --from=builder C:\app\dist\Worker.exe C:\release\Worker.exe

CMD ["cmd", "/c", "echo Worker.exe is available in C:\\release && timeout /t -1"]
