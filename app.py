from flask import Flask, render_template, request, send_file
import pdfplumber, zipfile, shutil
import re, os, pandas as pd, time
from threading import Thread
from werkzeug.utils import secure_filename

app = Flask(__name__)

UPLOAD_FOLDER = "uploads"
TEMP_FOLDER = "temp"
OUTPUT_FOLDER = "outputs"

EXCEL_FILE = os.path.join(OUTPUT_FOLDER, "resultados.xlsx")
RIPS_ZIP = os.path.join(OUTPUT_FOLDER, "RIPS_procesado.zip")

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(TEMP_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# =========================================================
# ================= PDF → EXCEL ===========================
# =========================================================

def extraer_datos_pdf(ruta_pdf):
    with pdfplumber.open(ruta_pdf) as pdf:
        texto = ""
        for pagina in pdf.pages:
            contenido = pagina.extract_text()
            if contenido:
                texto += contenido + "\n"

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


def extraer_numero_factura(nombre_archivo):
    match = re.search(r'FEH(\d+)', nombre_archivo)
    return match.group(1) if match else ""


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
        df.drop_duplicates(subset=["N. Factura"], inplace=True)
        df.to_excel(EXCEL_FILE, index=False)


def limpiar_pdf_excel():
    time.sleep(5)
    try:
        if os.path.exists(EXCEL_FILE):
            os.remove(EXCEL_FILE)

        for archivo in os.listdir(UPLOAD_FOLDER):
            ruta = os.path.join(UPLOAD_FOLDER, archivo)
            if os.path.isfile(ruta):
                os.remove(ruta)

    except Exception as e:
        print("Error limpiando PDF/Excel:", e)


# =========================================================
# ================= ZIP → RIPS ============================
# =========================================================

def procesar_zip_rips(path_zip, nit):
    temp_dir = os.path.join(TEMP_FOLDER, "rips_extract")
    rips_out = os.path.join(TEMP_FOLDER, "RIPS_out")

    os.makedirs(temp_dir, exist_ok=True)
    os.makedirs(rips_out, exist_ok=True)

    # 1️⃣ Extraer ZIP
    with zipfile.ZipFile(path_zip, 'r') as z:
        z.extractall(temp_dir)

    # 2️⃣ Recorrer carpetas FEH
    for feh in os.listdir(temp_dir):
        ruta_carpeta = os.path.join(temp_dir, feh)

        if os.path.isdir(ruta_carpeta) and feh.startswith("FEH"):

            for archivo in os.listdir(ruta_carpeta):
                origen = os.path.join(ruta_carpeta, archivo)

                if archivo.startswith("ResultadosMSPS") and archivo.endswith("_CUV.txt"):
                    nuevo = f"{nit}_{feh}_CUV.txt"
                    shutil.copy(origen, os.path.join(rips_out, nuevo))

                elif archivo.endswith(".json"):
                    nuevo = f"{nit}_{feh}_RIPS.json"
                    shutil.copy(origen, os.path.join(rips_out, nuevo))

    # 3️⃣ Crear ZIP final
    with zipfile.ZipFile(RIPS_ZIP, 'w', zipfile.ZIP_DEFLATED) as zf:
        for archivo in os.listdir(rips_out):
            ruta_archivo = os.path.join(rips_out, archivo)
            zf.write(ruta_archivo, arcname=archivo)

    return temp_dir, rips_out


def limpiar_rips(path_zip, temp_dir, rips_out):
    time.sleep(5)
    try:
        if os.path.exists(path_zip):
            os.remove(path_zip)

        if os.path.exists(RIPS_ZIP):
            os.remove(RIPS_ZIP)

        shutil.rmtree(temp_dir, ignore_errors=True)
        shutil.rmtree(rips_out, ignore_errors=True)

    except Exception as e:
        print("Error limpiando RIPS:", e)


# =========================================================
# ==================== RUTAS ==============================
# =========================================================

@app.route("/")
def index():
    return render_template("index.html")


# ---------- PDFs ----------
@app.route("/subir", methods=["POST"])
def subir():
    archivos = request.files.getlist("pdfs")

    for archivo in archivos:
        if archivo and archivo.filename.lower().endswith(".pdf"):
            nombre = secure_filename(archivo.filename)
            archivo.save(os.path.join(UPLOAD_FOLDER, nombre))

    return ("", 204)


@app.route("/descargar")
def descargar():
    procesar_pdfs()

    if os.path.exists(EXCEL_FILE):
        resp = send_file(EXCEL_FILE, as_attachment=True)
        Thread(target=limpiar_pdf_excel).start()
        return resp

    return "No hay PDFs para procesar."


# ---------- RIPS ----------
@app.route("/subir_rips", methods=["POST"])
def subir_rips():
    archivo_zip = request.files.get("zipfile")
    nit = request.form.get("nit", "").strip()

    if not archivo_zip or not nit:
        return "Falta ZIP o NIT", 400

    nombre = secure_filename(archivo_zip.filename)
    ruta_zip = os.path.join(UPLOAD_FOLDER, nombre)
    archivo_zip.save(ruta_zip)

    # procesar de una vez
    temp_dir, rips_out = procesar_zip_rips(ruta_zip, nit)

    # guardar rutas para limpieza
    app.config["RUTA_ZIP_ORIGINAL"] = ruta_zip
    app.config["RUTA_TEMP"] = temp_dir
    app.config["RUTA_RIPS_OUT"] = rips_out

    return ("", 204)


@app.route("/descargar_rips")
def descargar_rips():
    if os.path.exists(RIPS_ZIP):
        resp = send_file(RIPS_ZIP, as_attachment=True)

        Thread(target=limpiar_rips, args=(
            app.config.get("RUTA_ZIP_ORIGINAL"),
            app.config.get("RUTA_TEMP"),
            app.config.get("RUTA_RIPS_OUT")
        )).start()

        return resp

    return "No hay archivo para descargar."


# =========================================================

if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)