from flask import Flask, render_template, request, send_file
import pdfplumber, zipfile, shutil
import re, os, pandas as pd, time
from threading import Thread
from werkzeug.utils import secure_filename

app = Flask(__name__)

UPLOAD_FOLDER = "uploads"
EXCEL_FILE = "resultados.xlsx"

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# =====================================================
# ================= PDF → EXCEL =======================
# =====================================================

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
            if archivo.lower().endswith(".pdf"):
                os.remove(os.path.join(UPLOAD_FOLDER, archivo))
    except Exception as e:
        print("Error limpiando PDF/Excel:", e)


# =====================================================
# ================= ZIP → RIPS ========================
# =====================================================

def procesar_zip_rips(path_zip, nit):
    temp_dir = os.path.join(UPLOAD_FOLDER, "temp_rips")
    rips_root = os.path.join(UPLOAD_FOLDER, "RIPS")

    os.makedirs(temp_dir, exist_ok=True)
    os.makedirs(rips_root, exist_ok=True)

    # 1️⃣ Descomprimir ZIP
    with zipfile.ZipFile(path_zip, 'r') as z:
        z.extractall(temp_dir)

    # 2️⃣ Recorrer carpetas FEH
    for feh in os.listdir(temp_dir):
        carpeta_feh = os.path.join(temp_dir, feh)

        if os.path.isdir(carpeta_feh) and feh.startswith("FEH"):
            carpeta_destino = os.path.join(rips_root, feh)
            os.makedirs(carpeta_destino, exist_ok=True)

            for archivo in os.listdir(carpeta_feh):
                origen = os.path.join(carpeta_feh, archivo)

                # TXT CUV
                if archivo.startswith("ResultadosMSPS") and archivo.endswith("_CUV.txt"):
                    nuevo_nombre = f"{nit}_{feh}_CUV.txt"
                    shutil.copy(origen, os.path.join(carpeta_destino, nuevo_nombre))

                # JSON RIPS
                elif archivo.endswith(".json"):
                    nuevo_nombre = f"{nit}_{feh}_RIPS.json"
                    shutil.copy(origen, os.path.join(carpeta_destino, nuevo_nombre))

    # 3️⃣ Crear ZIP final
    zip_final = os.path.join(UPLOAD_FOLDER, "RIPS_procesado.zip")

    with zipfile.ZipFile(zip_final, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(rips_root):
            for file in files:
                ruta_archivo = os.path.join(root, file)
                arcname = os.path.relpath(ruta_archivo, UPLOAD_FOLDER)
                zf.write(ruta_archivo, arcname)

    return zip_final, temp_dir, rips_root


def limpiar_rips(path_zip, zip_final, temp_dir, rips_root):
    time.sleep(5)
    try:
        for p in [path_zip, zip_final]:
            if os.path.exists(p):
                os.remove(p)

        shutil.rmtree(temp_dir, ignore_errors=True)
        shutil.rmtree(rips_root, ignore_errors=True)

    except Exception as e:
        print("Error limpiando RIPS:", e)


# =====================================================
# ===================== RUTAS =========================
# =====================================================

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

    # Procesar inmediatamente
    zip_final, temp_dir, rips_root = procesar_zip_rips(ruta_zip, nit)

    # Guardar rutas para limpiar luego
    app.config["RIPS_DATA"] = (ruta_zip, zip_final, temp_dir, rips_root)

    return ("", 204)


@app.route("/descargar_rips")
def descargar_rips():
    data = app.config.get("RIPS_DATA")

    if not data:
        return "No hay archivo para descargar."

    ruta_zip, zip_final, temp_dir, rips_root = data

    if os.path.exists(zip_final):
        resp = send_file(zip_final, as_attachment=True)
        Thread(target=limpiar_rips, args=(ruta_zip, zip_final, temp_dir, rips_root)).start()
        return resp

    return "No hay archivo para descargar."


# =====================================================
# ===================== RUN ===========================
# =====================================================

if __name__ == "__main__":
    app.run(debug=True)