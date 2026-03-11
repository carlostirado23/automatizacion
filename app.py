from flask import Flask, render_template, request, send_file
import pdfplumber
import re
import os
import pandas as pd
import time
from threading import Thread
from werkzeug.utils import secure_filename

app = Flask(__name__)

UPLOAD_FOLDER = "uploads"
EXCEL_FILE = "resultados.xlsx"

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# ==============================
# EXTRAER DATOS DEL PDF
# ==============================
def extraer_datos_pdf(ruta_pdf):
    with pdfplumber.open(ruta_pdf) as pdf:
        texto = ""
        for pagina in pdf.pages:
            texto += pagina.extract_text() + "\n"

    entidad = re.search(r'Entidad:\s*(.+)', texto)
    if entidad:
        entidad = entidad.group(1).strip()
        entidad = entidad.split("Admisión")[0]
        entidad = entidad.split("-")[0]
        entidad = entidad.strip()
    else:
        entidad = ""

    total = re.search(r'Total:\s*\$\s*([\d\.,]+)', texto)
    total = total.group(1) if total else ""

    return entidad, total


# ==============================
# EXTRAER NÚMERO DE FACTURA
# ==============================
def extraer_numero_factura(nombre_archivo):
    match = re.search(r'FEH(\d+)', nombre_archivo)
    return match.group(1) if match else ""


# ==============================
# PROCESAR TODOS LOS PDFs
# ==============================
def procesar_pdfs():
    filas = []

    for nombre in os.listdir(UPLOAD_FOLDER):
        if nombre.lower().endswith(".pdf"):
            ruta = os.path.join(UPLOAD_FOLDER, nombre)

            entidad, total = extraer_datos_pdf(ruta)
            numero_factura = extraer_numero_factura(nombre)

            filas.append([numero_factura, entidad, total])

    if filas:
        columnas = ["N. Factura", "Entidad", "Total"]
        df = pd.DataFrame(filas, columns=columnas)

        # ❌ evitar duplicados
        df.drop_duplicates(subset=["N. Factura"], inplace=True)

        df.to_excel(EXCEL_FILE, index=False)


# ==============================
# LIMPIEZA DIFERIDA
# ==============================
def limpiar_archivos():
    time.sleep(5)
    try:
        if os.path.exists(EXCEL_FILE):
            os.remove(EXCEL_FILE)

        for archivo in os.listdir(UPLOAD_FOLDER):
            ruta = os.path.join(UPLOAD_FOLDER, archivo)
            if os.path.isfile(ruta):
                os.remove(ruta)
    except Exception as e:
        print("Error limpiando:", e)


# ==============================
# RUTA PRINCIPAL
# ==============================
@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


# ==============================
# SUBIR PDFs
# ==============================
@app.route("/subir", methods=["POST"])
def subir():
    archivos = request.files.getlist("pdfs")

    for archivo in archivos:
        if archivo and archivo.filename.lower().endswith(".pdf"):
            nombre = secure_filename(archivo.filename)
            ruta = os.path.join(app.config["UPLOAD_FOLDER"], nombre)
            archivo.save(ruta)

    return ("", 204)


# ==============================
# DESCARGAR (PROCESA TODO)
# ==============================
@app.route("/descargar")
def descargar():
    procesar_pdfs()

    if os.path.exists(EXCEL_FILE):
        response = send_file(EXCEL_FILE, as_attachment=True)

        # limpieza en segundo plano
        Thread(target=limpiar_archivos).start()

        return response

    return "No hay PDFs para procesar."


# ==============================
# RUN
# ==============================
if __name__ == "__main__":
    app.run(debug=True)